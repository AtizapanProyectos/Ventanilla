from io import BytesIO

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.validators import MaxLengthValidator
from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from .historia_pdf import generar_historia
from .models import Cita, ConsultaClinica, DocumentoClinico, ExpedienteClinico, validar_pdf_clinico


def personal_clinico(user):
    return user.is_authenticated and user.is_active and user.is_staff and user.has_perms((
        'ciudadanos.view_cita', 'ciudadanos.view_expedienteclinico',
    ))


class ConsultaForm(forms.ModelForm):
    VITALES = (
        'peso_kg', 'talla_m', 'tension_arterial', 'frecuencia_cardiaca', 'frecuencia_respiratoria',
        'temperatura_c', 'saturacion_oxigeno', 'glucosa_mg_dl', 'signos_vitales',
    )
    GRUPOS = (
        ('revision_sistemas', ConsultaClinica.SISTEMAS),
        ('revision_regiones', ConsultaClinica.REGIONES),
    )

    class Meta:
        model = ConsultaClinica
        fields = (
            'padecimiento_actual', 'diagnostico', 'acciones_linea_vida', 'pronostico',
            'indicaciones_especiales', 'tratamiento', 'medico', 'cedula_profesional',
            'interrogatorio', 'signos_vitales', 'habitus_exterior', 'exploracion_regiones',
            'peso_kg', 'talla_m', 'tension_arterial', 'frecuencia_cardiaca', 'frecuencia_respiratoria',
            'temperatura_c', 'saturacion_oxigeno', 'glucosa_mg_dl',
            'resultados', 'guia_clinica',
        )
        labels = {
            'padecimiento_actual': 'Motivo de atención', 'diagnostico': 'Análisis del caso',
            'acciones_linea_vida': 'Acciones realizadas', 'pronostico': 'Resolución',
            'indicaciones_especiales': 'Observaciones', 'tratamiento': 'Recomendaciones',
            'interrogatorio': 'Notas generales por aparatos y sistemas',
            'exploracion_regiones': 'Notas generales de exploración por regiones',
            'signos_vitales': 'Notas sobre signos vitales',
        }
        widgets = {
            nombre: forms.Textarea(attrs={'rows': 3})
            for nombre in (
                'padecimiento_actual', 'diagnostico', 'acciones_linea_vida', 'pronostico',
                'indicaciones_especiales', 'tratamiento', 'interrogatorio', 'signos_vitales',
                'habitus_exterior', 'exploracion_regiones', 'resultados', 'guia_clinica',
            )
        }

    def __init__(self, *args, expediente, **kwargs):
        super().__init__(*args, **kwargs)
        for nombre in ExpedienteClinico.CAMPOS_ANTECEDENTES:
            self.fields[nombre] = ExpedienteClinico._meta.get_field(nombre).formfield(
                widget=forms.Textarea(attrs={'rows': 3}),
            )
            self.initial[nombre] = getattr(expediente, nombre)
        for nombre in ('padecimiento_actual', 'diagnostico', 'acciones_linea_vida', 'pronostico'):
            self.fields[nombre].required = True
        for campo in self.fields.values():
            if isinstance(campo.widget, forms.Textarea):
                campo.max_length = 4000
                campo.validators.append(MaxLengthValidator(4000))
                campo.widget.attrs['maxlength'] = 4000
        for grupo, campos in self.GRUPOS:
            valores = getattr(self.instance, grupo)
            for nombre, etiqueta in campos:
                self.fields[f'{grupo}_{nombre}'] = forms.CharField(
                    label=etiqueta, required=False, max_length=500,
                    widget=forms.Textarea(attrs={'rows': 2}), initial=valores.get(nombre, ''),
                )

    @property
    def secciones_adicionales(self):
        return (
            ('Antecedentes clínicos', [self[nombre] for nombre in ExpedienteClinico.CAMPOS_ANTECEDENTES]),
            ('Signos vitales', [self[nombre] for nombre in self.VITALES]),
            ('Interrogatorio por aparatos y sistemas', [
                *[self[f'revision_sistemas_{nombre}'] for nombre, _ in ConsultaClinica.SISTEMAS],
                self['interrogatorio'],
            ]),
            ('Exploración por regiones', [
                *[self[f'revision_regiones_{nombre}'] for nombre, _ in ConsultaClinica.REGIONES],
                self['exploracion_regiones'],
            ]),
            ('Exploración general y resultados', [
                self['habitus_exterior'], self['resultados'], self['guia_clinica'],
            ]),
        )

    def save(self, commit=True):
        consulta = super().save(commit=False)
        for grupo, campos in self.GRUPOS:
            valores = {
                nombre: self.cleaned_data[f'{grupo}_{nombre}']
                for nombre, _ in campos if self.cleaned_data[f'{grupo}_{nombre}']
            }
            setattr(consulta, grupo, valores)
        if commit:
            consulta.save()
            self.save_m2m()
        return consulta


class EvidenciaForm(forms.Form):
    archivo = forms.FileField(
        label='Evidencia PDF', help_text='Máximo 5 MB.', validators=[validar_pdf_clinico],
    )


def _puede_capturar(user, consulta):
    permiso = 'change_consultaclinica' if consulta else 'add_consultaclinica'
    return user.has_perms(('ciudadanos.change_cita', f'ciudadanos.{permiso}'))


@never_cache
@require_http_methods(['GET', 'POST'])
def cita_detalle(request, pk):
    if not personal_clinico(request.user):
        raise PermissionDenied

    with transaction.atomic():
        consulta_cita = Cita.objects.filter(pk=pk, tramite__es_cita_medica=True)
        expedientes = ExpedienteClinico.objects.all()
        if request.method == 'POST':
            consulta_cita = consulta_cita.select_for_update()
            expedientes = expedientes.select_for_update()
        cita = get_object_or_404(consulta_cita)
        expediente = get_object_or_404(expedientes, ciudadano_id=cita.ciudadano_id)
        consulta = getattr(cita, 'consulta_clinica', None)
        documento = DocumentoClinico.objects.filter(consulta=consulta).defer('contenido').first() if consulta else None
        disponible = cita.estado in ('Programada', 'Atendida') and not documento
        puede_capturar = disponible and _puede_capturar(request.user, consulta)
        datos = request.POST if request.method == 'POST' else None
        formulario = ConsultaForm(datos, instance=consulta, expediente=expediente)
        if consulta is None:
            medico = f'{request.user.nombre} {request.user.apellidos}'.strip()
            for campo, valor in (('medico', medico), ('cedula_profesional', request.user.cedula_profesional)):
                if valor:
                    formulario.initial[campo] = valor
                    formulario.fields[campo].disabled = True
        if request.method == 'POST' and not documento:
            if not puede_capturar:
                raise PermissionDenied
            if formulario.is_valid():
                consulta = formulario.save(commit=False)
                consulta.cita = cita
                consulta.save()
                antecedentes = [
                    campo for campo in ExpedienteClinico.CAMPOS_ANTECEDENTES if campo in request.POST
                ]
                for campo in antecedentes:
                    setattr(expediente, campo, formulario.cleaned_data[campo])
                if antecedentes:
                    expediente.save(update_fields=antecedentes)
                documento = DocumentoClinico.objects.create(
                    expediente=expediente, consulta=consulta, generado_por=request.user,
                    nombre=f'Historia-clinica-{cita.folio_cita}.pdf',
                    contenido=generar_historia(expediente, consulta),
                )
                cita.estado = 'Atendida'
                cita.funcionario = request.user
                cita.save(update_fields=['estado', 'funcionario'])
                puede_capturar = False
    campos = list(formulario) if puede_capturar else []
    return render(request, 'ventanilla/panel_cita_medica.html', {
        'cita': cita, 'expediente': expediente, 'formulario': formulario,
        'campos_principales': campos[:8],
        'puede_capturar': puede_capturar, 'documento': documento,
        'puede_descargar': request.user.has_perm('ciudadanos.view_documentoclinico'),
    })


@never_cache
@require_http_methods(['GET', 'POST'])
def expediente_detalle(request, pk):
    if not personal_clinico(request.user):
        raise PermissionDenied
    expediente = get_object_or_404(ExpedienteClinico.objects.select_related('ciudadano'), pk=pk)
    puede_adjuntar = request.user.has_perm('ciudadanos.add_documentoclinico')
    evidencia = EvidenciaForm(
        request.POST if request.method == 'POST' else None,
        request.FILES if request.method == 'POST' else None,
    )
    if request.method == 'POST':
        if not puede_adjuntar:
            raise PermissionDenied
        if evidencia.is_valid():
            archivo = evidencia.cleaned_data['archivo']
            DocumentoClinico.objects.create(
                expediente=expediente, nombre=archivo.name, contenido=archivo.read(),
                generado_por=request.user,
            )
            evidencia = EvidenciaForm()
    citas = list(Cita.objects.filter(
        ciudadano=expediente.ciudadano, tramite__es_cita_medica=True,
    ).select_related('tramite', 'consulta_clinica').order_by('-fecha', '-hora'))
    documentos = list(expediente.documentos.defer('contenido').order_by('-fecha_subida'))
    bitacora = [(expediente.creado, 'Se abrió el expediente')]
    bitacora.extend((cita.fecha_creacion, f'Se programó {cita.folio_cita}') for cita in citas)
    bitacora.extend(
        (cita.consulta_clinica.elaborada, f'Se registró la consulta {cita.folio_cita}')
        for cita in citas if hasattr(cita, 'consulta_clinica')
    )
    bitacora.extend((doc.fecha_subida, f'Se incorporó {doc.nombre}') for doc in documentos)
    return render(request, 'ventanilla/panel_expediente_clinico.html', {
        'expediente': expediente, 'citas': citas, 'documentos': documentos,
        'bitacora': sorted(bitacora, reverse=True), 'evidencia': evidencia,
        'puede_adjuntar': puede_adjuntar,
        'puede_descargar': request.user.has_perm('ciudadanos.view_documentoclinico'),
    })


@login_required(login_url='iniciar_sesion')
@never_cache
@require_GET
def documento_descargar(request, pk):
    documentos = DocumentoClinico.objects.all()
    if not (personal_clinico(request.user) and request.user.has_perm('ciudadanos.view_documentoclinico')):
        documentos = documentos.filter(expediente__ciudadano=request.user, consulta__isnull=False)
    documento = get_object_or_404(documentos, pk=pk)
    return FileResponse(
        BytesIO(documento.contenido), as_attachment=True, filename=documento.nombre,
        content_type='application/pdf',
    )
