from io import BytesIO
import re
from uuid import uuid4

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.validators import FileExtensionValidator
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from PIL import Image, UnidentifiedImageError

from . import citas_medicas, servicio_social
from .models import ArchivoRequisito, Cita, Ciudadano, Solicitud, Tramite, validar_pdf_clinico


def puede_validar(user):
    return user.is_authenticated and user.is_active and user.is_staff and user.has_perm(
        'ciudadanos.validar_proveedores'
    )


class PerfilProveedorForm(forms.Form):
    tipo_persona = forms.ChoiceField(label='Tipo de persona', choices=Ciudadano.TIPOS_PERSONA)
    rfc = forms.CharField(label='RFC del proveedor', max_length=13)
    razon_social = forms.CharField(label='Razón social (persona moral)', max_length=250, required=False)
    tiene_representante = forms.BooleanField(label='Actúo mediante representante legal', required=False)

    def clean(self):
        datos = super().clean()
        tipo = datos.get('tipo_persona')
        rfc = datos.get('rfc', '').strip().upper()
        patron = r'[A-ZÑ&]{3}[0-9]{6}[A-Z0-9]{3}' if tipo == 'moral' else r'[A-ZÑ&]{4}[0-9]{6}[A-Z0-9]{3}'
        if not re.fullmatch(patron, rfc):
            self.add_error('rfc', 'Revisa el RFC de 12 caracteres para persona moral o 13 para persona física.')
        datos['rfc'] = rfc
        if tipo == 'moral':
            if not datos.get('razon_social', '').strip():
                self.add_error('razon_social', 'Escribe la razón social de la empresa.')
            datos['tiene_representante'] = True
        else:
            datos['razon_social'] = ''
        return datos


def requisitos_aplicables(tramite, datos):
    return [
        req for req in tramite.requisitos.order_by('pk')
        if (not req.aplica_persona or req.aplica_persona == datos['tipo_persona'])
        and (not req.requiere_representante or datos['tiene_representante'])
        and not req.es_fotografia and req.tipo_documento != 'fotografias'
    ]


def titular(req, datos, usuario):
    # La identificación y las fotografías son de la persona que opera la cuenta.
    if req.tipo_documento in ('acta_nacimiento', 'identificacion_oficial', 'fotografias'):
        return f'CURP:{usuario.pk}'
    return f'RFC:{datos["rfc"]}'


def reutilizable(req, datos, usuario):
    if not req.tipo_documento:
        return None
    candidatos = ArchivoRequisito.objects.filter(
        solicitud__ciudadano=usuario, tipo_documento=req.tipo_documento,
        titular_documento=titular(req, datos, usuario), estado_validacion='Aprobado',
        origen__isnull=True,
    ).filter(Q(contenido_pdf__isnull=False) | ~Q(archivo='')).defer('contenido_pdf').order_by('-fecha_subida', '-pk')
    for archivo in candidatos:
        if archivo.nombre_pdf:
            return archivo
        if archivo.archivo and archivo.archivo.storage.exists(archivo.archivo.name):
            return archivo
    return None


def validar_fotografias(archivo):
    FileExtensionValidator(('pdf', 'jpg', 'jpeg', 'png'))(archivo)
    if archivo.size > 5 * 1024 * 1024:
        raise forms.ValidationError('El archivo supera los 5 MB.')
    if archivo.name.lower().endswith('.pdf'):
        validar_pdf_clinico(archivo)
        return
    try:
        imagen = Image.open(archivo)
        if imagen.format not in ('JPEG', 'PNG'):
            raise forms.ValidationError('Selecciona fotografías JPG, PNG o PDF.')
        imagen.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise forms.ValidationError('La imagen no se puede leer.') from None
    finally:
        archivo.seek(0)


class DocumentosProveedorForm(forms.Form):
    def __init__(self, *args, requisitos, datos, usuario, existentes, **kwargs):
        super().__init__(*args, **kwargs)
        self.documentos = []
        for req in requisitos:
            existente = existentes.get(req.pk)
            editable = not existente or existente.estado_validacion == 'Rechazado'
            previo = reutilizable(req, datos, usuario) if not existente else None
            nombre = f'req_{req.pk}'
            if editable:
                self.fields[nombre] = forms.FileField(
                    label=req.descripcion, required=previo is None,
                    validators=[validar_fotografias if req.es_fotografia else validar_pdf_clinico],
                    widget=forms.ClearableFileInput(attrs={
                        'accept': '.pdf,.jpg,.jpeg,.png' if req.es_fotografia else '.pdf',
                    }),
                )
            self.documentos.append({
                'requisito': req, 'campo': self[nombre] if editable else None,
                'existente': existente, 'previo': previo,
            })


def validada(solicitud):
    datos = solicitud.datos_proveedor
    if not datos.get('rfc') or datos.get('tipo_persona') not in dict(Ciudadano.TIPOS_PERSONA):
        return False
    ids = {r.pk for r in requisitos_aplicables(solicitud.tramite, datos)}
    archivos = list(solicitud.archivos.filter(requisito_id__in=ids).values_list('requisito_id', 'estado_validacion'))
    return bool(ids) and ids == {pk for pk, estado in archivos if estado == 'Aprobado'} and all(
        estado == 'Aprobado' for _, estado in archivos
    )


@never_cache
def iniciar(request, tramite, solicitud=None):
    perfil = PerfilProveedorForm(
        request.POST if request.method == 'POST' else None,
        initial={campo: getattr(request.user, campo) for campo in PerfilProveedorForm.base_fields},
    )
    existentes = {}
    if solicitud:
        existentes = {a.requisito_id: a for a in solicitud.archivos.select_related('origen').defer('contenido_pdf')}
    datos = solicitud.datos_proveedor if solicitud else None
    perfil_valido = perfil.is_valid() if request.method == 'POST' and not datos else False
    if perfil_valido:
        datos = perfil.cleaned_data.copy()
        datos['nombre_proveedor'] = datos['razon_social'] or f'{request.user.nombre} {request.user.apellidos}'.strip()
        datos['curp_representante'] = request.user.pk
    documentos = None
    editable = solicitud is None or solicitud.estado == 'Rechazado'
    if solicitud and hasattr(solicitud, 'cita'):
        editable = False
    if datos:
        requisitos = requisitos_aplicables(tramite, datos)
        if not requisitos:
            raise Http404('No se han configurado los requisitos del proveedor.')
        enviar = request.method == 'POST' and request.POST.get('accion') == 'enviar'
        documentos = DocumentosProveedorForm(
            request.POST if enviar else None, request.FILES if enviar else None,
            requisitos=requisitos, datos=datos, usuario=request.user, existentes=existentes,
        )
        if enviar and editable and documentos.is_valid():
            era_nueva = solicitud is None
            with transaction.atomic():
                Ciudadano.objects.select_for_update().get(pk=request.user.pk)
                if solicitud:
                    solicitud = Solicitud.objects.select_for_update().get(pk=solicitud.pk)
                    if solicitud.estado != 'Rechazado' or hasattr(solicitud, 'cita'):
                        raise PermissionDenied
                else:
                    activa = Solicitud.objects.filter(
                        ciudadano=request.user, tramite=tramite, datos_proveedor__rfc=datos['rfc'],
                    ).exclude(cita__estado__in=('Atendida', 'Cancelada', 'Reprogramada')).first()
                    if activa:
                        return redirect('corregir_solicitud', activa.pk)
                    solicitud = Solicitud(
                        ciudadano=request.user, tramite=tramite, datos_proveedor=datos,
                        folio=f'TRAM-{uuid4().hex[:15].upper()}',
                    )
                solicitud.estado = 'Pendiente'
                solicitud.save()
                for item in documentos.documentos:
                    campo, req = item['campo'], item['requisito']
                    if campo is None:
                        continue
                    nuevo = documentos.cleaned_data[campo.name]
                    previo = item['previo']
                    archivo = item['existente']
                    # Los vínculos son inmutables. Al corregir se crea una revisión nueva si ya tiene vínculos.
                    if archivo and archivo.vinculos.exists():
                        raise PermissionDenied('Este archivo ya está vinculado a otro trámite.')
                    if archivo is None:
                        archivo = ArchivoRequisito(solicitud=solicitud, requisito=req)
                    archivo.origen = None
                    archivo.archivo = ''
                    archivo.nombre_pdf = ''
                    archivo.contenido_pdf = None
                    if nuevo:
                        archivo.nombre_pdf = nuevo.name
                        archivo.contenido_pdf = nuevo.read()
                    else:
                        previo = ArchivoRequisito.objects.select_for_update().get(pk=previo.pk)
                        if (previo.estado_validacion != 'Aprobado' or previo.origen_id
                                or previo.solicitud.ciudadano_id != request.user.pk
                                or previo.tipo_documento != req.tipo_documento
                                or previo.titular_documento != titular(req, datos, request.user)):
                            documentos.add_error(campo.name, 'El documento requiere una nueva revisión. Recarga la página.')
                            transaction.set_rollback(True)
                            break
                        archivo.origen = previo
                    archivo.tipo_documento = req.tipo_documento
                    archivo.titular_documento = titular(req, datos, request.user)
                    archivo.estado_validacion = 'Pendiente'
                    archivo.observaciones = ''
                    archivo.save()
                else:
                    Ciudadano.objects.filter(pk=request.user.pk).update(**{
                        campo: datos[campo] for campo in PerfilProveedorForm.base_fields
                    })
                    messages.success(request, f'Alta de proveedor {solicitud.folio} enviada a revisión.')
                    return redirect('mis_tramites')
            if era_nueva:
                solicitud = None
        elif enviar and not editable:
            raise PermissionDenied
    return render(request, 'ventanilla/alta_proveedor.html', {
        'tramite': tramite, 'solicitud': solicitud, 'perfil': perfil, 'datos': datos,
        'documentos': documentos, 'editable': editable,
    })


@never_cache
def revisar(request, solicitud):
    with transaction.atomic():
        if request.method == 'POST':
            solicitud = Solicitud.objects.select_for_update().get(pk=solicitud.pk)
        requisitos = requisitos_aplicables(solicitud.tramite, solicitud.datos_proveedor)
        archivos = list(solicitud.archivos.filter(requisito__in=requisitos).select_related('requisito', 'origen').defer('contenido_pdf'))
        if request.method == 'POST' and not hasattr(solicitud, 'cita'):
            for archivo in archivos:
                estado = request.POST.get(f'estado_doc_{archivo.pk}')
                if estado in dict(ArchivoRequisito.ESTADO_DOC_CHOICES):
                    archivo.estado_validacion = estado
                    archivo.observaciones = request.POST.get(f'obs_doc_{archivo.pk}', '').strip()
                    archivo.save(update_fields=['estado_validacion', 'observaciones'])
            solicitud.estado = 'Aprobado' if validada(solicitud) else (
                'Rechazado' if any(a.estado_validacion == 'Rechazado' for a in archivos) else 'En proceso'
            )
            solicitud.save(update_fields=['estado'])
            return redirect('panel_funcionario')
    return render(request, 'ventanilla/revisar_proveedor.html', {'solicitud': solicitud, 'archivos': archivos})


@require_GET
@never_cache
def descargar(request, pk):
    if not request.user.is_authenticated:
        raise Http404
    acceso = Q(solicitud__ciudadano=request.user)
    if puede_validar(request.user):
        acceso |= Q(solicitud__tramite__es_alta_proveedor=True)
    archivo = get_object_or_404(
        ArchivoRequisito.objects.select_related('solicitud__tramite').filter(acceso), pk=pk,
    )
    original = archivo.origen or archivo
    if original.solicitud.ciudadano_id != archivo.solicitud.ciudadano_id:
        raise Http404
    if original.nombre_pdf and original.contenido_pdf is not None:
        nombre = original.nombre_pdf
        tipo = 'application/pdf'
        if nombre.lower().endswith(('.jpg', '.jpeg')):
            tipo = 'image/jpeg'
        elif nombre.lower().endswith('.png'):
            tipo = 'image/png'
        return FileResponse(BytesIO(original.contenido_pdf), filename=nombre, content_type=tipo)
    if original.archivo:
        try:
            return FileResponse(original.archivo.open('rb'), as_attachment=True)
        except FileNotFoundError:
            pass
    raise Http404


@never_cache
def agendar(request, solicitud):
    if hasattr(solicitud, 'cita'):
        return redirect('ticket_proveedor', solicitud.pk)
    if not validada(solicitud):
        messages.error(request, 'Administración debe validar todos los documentos para habilitar la cita.')
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
                    return redirect('ticket_proveedor', solicitud.pk)
                if (
                    solicitud.estado == 'Aprobado' and validada(solicitud)
                    and citas_medicas.en_ventana(fecha, hora, timezone.localtime())
                    and (fecha.weekday(), hora) in set(servicio_social._horarios(tramite))
                    and not Cita.objects.filter(tramite=tramite, fecha=fecha, hora=hora)
                    .exclude(estado__in=('Cancelada', 'Reprogramada')).exists()
                ):
                    Cita.objects.create(
                        solicitud=solicitud, tramite=tramite, ciudadano_id=solicitud.ciudadano_id,
                        fecha=fecha, hora=hora, folio_cita=f'CITA-{uuid4().hex[:15].upper()}',
                    )
                    return redirect('ticket_proveedor', solicitud.pk)
        error = 'Ese turno ya no está disponible. Selecciona otro horario.'
    return render(request, 'ventanilla/cita_medica_agenda.html', {
        'solicitud': solicitud, 'error': error, 'titulo_agenda': 'Cita de alta de proveedor',
        'dias': citas_medicas.calendario(
            solicitud.tramite, timezone.localtime(), list(servicio_social._horarios(solicitud.tramite)),
        ),
    })
