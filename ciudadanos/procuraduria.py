from datetime import datetime, timedelta
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import (
    ArchivoRequisito, AtencionSocial, Cita, Ciudadano, DocumentoSocial, HorarioSocial,
    PersonaSocial, RequisitoSocial, SedeSocial, Solicitud, Tramite, TurnoSocial, validar_pdf_clinico,
)
from .social_forms import (
    CONTACTO, EntrevistaForm, FamiliaFormSet, IdentificacionForm, datos_cuenta, serializable,
)

DOCUMENTOS = {
    'comprobante_domicilio': 'Comprobante de domicilio (agua, luz o teléfono), hasta tres meses',
    'comprobante_ingresos': 'Comprobante de ingresos de hasta tres meses',
    'identificacion_oficial': 'Identificación vigente del peticionario (INE, pasaporte o cédula profesional)',
    'solicitud_institucion': 'Hoja de solicitud del estudio expedida por la institución',
    'comprobante_estudios': 'Última boleta de calificaciones o comprobante de estudios',
    'oficio_judicial': 'Oficio judicial dirigido a la Procuraduría, solicitando el estudio',
}
TEMPORALES = ('comprobante_domicilio', 'comprobante_ingresos')


def revisar_permitido(user):
    return user.is_authenticated and user.is_active and user.is_staff and user.has_perm('ciudadanos.revisar_procuraduria')


def atender_permitido(user, servicio):
    permiso = 'atender_psicologia' if servicio == 'psicologia' else 'atender_socioeconomico'
    return user.is_authenticated and user.is_active and user.is_staff and user.has_perm(f'ciudadanos.{permiso}')


def filtro_personal(user):
    from django.db.models import Q
    filtro = Q(pk__in=[])
    for servicio in ('psicologia', 'socioeconomico'):
        if atender_permitido(user, servicio):
            filtro |= Q(tramite__servicio_procuraduria=servicio)
    if revisar_permitido(user):
        filtro |= Q(tramite__servicio_procuraduria='socioeconomico')
    return filtro


def domicilio(datos):
    return ', '.join(str(datos.get(n) or '') for n in (
        'calle', 'numero', 'numero_interior', 'colonia', 'municipio', 'estado_domicilio', 'cp',
    ))


def contexto(solicitud, tipo):
    if tipo == 'identificacion_oficial':
        valor = f'peticionario:{solicitud.ciudadano_id}'
    elif tipo in TEMPORALES:
        valor = domicilio(solicitud.datos_sociales).strip().casefold()
    else:
        valor = f'{solicitud.persona_social_id}:{solicitud.datos_sociales.get("referencia", "").strip().casefold()}:{tipo}'
    return sha256(valor.encode()).hexdigest()


def tipos_requeridos(solicitud):
    if solicitud.tramite.servicio_procuraduria == 'psicologia':
        return []
    tipos = [*TEMPORALES, 'identificacion_oficial']
    modalidad = solicitud.datos_sociales.get('modalidad', 'general')
    tipos.append('oficio_judicial' if modalidad == 'judicial' else 'solicitud_institucion')
    if modalidad == 'beca':
        tipos.append('comprobante_estudios')
    return tipos


def apta(solicitud):
    if not solicitud.persona_social_id:
        return False
    enlaces = {r.tipo: r for r in solicitud.requisitos_sociales.select_related('documento')}
    return all(
        tipo in enlaces and enlaces[tipo].documento.contexto == contexto(solicitud, tipo)
        and enlaces[tipo].documento.estado == 'Aprobado'
        for tipo in tipos_requeridos(solicitud)
    )


def _encontrar_documento(solicitud, tipo):
    qs = DocumentoSocial.objects.filter(
        responsable=solicitud.ciudadano, contexto=contexto(solicitud, tipo), tipo=tipo,
    ).defer('contenido').order_by('-validado', '-creado')
    for doc in qs:
        if doc.estado == 'Aprobado':
            return doc
    return None


@never_cache
def iniciar(request, tramite):
    propias = request.user.personas_sociales.all()
    seleccion = request.GET.get('persona') or request.POST.get('persona') or 'titular'
    persona = None
    if seleccion not in ('titular', 'nueva'):
        persona = get_object_or_404(propias, pk=seleccion)
    elif seleccion == 'titular':
        persona = propias.filter(clave='titular').first()
    psicologia = tramite.servicio_procuraduria == 'psicologia'
    inicial = persona.datos.copy() if persona else datos_cuenta(request.user) if seleccion == 'titular' else {
        'telefono': request.user.telefono_cel or request.user.telefono_casa, 'correo': request.user.email,
    }
    if persona:
        inicial.update(nombre=persona.nombre, curp=persona.curp, parentesco=persona.parentesco,
                       fecha_nacimiento=persona.fecha_nacimiento)
    if psicologia:
        inicial['municipio'] = inicial.get('municipio') or 'Atizapán de Zaragoza'
        inicial['estado_domicilio'] = inicial.get('estado_domicilio') or 'Estado de México'
    inicial['modalidad'] = 'general'
    campos_faltantes = [
        n for n in IdentificacionForm.base_fields
        if not inicial.get(n) and n not in ('curp', 'rfc_personal', 'numero_interior', 'correo', 'referencia', 'modalidad')
    ]
    formulario = IdentificacionForm(
        request.POST if request.method == 'POST' else None, initial=inicial, psicologia=psicologia,
    )
    if request.method == 'POST' and formulario.is_valid():
        datos = {**serializable(inicial), **serializable(formulario.cleaned_data)}
        if psicologia:
            datos.pop('modalidad', None)
            datos.pop('referencia', None)
        with transaction.atomic():
            Ciudadano.objects.select_for_update().get(pk=request.user.pk)
            if persona is None:
                clave = 'titular' if seleccion == 'titular' else datos['curp'] or uuid4().hex
                persona = propias.filter(clave=clave).first()
                if persona is None:
                    persona = PersonaSocial(responsable=request.user, clave=clave)
            persona.nombre = datos['nombre']
            persona.curp = datos['curp']
            if persona.clave == 'titular':
                persona.curp = request.user.pk
                datos['curp'] = request.user.pk
                datos['parentesco'] = 'Titular'
            persona.fecha_nacimiento = formulario.cleaned_data['fecha_nacimiento']
            persona.parentesco = datos['parentesco']
            persona.datos = datos
            persona.save()
            if persona.clave == 'titular':
                Ciudadano.objects.filter(pk=request.user.pk).update(**{
                    n: datos[n] for n in ('calle', 'numero', 'numero_interior', 'colonia', 'municipio', 'estado_domicilio', 'cp')
                })
            activa = Solicitud.objects.filter(
                ciudadano=request.user, tramite=tramite, persona_social=persona,
            ).exclude(cita__estado__in=('Atendida', 'Cancelada', 'Reprogramada')).exclude(estado='Rechazado').first()
            if activa:
                return redirect('social_agenda' if psicologia else 'social_solicitud', activa.pk)
            solicitud = Solicitud.objects.create(
                ciudadano=request.user, tramite=tramite, persona_social=persona, datos_sociales=datos,
                estado='Aprobado' if psicologia else 'Pendiente', folio=f'TRAM-{uuid4().hex[:15].upper()}',
            )
            for tipo in tipos_requeridos(solicitud):
                doc = _encontrar_documento(solicitud, tipo) or _importar_antiguo(solicitud, tipo)
                if doc:
                    RequisitoSocial.objects.create(solicitud=solicitud, tipo=tipo, documento=doc, reutilizado=True)
            if not psicologia and apta(solicitud):
                solicitud.estado = 'Aprobado'
                solicitud.save(update_fields=['estado'])
        return redirect('social_agenda' if psicologia or solicitud.estado == 'Aprobado' else 'social_solicitud', solicitud.pk)
    grupos = []
    etiquetas = {
        'nombre': 'Nombre completo', 'curp': 'CURP', 'fecha_nacimiento': 'Fecha de nacimiento',
        'parentesco': 'Persona atendida', 'telefono': 'Teléfono', 'correo': 'Correo electrónico',
        'rfc_personal': 'RFC personal',
    }
    for nombre, campo in formulario.fields.items():
        if nombre not in ('modalidad', 'referencia') and inicial.get(nombre) and not request.GET.get('editar') and not formulario.is_bound:
            campo.widget = forms.HiddenInput()
            grupos.append((etiquetas.get(nombre) or campo.label or nombre.replace('_', ' ').capitalize(), inicial[nombre]))
    return render(request, 'ventanilla/social_inicio.html', {
        'tramite': tramite, 'formulario': formulario, 'personas': propias, 'seleccion': seleccion,
        'grupos': grupos, 'faltantes': campos_faltantes,
    })


def _importar_antiguo(solicitud, tipo):
    # Los archivos históricos se vinculan sin duplicarlos y pasan a revisión del personal.
    if tipo != 'identificacion_oficial' and solicitud.persona_social.clave != 'titular':
        return None
    descripciones = {
        'comprobante_domicilio': ('Comprobante de domicilio', 'Comprobante de domicilio (no mayor a 3 meses)'),
        'comprobante_ingresos': ('Comprobante de ingresos',),
        'identificacion_oficial': ('Identificación oficial', 'Identificación oficial (INE o credencial escolar)',
                                   'Identificación oficial del propietario o representante legal'),
    }
    from django.db.models import Q
    filtro = Q(requisito__tipo_documento=tipo) | Q(tipo_documento=tipo)
    for texto in descripciones.get(tipo, ()):
        filtro |= Q(requisito__descripcion__iexact=texto)
    candidato = ArchivoRequisito.objects.filter(
        filtro, solicitud__ciudadano=solicitud.ciudadano, estado_validacion='Aprobado', origen__isnull=True,
    ).filter(
        Q(titular_documento='') | Q(titular_documento=f'CURP:{solicitud.ciudadano_id}')
    ).defer('contenido_pdf').order_by('-fecha_subida').first()
    if candidato and (candidato.nombre_pdf or candidato.archivo):
        return DocumentoSocial.objects.create(
            responsable=solicitud.ciudadano, persona=solicitud.persona_social, tipo=tipo,
            contexto=contexto(solicitud, tipo), archivo_original=candidato, nombre=candidato.nombre_pdf or candidato.archivo.name,
        )
    return None


@login_required(login_url='iniciar_sesion')
@never_cache
def solicitud_detalle(request, pk):
    solicitud = get_object_or_404(Solicitud, pk=pk, ciudadano=request.user, persona_social__isnull=False)
    with transaction.atomic():
        if request.method == 'POST':
            solicitud = Solicitud.objects.select_for_update().get(pk=pk)
        enlaces = {r.tipo: r for r in solicitud.requisitos_sociales.select_related('documento').defer('documento__contenido')}
        formulario = forms.Form(request.POST if request.method == 'POST' else None, request.FILES or None)
        editable = solicitud.estado not in ('Rechazado',) and not hasattr(solicitud, 'cita')
        items = []
        for tipo in tipos_requeridos(solicitud):
            enlace = enlaces.get(tipo)
            doc = enlace.documento if enlace else None
            requerido = doc is None or doc.estado in ('Rechazado', 'Requiere corrección')
            if requerido and editable:
                formulario.fields[tipo] = forms.FileField(
                    label=DOCUMENTOS[tipo], validators=[validar_pdf_clinico],
                    widget=forms.FileInput(attrs={'accept': '.pdf,application/pdf'}),
                )
            items.append((DOCUMENTOS[tipo], tipo, doc, enlace.reutilizado if enlace else False))
        if request.method == 'POST' and request.POST.get('accion') == 'vincular':
            if not editable:
                raise PermissionDenied
            for _, tipo, doc, _ in items:
                if doc is None:
                    reutilizado = _encontrar_documento(solicitud, tipo)
                    anterior = reutilizado or _importar_antiguo(solicitud, tipo)
                    if anterior:
                        RequisitoSocial.objects.update_or_create(
                            solicitud=solicitud, tipo=tipo, defaults={'documento': anterior, 'reutilizado': True},
                        )
            return redirect('social_solicitud', pk)
        if request.method == 'POST' and request.POST.get('accion') == 'enviar':
            if not editable:
                raise PermissionDenied
            if formulario.is_valid():
                for tipo in formulario.fields:
                    archivo = formulario.cleaned_data[tipo]
                    doc = DocumentoSocial.objects.create(
                        responsable=request.user, persona=solicitud.persona_social, tipo=tipo,
                        contexto=contexto(solicitud, tipo), contenido=archivo.read(), nombre=archivo.name,
                    )
                    RequisitoSocial.objects.update_or_create(
                        solicitud=solicitud, tipo=tipo, defaults={'documento': doc, 'reutilizado': False},
                    )
                solicitud.estado = 'Aprobado' if apta(solicitud) else 'En revisión'
                solicitud.save(update_fields=['estado'])
                return redirect('social_solicitud', pk)
    return render(request, 'ventanilla/social_solicitud.html', {
        'solicitud': solicitud, 'formulario': formulario, 'items': items, 'editable': editable,
        'lista_agenda': apta(solicitud) and solicitud.estado == 'Aprobado',
    })


class ValidacionDocumentoForm(forms.Form):
    estado = forms.ChoiceField(label='Validación', choices=ArchivoRequisito.ESTADO_DOC_CHOICES)
    observaciones = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, documento, **kwargs):
        self.documento = documento
        super().__init__(*args, **kwargs)
        self.initial['estado'] = {
            'En revisión': 'Pendiente', 'Requiere corrección': 'Rechazado',
        }.get(documento.estado, documento.estado)


@never_cache
def revisar(request, pk):
    if not revisar_permitido(request.user):
        raise PermissionDenied
    solicitud = get_object_or_404(Solicitud, pk=pk, tramite__servicio_procuraduria='socioeconomico')
    with transaction.atomic():
        if request.method == 'POST':
            solicitud = Solicitud.objects.select_for_update().get(pk=pk)
        enlaces = list(solicitud.requisitos_sociales.select_related('documento'))
        formularios = []
        for enlace in enlaces:
            doc = enlace.documento
            if request.method == 'POST':
                doc = DocumentoSocial.objects.select_for_update().get(pk=doc.pk)
            form = ValidacionDocumentoForm(
                request.POST if request.method == 'POST' else None, documento=doc, prefix=f'doc{doc.pk}',
                initial={n: getattr(doc, n) for n in ValidacionDocumentoForm.base_fields},
            )
            if hasattr(solicitud, 'cita'):
                for campo in form.fields.values():
                    campo.disabled = True
            formularios.append((DOCUMENTOS[enlace.tipo], enlace, form))
        rechazo = request.POST.get('rechazar') == '1'
        error = ''
        if request.method == 'POST' and not hasattr(solicitud, 'cita'):
            if rechazo:
                motivo = request.POST.get('motivo_rechazo', '').strip()
                if not motivo:
                    error = 'Escribe el motivo del rechazo de la solicitud.'
                else:
                    solicitud.datos_sociales = {**solicitud.datos_sociales, 'motivo_rechazo': motivo}
                    solicitud.estado = 'Rechazado'
                    solicitud.save(update_fields=['datos_sociales', 'estado'])
                    return redirect('panel_funcionario')
            elif formularios and all([form.is_valid() for _, _, form in formularios]):
                for _, enlace, form in formularios:
                    doc = form.documento
                    for n, valor in form.cleaned_data.items():
                        setattr(doc, n, valor)
                    doc.revisor = request.user
                    doc.validado = timezone.now()
                    doc.save()
                documentos = [f.documento for _, _, f in formularios]
                solicitud.estado = 'Aprobado' if apta(solicitud) else (
                    'Requiere corrección' if any(d.estado in ('Rechazado', 'Requiere corrección') for d in documentos)
                    else 'En revisión'
                )
                solicitud.save(update_fields=['estado'])
                return redirect('panel_funcionario')
    return render(request, 'ventanilla/social_revisar.html', {
        'solicitud': solicitud, 'formularios': formularios, 'error': error,
    })


def _turnos(tramite, sede, fecha):
    for horario in HorarioSocial.objects.filter(tramite=tramite, sede=sede, dia=fecha.weekday()):
        if not horario.duracion:
            continue
        inicio = datetime.combine(fecha, horario.inicio)
        fin = datetime.combine(fecha, horario.fin)
        while inicio + timedelta(minutes=horario.duracion) <= fin:
            yield inicio.time(), horario.cupo
            inicio += timedelta(minutes=horario.duracion)


@login_required(login_url='iniciar_sesion')
@never_cache
def agenda(request, pk):
    solicitud = get_object_or_404(Solicitud.objects.select_related('tramite', 'persona_social'), pk=pk, ciudadano=request.user)
    if not solicitud.tramite.servicio_procuraduria:
        raise Http404
    if hasattr(solicitud, 'cita'):
        return redirect('social_ticket', solicitud.cita.pk)
    if solicitud.estado != 'Aprobado' or not apta(solicitud):
        return redirect('social_solicitud', pk)
    sedes = SedeSocial.objects.filter(activa=True, horariosocial__tramite=solicitud.tramite).distinct()
    sede_id = request.GET.get('sede') or request.POST.get('sede')
    sede = get_object_or_404(sedes, pk=sede_id) if sede_id else sedes.first()
    error = ''
    ahora = timezone.localtime()
    if request.method == 'POST' and sede:
        from .citas_medicas import en_ventana, leer_turno
        elegido = leer_turno(request.POST.get('turno', ''))
        if elegido:
            fecha, hora = elegido
            with transaction.atomic():
                # El bloqueo de sede serializa reservas y cambios de cupo en espacios ya creados.
                sede = SedeSocial.objects.select_for_update().get(pk=sede.pk)
                solicitud = Solicitud.objects.select_for_update().get(pk=pk)
                if hasattr(solicitud, 'cita'):
                    return redirect('social_ticket', solicitud.cita.pk)
                cupo = dict(_turnos(solicitud.tramite, sede, fecha)).get(hora, 0)
                if cupo and en_ventana(fecha, hora, ahora):
                    turno, _ = TurnoSocial.objects.get_or_create(
                        tramite=solicitud.tramite, sede=sede, fecha=fecha, hora=hora,
                    )
                    ocupadas = turno.cita_set.exclude(estado__in=('Cancelada', 'Reprogramada')).count()
                    if (sede.activa and solicitud.estado == 'Aprobado' and apta(solicitud)
                            and ocupadas < cupo):
                        cita = Cita.objects.create(
                            solicitud=solicitud, tramite=solicitud.tramite, ciudadano=request.user,
                            turno_social=turno, fecha=fecha, hora=hora, folio_cita=f'CITA-{uuid4().hex[:15].upper()}',
                        )
                        return redirect('social_ticket', cita.pk)
        error = 'El turno seleccionado ya no tiene cupo. Selecciona otro horario.'
    dias = []
    if sede:
        for i in range(28):
            fecha = ahora.date() + timedelta(days=i)
            horarios = []
            for hora, cupo in _turnos(solicitud.tramite, sede, fecha):
                if (fecha, hora) <= (ahora.date(), ahora.time()):
                    continue
                ocupadas = Cita.objects.filter(
                    turno_social__tramite=solicitud.tramite, turno_social__sede=sede, fecha=fecha, hora=hora,
                ).exclude(estado__in=('Cancelada', 'Reprogramada')).count()
                horarios.append((hora, ocupadas >= cupo))
            if horarios:
                dias.append((fecha, horarios))
    return render(request, 'ventanilla/social_agenda.html', {
        'solicitud': solicitud, 'sedes': sedes, 'sede': sede, 'dias': dias, 'error': error,
    })


@login_required(login_url='iniciar_sesion')
@never_cache
def ticket(request, pk):
    cita = get_object_or_404(
        Cita.objects.select_related('solicitud__persona_social', 'turno_social__sede', 'tramite'),
        pk=pk, ciudadano=request.user, turno_social__isnull=False,
    )
    return render(request, 'ventanilla/social_ticket.html', {'cita': cita})


@login_required(login_url='iniciar_sesion')
@require_GET
@never_cache
def documento(request, pk):
    doc = get_object_or_404(DocumentoSocial, pk=pk)
    if request.user.pk != doc.responsable_id and not revisar_permitido(request.user):
        raise Http404
    if doc.archivo_original_id:
        archivo = doc.archivo_original.origen or doc.archivo_original
        if archivo.solicitud.ciudadano_id != doc.responsable_id:
            raise Http404
        if archivo.contenido_pdf is not None:
            contenido = bytes(archivo.contenido_pdf)
        else:
            try:
                contenido = archivo.archivo.open('rb').read()
            except FileNotFoundError:
                raise Http404 from None
    else:
        contenido = bytes(doc.contenido or b'')
    return FileResponse(BytesIO(contenido), content_type='application/pdf', filename=doc.nombre, as_attachment=False)


@never_cache
def atender(request, pk):
    cita = get_object_or_404(Cita.objects.select_related('solicitud__persona_social', 'tramite'), pk=pk, turno_social__isnull=False)
    servicio = cita.tramite.servicio_procuraduria
    if not atender_permitido(request.user, servicio):
        raise PermissionDenied
    identidad = cita.solicitud.datos_sociales.copy()
    persona = cita.solicitud.persona_social
    entrevista = AtencionSocial.objects.filter(cita=cita).first()
    anterior = AtencionSocial.objects.filter(
        cita__solicitud__persona_social=persona, cita__tramite__servicio_procuraduria=servicio,
        finalizada__isnull=False,
    ).order_by('-finalizada').first()
    inicial = entrevista.datos.copy() if entrevista else anterior.datos.copy() if anterior else {}
    if entrevista is None:
        for n in ('sexo', 'escolaridad', 'estado_civil', 'ocupacion'):
            if not inicial.get(n):
                inicial[n] = persona.datos.get(n, '')
        for n in ('pago_realizado', 'importe', 'fecha_pago', 'recibo', 'libro_gobierno'):
            inicial.pop(n, None)
    finalizar = request.method == 'POST' and request.POST.get('accion') == 'finalizar'
    form = EntrevistaForm(request.POST if request.method == 'POST' else None, initial=inicial, servicio=servicio, finalizando=finalizar)
    familia = FamiliaFormSet(
        request.POST if request.method == 'POST' else None,
        prefix='familia', initial=inicial.get('familia', []),
    ) if servicio == 'socioeconomico' else None
    error = ''
    if request.method == 'POST':
        if cita.estado not in ('Programada', 'Atendida') or cita.fecha > timezone.localdate():
            raise PermissionDenied('La atención se registra a partir del día de la cita.')
        if form.is_valid() and (familia is None or familia.is_valid()):
            datos = serializable(form.cleaned_data)
            if familia:
                datos['familia'] = [serializable(f.cleaned_data) for f in familia if f.cleaned_data and not f.cleaned_data.get('DELETE')]
            with transaction.atomic():
                cita = Cita.objects.select_for_update().get(pk=cita.pk)
                entrevista, _ = AtencionSocial.objects.get_or_create(cita=cita)
                if entrevista.finalizada:
                    return redirect('social_atender', pk)
                entrevista.datos = datos
                entrevista.identificacion = identidad
                entrevista.funcionario = request.user
                entrevista.save()
            if finalizar:
                try:
                    from .social_documentos import generar
                    word, pdf = generar(entrevista)
                except (RuntimeError, OSError, ValueError) as exc:
                    import logging
                    logging.getLogger(__name__).exception('Fallo al generar documentos de atención %s', entrevista.pk)
                    error = 'El borrador está guardado. No fue posible generar los documentos. Puedes volver a finalizar.'
                else:
                    with transaction.atomic():
                        cita = Cita.objects.select_for_update().get(pk=cita.pk)
                        actual = AtencionSocial.objects.select_for_update().get(pk=entrevista.pk)
                        if not actual.finalizada and actual.actualizado == entrevista.actualizado:
                            actual.word, actual.pdf = word, pdf
                            actual.finalizada = timezone.now()
                            actual.version += 1
                            actual.save()
                            cita.estado = 'Atendida'
                            cita.funcionario = request.user
                            cita.save(update_fields=['estado', 'funcionario'])
                            for n in ('sexo', 'escolaridad', 'estado_civil', 'ocupacion'):
                                if datos.get(n):
                                    persona.datos[n] = datos[n]
                            persona.save(update_fields=['datos', 'actualizado'])
                        elif not actual.finalizada:
                            error = 'Otro funcionario actualizó el borrador. Recarga la atención antes de finalizar.'
                    if not error:
                        return redirect('social_atender', pk)
            else:
                messages.success(request, 'Borrador guardado.')
                return redirect('social_atender', pk)
    return render(request, 'ventanilla/social_atender.html', {
        'cita': cita, 'entrevista': entrevista, 'formulario': form, 'familia': familia,
        'identidad': identidad, 'error': error,
    })


@login_required(login_url='iniciar_sesion')
@require_GET
@never_cache
def formato(request, pk, extension):
    entrevista = get_object_or_404(AtencionSocial, pk=pk, finalizada__isnull=False)
    if request.user.pk != entrevista.cita.ciudadano_id and not atender_permitido(
        request.user, entrevista.cita.tramite.servicio_procuraduria,
    ):
        raise Http404
    if extension not in ('pdf', 'docx'):
        raise Http404
    contenido = entrevista.pdf if extension == 'pdf' else entrevista.word
    tipo = 'application/pdf' if extension == 'pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    return FileResponse(
        BytesIO(bytes(contenido)), filename=f'{entrevista.cita.folio_cita}.{extension}', content_type=tipo,
        as_attachment=extension == 'docx' or request.GET.get('descargar') == '1',
    )
