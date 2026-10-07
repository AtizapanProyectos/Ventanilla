from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

class CiudadanoManager(BaseUserManager):
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

    def __str__(self):
        return self.nombre


class Requisito(models.Model):
    tramite = models.ForeignKey(Tramite, on_delete=models.CASCADE, related_name='requisitos')
    descripcion = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.tramite.nombre} - {self.descripcion}"


# --- GESTIÓN DE SOLICITUDES Y ARCHIVOS ---

class Solicitud(models.Model):
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
    archivo = models.FileField(upload_to='tramites_archivos/')
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