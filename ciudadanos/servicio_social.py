from datetime import datetime, timedelta
from io import BytesIO
from uuid import uuid4

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from . import citas_medicas
from .models import ArchivoRequisito, Cita, Ciudadano, Solicitud, Tramite, validar_pdf_clinico


CREDITOS_MINIMOS = {'licenciatura': 70, 'tecnico': 50}
REQUISITOS_CITA = (
    '2 fotografías tamaño infantil',
    'Certificado médico expedido por el DIF',
    'Folder azul cielo tamaño carta',
)


def puede_validar(usuario):
    return usuario.is_authenticated and usuario.is_active and usuario.is_staff and usuario.has_perm(
        'ciudadanos.validar_servicio_social'
    )


class SolicitudServicioSocialForm(forms.Form):
    nivel_estudios = forms.ChoiceField(
        label='Nivel de estudios', choices=[('', 'Selecciona una opción'), *Solicitud.NIVELES_SERVICIO_SOCIAL],
    )
    porcentaje_creditos = forms.DecimalField(
        label='Porcentaje de créditos acreditados', min_value=0, max_value=100,
        max_digits=5, decimal_places=2, localize=True,
    )

    def __init__(self, *args, requisitos, archivos, **kwargs):
        super().__init__(*args, **kwargs)
        self.documentos = []
        for requisito in requisitos:
            existente = archivos.get(requisito.pk)
            nombre = f'req_{requisito.pk}'
            if not existente or existente.estado_validacion == 'Rechazado':
                self.fields[nombre] = forms.FileField(
                    label=requisito.descripcion, validators=[validar_pdf_clinico],
                    widget=forms.ClearableFileInput(attrs={'accept': 'application/pdf,.pdf'}),
                )
            self.documentos.append((requisito, self[nombre] if nombre in self.fields else None, existente))

    def clean(self):
        datos = super().clean()
        minimo = CREDITOS_MINIMOS.get(datos.get('nivel_estudios'))
        porcentaje = datos.get('porcentaje_creditos')
        if minimo is not None and porcentaje is not None and porcentaje < minimo:
            self.add_error('porcentaje_creditos', f'Para este nivel necesitas al menos {minimo}% de créditos.')
        return datos


def validada(solicitud):
    minimo = CREDITOS_MINIMOS.get(solicitud.nivel_estudios)
    if minimo is None or solicitud.porcentaje_creditos is None or solicitud.porcentaje_creditos < minimo:
        return False
    requisitos = set(solicitud.tramite.requisitos.values_list('pk', flat=True))
    archivos = list(solicitud.archivos.values_list('requisito_id', 'estado_validacion'))
    return bool(requisitos) and requisitos == {
        requisito for requisito, estado in archivos if estado == 'Aprobado'
    } and all(estado == 'Aprobado' for _, estado in archivos)


@never_cache
def cuestionario(request, tramite, solicitud=None):
    requisitos = list(tramite.requisitos.order_by('pk'))
    if request.method == 'POST' and not requisitos:
        raise Http404('Servicio Social todavía no tiene requisitos configurados.')

    with transaction.atomic():
        if solicitud is None:
            if request.method == 'POST':
                Ciudadano.objects.select_for_update().get(pk=request.user.pk)
            activa = Solicitud.objects.filter(ciudadano=request.user, tramite=tramite).exclude(
                cita__estado__in=('Atendida', 'Cancelada', 'Reprogramada'),
            ).order_by('-fecha_creacion').first()
            if activa:
                return redirect('corregir_solicitud', activa.pk)
        elif request.method == 'POST':
            solicitud = Solicitud.objects.select_for_update().get(pk=solicitud.pk)
        existentes = {
            archivo.requisito_id: archivo
            for archivo in solicitud.archivos.defer('contenido_pdf')
        } if solicitud else {}
        corregir = solicitud is None or solicitud.estado == 'Rechazado' or (
            solicitud.porcentaje_creditos is None or any(req.pk not in existentes for req in requisitos)
        )
        if solicitud and (hasattr(solicitud, 'cita') or (solicitud.estado == 'Aprobado' and validada(solicitud))):
            corregir = False
        datos = request.POST if request.method == 'POST' else None
        formulario = SolicitudServicioSocialForm(
            datos, request.FILES if datos is not None else None,
            requisitos=requisitos, archivos=existentes,
            initial={
                'nivel_estudios': solicitud.nivel_estudios,
                'porcentaje_creditos': solicitud.porcentaje_creditos,
            } if solicitud else None,
        )
        if request.method == 'POST':
            if not corregir:
                raise PermissionDenied
            if formulario.is_valid():
                if solicitud is None:
                    solicitud = Solicitud(
                        tramite=tramite, ciudadano=request.user, folio=f'TRAM-{uuid4().hex[:15].upper()}',
                    )
                solicitud.nivel_estudios = formulario.cleaned_data['nivel_estudios']
                solicitud.porcentaje_creditos = formulario.cleaned_data['porcentaje_creditos']
                solicitud.estado = 'Pendiente'
                solicitud.save()
                for requisito, campo, existente in formulario.documentos:
                    if campo is None:
                        continue
                    pdf = formulario.cleaned_data[campo.name]
                    archivo = existente or ArchivoRequisito(solicitud=solicitud, requisito=requisito)
                    archivo.archivo = ''
                    archivo.nombre_pdf = pdf.name
                    archivo.contenido_pdf = pdf.read()
                    archivo.estado_validacion = 'Pendiente'
                    archivo.observaciones = ''
                    archivo.save()
                messages.success(request, f'Solicitud {solicitud.folio} enviada a revisión.')
                return redirect('mis_tramites')

    return render(request, 'ventanilla/servicio_social.html', {
        'tramite': tramite, 'solicitud': solicitud, 'formulario': formulario, 'puede_enviar': corregir and bool(requisitos),
    })


@never_cache
def revisar(request, solicitud):
    with transaction.atomic():
        if request.method == 'POST':
            solicitud = Solicitud.objects.select_for_update().get(pk=solicitud.pk)
        archivos = list(solicitud.archivos.select_related('requisito').defer('contenido_pdf'))
        if request.method == 'POST' and not hasattr(solicitud, 'cita'):
            for archivo in archivos:
                estado = request.POST.get(f'estado_doc_{archivo.pk}')
                if estado not in dict(ArchivoRequisito.ESTADO_DOC_CHOICES):
                    continue
                archivo.estado_validacion = estado
                archivo.observaciones = request.POST.get(f'obs_doc_{archivo.pk}', '').strip()
                archivo.save(update_fields=['estado_validacion', 'observaciones'])
            if validada(solicitud):
                solicitud.estado = 'Aprobado'
            elif any(archivo.estado_validacion == 'Rechazado' for archivo in archivos):
                solicitud.estado = 'Rechazado'
            else:
                solicitud.estado = 'En proceso'
            solicitud.save(update_fields=['estado'])
            return redirect('panel_funcionario')
    return render(request, 'ventanilla/revisar_solicitud.html', {
        'solicitud': solicitud, 'archivos': archivos,
    })


@require_GET
@never_cache
def descargar(request, pk):
    archivo = get_object_or_404(
        ArchivoRequisito.objects.select_related('solicitud'), pk=pk,
        solicitud__tramite__es_servicio_social=True,
    )
    if not (puede_validar(request.user) or request.user.pk == archivo.solicitud.ciudadano_id):
        raise Http404
    if archivo.nombre_pdf and archivo.contenido_pdf is not None:
        return FileResponse(BytesIO(archivo.contenido_pdf), filename=archivo.nombre_pdf,
                            content_type='application/pdf')
    if archivo.archivo:
        try:
            return FileResponse(archivo.archivo.open('rb'), as_attachment=True)
        except FileNotFoundError:
            pass
    raise Http404


def _horarios(tramite):
    for horario in tramite.direccion.horarios.all():
        if horario.duracion_cita_minutos <= 0:
            continue
        dia = timezone.localdate()
        inicio = datetime.combine(dia, horario.hora_inicio)
        fin = datetime.combine(dia, horario.hora_fin)
        intervalo = timedelta(minutes=horario.duracion_cita_minutos)
        while inicio + intervalo <= fin:
            yield horario.dia_semana, inicio.time()
            inicio += intervalo


@never_cache
def agendar(request, solicitud):
    if hasattr(solicitud, 'cita'):
        return redirect('ticket_servicio_social', solicitud.pk)
    if not validada(solicitud):
        messages.error(request, 'La cita se habilita cuando se validan todos los requisitos.')
        return redirect('mis_tramites')

    error = ''
    if request.method == 'POST':
        turno = citas_medicas.leer_turno(request.POST.get('turno', ''))
        if turno:
            fecha, hora = turno
            with transaction.atomic():
                tramite = Tramite.objects.select_for_update().get(pk=solicitud.tramite_id)
                solicitud = Solicitud.objects.select_for_update().get(pk=solicitud.pk)
                if hasattr(solicitud, 'cita'):
                    return redirect('ticket_servicio_social', solicitud.pk)
                if (
                    solicitud.estado == 'Aprobado' and validada(solicitud)
                    and citas_medicas.en_ventana(fecha, hora, timezone.localtime())
                    and (fecha.weekday(), hora) in set(_horarios(tramite))
                    and not Cita.objects.filter(tramite=tramite, fecha=fecha, hora=hora)
                    .exclude(estado__in=('Cancelada', 'Reprogramada')).exists()
                ):
                    Cita.objects.create(
                        solicitud=solicitud, tramite=tramite, ciudadano_id=solicitud.ciudadano_id,
                        fecha=fecha, hora=hora, folio_cita=f'CITA-{uuid4().hex[:15].upper()}',
                    )
                    return redirect('ticket_servicio_social', solicitud.pk)
        error = 'Ese turno ya no está disponible. Selecciona otro horario.'

    return render(request, 'ventanilla/cita_medica_agenda.html', {
        'solicitud': solicitud, 'error': error, 'requisitos_cita': REQUISITOS_CITA,
        'dias': citas_medicas.calendario(solicitud.tramite, timezone.localtime(), list(_horarios(solicitud.tramite))),
    })
