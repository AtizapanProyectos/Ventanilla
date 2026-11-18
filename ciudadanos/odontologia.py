from datetime import date
from io import BytesIO

from django import forms
from django.conf import settings
from django.utils import timezone
from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from .historia_pdf import _lineas
from .models import ConsultaClinica


PLANTILLA = 'Historia Clinica Odontologia.pdf'
ESCALA = 1.5
OPCIONES = [('', 'Sin respuesta'), ('si', 'Sí'), ('no', 'No')]

# Centros de las casillas Sí / No sobre una vista de la primera página a escala 1.5.
PREGUNTAS = (
    ('diagnostico_previo', '¿Le diagnosticaron alguna enfermedad en consulta médica?', 508, 567, 294),
    ('cardiopatias', 'Enfermedades del corazón', 794, 853, 295),
    ('diabetes', 'Diabetes', 147, 206, 321),
    ('tuberculosis', 'Tuberculosis', 349, 408, 321),
    ('fiebre_reumatica', 'Fiebre reumática', 577, 636, 321),
    ('amigdalitis', 'Amigdalitis', 795, 854, 320),
    ('anemia', 'Anemia', 147, 206, 349),
    ('hepatitis', 'Hepatitis', 349, 408, 349),
    ('enfermedades_virales', 'Enfermedades virales', 578, 637, 349),
    ('asma', 'Asma', 796, 856, 348),
    ('alergia_penicilina', '¿Es alérgico a la penicilina?', 296, 357, 375),
    ('alergia_otros', '¿Es alérgico a otro medicamento?', 511, 571, 376),
    ('anestesia_previa', '¿Lo han anestesiado anteriormente?', 311, 372, 404),
    ('problemas_anestesia', '¿Tuvo problemas con la anestesia?', 796, 856, 402),
    ('sangrado', '¿Presentó sangrado?', 213, 274, 431),
    ('anticoagulantes', '¿Usa anticoagulantes?', 317, 378, 458),
    ('tranquilizantes', '¿Usa tranquilizantes?', 507, 568, 457),
    ('familiar_diabetico', '¿Algún familiar es diabético?', 264, 324, 485),
    ('hipertension', '¿Hipertensión arterial?', 795, 855, 485),
)

IDENTIFICACION = (
    'tipo_sangre', 'sexo', 'edad', 'anio_escolar', 'grupo', 'domicilio',
    'embarazada', 'unidad_aplicativa', 'fecha_primera_atencion', 'escuela',
)
DETALLES_POR_PREGUNTA = {
    'alergia_otros': 'medicamentos_alergia',
    'sangrado': 'problemas_detalle',
    'tranquilizantes': 'medicamentos_actuales',
    'familiar_diabetico': 'parentesco',
}


class ConsultaDentalForm(forms.Form):
    tipo_sangre = forms.CharField(label='Tipo de sangre', max_length=15, required=False)
    sexo = forms.CharField(label='Sexo', max_length=30, required=False)
    edad = forms.IntegerField(label='Edad', min_value=0, max_value=150)
    anio_escolar = forms.CharField(label='Año escolar', max_length=15, required=False)
    grupo = forms.CharField(label='Grupo', max_length=15, required=False)
    domicilio = forms.CharField(label='Domicilio', max_length=250, required=False)
    embarazada = forms.ChoiceField(
        label='Embarazada', choices=[*OPCIONES, ('no_aplica', 'No aplica')], required=False,
    )
    unidad_aplicativa = forms.CharField(label='Unidad aplicativa', max_length=120, required=False)
    fecha_primera_atencion = forms.DateField(
        label='Fecha de primera atención al servicio', input_formats=['%Y-%m-%d'],
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
    )
    escuela = forms.CharField(label='Nombre de la escuela', max_length=90, required=False)
    enfermedad_actual = forms.CharField(label='¿Qué enfermedad padece actualmente?', max_length=140, required=False)
    medicamentos_alergia = forms.CharField(label='¿A cuáles medicamentos es alérgico?', max_length=45, required=False)
    problemas_detalle = forms.CharField(label='¿Qué sucedió con la anestesia o el sangrado?', max_length=95, required=False)
    medicamentos_actuales = forms.CharField(label='¿Cuáles anticoagulantes o tranquilizantes?', max_length=45, required=False)
    parentesco = forms.CharField(label='Parentesco del familiar diabético', max_length=35, required=False)

    def __init__(self, *args, expediente, cita, consulta, **kwargs):
        anterior = ConsultaClinica.objects.filter(
            cita__ciudadano_id=cita.ciudadano_id, cita__tramite__es_cita_dental=True,
        ).exclude(cita_id=cita.pk).order_by('elaborada').first()
        fecha = timezone.localdate()
        if anterior:
            fecha = anterior.datos_odontologicos.get('fecha_primera_atencion') or timezone.localdate(anterior.elaborada)
        inicial = {
            'sexo': expediente.genero, 'edad': expediente.edad, 'domicilio': expediente.domicilio,
            'unidad_aplicativa': cita.tramite.direccion.nombre, 'fecha_primera_atencion': fecha,
        }
        if consulta:
            inicial.update(consulta.datos_odontologicos)
        super().__init__(*args, initial=inicial, **kwargs)
        for nombre, etiqueta, *_ in PREGUNTAS:
            self.fields[nombre] = forms.ChoiceField(label=etiqueta, choices=OPCIONES, required=False)

    @property
    def campos_identificacion(self):
        return [self[nombre] for nombre in IDENTIFICACION]

    @property
    def secciones_adicionales(self):
        campos = [self['enfermedad_actual']]
        for nombre, *_ in PREGUNTAS:
            campos.append(self[nombre])
            if nombre in DETALLES_POR_PREGUNTA:
                campos.append(self[DETALLES_POR_PREGUNTA[nombre]])
        return [('Antecedentes de odontología', campos)]


def generar_historia_dental(expediente, datos):
    original = PdfReader(settings.BASE_DIR / 'Tramites' / PLANTILLA)
    buffer = BytesIO()
    capa = canvas.Canvas(buffer, pagesize=(612, 792))
    capa.setFillColorRGB(.12, .14, .23)

    def texto(valor, x, y, ancho):
        if valor is None or valor == '':
            return
        valor = str(valor)
        longitud = stringWidth(valor, 'Helvetica', 8)
        tamano = min(8, 8 * (ancho / ESCALA) / longitud) if longitud else 8
        capa.setFont('Helvetica', tamano)
        capa.drawString(x / ESCALA, 792 - y / ESCALA, valor)

    paciente = expediente.ciudadano
    nombre = f'{paciente.nombre} {paciente.apellidos}'.strip()
    texto(nombre, 189, 135, 389)
    lineas_domicilio = list(_lineas(datos['domicilio'], 8, 338 / ESCALA))
    if lineas_domicilio:
        texto(lineas_domicilio[0], 518, 162, 335)
        texto(' '.join(lineas_domicilio[1:]), 56, 189, 533)
    for campo, x, y, ancho in (
        ('tipo_sangre', 671, 135, 184), ('sexo', 86, 162, 65), ('edad', 191, 162, 36),
        ('anio_escolar', 306, 162, 59), ('grupo', 410, 162, 48),
        ('unidad_aplicativa', 148, 217, 473), ('escuela', 479, 244, 371),
        ('enfermedad_actual', 286, 271, 562), ('medicamentos_alergia', 647, 380, 180),
        ('problemas_detalle', 446, 435, 394), ('medicamentos_actuales', 649, 462, 184),
        ('parentesco', 418, 490, 147),
    ):
        texto(datos[campo], x, y, ancho)
    texto({'si': 'Sí', 'no': 'No', 'no_aplica': 'No aplica'}.get(datos['embarazada']), 669, 189, 185)
    texto('Sí' if datos['edad'] >= 18 else 'No', 668, 217, 185)
    fecha = date.fromisoformat(datos['fecha_primera_atencion'])
    texto(fecha.strftime('%d/%m/%Y'), 253, 244, 98)

    capa.setFont('Helvetica-Bold', 7)
    for nombre, _, si, no, y in PREGUNTAS:
        respuesta = datos[nombre]
        if respuesta in ('si', 'no'):
            x = si if respuesta == 'si' else no
            capa.drawCentredString(x / ESCALA, 792 - (y + 3.5) / ESCALA, 'X')
    capa.save()
    buffer.seek(0)
    original.pages[0].merge_page(PdfReader(buffer).pages[0])
    salida = BytesIO()
    writer = PdfWriter()
    writer.append_pages_from_reader(original)
    writer.write(salida)
    return salida.getvalue()
