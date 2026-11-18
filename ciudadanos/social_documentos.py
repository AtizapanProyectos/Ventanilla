from copy import deepcopy
from datetime import date
from decimal import Decimal
from io import BytesIO
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from django.conf import settings
from django.utils import timezone
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_SECTION_START

from .social_forms import ALIMENTOS, GASTOS, INGRESOS


PLANTILLA = 'Estudio Socioeconomico Procuraduria.docx'


def _contenido(parrafo, texto):
    tamano = next((r.font.size for r in parrafo.runs if r.font.size), Pt(10))
    parrafo.clear()
    run = parrafo.add_run(str(texto))
    run.font.size = tamano


def _celda(celda, texto):
    parrafo = celda.paragraphs[0]
    _contenido(parrafo, texto)
    for p in celda.paragraphs[1:]:
        p._element.getparent().remove(p._element)


def _monto(datos, nombre):
    return Decimal(str(datos.get(nombre) or 0))


def construir_word(entrevista):
    servicio = entrevista.cita.tramite.servicio_procuraduria
    datos, identidad = entrevista.datos, entrevista.identificacion
    fecha = timezone.localdate()
    nacimiento = date.fromisoformat(identidad['fecha_nacimiento'])
    edad = fecha.year - nacimiento.year - ((fecha.month, fecha.day) < (nacimiento.month, nacimiento.day))
    from .procuraduria import domicilio
    if servicio == 'socioeconomico':
        doc = Document(settings.BASE_DIR / 'Tramites' / PLANTILLA)
        cambios = {
            6: f'FECHA: {fecha:%d/%m/%Y}\nDATOS DE IDENTIFICACIÓN',
            7: f'NOMBRE: {identidad["nombre"]}    EDAD: {edad}    SEXO: {datos.get("sexo", "")}\n'
               f'ESCOLARIDAD: {datos.get("escolaridad", "")}    ESTADO CIVIL: {datos.get("estado_civil", "")}',
            8: f'OCUPACIÓN: {datos.get("ocupacion", "")}    RELIGIÓN: {datos.get("religion", "")}\n'
               f'SEGURO SOCIAL: {datos.get("seguro_social", "")}    DOMICILIO: {domicilio(identidad)}',
            9: f'MUNICIPIO: {identidad["municipio"]}    TELÉFONO: {identidad["telefono"]}',
            17: f'ENFERMEDADES PADECIDAS EN LOS ÚLTIMOS 6 MESES Y QUIÉN LAS PADECIÓ: {datos.get("enfermedades", "")}',
            37: f'TENENCIA: {datos.get("tenencia", "")}',
            40: f'TIPO DE VIVIENDA: {datos.get("tipo_vivienda", "")}',
            43: '    '.join(f'{n.upper()}: {datos.get(n, "")}' for n in ('dormitorios', 'sala', 'comedor', 'cocina', 'bano', 'ventanas')),
            47: f'PISO: {datos.get("piso", "")}    PAREDES: {datos.get("paredes", "")}',
            49: f'TECHO: {datos.get("techo", "")}    ACABADOS: {datos.get("acabados", "")}',
            53: f'ZONIFICACIÓN: {datos.get("zonificacion", "")}',
            57: datos.get('diagnostico', ''),
            67: '',
            72: datos.get('conclusion', ''),
        }
        for indice, valor in cambios.items():
            _contenido(doc.paragraphs[indice], valor)
            doc.paragraphs[indice].alignment = WD_ALIGN_PARAGRAPH.LEFT
        doc.paragraphs[6].alignment = WD_ALIGN_PARAGRAPH.CENTER
        # Permitir el crecimiento de la familia sin dejar una hoja aislada de alimentación.
        for seccion in doc.sections[1:]:
            seccion.start_type = WD_SECTION_START.CONTINUOUS
        # Las líneas vacías eran espacio para escritura manual; el texto digital crece por sí mismo.
        parrafos = doc.paragraphs
        for indice in (*range(58, 69), *range(73, 88)):
            parrafo = parrafos[indice]._p
            parrafo.getparent().remove(parrafo)
        familiares = datos.get('familia', [])
        tabla = doc.tables[0]
        while len(tabla.rows) - 1 < len(familiares):
            tabla._tbl.append(deepcopy(tabla.rows[-1]._tr))
        encabezado = OxmlElement('w:tblHeader')
        tabla.rows[0]._tr.get_or_add_trPr().append(encabezado)
        columnas = ('nombre', 'parentesco', 'edad', 'estado_civil', 'escolaridad', 'ocupacion', 'sueldo')
        for i, familiar in enumerate(familiares, 1):
            for j, campo in enumerate(columnas):
                _celda(tabla.rows[i].cells[j], familiar.get(campo) or '')
        for i, campo in enumerate(('alcohol', 'cigarros', 'drogas'), 1):
            valor = datos.get(campo, '')
            _celda(doc.tables[1].rows[i].cells[1], {'si': 'Sí', 'no': 'No'}.get(datos.get(campo + '_consumo'), 'Sin registrar'))
            _celda(doc.tables[1].rows[i].cells[2], valor)
        for i, alimento in enumerate(ALIMENTOS):
            fila, columna = divmod(i, 2)
            valor = datos.get(f'alimento_{alimento}')
            _celda(doc.tables[2].rows[fila].cells[columna], f'{alimento.upper()}: {valor if valor is not None else ""} veces')
        tabla = doc.tables[3]
        for i, campo in enumerate(INGRESOS, 1):
            _celda(tabla.rows[i].cells[1], f'$ {_monto(datos, "ingreso_" + campo):,.2f}')
        posiciones = ((1, 3), (2, 3), (3, 3), (4, 3), (5, 3), (1, 5), (2, 5), (3, 5), (4, 5))
        for campo, (fila, columna) in zip(GASTOS, posiciones):
            _celda(tabla.rows[fila].cells[columna], f'$ {_monto(datos, "gasto_" + campo):,.2f}')
        total_ingreso = sum((_monto(datos, 'ingreso_' + n) for n in INGRESOS), Decimal(0))
        total_gasto = sum((_monto(datos, 'gasto_' + n) for n in GASTOS), Decimal(0))
        _celda(tabla.rows[5].cells[1], f'$ {total_ingreso:,.2f}')
        _celda(tabla.rows[6].cells[5], f'$ {total_gasto:,.2f}')
        for tabla in doc.tables:
            for fila in tabla.rows:
                for alto in fila._tr.xpath('./w:trPr/w:trHeight'):
                    alto.set(qn('w:hRule'), 'atLeast')
        doc.add_page_break()
        doc.add_heading('Datos del trámite y registro de pago', level=1)
        for etiqueta, campo in (
            ('Pago realizado', 'pago_realizado'), ('Importe', 'importe'), ('Fecha de pago', 'fecha_pago'),
            ('Recibo', 'recibo'), ('Libro de gobierno', 'libro_gobierno'),
        ):
            valor = datos.get(campo, '')
            if isinstance(valor, bool):
                valor = 'Sí' if valor else 'No'
            doc.add_paragraph(f'{etiqueta}: {valor}')
    else:
        doc = Document()
        seccion = doc.sections[0]
        seccion.page_width, seccion.page_height = Inches(8.5), Inches(11)
        seccion.top_margin, seccion.bottom_margin = Inches(.9), Inches(.7)
        seccion.left_margin = seccion.right_margin = Inches(.8)
        seccion.header_distance = Inches(.25)
        normal = doc.styles['Normal']
        normal.font.name, normal.font.size = 'Calibri', Pt(11)
        normal.paragraph_format.space_after = Pt(5)
        for nombre, tamano in (('Title', 21), ('Heading 1', 13)):
            estilo = doc.styles[nombre]
            estilo.font.color.rgb, estilo.font.size = RGBColor(0, 0, 0), Pt(tamano)
            for borde in estilo.element.xpath('.//w:pBdr'):
                borde.getparent().remove(borde)
        seccion.header.paragraphs[0].add_run().add_picture(str(settings.BASE_DIR / 'static/assets/DIF.png'), width=Inches(1.2))
        doc.add_paragraph('Ficha de atención psicológica', style='Title')
        doc.add_paragraph(f'{identidad["nombre"]} · {edad} años')
        doc.add_paragraph(f'Contacto: {identidad["telefono"]} · {identidad.get("correo", "")}')
        doc.add_paragraph(f'Domicilio: {domicilio(identidad)}')
        for campo, etiqueta in (
            ('motivo', 'Motivo de consulta'), ('valoracion', 'Valoración'), ('atencion', 'Atención realizada'),
            ('recomendaciones', 'Recomendaciones'), ('seguimiento', 'Seguimiento'),
        ):
            doc.add_heading(etiqueta, level=1)
            doc.add_paragraph(datos.get(campo, ''))
    for etiqueta, valor in (
        ('Folio de cita', entrevista.cita.folio_cita), ('Fecha de atención', fecha.strftime('%d/%m/%Y')),
        ('Persona atendida', identidad['nombre']), ('CURP', identidad.get('curp', '')),
        ('RFC personal', identidad.get('rfc_personal', '')), ('Correo', identidad.get('correo', '')),
        ('Responsable', f'{entrevista.cita.ciudadano.nombre} {entrevista.cita.ciudadano.apellidos}'),
        ('Institución o juzgado y referencia', identidad.get('referencia', '')),
        ('Sede', entrevista.cita.turno_social.sede.nombre),
        ('Personal que atendió', f'{entrevista.funcionario.nombre} {entrevista.funcionario.apellidos}'),
        ('Cédula profesional', entrevista.funcionario.cedula_profesional),
    ):
        doc.add_paragraph(f'{etiqueta}: {valor}')
    doc.add_paragraph('Firma del personal: ____________________')
    salida = BytesIO()
    doc.save(salida)
    return salida.getvalue()


def convertir_pdf(word):
    ejecutable = os.environ.get('LIBREOFFICE_BIN') or shutil.which('soffice') or shutil.which('soffice.exe')
    if not ejecutable:
        raise RuntimeError('LibreOffice no está disponible.')
    with tempfile.TemporaryDirectory(prefix='dif-social-') as temporal:
        carpeta = Path(temporal)
        origen = carpeta / 'atencion.docx'
        origen.write_bytes(word)
        perfil = (carpeta / 'perfil').as_uri()
        try:
            resultado = subprocess.run(
                [ejecutable, f'-env:UserInstallation={perfil}', '--headless', '--convert-to',
                 'pdf:writer_pdf_Export', '--outdir', str(carpeta), str(origen)],
                capture_output=True, timeout=85, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('Se agotó el tiempo de conversión.') from exc
        pdf = carpeta / 'atencion.pdf'
        if resultado.returncode or not pdf.exists():
            raise RuntimeError('LibreOffice no pudo generar el PDF.')
        return pdf.read_bytes()


def generar(entrevista):
    word = construir_word(entrevista)
    return word, convertir_pdf(word)
