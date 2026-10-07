from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
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
        ('Permisos', {
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


@admin.register(Tramite)
class TramiteAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'direccion', 'tiempo', 'costo', 'modalidad')
    list_filter = ('direccion', 'modalidad')
    search_fields = ('nombre',)
    inlines = [RequisitoInline]


@admin.register(Requisito)
class RequisitoAdmin(admin.ModelAdmin):
    list_display = ('tramite', 'descripcion')
    list_filter = ('tramite',)
    search_fields = ('descripcion',)


class ArchivoRequisitoInline(admin.TabularInline):
    model = ArchivoRequisito
    extra = 0


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


@admin.register(Cita)
class CitaAdmin(admin.ModelAdmin):
    list_display = ('folio_cita', 'ciudadano', 'funcionario', 'tramite', 'fecha', 'hora', 'estado')
    list_filter = ('estado', 'fecha', 'tramite')
    search_fields = ('folio_cita', 'ciudadano__curp', 'ciudadano__nombre')
    readonly_fields = ('folio_cita', 'fecha_creacion')
    date_hierarchy = 'fecha'


@admin.register(HorarioDireccion)
class HorarioDireccionAdmin(admin.ModelAdmin):
    list_display = ('direccion', 'dia_semana', 'hora_inicio', 'hora_fin', 'duracion_cita_minutos')
    list_filter = ('direccion', 'dia_semana')