from decimal import Decimal, ROUND_HALF_UP

from asgiref.sync import sync_to_async
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

class CiudadanoManager(BaseUserManager):
    def get_by_natural_key(self, username):
        curp = username.strip()
        try:
            return super().get_by_natural_key(curp)
        except self.model.DoesNotExist:
            try:
                return self.get(curp__iexact=curp)
            except self.model.MultipleObjectsReturned:
                raise self.model.DoesNotExist from None

    async def aget_by_natural_key(self, username):
        return await sync_to_async(self.get_by_natural_key)(username)

    def create_user(self, curp, email, password=None, **extra_fields):
        if not curp:
            raise ValueError('La CURP es obligatoria')
        email = self.normalize_email(email)
        user = self.model(curp=curp, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, curp, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        return self.create_user(curp, email, password, **extra_fields)

class Ciudadano(AbstractBaseUser, PermissionsMixin):
    # --- LA CURP ES LA LLAVE PRIMARIA (PK) ---
    curp = models.CharField(max_length=18, primary_key=True, unique=True)
    
    # --- DATOS BASE Y AUTENTICACIÓN ---
    email = models.EmailField(unique=True)
    nombre = models.CharField(max_length=150)
    apellidos = models.CharField(max_length=150)
    cedula_profesional = models.CharField('cédula profesional', max_length=30, blank=True)
    
    # --- DATOS EXTRAÍDOS DEL PDF ---
    fecha_nacimiento = models.CharField(max_length=20, blank=True, null=True)
    
    # --- DOMICILIO ---
    cp = models.CharField(max_length=5, blank=True, null=True)
    colonia = models.CharField(max_length=150, blank=True, null=True)
    calle = models.CharField(max_length=150, blank=True, null=True)
    numero = models.CharField(max_length=50, blank=True, null=True)
    mz_lt = models.CharField(max_length=50, blank=True, null=True)
    
    # --- CONTACTO Y GÉNERO ---
    genero = models.CharField(max_length=50, blank=True, null=True)
    telefono_cel = models.CharField(max_length=10, blank=True, null=True)
    telefono_casa = models.CharField(max_length=10, blank=True, null=True)
    
    # --- REQUISITOS INTERNOS DE DJANGO ---
    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    fecha_registro = models.DateTimeField(auto_now_add=True)

    objects = CiudadanoManager()

    USERNAME_FIELD = 'curp'
    EMAIL_FIELD = 'email'
    REQUIRED_FIELDS = ['email', 'nombre', 'apellidos']

    def __str__(self):
        return self.curp


# --- DOCUMENTOS VINCULADOS AL CIUDADANO ---

class Documento(models.Model):
    ciudadano = models.ForeignKey(Ciudadano, on_delete=models.CASCADE, related_name='documentos')
    archivo_curp = models.FileField(upload_to='documentos_curp/')
    fecha_subida = models.DateTimeField(auto_now_add=True)
    verificado = models.BooleanField(default=False)

    def __str__(self):
        return f"CURP PDF de {self.ciudadano.curp}"


# --- CATÁLOGOS DE TRÁMITES Y DIRECCIONES ---

class Direccion(models.Model):
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.nombre


class Tramite(models.Model):
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True, null=True)
    direccion = models.ForeignKey(Direccion, on_delete=models.CASCADE)
    tiempo = models.CharField(max_length=50)
    costo = models.CharField(max_length=50)
    modalidad = models.CharField(max_length=50)
    es_cita_medica = models.BooleanField(
        'Cita médica', default=False,
        help_text='Usa la ficha clínica y los turnos médicos en lugar de los requisitos generales.',
    )
    es_servicio_social = models.BooleanField('Servicio social estudiantil', default=False)

    def __str__(self):
        return self.nombre


class Requisito(models.Model):
    tramite = models.ForeignKey(Tramite, on_delete=models.CASCADE, related_name='requisitos')
    descripcion = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.tramite.nombre} - {self.descripcion}"


# --- GESTIÓN DE SOLICITUDES Y ARCHIVOS ---

class Solicitud(models.Model):
    NIVELES_SERVICIO_SOCIAL = [('licenciatura', 'Licenciatura'), ('tecnico', 'Nivel técnico')]
    ESTADO_CHOICES = [
        ('Pendiente', 'Pendiente de revisión'),
        ('En proceso', 'En proceso'),
        ('Aprobado', 'Aprobado'),
        ('Rechazado', 'Rechazado / Con observaciones'),
    ]

    tramite = models.ForeignKey(Tramite, on_delete=models.CASCADE)
    folio = models.CharField(max_length=20, unique=True, blank=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    
    # Relación real con el modelo Ciudadano
    ciudadano = models.ForeignKey(
        Ciudadano, on_delete=models.CASCADE, related_name='solicitudes'
    )

    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='Pendiente')
    nivel_estudios = models.CharField(max_length=12, choices=NIVELES_SERVICIO_SOCIAL, blank=True)
    porcentaje_creditos = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    class Meta:
        permissions = [('validar_servicio_social', 'Puede validar solicitudes de Servicio Social')]

    def save(self, *args, **kwargs):
        if not self.folio:
            self.folio = f"TRAM-{timezone.now().strftime('%Y%m%d')}-{Solicitud.objects.count() + 1}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.folio} - {self.tramite.nombre} ({self.estado})"


class ArchivoRequisito(models.Model):
    ESTADO_DOC_CHOICES = [
        ('Pendiente', 'Pendiente de revisión'),
        ('Aprobado', 'Documento Válido'),
        ('Rechazado', 'Rechazado / Con errores'),
    ]

    solicitud = models.ForeignKey(Solicitud, on_delete=models.CASCADE, related_name='archivos')
    requisito = models.ForeignKey(Requisito, on_delete=models.CASCADE)
    archivo = models.FileField(upload_to='tramites_archivos/', blank=True)
    contenido_pdf = models.BinaryField(null=True, blank=True)
    nombre_pdf = models.CharField(max_length=255, blank=True, editable=False)
    fecha_subida = models.DateTimeField(auto_now_add=True)

    estado_validacion = models.CharField(max_length=20, choices=ESTADO_DOC_CHOICES, default='Pendiente')
    observaciones = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Archivo para {self.requisito.descripcion} - Solicitud {self.solicitud.folio}"



class Cita(models.Model):
    ESTADO_CITA_CHOICES = [
        ('Programada', 'Programada'),
        ('Atendida', 'Atendida'),
        ('Cancelada', 'Cancelada'),
        ('Reprogramada', 'Reprogramada'),
    ]

    # --- RELACIONES ---
    # El ciudadano que saca la cita
    ciudadano = models.ForeignKey(
        Ciudadano, on_delete=models.CASCADE, related_name='citas_como_ciudadano'
    )
    
    # El funcionario asignado para atenderlo (on_delete=SET_NULL por si el funcionario renuncia, no se borre la cita)
    funcionario = models.ForeignKey(
        Ciudadano, on_delete=models.SET_NULL, null=True, blank=True, related_name='citas_como_funcionario'
    )
    
    # El trámite que se va a gestionar
    tramite = models.ForeignKey(
        Tramite, on_delete=models.CASCADE, related_name='citas'
    )
    solicitud = models.OneToOneField(
        Solicitud, on_delete=models.CASCADE, null=True, blank=True, related_name='cita'
    )

    # --- FECHA Y HORA ---
    fecha = models.DateField()
    hora = models.TimeField()

    # --- CAMPOS EXTRA RECOMENDADOS ---
    folio_cita = models.CharField(max_length=20, unique=True, blank=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CITA_CHOICES, default='Programada')
    observaciones = models.TextField(blank=True, null=True, help_text="Notas o instrucciones para el ciudadano")
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'principal_cita' # Mantenemos el estándar de tus tablas
        ordering = ['fecha', 'hora'] # Ordena las citas de la más próxima a la más lejana

    def save(self, *args, **kwargs):
        # Generación automática de folio único (Igual que como lo hiciste en Solicitud)
        if not self.folio_cita:
            self.folio_cita = f"CITA-{timezone.now().strftime('%Y%m%d')}-{Cita.objects.count() + 1}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.folio_cita} - {self.ciudadano.nombre} ({self.fecha} a las {self.hora})"



class HorarioDireccion(models.Model):
    DIAS_SEMANA = [
        (0, 'Lunes'),
        (1, 'Martes'),
        (2, 'Miércoles'),
        (3, 'Jueves'),
        (4, 'Viernes'),
        (5, 'Sábado'),
        (6, 'Domingo'),
    ]

    direccion = models.ForeignKey(Direccion, on_delete=models.CASCADE, related_name='horarios')
    dia_semana = models.IntegerField(choices=DIAS_SEMANA)
    hora_inicio = models.TimeField(help_text="Hora a la que abren la ventanilla")
    hora_fin = models.TimeField(help_text="Hora a la que cierran la ventanilla")
    duracion_cita_minutos = models.IntegerField(default=30, help_text="¿Cuánto dura cada cita en minutos?")

    class Meta:
        db_table = 'principal_horario_direccion'
        unique_together = ('direccion', 'dia_semana') # Evita que registren dos horarios para el mismo lunes

    def __str__(self):
        return f"{self.direccion.nombre} - {self.get_dia_semana_display()} ({self.hora_inicio} a {self.hora_fin})"


class TurnoMedico(models.Model):
    tramite = models.ForeignKey(Tramite, on_delete=models.CASCADE, related_name='turnos_medicos')
    dia_semana = models.PositiveSmallIntegerField('día', choices=[(0, 'Lunes'), (1, 'Martes')])
    hora = models.TimeField()

    class Meta:
        ordering = ('dia_semana', 'hora')
        verbose_name_plural = 'turnos médicos'
        constraints = [
            models.UniqueConstraint(fields=('tramite', 'dia_semana', 'hora'), name='turno_medico_unico'),
            models.CheckConstraint(condition=models.Q(dia_semana__in=(0, 1)), name='turno_medico_lunes_martes'),
        ]

    def __str__(self):
        return f'{self.get_dia_semana_display()} {self.hora:%H:%M}'


class ExpedienteClinico(models.Model):
    CAMPOS_ANTECEDENTES = (
        'antecedentes_familiares', 'antecedentes_no_patologicos',
        'antecedentes_patologicos', 'antecedentes_gineco_obstetricos',
    )

    ciudadano = models.OneToOneField(
        Ciudadano, on_delete=models.CASCADE, related_name='expediente_clinico'
    )
    creado = models.DateTimeField(auto_now_add=True)
    edad = models.PositiveSmallIntegerField()
    genero = models.CharField('género', max_length=50)
    estado_civil = models.CharField(max_length=50)
    ocupacion = models.CharField('ocupación', max_length=150)
    lugar_origen = models.CharField(max_length=150)
    lugar_residencia = models.CharField(max_length=150)
    escolaridad = models.CharField(max_length=100)
    domicilio = models.CharField(max_length=250)
    telefono = models.CharField('teléfono', max_length=25)
    tutor = models.CharField('nombre del padre o tutor', max_length=200, blank=True)
    parentesco = models.CharField(max_length=100, blank=True)
    antecedentes_familiares = models.TextField('antecedentes heredofamiliares', blank=True)
    antecedentes_no_patologicos = models.TextField('antecedentes personales no patológicos', blank=True)
    antecedentes_patologicos = models.TextField('antecedentes personales patológicos', blank=True)
    antecedentes_gineco_obstetricos = models.TextField('antecedentes gineco-obstétricos', blank=True)

    class Meta:
        verbose_name = 'expediente clínico'
        verbose_name_plural = 'expedientes clínicos'

    def __str__(self):
        return f'Expediente {self.pk} · {self.ciudadano}'


class ConsultaClinica(models.Model):
    SISTEMAS = (
        ('cardiovascular', 'Cardiovascular'), ('respiratorio', 'Respiratorio'),
        ('gastrointestinal', 'Gastrointestinal'), ('genitourinario', 'Genitourinario'),
        ('hematico_linfatico', 'Hemático y linfático'), ('endocrino', 'Endocrino'),
        ('nervioso', 'Nervioso'), ('musculoesqueletico', 'Musculoesquelético'),
        ('piel', 'Piel, mucosas y anexos'), ('psicosomatico', 'Psicosomático'),
    )
    REGIONES = (
        ('cabeza', 'Cabeza'), ('cuello', 'Cuello'), ('torax', 'Tórax'),
        ('abdomen', 'Abdomen'), ('extremidades', 'Extremidades'), ('genitales', 'Genitales'),
    )

    cita = models.OneToOneField(Cita, on_delete=models.CASCADE, related_name='consulta_clinica')
    elaborada = models.DateTimeField(auto_now_add=True)
    padecimiento_actual = models.TextField(blank=True)
    interrogatorio = models.TextField('interrogatorio por aparatos y sistemas', blank=True)
    signos_vitales = models.TextField(blank=True)
    peso_kg = models.DecimalField('Peso (kg)', max_digits=5, decimal_places=2, null=True, blank=True,
                                  validators=[MinValueValidator(Decimal('0.01'))])
    talla_m = models.DecimalField('Talla (m)', max_digits=4, decimal_places=2, null=True, blank=True,
                                  validators=[MinValueValidator(Decimal('0.01'))])
    tension_arterial = models.CharField('Tensión arterial (mmHg)', max_length=15, blank=True)
    frecuencia_cardiaca = models.PositiveSmallIntegerField('Frecuencia cardíaca (por minuto)', null=True, blank=True)
    frecuencia_respiratoria = models.PositiveSmallIntegerField('Frecuencia respiratoria (por minuto)', null=True, blank=True)
    temperatura_c = models.DecimalField('Temperatura (°C)', max_digits=4, decimal_places=1, null=True, blank=True)
    saturacion_oxigeno = models.PositiveSmallIntegerField('Saturación de oxígeno (%)', null=True, blank=True,
                                                           validators=[MaxValueValidator(100)])
    glucosa_mg_dl = models.PositiveSmallIntegerField('Glucosa (mg/dL)', null=True, blank=True)
    revision_sistemas = models.JSONField(default=dict, blank=True)
    revision_regiones = models.JSONField(default=dict, blank=True)
    habitus_exterior = models.TextField(blank=True)
    exploracion_regiones = models.TextField('exploración por regiones', blank=True)
    resultados = models.TextField('resultados de laboratorio y gabinete', blank=True)
    diagnostico = models.TextField('impresión diagnóstica', blank=True)
    tratamiento = models.TextField('tratamiento e indicaciones', blank=True)
    indicaciones_especiales = models.TextField(blank=True)
    pronostico = models.TextField('pronóstico', blank=True)
    guia_clinica = models.TextField('guía de práctica clínica de referencia', blank=True)
    acciones_linea_vida = models.TextField('acciones de línea de vida', blank=True)
    medico = models.CharField('nombre del médico', max_length=200)
    cedula_profesional = models.CharField('cédula profesional', max_length=30)

    class Meta:
        verbose_name = 'consulta clínica'
        verbose_name_plural = 'consultas clínicas'

    def __str__(self):
        return self.cita.folio_cita

    @property
    def imc(self):
        if self.peso_kg and self.talla_m:
            return (self.peso_kg / self.talla_m ** 2).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return None


def validar_pdf_clinico(archivo):
    if archivo.size > 5 * 1024 * 1024:
        raise ValidationError('El PDF supera los 5 MB.')
    cabecera = archivo.read(5)
    archivo.seek(0)
    if not archivo.name.lower().endswith('.pdf') or cabecera != b'%PDF-':
        raise ValidationError('Selecciona un archivo PDF.')


class DocumentoClinico(models.Model):
    expediente = models.ForeignKey(ExpedienteClinico, on_delete=models.CASCADE, related_name='documentos')
    consulta = models.OneToOneField(
        ConsultaClinica, on_delete=models.CASCADE, null=True, blank=True,
        related_name='pdf_institucional', editable=False,
    )
    generado_por = models.ForeignKey(
        Ciudadano, on_delete=models.SET_NULL, null=True, blank=True, editable=False,
    )
    nombre = models.CharField(max_length=255, editable=False)
    contenido = models.BinaryField()
    fecha_subida = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'documento clínico'
        verbose_name_plural = 'documentos clínicos'

    def __str__(self):
        return self.nombre
