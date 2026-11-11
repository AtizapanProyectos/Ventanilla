from io import BytesIO

from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html
from .models import *


@admin.register(Ciudadano)
class CiudadanoAdmin(UserAdmin):
    # Como Ciudadano usa curp como PK y no username, hay que sobreescribir
    # los fieldsets/list que UserAdmin trae por defecto
    model = Ciudadano
    list_display = ('curp', 'nombre', 'apellidos', 'email', 'is_active', 'is_staff')
    list_filter = ('is_active', 'is_staff', 'genero')
    search_fields = ('curp', 'nombre', 'apellidos', 'email')
    ordering = ('curp',)

    fieldsets = (
        (None, {'fields': ('curp', 'password')}),
        ('Datos personales', {
            'fields': (
                'nombre', 'apellidos', 'email', 'fecha_nacimiento', 'genero',
                'telefono_cel', 'telefono_casa',
            )
        }),
        ('Domicilio', {
            'fields': ('cp', 'colonia', 'calle', 'numero', 'mz_lt')
        }),
        ('Datos profesionales', {'fields': ('cedula_profesional',)}),
        ('Permisos', {
            'description': 'Para entrar a Django Admin, la cuenta debe estar activa y marcada como staff.',
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')
        }),
        ('Fechas', {'fields': ('fecha_registro', 'last_login')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('curp', 'email', 'nombre', 'apellidos', 'password1', 'password2'),
        }),
    )

    readonly_fields = ('fecha_registro', 'last_login')


@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ('ciudadano', 'archivo_curp', 'fecha_subida', 'verificado')
    list_filter = ('verificado',)
    search_fields = ('ciudadano__curp', 'ciudadano__nombre')


@admin.register(Direccion)
class DireccionAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'descripcion')
    search_fields = ('nombre',)


class RequisitoInline(admin.TabularInline):
    model = Requisito
    extra = 1


class TurnoMedicoInline(admin.TabularInline):
    model = TurnoMedico
    extra = 0


@admin.register(Tramite)
class TramiteAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'direccion', 'tiempo', 'costo', 'modalidad', 'es_cita_medica', 'es_servicio_social')
    list_filter = ('direccion', 'modalidad', 'es_cita_medica', 'es_servicio_social')
    search_fields = ('nombre',)
    inlines = [RequisitoInline, TurnoMedicoInline]


@admin.register(Requisito)
class RequisitoAdmin(admin.ModelAdmin):
    list_display = ('tramite', 'descripcion')
    list_filter = ('tramite',)
    search_fields = ('descripcion',)


class ArchivoRequisitoInline(admin.TabularInline):
    model = ArchivoRequisito
    extra = 0

    def get_queryset(self, request):
        return super().get_queryset(request).defer('contenido_pdf')


@admin.register(Solicitud)
class SolicitudAdmin(admin.ModelAdmin):
    list_display = ('folio', 'tramite', 'ciudadano', 'estado', 'fecha_creacion')
    list_filter = ('estado', 'tramite')
    search_fields = ('folio', 'ciudadano__curp', 'ciudadano__nombre')
    readonly_fields = ('folio', 'fecha_creacion')
    inlines = [ArchivoRequisitoInline]


@admin.register(ArchivoRequisito)
class ArchivoRequisitoAdmin(admin.ModelAdmin):
    list_display = ('solicitud', 'requisito', 'estado_validacion', 'fecha_subida')
    list_filter = ('estado_validacion',)
    search_fields = ('solicitud__folio',)

    def get_queryset(self, request):
        return super().get_queryset(request).defer('contenido_pdf')


class CitaAdminForm(forms.ModelForm):
    def clean(self):
        datos = super().clean()
        tramite = datos.get('tramite')
        if tramite and tramite.es_cita_medica:
            self.add_error('tramite', 'La cita médica se crea desde la agenda del ciudadano.')
        if self.instance.solicitud_id and self.instance.estado in ('Cancelada', 'Reprogramada'):
            if datos.get('estado') == 'Programada':
                self.add_error('estado', 'La cita debe reservarse de nuevo desde la agenda.')
        return datos


class ConsultaClinicaInline(admin.StackedInline):
    model = ConsultaClinica
    extra = 0
    readonly_fields = ('elaborada',)

    def has_change_permission(self, request, obj=None):
        if obj and DocumentoClinico.objects.filter(consulta__cita=obj).exists():
            return False
        return super().has_change_permission(request, obj)


@admin.register(Cita)
class CitaAdmin(admin.ModelAdmin):
    form = CitaAdminForm
    list_display = ('folio_cita', 'ciudadano', 'funcionario', 'tramite', 'fecha', 'hora', 'estado')
    list_filter = ('estado', 'fecha', 'tramite')
    search_fields = ('folio_cita', 'ciudadano__curp', 'ciudadano__nombre')
    readonly_fields = ('folio_cita', 'fecha_creacion')
    date_hierarchy = 'fecha'

    def get_readonly_fields(self, request, obj=None):
        campos = (*self.readonly_fields, 'solicitud')
        if obj and obj.solicitud_id:
            return (*campos, 'ciudadano', 'tramite', 'fecha', 'hora', 'expediente')
        return campos

    def get_inlines(self, request, obj=None):
        return [ConsultaClinicaInline] if obj and obj.solicitud_id else []

    @admin.display(description='Expediente clínico')
    def expediente(self, cita):
        expediente = getattr(cita.ciudadano, 'expediente_clinico', None)
        if expediente:
            url = reverse('admin:ciudadanos_expedienteclinico_change', args=[expediente.pk])
            return format_html('<a href="{}">{}</a>', url, expediente)
        return 'Sin expediente'


@admin.register(HorarioDireccion)
class HorarioDireccionAdmin(admin.ModelAdmin):
    list_display = ('direccion', 'dia_semana', 'hora_inicio', 'hora_fin', 'duracion_cita_minutos')
    list_filter = ('direccion', 'dia_semana')


class DocumentoClinicoForm(forms.ModelForm):
    archivo = forms.FileField(label='PDF', help_text='Máximo 5 MB.', validators=[validar_pdf_clinico])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['archivo'].required = False
        if self.instance.consulta_id:
            self.fields['archivo'].disabled = True

    def save(self, commit=True):
        documento = super().save(commit=False)
        archivo = self.cleaned_data.get('archivo')
        if archivo:
            documento.nombre = archivo.name
            documento.contenido = archivo.read()
        if commit:
            documento.save()
        return documento


class DocumentoClinicoInline(admin.TabularInline):
    model = DocumentoClinico
    form = DocumentoClinicoForm
    fields = ('archivo', 'descarga', 'fecha_subida')
    readonly_fields = ('descarga', 'fecha_subida')
    extra = 0

    @admin.display(description='Documento guardado')
    def descarga(self, documento):
        if documento.pk:
            url = reverse('admin:ciudadanos_documentoclinico_descargar', args=[documento.pk])
            return format_html('<a href="{}">{}</a>', url, documento.nombre)
        return '—'

    def get_queryset(self, request):
        return super().get_queryset(request).defer('contenido')


@admin.register(ExpedienteClinico)
class ExpedienteClinicoAdmin(admin.ModelAdmin):
    list_display = ('id', 'ciudadano', 'creado')
    search_fields = ('ciudadano__curp', 'ciudadano__nombre', 'ciudadano__apellidos')
    autocomplete_fields = ('ciudadano',)
    readonly_fields = ('creado',)
    inlines = [DocumentoClinicoInline]

    def get_readonly_fields(self, request, obj=None):
        return (*self.readonly_fields, 'ciudadano') if obj else self.readonly_fields

    def get_urls(self):
        return [
            path('documento/<int:pk>/', self.admin_site.admin_view(self.descargar_documento),
                 name='ciudadanos_documentoclinico_descargar'),
            *super().get_urls(),
        ]

    def descargar_documento(self, request, pk):
        if not self.has_view_or_change_permission(request) or not request.user.has_perm(
            'ciudadanos.view_documentoclinico'
        ):
            raise PermissionDenied
        documento = get_object_or_404(DocumentoClinico, pk=pk)
        return FileResponse(
            BytesIO(documento.contenido), as_attachment=True, filename=documento.nombre,
            content_type='application/pdf',
        )
