from datetime import date, datetime
from decimal import Decimal

from django import forms
from django.forms import formset_factory
from django.utils import timezone

from .models import Ciudadano, PersonaSocial


CONTACTO = (
    'telefono', 'correo', 'calle', 'numero', 'numero_interior', 'colonia', 'municipio',
    'estado_domicilio', 'cp', 'rfc_personal',
)
IDENTIFICACION = ('nombre', 'curp', 'fecha_nacimiento', 'parentesco', *CONTACTO)


def fecha_nacimiento(valor):
    for formato in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(valor or '', formato).date()
        except ValueError:
            continue
    return None


def datos_cuenta(user):
    datos = {
        'nombre': f'{user.nombre} {user.apellidos}'.strip(), 'curp': user.pk,
        'fecha_nacimiento': fecha_nacimiento(user.fecha_nacimiento), 'parentesco': 'Titular',
        'telefono': user.telefono_cel or user.telefono_casa, 'correo': user.email,
        'rfc_personal': user.rfc if user.tipo_persona == 'fisica' else '',
        **{n: getattr(user, n) for n in CONTACTO if n not in ('telefono', 'correo', 'rfc_personal')},
        'estado_domicilio': user.estado_domicilio,
        'sexo': user.genero,
    }
    expediente = getattr(user, 'expediente_clinico', None)
    if expediente:
        datos.update(escolaridad=expediente.escolaridad, estado_civil=expediente.estado_civil,
                     ocupacion=expediente.ocupacion, sexo=expediente.genero)
        if not datos['telefono']:
            datos['telefono'] = expediente.telefono
    return datos


class IdentificacionForm(forms.Form):
    nombre = forms.CharField(label='Nombre completo de la persona atendida', max_length=250)
    curp = forms.CharField(label='CURP de la persona atendida (si cuenta con ella)', max_length=18, required=False)
    fecha_nacimiento = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    parentesco = forms.CharField(label='Parentesco con la cuenta responsable', max_length=80)
    telefono = forms.CharField(label='Teléfono de contacto', max_length=20)
    correo = forms.EmailField(label='Correo de contacto', required=False)
    calle = forms.CharField(max_length=150)
    numero = forms.CharField(label='Número exterior', max_length=50)
    numero_interior = forms.CharField(label='Número interior', max_length=50, required=False)
    colonia = forms.CharField(max_length=150)
    municipio = forms.CharField(max_length=150)
    estado_domicilio = forms.CharField(label='Estado', max_length=150)
    cp = forms.RegexField(label='Código postal', regex=r'^[0-9]{5}$')
    rfc_personal = forms.CharField(label='RFC personal (si existe)', max_length=13, required=False)
    modalidad = forms.ChoiceField(choices=[('general', 'General'), ('beca', 'Beca'), ('judicial', 'Solicitud judicial')])
    referencia = forms.CharField(label='Institución o juzgado y referencia de la solicitud', max_length=250, required=False)

    def __init__(self, *args, psicologia=False, **kwargs):
        super().__init__(*args, **kwargs)
        if psicologia:
            self.fields.pop('modalidad')
            self.fields.pop('referencia')

    def clean_fecha_nacimiento(self):
        valor = self.cleaned_data['fecha_nacimiento']
        if valor > timezone.localdate():
            raise forms.ValidationError('Revisa la fecha de nacimiento.')
        return valor

    def clean_curp(self):
        return self.cleaned_data['curp'].strip().upper()

    def clean(self):
        datos = super().clean()
        if datos.get('modalidad') and not datos.get('referencia'):
            self.add_error('referencia', 'Indica la institución o juzgado y la referencia de la solicitud.')
        return datos


class FamiliarForm(forms.Form):
    nombre = forms.CharField(max_length=250)
    parentesco = forms.CharField(max_length=80)
    edad = forms.IntegerField(min_value=0, max_value=150)
    estado_civil = forms.CharField(max_length=80, required=False)
    escolaridad = forms.CharField(max_length=100, required=False)
    ocupacion = forms.CharField(max_length=150, required=False)
    sueldo = forms.DecimalField(min_value=0, decimal_places=2, max_digits=12, required=False)


FamiliaFormSet = formset_factory(FamiliarForm, extra=0, can_delete=True, max_num=60, validate_max=True)

INGRESOS = ('padre', 'madre', 'otros')
GASTOS = ('renta', 'alimentos', 'transporte', 'creditos', 'recreacion', 'luz', 'agua', 'gas', 'otros')
ALIMENTOS = ('carne', 'huevo', 'leche', 'fruta', 'verduras', 'cereales', 'harinas', 'leguminosas', 'pescado', 'pollo')
SECCIONES_ESTUDIO = (
    ('Datos de identificación', ('sexo', 'escolaridad', 'estado_civil', 'ocupacion', 'religion', 'seguro_social')),
    ('Información sanitaria', ('alcohol_consumo', 'alcohol', 'cigarros_consumo', 'cigarros', 'drogas_consumo', 'drogas', 'enfermedades')),
    ('Alimentación por semana', tuple(f'alimento_{n}' for n in ALIMENTOS)),
    ('Ingresos mensuales', tuple(f'ingreso_{n}' for n in INGRESOS)),
    ('Egresos mensuales', tuple(f'gasto_{n}' for n in GASTOS)),
    ('Condiciones de vivienda', (
        'tenencia', 'tipo_vivienda', 'dormitorios', 'sala', 'comedor', 'cocina', 'bano', 'ventanas',
        'piso', 'paredes', 'techo', 'acabados', 'zonificacion',
    )),
    ('Resultado de la entrevista', ('diagnostico', 'conclusion')),
    ('Pago y libro de gobierno', ('pago_realizado', 'importe', 'fecha_pago', 'recibo', 'libro_gobierno')),
)
SECCIONES_PSICOLOGIA = (
    ('Consulta psicológica', ('motivo', 'valoracion', 'atencion', 'recomendaciones', 'seguimiento')),
)
TEXTOS = {
    'sexo': 'Sexo', 'escolaridad': 'Escolaridad', 'estado_civil': 'Estado civil',
    'ocupacion': 'Ocupación', 'religion': 'Religión', 'seguro_social': 'Seguro social',
    'alcohol': 'Bebidas alcohólicas, persona que consume y frecuencia',
    'cigarros': 'Cigarros, persona que consume y frecuencia',
    'drogas': 'Drogas, persona que consume y frecuencia',
    'enfermedades': 'Enfermedades de los últimos seis meses y quién las padeció',
    'tenencia': 'Tenencia (propia, rentada, crédito, prestada u otra)',
    'tipo_vivienda': 'Tipo de vivienda', 'piso': 'Piso', 'paredes': 'Paredes', 'techo': 'Techo',
    'acabados': 'Acabados', 'zonificacion': 'Zonificación', 'diagnostico': 'Diagnóstico social',
    'conclusion': 'Conclusión', 'motivo': 'Motivo de consulta', 'valoracion': 'Valoración',
    'atencion': 'Atención realizada', 'recomendaciones': 'Recomendaciones', 'seguimiento': 'Seguimiento',
}


class EntrevistaForm(forms.Form):
    def __init__(self, *args, servicio, finalizando=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.secciones = SECCIONES_PSICOLOGIA if servicio == 'psicologia' else SECCIONES_ESTUDIO
        for _, nombres in self.secciones:
            for nombre in nombres:
                if nombre.endswith('_consumo'):
                    etiqueta = {'alcohol': 'Bebidas alcohólicas', 'cigarros': 'Cigarros', 'drogas': 'Drogas'}[nombre.removesuffix('_consumo')]
                    self.fields[nombre] = forms.ChoiceField(
                        label=f'¿Alguien en la familia consume {etiqueta.lower()}?', required=False,
                        choices=(('', 'Sin registrar'), ('si', 'Sí'), ('no', 'No')),
                    )
                elif nombre in TEXTOS:
                    larga = nombre not in ('sexo', 'escolaridad', 'estado_civil', 'ocupacion', 'religion', 'seguro_social')
                    self.fields[nombre] = forms.CharField(
                        label=TEXTOS[nombre], max_length=10000 if larga else 250, required=False,
                        widget=forms.Textarea(attrs={'rows': 3}) if larga else forms.TextInput(),
                    )
                elif nombre.startswith(('ingreso_', 'gasto_')) or nombre == 'importe':
                    self.fields[nombre] = forms.DecimalField(
                        label=nombre.replace('_', ' ').capitalize(), min_value=0,
                        max_digits=12, decimal_places=2, required=False,
                    )
                elif nombre.startswith('alimento_'):
                    self.fields[nombre] = forms.IntegerField(
                        label=nombre.replace('alimento_', '').capitalize(), min_value=0, max_value=7, required=False,
                    )
                elif nombre in ('dormitorios', 'sala', 'comedor', 'cocina', 'bano', 'ventanas'):
                    self.fields[nombre] = forms.IntegerField(label=nombre.capitalize(), min_value=0, max_value=1000, required=False)
                elif nombre == 'pago_realizado':
                    self.fields[nombre] = forms.BooleanField(label='Pago realizado', required=False)
                elif nombre == 'fecha_pago':
                    self.fields[nombre] = forms.DateField(
                        label='Fecha de pago', required=False,
                        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
                    )
                else:
                    self.fields[nombre] = forms.CharField(label=nombre.replace('_', ' ').capitalize(), required=False, max_length=250)
        obligatorios = ('motivo', 'valoracion', 'atencion') if servicio == 'psicologia' else (
            'diagnostico', 'conclusion', 'pago_realizado', 'importe', 'fecha_pago', 'recibo', 'libro_gobierno',
        )
        if finalizando:
            for nombre in obligatorios:
                self.fields[nombre].required = True
        self.finalizando = finalizando

    def clean_fecha_pago(self):
        fecha = self.cleaned_data.get('fecha_pago')
        if fecha and fecha > timezone.localdate():
            raise forms.ValidationError('El pago no puede tener fecha futura.')
        return fecha

    @property
    def grupos(self):
        return [(titulo, [self[n] for n in nombres]) for titulo, nombres in self.secciones]


def serializable(datos):
    return {
        campo: valor.isoformat() if isinstance(valor, date) else str(valor) if isinstance(valor, Decimal) else valor
        for campo, valor in datos.items()
    }
