from io import BytesIO

from django.conf import settings
from django.utils import timezone
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


PLANTILLA = '11 Historia Clinica General - CARTA - DOBLE CARA.pdf'
# Coordenadas medidas sobre una vista a escala 1.3 desde la esquina superior.
ESCALA = 1.3


def _lineas(texto, tamano, ancho):
    for parrafo in str(texto).splitlines():
        for linea in simpleSplit(parrafo, 'Helvetica', tamano, ancho) or ['']:
            if stringWidth(linea, 'Helvetica', tamano) <= ancho:
                yield linea
                continue
            bloque = ''
            for letra in linea:
                if stringWidth(bloque + letra, 'Helvetica', tamano) > ancho:
                    yield bloque
                    bloque = ''
                bloque += letra
            if bloque:
                yield bloque


def generar_historia(expediente, consulta):
    cita = consulta.cita
    paciente = expediente.ciudadano
    nombre = f'{paciente.nombre} {paciente.apellidos}'.strip()
    fecha = timezone.localtime(consulta.elaborada)
    original = PdfReader(settings.BASE_DIR / 'Tramites' / PLANTILLA)
    writer = PdfWriter()
    desbordes = []

    def superponer(pagina, campos):
        buffer = BytesIO()
        capa = canvas.Canvas(buffer, pagesize=(612, 792))
        capa.setFillColorRGB(.12, .14, .23)
        for etiqueta, valor, x, y, ancho, filas in campos:
            if valor is None or valor == '':
                continue
            tamano = 7.5
            if filas == 1 and '\n' not in str(valor):
                longitud = stringWidth(str(valor), 'Helvetica', tamano)
                if longitud:
                    tamano = max(6, min(tamano, tamano * (ancho / ESCALA) / longitud))
            lineas = list(_lineas(valor, tamano, ancho / ESCALA))
            if len(lineas) > filas:
                desbordes.append((etiqueta, str(valor)))
                lineas = lineas[:filas - 1] + ['Ver anexo']
            capa.setFont('Helvetica', tamano)
            for indice, linea in enumerate(lineas):
                capa.drawString(x / ESCALA, 792 - y / ESCALA - indice * 12.5, linea)
        capa.save()
        buffer.seek(0)
        original.pages[pagina].merge_page(PdfReader(buffer).pages[0])
        writer.add_page(original.pages[pagina])

    genero = expediente.genero.casefold()
    estado = expediente.estado_civil.casefold()
    sistemas = [
        (etiqueta, consulta.revision_sistemas.get(nombre), 169, y, 590, 1)
        for (nombre, etiqueta), y in zip(consulta.SISTEMAS, (707, 744, 781, 819, 857, 894, 932, 85, 122, 160))
    ]
    regiones = [
        (etiqueta, consulta.revision_regiones.get(nombre), 137, y, 622, 1)
        for (nombre, etiqueta), y in zip(consulta.REGIONES, (376, 408, 441, 473, 506, 538))
    ]
    superponer(0, [
        ('Fecha', fecha.strftime('%d/%m/%Y'), 168, 191, 100, 1),
        ('Hora', fecha.strftime('%H:%M'), 431, 191, 98, 1),
        ('Expediente', f'EXP-{expediente.pk}', 621, 191, 101, 1),
        ('Nombre completo', nombre, 168, 236, 251, 1),
        ('Edad', expediente.edad, 473, 236, 81, 1),
        ('Género masculino', 'X' if genero in ('hombre', 'masculino') else '', 698, 236, 12, 1),
        ('Género femenino', 'X' if genero in ('mujer', 'femenino') else '', 750, 236, 12, 1),
        *[(etiqueta, 'X' if estado in opciones else '', x, 258, 14, 1)
          for etiqueta, opciones, x in (
              ('Casado', ('casado', 'casada'), 170), ('Soltero', ('soltero', 'soltera'), 236),
              ('Viudo', ('viudo', 'viuda'), 302), ('Divorciado', ('divorciado', 'divorciada'), 402),
          )],
        ('Ocupación', expediente.ocupacion, 513, 258, 145, 1),
        ('Teléfono', expediente.telefono, 701, 258, 62, 1),
        ('Lugar de origen', expediente.lugar_origen, 135, 278, 130, 1),
        ('Lugar de residencia', expediente.lugar_residencia, 428, 278, 135, 1),
        ('Escolaridad', expediente.escolaridad, 650, 278, 111, 1),
        ('Domicilio', expediente.domicilio, 95, 296, 665, 1),
        ('Padre o tutor', expediente.tutor, 35, 314, 550, 1),
        ('Parentesco', expediente.parentesco, 600, 314, 161, 1),
        ('Antecedentes heredofamiliares', expediente.antecedentes_familiares, 35, 360, 725, 1),
        ('Antecedentes no patológicos', expediente.antecedentes_no_patologicos, 35, 420, 725, 2),
        ('Antecedentes patológicos', expediente.antecedentes_patologicos, 35, 486, 725, 2),
        ('Antecedentes gineco-obstétricos', expediente.antecedentes_gineco_obstetricos, 35, 558, 725, 2),
        ('Motivo de atención', consulta.padecimiento_actual, 35, 634, 725, 2),
        *sistemas[:7],
    ])
    superponer(1, [
        *sistemas[7:],
        ('Peso', consulta.peso_kg, 216, 201, 71, 1),
        ('Talla', consulta.talla_m, 429, 201, 53, 1),
        ('Índice de masa corporal', consulta.imc, 678, 201, 59, 1),
        ('Tensión arterial', consulta.tension_arterial, 136, 221, 87, 1),
        ('Frecuencia cardíaca', consulta.frecuencia_cardiaca, 526, 221, 77, 1),
        ('Frecuencia respiratoria', consulta.frecuencia_respiratoria, 169, 240, 75, 1),
        ('Temperatura', consulta.temperatura_c, 493, 240, 69, 1),
        ('Saturación de oxígeno', consulta.saturacion_oxigeno, 169, 259, 75, 1),
        ('Glucosa', consulta.glucosa_mg_dl, 493, 259, 69, 1),
        ('Exploración general', consulta.habitus_exterior, 35, 320, 725, 2),
        *regiones,
        ('Resultados', consulta.resultados, 35, 582, 725, 1),
        ('Análisis del caso', consulta.diagnostico, 98, 631, 663, 3),
        ('Recomendaciones', consulta.tratamiento, 35, 711, 725, 3),
        ('Observaciones', consulta.indicaciones_especiales, 35, 847, 725, 1),
        ('Resolución', consulta.pronostico, 35, 883, 725, 1),
        ('Guía de referencia', consulta.guia_clinica, 278, 905, 482, 1),
        ('Acciones realizadas', consulta.acciones_linea_vida, 278, 931, 482, 1),
        ('Médico y cédula', f'{consulta.medico} · {consulta.cedula_profesional}', 265, 969, 420, 1),
    ])

    anexo = BytesIO()
    pagina = canvas.Canvas(anexo, pagesize=(612, 792))

    def encabezado():
        pagina.setFont('Helvetica-Bold', 15)
        pagina.drawString(44, 746, 'Anexo de la Historia Clínica General')
        pagina.setFont('Helvetica', 9)
        pagina.drawString(44, 729, cita.folio_cita)
        return 700

    y = encabezado()
    for titulo, texto in [
        ('Paciente', nombre),
        ('CURP', paciente.curp),
        ('Dependencia', cita.tramite.direccion.nombre),
        ('Trámite', cita.tramite.nombre),
        ('Folio de solicitud', cita.solicitud.folio if cita.solicitud_id else ''),
        ('Folio de cita', cita.folio_cita),
        ('Fecha y hora de la cita', f'{cita.fecha:%d/%m/%Y} · {cita.hora:%H:%M}'),
        ('Género', expediente.genero),
        ('Estado civil', expediente.estado_civil),
        ('Interrogatorio por aparatos y sistemas', consulta.interrogatorio),
        ('Signos vitales', consulta.signos_vitales),
        ('Exploración por regiones', consulta.exploracion_regiones),
        *desbordes,
    ]:
        if not texto:
            continue
        if y < 90:
            pagina.showPage()
            y = encabezado()
        pagina.setFont('Helvetica-Bold', 10)
        pagina.drawString(44, y, titulo)
        y -= 15
        pagina.setFont('Helvetica', 10)
        for linea in _lineas(texto, 10, 520):
            if y < 48:
                pagina.showPage()
                y = encabezado()
                pagina.setFont('Helvetica', 10)
            pagina.drawString(44, y, linea)
            y -= 14
        y -= 11
    pagina.save()
    anexo.seek(0)
    writer.append(PdfReader(anexo))
    resultado = BytesIO()
    writer.write(resultado)
    return resultado.getvalue()
