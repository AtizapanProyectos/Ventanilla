from datetime import date, datetime, time
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import Permission
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from pypdf import PdfReader

from .models import (
    Cita, Ciudadano, ConsultaClinica, Direccion, DocumentoClinico, ExpedienteClinico,
    HorarioDireccion, Solicitud, Tramite, TurnoMedico,
)


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class RegistroTests(TestCase):
    def test_registro_activa_y_abre_sesion_sin_correo(self):
        navegador = Client(enforce_csrf_checks=True)
        registro = reverse('registro')
        exito = reverse('registro_exito')
        navegador.get(registro)
        token = navegador.cookies['csrftoken'].value
        datos = {
            'curp': 'PACIENTE3', 'email': 'paciente3@example.com', 'nombre': 'Paciente',
            'paterno': 'Prueba', 'materno': '', 'password': 'Prueba-123', 'password-conf': 'Prueba-123',
            'cp': '01234', 'colonia': 'Colonia sin catálogo', 'mz': 'Mz 2 Lt 4',
            'csrfmiddlewaretoken': token,
        }
        self.assertEqual(Client(enforce_csrf_checks=True).post(registro, datos).status_code, 403)
        self.assertFalse(Ciudadano.objects.filter(pk='PACIENTE3').exists())
        respuesta = navegador.post(registro, datos, follow=True)
        self.assertRedirects(respuesta, exito)
        self.assertContains(respuesta, 'Tu cuenta está activa')
        usuario = Ciudadano.objects.get(pk='PACIENTE3')
        self.assertTrue(usuario.is_active)
        self.assertFalse(usuario.is_staff)
        self.assertEqual(usuario.colonia, 'Colonia sin catálogo')
        self.assertEqual(usuario.mz_lt, 'Mz 2 Lt 4')
        self.assertEqual(navegador.session['_auth_user_id'], usuario.pk)
        self.assertNotEqual(navegador.cookies['csrftoken'].value, token)
        self.assertRedirects(navegador.post(registro, datos), exito)
        self.assertEqual(Ciudadano.objects.filter(pk=usuario.pk).count(), 1)
        self.assertRedirects(self.client.get(exito), reverse('inicio'))
        self.assertEqual(len(mail.outbox), 0)

    def test_admin_exige_que_la_cuenta_staff_este_activa(self):
        usuario = Ciudadano.objects.create_user(
            'STAFF2', 'staff2@example.com', 'Prueba-123', is_staff=True,
        )
        admin_login = reverse('admin:login')
        credenciales = {'username': usuario.pk, 'password': 'Prueba-123', 'next': reverse('admin:index')}
        self.assertEqual(self.client.post(admin_login, credenciales).status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        usuario.is_active = True
        usuario.save(update_fields=['is_active'])
        self.assertRedirects(self.client.post(admin_login, credenciales), reverse('admin:index'))

    def test_contrasena_cambiada_en_admin_funciona_con_curp_pegada(self):
        staff = Ciudadano.objects.create_user(
            'XEXX010101HNEXXXA4', 'clinica@example.com', 'Anterior-807!',
            is_staff=True, is_active=True,
        )
        staff.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='ciudadanos', codename__in=('view_cita', 'view_expedienteclinico'),
        ))
        administrador = Ciudadano.objects.create_superuser('ADMINQA', 'admin@example.com')
        self.client.force_login(administrador)
        nueva = 'Nueva-clave-915!'
        cambio = reverse('admin:auth_user_password_change', args=[staff.pk])
        respuesta = self.client.post(cambio, {
            'usable_password': 'true', 'password1': nueva, 'password2': nueva,
        })
        self.assertRedirects(respuesta, reverse('admin:ciudadanos_ciudadano_change', args=[staff.pk]))
        staff.refresh_from_db()
        self.assertTrue(staff.check_password(nueva))
        self.client.logout()
        curp_pegada = f'  {staff.pk.lower()} '
        self.assertRedirects(self.client.post(reverse('admin:login'), {
            'username': curp_pegada, 'password': nueva, 'next': reverse('admin:index'),
        }), reverse('admin:index'))
        self.client.logout()
        self.assertRedirects(self.client.post(reverse('login_funcionario'), {
            'curp': curp_pegada, 'password': nueva,
        }), reverse('panel_funcionario'))


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class ServicioSocialTests(TestCase):
    def test_carga_revision_correccion_y_agenda(self):
        tramite = Tramite.objects.get(es_servicio_social=True)
        requisitos = list(tramite.requisitos.all())
        self.assertEqual(len(requisitos), 6)
        HorarioDireccion.objects.create(
            direccion=tramite.direccion, dia_semana=0,
            hora_inicio=time(12), hora_fin=time(13), duracion_cita_minutos=30,
        )
        aspirante = Ciudadano.objects.create_user('ASPIRANTEQA', 'aspirante@example.com', is_active=True)
        revisor = Ciudadano.objects.create_user(
            'REVISORQA', 'revisor@example.com', is_active=True, is_staff=True,
        )
        revisor.user_permissions.add(Permission.objects.get(codename='validar_servicio_social'))
        inicio = reverse('iniciar_tramite', args=[tramite.pk])
        self.client.force_login(aspirante)
        self.assertContains(self.client.get(reverse('inicio')), inicio)
        self.assertContains(self.client.get(inicio), 'Dafne Marilu Suarez Salazar')
        self.assertContains(self.client.post(inicio, {
            'nivel_estudios': 'licenciatura', 'porcentaje_creditos': 69,
        }), 'al menos 70%')
        self.assertFalse(Solicitud.objects.exists())

        datos = {'nivel_estudios': 'tecnico', 'porcentaje_creditos': 50}
        for requisito in requisitos:
            datos[f'req_{requisito.pk}'] = SimpleUploadedFile('requisito.pdf', b'%PDF-1.4\n', 'application/pdf')
        self.assertRedirects(self.client.post(inicio, datos), reverse('mis_tramites'))
        solicitud = Solicitud.objects.get()
        agenda = reverse('agendar_cita', args=[solicitud.pk])
        revisar = reverse('revisar_solicitud', args=[solicitud.pk])
        corregir = reverse('corregir_solicitud', args=[solicitud.pk])
        self.assertRedirects(self.client.get(inicio), corregir)
        self.assertRedirects(self.client.get(agenda), reverse('mis_tramites'))
        primero = solicitud.archivos.first()
        descarga = reverse('descargar_documento_servicio_social', args=[primero.pk])
        self.assertEqual(Client().get(descarga).status_code, 404)
        self.assertEqual(self.client.get(descarga).status_code, 200)

        self.client.force_login(revisor)
        self.assertContains(self.client.get(reverse('panel_funcionario')), solicitud.folio)
        self.assertContains(self.client.get(revisar), 'Nivel técnico')
        self.assertEqual(self.client.get(descarga).status_code, 200)
        revision = {f'estado_doc_{archivo.pk}': 'Aprobado' for archivo in solicitud.archivos.all()}
        self.client.post(revisar, {**revision, f'estado_doc_{primero.pk}': 'Rechazado',
                                  f'obs_doc_{primero.pk}': 'Documento ilegible'})
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, 'Rechazado')
        self.client.force_login(aspirante)
        self.assertContains(self.client.get(corregir), 'Documento ilegible')
        self.assertRedirects(self.client.post(corregir, {
            'nivel_estudios': 'tecnico', 'porcentaje_creditos': 50,
            f'req_{primero.requisito_id}': SimpleUploadedFile('corregido.pdf', b'%PDF-1.4\n', 'application/pdf'),
        }), reverse('mis_tramites'))
        self.client.force_login(revisor)
        self.client.post(revisar, revision)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, 'Aprobado')
        self.client.force_login(aspirante)
        ahora = datetime(2026, 11, 9, 9, tzinfo=ZoneInfo('America/Mexico_City'))
        with patch('ciudadanos.servicio_social.timezone.localtime', return_value=ahora):
            self.assertContains(self.client.get(agenda), 'Folder azul cielo tamaño carta')
            self.assertContains(self.client.post(agenda, {'turno': '2026-11-09|11:00:00'}), 'ya no está disponible')
            ticket = reverse('ticket_servicio_social', args=[solicitud.pk])
            for _ in range(2):
                self.assertRedirects(self.client.post(agenda, {'turno': '2026-11-09|12:30:00'}), ticket)
            self.assertContains(self.client.get(ticket), 'Certificado médico expedido por el DIF')
            self.assertEqual(Cita.objects.filter(solicitud=solicitud).count(), 1)


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class CitasMedicasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ciudadano = Ciudadano.objects.create_user('PACIENTE1', 'paciente1@example.com', is_active=True)
        cls.otro = Ciudadano.objects.create_user('PACIENTE2', 'paciente2@example.com', is_active=True)
        cls.admin = Ciudadano.objects.create_superuser('CLINICA1', 'clinica1@example.com')
        cls.staff = Ciudadano.objects.create_user(
            'STAFF1', 'staff1@example.com', is_staff=True, is_active=True,
        )
        direccion = Direccion.objects.create(nombre='DIF')
        cls.tramite = Tramite.objects.create(
            nombre='Cita Médica', direccion=direccion, tiempo='30 min',
            costo='Según catálogo', modalidad='Presencial', es_cita_medica=True,
        )
        TurnoMedico.objects.create(tramite=cls.tramite, dia_semana=0, hora=time(12, 30))

    ficha = {
        'edad': 35, 'genero': 'Femenino', 'estado_civil': 'Soltera', 'ocupacion': 'Otra',
        'lugar_origen': 'Atizapán', 'lugar_residencia': 'Atizapán', 'escolaridad': 'Secundaria',
        'domicilio': 'Calle de prueba', 'telefono': '5555555555',
    }
    inicio_fecha = datetime(2026, 11, 9, 9, tzinfo=ZoneInfo('America/Mexico_City'))
    turno = '2026-11-09|12:30:00'

    def setUp(self):
        self.inicio = reverse('iniciar_tramite', args=[self.tramite.pk])
        self.client.force_login(self.ciudadano)
        reloj = patch('ciudadanos.citas_medicas.timezone.localtime', return_value=self.inicio_fecha)
        reloj.start()
        self.addCleanup(reloj.stop)

    def test_primera_cita_ticket_y_cita_recurrente(self):
        self.assertContains(self.client.get(self.inicio), 'Ficha clínica de primera vez')
        self.assertNotContains(self.client.get(self.inicio), 'name="antecedentes_familiares"')
        self.assertContains(self.client.post(self.inicio, {}), 'Ficha clínica de primera vez')
        self.assertContains(self.client.post(self.inicio, {**self.ficha, 'edad': 12}), 'datos del padre o tutor')
        self.assertFalse(Solicitud.objects.exists())
        primera = self.client.post(self.inicio, {
            **self.ficha, 'tutor': 'No corresponde', 'parentesco': 'Padre',
            'antecedentes_familiares': 'Dato enviado desde el formulario ciudadano',
        })
        solicitud = Solicitud.objects.get(ciudadano=self.ciudadano)
        expediente = ExpedienteClinico.objects.get(ciudadano=self.ciudadano)
        self.assertEqual((expediente.tutor, expediente.parentesco), ('', ''))
        self.assertEqual(expediente.antecedentes_familiares, '')
        agenda = reverse('agendar_cita', args=[solicitud.pk])
        ticket = reverse('ticket_cita_medica', args=[solicitud.pk])
        self.assertRedirects(primera, agenda)
        self.assertContains(self.client.get(agenda), self.turno)
        self.assertRedirects(self.client.post(agenda, {'turno': self.turno}), ticket)
        self.assertRedirects(self.client.post(agenda, {'turno': self.turno}), ticket)
        cita = Cita.objects.get(solicitud=solicitud)
        self.assertContains(self.client.get(ticket), cita.folio_cita)
        self.assertContains(self.client.get(reverse('mis_tramites')), 'Ver ticket')
        self.assertRedirects(self.client.post(self.inicio, {}), ticket)

        cita.estado = 'Atendida'
        cita.save()
        self.assertContains(self.client.get(self.inicio), 'Ya tienes un expediente clínico')
        self.client.post(self.inicio, {})
        self.assertEqual(Solicitud.objects.filter(ciudadano=self.ciudadano).count(), 2)
        self.assertEqual(ExpedienteClinico.objects.filter(ciudadano=self.ciudadano).count(), 1)

    def test_cita_dental_usa_el_formato_y_deja_el_reverso_intacto(self):
        dental = Tramite.objects.get(es_cita_dental=True)
        TurnoMedico.objects.create(tramite=dental, dia_semana=0, hora=time(12, 30))
        inicio = reverse('iniciar_tramite', args=[dental.pk])
        portada = self.client.get(reverse('inicio')).content.decode()
        self.assertLess(portada.index('>Cita Médica'), portada.index('>Cita Dental'))
        self.client.post(inicio, self.ficha)
        solicitud = Solicitud.objects.get(tramite=dental)
        agenda = reverse('agendar_cita', args=[solicitud.pk])
        ticket = reverse('ticket_cita_medica', args=[solicitud.pk])
        self.assertContains(self.client.get(agenda), 'Agenda de cita dental')
        self.assertRedirects(self.client.post(agenda, {'turno': self.turno}), ticket)
        self.assertContains(self.client.get(ticket), 'Ticket de cita dental')
        cita = Cita.objects.get(solicitud=solicitud)
        detalle = reverse('panel_cita_medica', args=[cita.pk])
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(detalle), 'name="hipertension"')
        self.assertNotContains(self.client.get(detalle), 'name="signos_vitales"')
        respuesta = self.client.post(detalle, {
            'edad': 35, 'fecha_primera_atencion': '2026-11-09', 'tipo_sangre': 'O+',
            'diabetes': 'no', 'hipertension': 'si', 'enfermedad_actual': 'Captura odontológica de prueba',
            'odontograma': 'Este dato debe ignorarse',
        })
        self.assertContains(respuesta, 'Historia odontológica generada')
        cita.refresh_from_db()
        self.assertEqual(cita.estado, 'Atendida')
        consulta = cita.consulta_clinica
        self.assertEqual(consulta.datos_odontologicos['hipertension'], 'si')
        self.assertNotIn('odontograma', consulta.datos_odontologicos)
        documento = consulta.pdf_institucional
        pdf = PdfReader(BytesIO(documento.contenido))
        plantilla = PdfReader(Path(__file__).resolve().parents[1] / 'Tramites' / 'Historia Clinica Odontologia.pdf')
        self.assertEqual(len(pdf.pages), 2)
        self.assertIn('Captura odontológica de prueba', pdf.pages[0].extract_text())
        self.assertEqual(pdf.pages[1].get_contents().get_data(), plantilla.pages[1].get_contents().get_data())
        self.client.force_login(self.ciudadano)
        self.assertContains(self.client.get(ticket), 'Descargar historia odontológica en PDF')

    def test_turno_ocupado_y_fuera_de_horario(self):
        Cita.objects.create(
            ciudadano=self.otro, tramite=self.tramite, fecha=date(2026, 11, 9), hora=time(12, 30),
        )
        self.client.post(self.inicio, self.ficha)
        agenda = reverse('agendar_cita', args=[Solicitud.objects.get(ciudadano=self.ciudadano).pk])
        respuesta = self.client.get(agenda)
        self.assertContains(respuesta, self.turno)
        self.assertContains(respuesta, 'Ocupado')
        for turno in (self.turno, '2026-11-09|09:00:00', '2026-11-09|14:00:00', '2026-11-10|12:30:00'):
            self.assertContains(self.client.post(agenda, {'turno': turno}), 'ya no está disponible')
        self.assertFalse(Cita.objects.filter(ciudadano=self.ciudadano).exists())

    def test_panel_y_archivo_clinico_privado(self):
        self.client.post(self.inicio, self.ficha)
        expediente = ExpedienteClinico.objects.get()
        solicitud = Solicitud.objects.get()
        self.client.post(reverse('agendar_cita', args=[solicitud.pk]), {'turno': self.turno})
        ticket = reverse('ticket_cita_medica', args=[solicitud.pk])
        expediente_url = reverse('admin:ciudadanos_expedienteclinico_change', args=[expediente.pk])
        cita_url = reverse('admin:ciudadanos_cita_change', args=[Cita.objects.get().pk])
        self.client.force_login(self.otro)
        self.assertEqual(self.client.get(ticket).status_code, 404)

        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('panel_funcionario')), 'Ver expediente')
        self.assertContains(self.client.get(cita_url), 'Cédula profesional')
        respuesta = self.client.post(cita_url, {
            'estado': 'Atendida',
            'consulta_clinica-TOTAL_FORMS': '1', 'consulta_clinica-INITIAL_FORMS': '0',
            'consulta_clinica-0-medico': 'Personal de prueba',
            'consulta_clinica-0-cedula_profesional': '1234567',
        })
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(ConsultaClinica.objects.get().cita.estado, 'Atendida')
        respuesta = self.client.post(expediente_url, {
            **self.ficha,
            'documentos-TOTAL_FORMS': '1', 'documentos-INITIAL_FORMS': '0',
            'documentos-0-archivo': SimpleUploadedFile('prueba.pdf', b'%PDF-1.4\n', 'application/pdf'),
        })
        self.assertEqual(respuesta.status_code, 302)
        documento = DocumentoClinico.objects.get(expediente=expediente)
        descarga = reverse('admin:ciudadanos_documentoclinico_descargar', args=[documento.pk])
        respuesta = self.client.get(descarga)
        self.assertEqual(b''.join(respuesta.streaming_content), b'%PDF-1.4\n')
        self.assertIn('attachment', respuesta.headers['Content-Disposition'])

        self.staff.user_permissions.add(Permission.objects.get(codename='view_expedienteclinico'))
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(descarga).status_code, 403)
        self.staff.user_permissions.add(Permission.objects.get(codename='view_documentoclinico'))
        self.assertEqual(self.client.get(descarga).status_code, 200)
        self.client.force_login(self.ciudadano)
        self.assertEqual(self.client.get(descarga).status_code, 302)

    def test_panel_finaliza_una_vez_y_publica_pdf_privado(self):
        self.client.post(self.inicio, self.ficha)
        expediente = ExpedienteClinico.objects.get()
        expediente.antecedentes_patologicos = 'Antecedente anterior'
        expediente.save(update_fields=['antecedentes_patologicos'])
        solicitud = Solicitud.objects.get()
        self.client.post(reverse('agendar_cita', args=[solicitud.pk]), {'turno': self.turno})
        cita = Cita.objects.get()
        detalle = reverse('panel_cita_medica', args=[cita.pk])
        historia = reverse('panel_expediente_clinico', args=[expediente.pk])
        ticket = reverse('ticket_cita_medica', args=[solicitud.pk])
        self.assertEqual(self.client.get(historia).status_code, 403)
        self.staff.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='ciudadanos', codename__in=(
                'view_cita', 'change_cita', 'view_expedienteclinico', 'add_consultaclinica',
                'view_documentoclinico',
            ),
        ))
        self.staff.nombre = 'Médico'
        self.staff.apellidos = 'de prueba'
        self.staff.cedula_profesional = '7654321'
        self.staff.save(update_fields=['nombre', 'apellidos', 'cedula_profesional'])
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse('panel_funcionario')), 'data-clinical-modal')
        self.assertContains(self.client.get(detalle), 'Motivo de atención', count=1)
        self.assertContains(self.client.get(detalle), 'value="7654321"')
        self.assertContains(self.client.get(detalle), 'Antecedente anterior')
        self.assertContains(self.client.post(detalle, {}), 'Revisa los campos marcados')
        captura = {
            'padecimiento_actual': 'Motivo de prueba', 'diagnostico': 'Análisis de prueba',
            'acciones_linea_vida': 'Acción de prueba', 'pronostico': 'Resolución de prueba',
            'medico': 'Personal de prueba', 'cedula_profesional': '1234567',
            'antecedentes_familiares': 'Antecedente familiar capturado por el médico',
            'peso_kg': '70.20', 'talla_m': '1.75', 'tension_arterial': '120/80',
            'frecuencia_cardiaca': '72', 'frecuencia_respiratoria': '16',
            'temperatura_c': '36.5', 'saturacion_oxigeno': '98', 'glucosa_mg_dl': '92',
            'revision_sistemas_cardiovascular': 'Registro cardiovascular de prueba',
            'revision_sistemas_piel': 'Registro de piel de prueba',
            'revision_regiones_cabeza': 'Exploración de cabeza de prueba',
        }
        for _ in range(2):
            self.assertContains(self.client.post(detalle, captura), 'Historia clínica generada')
        cita.refresh_from_db()
        self.assertEqual(cita.estado, 'Atendida')
        documento = DocumentoClinico.objects.get(consulta__cita=cita)
        expediente.refresh_from_db()
        self.assertEqual(expediente.antecedentes_familiares, 'Antecedente familiar capturado por el médico')
        self.assertEqual(expediente.antecedentes_patologicos, 'Antecedente anterior')
        self.assertEqual(documento.generado_por, self.staff)
        self.assertEqual(documento.consulta.medico, 'Médico de prueba')
        self.assertEqual(documento.consulta.cedula_profesional, '7654321')
        self.assertContains(self.client.get(historia), documento.nombre)
        pdf = PdfReader(BytesIO(documento.contenido))
        self.assertEqual(len(pdf.pages), 3)
        self.assertIn('Motivo de prueba', pdf.pages[0].extract_text())
        self.assertIn(f'EXP-{expediente.pk}', pdf.pages[0].extract_text())
        self.assertIn('Registro cardiovascular de prueba', pdf.pages[0].extract_text())
        self.assertIn('Antecedente familiar capturado por el médico', pdf.pages[0].extract_text())
        segunda_pagina = pdf.pages[1].extract_text()
        for valor in ('Resolución de prueba', '70.20', '1.75', '22.92', '120/80', '72', '16', '36.5', '98', '92',
                      'Registro de piel de prueba', 'Exploración de cabeza de prueba'):
            self.assertIn(valor, segunda_pagina)
        self.assertIn(self.ciudadano.curp, pdf.pages[2].extract_text())
        self.assertIn(cita.folio_cita, pdf.pages[2].extract_text())

        descarga = reverse('descargar_documento_clinico', args=[documento.pk])
        self.assertEqual(self.client.get(descarga).status_code, 200)
        self.client.force_login(self.otro)
        self.assertEqual(self.client.get(descarga).status_code, 404)
        self.client.force_login(self.ciudadano)
        self.assertContains(self.client.get(ticket), descarga)
        self.assertEqual(self.client.get(descarga).status_code, 200)

    def test_borrado_clinico_en_cascada(self):
        expediente = ExpedienteClinico.objects.create(ciudadano=self.ciudadano, **self.ficha)
        evidencia = DocumentoClinico.objects.create(
            expediente=expediente, nombre='evidencia.pdf', contenido=b'%PDF-1.4',
        )
        cita = Cita.objects.create(
            ciudadano=self.ciudadano, tramite=self.tramite,
            fecha=self.inicio_fecha.date(), hora=time(12, 30),
        )
        consulta = ConsultaClinica.objects.create(cita=cita, medico='Prueba', cedula_profesional='1234567')
        historia = DocumentoClinico.objects.create(
            expediente=expediente, consulta=consulta, nombre='historia.pdf', contenido=b'%PDF-1.4',
        )

        cita.delete()
        self.assertFalse(ConsultaClinica.objects.filter(pk=consulta.pk).exists())
        self.assertFalse(DocumentoClinico.objects.filter(pk=historia.pk).exists())
        self.assertTrue(DocumentoClinico.objects.filter(pk=evidencia.pk).exists())

        self.ciudadano.delete()
        self.assertFalse(ExpedienteClinico.objects.filter(pk=expediente.pk).exists())
        self.assertFalse(DocumentoClinico.objects.filter(pk=evidencia.pk).exists())

@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class ProveedoresTests(TestCase):
    def setUp(self):
        from .models import ArchivoRequisito, Requisito
        self.Archivo = ArchivoRequisito
        self.Requisito = Requisito
        self.tramite = Tramite.objects.get(es_alta_proveedor=True)
        self.usuario = Ciudadano.objects.create_user(
            'PROVEEDORQA', 'proveedor@example.com', is_active=True, nombre='Proveedor', apellidos='Prueba',
        )
        self.otro = Ciudadano.objects.create_user('OTROPROVQA', 'otroprov@example.com', is_active=True)
        self.revisor = Ciudadano.objects.create_user(
            'ADMINPROVQA', 'adminprov@example.com', is_active=True, is_staff=True,
        )
        self.revisor.user_permissions.add(Permission.objects.get(codename='validar_proveedores'))
        self.client.force_login(self.usuario)
        self.inicio = reverse('iniciar_tramite', args=[self.tramite.pk])
        self.perfil = {
            'tipo_persona': 'fisica', 'rfc': 'LOHA050220AB1', 'accion': 'enviar',
        }

    def datos_carga(self, perfil):
        from .proveedores import requisitos_aplicables
        datos = dict(perfil)
        for req in requisitos_aplicables(self.tramite, {
            'tipo_persona': perfil['tipo_persona'], 'tiene_representante': perfil['tipo_persona'] == 'moral',
        }):
            datos[f'req_{req.pk}'] = SimpleUploadedFile('documento.pdf', b'%PDF-1.4', 'application/pdf')
        return datos

    def test_persona_fisica_reutiliza_y_se_valida_antes_de_cita(self):
        req = self.tramite.requisitos.get(tipo_documento='acta_nacimiento')
        anterior = Solicitud.objects.create(
            ciudadano=self.usuario, tramite=Tramite.objects.get(es_servicio_social=True), folio='TRAM-PREVIO',
        )
        origen = self.Archivo.objects.create(
            solicitud=anterior, requisito=req, contenido_pdf=b'%PDF-1.4', nombre_pdf='acta.pdf',
            tipo_documento='acta_nacimiento', titular_documento=f'CURP:{self.usuario.pk}',
            estado_validacion='Aprobado',
        )
        preparada = self.client.post(self.inicio, {**self.perfil, 'accion': 'preparar'})
        self.assertContains(preparada, 'Documento reutilizado')
        self.assertNotContains(preparada, 'Acta constitutiva')
        self.assertNotContains(preparada, 'Poder suficiente')
        fotografia = self.tramite.requisitos.get(tipo_documento='fotografias')
        self.assertNotContains(preparada, f'name="req_{fotografia.pk}"')
        datos = self.datos_carga(self.perfil)
        del datos[f'req_{req.pk}']
        self.assertRedirects(self.client.post(self.inicio, datos), reverse('mis_tramites'))
        solicitud = Solicitud.objects.get(tramite=self.tramite)
        self.assertEqual(solicitud.archivos.count(), 6)
        vinculo = solicitud.archivos.get(requisito=req)
        self.assertEqual(vinculo.origen, origen)
        self.assertIsNone(vinculo.contenido_pdf)
        self.assertEqual(vinculo.estado_validacion, 'Pendiente')
        self.assertEqual(origen.estado_validacion, 'Aprobado')
        descarga = reverse('documento_proveedor', args=[vinculo.pk])
        self.assertEqual(b''.join(self.client.get(descarga).streaming_content), b'%PDF-1.4')
        agenda = reverse('agendar_cita', args=[solicitud.pk])
        self.assertRedirects(self.client.get(agenda), reverse('mis_tramites'))
        self.client.force_login(self.otro)
        self.assertEqual(self.client.get(descarga).status_code, 404)
        self.client.force_login(self.revisor)
        self.assertContains(self.client.get(reverse('panel_funcionario')), solicitud.folio)
        revision = reverse('revisar_solicitud', args=[solicitud.pk])
        self.assertContains(self.client.get(revision), 'Documento reutilizado')
        decisiones = {f'estado_doc_{a.pk}': 'Aprobado' for a in solicitud.archivos.all()}
        self.client.post(revision, {**decisiones, f'estado_doc_{vinculo.pk}': 'Rechazado',
                                   f'obs_doc_{vinculo.pk}': 'Reemplazar documento'})
        origen.refresh_from_db()
        self.assertEqual(origen.estado_validacion, 'Aprobado')
        self.client.force_login(self.usuario)
        correccion = reverse('corregir_solicitud', args=[solicitud.pk])
        self.assertContains(self.client.get(correccion), 'Reemplazar documento')
        self.assertRedirects(self.client.post(correccion, {
            'accion': 'enviar', f'req_{req.pk}': SimpleUploadedFile('nueva.pdf', b'%PDF-1.4 NUEVA'),
        }), reverse('mis_tramites'))
        vinculo.refresh_from_db()
        self.assertIsNone(vinculo.origen)
        self.client.force_login(self.revisor)
        self.client.post(revision, decisiones)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, 'Aprobado')
        # Una fotografía de una solicitud anterior no debe bloquear la agenda ni pedirse al revisor.
        foto_anterior = self.Archivo.objects.create(
            solicitud=solicitud, requisito=fotografia, nombre_pdf='foto.pdf', contenido_pdf=b'%PDF-1.4',
            estado_validacion='Rechazado',
        )
        from .proveedores import validada
        self.assertTrue(validada(solicitud))
        self.assertNotContains(self.client.get(revision), f'name="estado_doc_{foto_anterior.pk}"')
        HorarioDireccion.objects.create(
            direccion=self.tramite.direccion, dia_semana=0, hora_inicio=time(12),
            hora_fin=time(13), duracion_cita_minutos=30,
        )
        self.client.force_login(self.usuario)
        ahora = datetime(2026, 11, 23, 9, tzinfo=ZoneInfo('America/Mexico_City'))
        with patch('ciudadanos.proveedores.timezone.localtime', return_value=ahora):
            self.assertContains(self.client.get(agenda), 'Recuerda llevar dos fotografías')
            ticket = reverse('ticket_proveedor', args=[solicitud.pk])
            for _ in range(2):
                self.assertRedirects(self.client.post(agenda, {'turno': '2026-11-23|12:30:00'}), ticket)
            self.assertContains(self.client.get(ticket), self.perfil['rfc'])
            self.assertContains(self.client.get(ticket), 'Recuerda llevar dos fotografías')
            self.assertEqual(Cita.objects.filter(solicitud=solicitud).count(), 1)

    def test_moral_requiere_razon_social_y_no_reutiliza_otro_rfc(self):
        from .proveedores import PerfilProveedorForm, reutilizable
        perfil = {**self.perfil, 'tipo_persona': 'moral', 'rfc': 'DIF050220AB1', 'razon_social': 'Empresa de Prueba'}
        self.assertFalse(PerfilProveedorForm({**perfil, 'razon_social': ''}).is_valid())
        datos = PerfilProveedorForm(perfil)
        self.assertTrue(datos.is_valid())
        req = self.tramite.requisitos.get(tipo_documento='cedula_fiscal')
        anterior = Solicitud.objects.create(ciudadano=self.usuario, tramite=self.tramite, folio='TRAM-OTRAEMPRESA')
        self.Archivo.objects.create(
            solicitud=anterior, requisito=req, nombre_pdf='rfc.pdf', contenido_pdf=b'%PDF-1.4',
            tipo_documento='cedula_fiscal', titular_documento='RFC:OTR050220AB1', estado_validacion='Aprobado',
        )
        self.assertIsNone(reutilizable(req, datos.cleaned_data, self.usuario))
        self.assertRedirects(self.client.post(self.inicio, self.datos_carga(perfil)), reverse('mis_tramites'))
        solicitud = Solicitud.objects.exclude(pk=anterior.pk).get(tramite=self.tramite)
        self.assertEqual(solicitud.archivos.count(), 7)
        self.assertTrue(solicitud.archivos.filter(requisito__tipo_documento='poder_representante').exists())
        self.assertFalse(solicitud.archivos.filter(requisito__tipo_documento='acta_nacimiento').exists())
        self.assertEqual(solicitud.datos_proveedor['razon_social'], 'Empresa de Prueba')

    def test_registro_moral_guarda_identidad_y_entra_con_curp(self):
        self.client.logout()
        respuesta = self.client.post(reverse('registro'), {
            'curp': 'NUEVOPROVQA', 'email': 'nuevoprov@example.com', 'nombre': 'Representante',
            'paterno': 'Prueba', 'password': 'Prueba-123', 'password-conf': 'Prueba-123',
            'colonia': 'Centro', 'tipo_persona': 'moral', 'rfc': 'DIF050220AB1', 'razon_social': 'Empresa',
        })
        self.assertRedirects(respuesta, reverse('registro_exito'))
        usuario = Ciudadano.objects.get(pk='NUEVOPROVQA')
        self.assertEqual(usuario.rfc, 'DIF050220AB1')
        self.assertTrue(usuario.tiene_representante)
        self.assertEqual(self.client.session['_auth_user_id'], usuario.pk)

@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class ProcuraduriaTests(TestCase):
    def setUp(self):
        from .models import SedeSocial, HorarioSocial
        self.user = Ciudadano.objects.create_user(
            'SOCIALQA', 'socialqa@example.com', nombre='Persona', apellidos='Prueba', is_active=True,
            calle='Calle', numero='10', colonia='Centro', municipio='Atizapan', estado_domicilio='Mexico', cp='52900',
            telefono_cel='5555555555', fecha_nacimiento='10/05/1990',
        )
        self.otro = Ciudadano.objects.create_user('OTROSOCIAL', 'otrosocial@example.com', is_active=True)
        self.admin = Ciudadano.objects.create_superuser('SOCIALADMIN', 'socialadmin@example.com', nombre='Responsable')
        self.estudio = Tramite.objects.get(servicio_procuraduria='socioeconomico')
        self.psico = Tramite.objects.get(servicio_procuraduria='psicologia')
        self.sede = SedeSocial.objects.create(nombre='Sede de prueba', direccion='Direccion de prueba')
        self.hoy = date(2026, 11, 18)
        self.ahora = datetime(2026, 11, 18, 9, tzinfo=ZoneInfo('America/Mexico_City'))
        for tramite in (self.estudio, self.psico):
            HorarioSocial.objects.create(tramite=tramite, sede=self.sede, dia=2, inicio=time(12), fin=time(13))
        for destino, retorno in (('django.utils.timezone.localdate', self.hoy), ('django.utils.timezone.localtime', self.ahora)):
            mock = patch(destino, return_value=retorno)
            mock.start()
            self.addCleanup(mock.stop)
        self.client.force_login(self.user)
        self.datos = {
            'persona': 'titular', 'nombre': 'Persona Prueba', 'curp': self.user.pk, 'fecha_nacimiento': '1990-05-10',
            'parentesco': 'Titular', 'telefono': '5555555555', 'correo': self.user.email, 'calle': 'Calle', 'numero': '10',
            'colonia': 'Centro', 'municipio': 'Atizapan', 'estado_domicilio': 'Mexico', 'cp': '52900',
            'modalidad': 'general', 'referencia': 'Institucion y caso 1',
        }

    def iniciar(self, tramite, **datos):
        self.client.post(reverse('iniciar_tramite', args=[tramite.pk]), {**self.datos, **datos})
        return Solicitud.objects.filter(tramite=tramite).latest('pk')

    def documentos_aprobados(self, solicitud):
        from .procuraduria import tipos_requeridos
        direccion = reverse('social_solicitud', args=[solicitud.pk])
        datos = {'accion': 'enviar'}
        for tipo in tipos_requeridos(solicitud):
            datos[tipo] = SimpleUploadedFile(tipo + '.pdf', b'%PDF-1.4', 'application/pdf')
        self.client.post(direccion, datos)
        self.client.force_login(self.admin)
        validaciones = {}
        for enlace in solicitud.requisitos_sociales.all():
            prefijo = f'doc{enlace.documento_id}-'
            validaciones.update({
                prefijo + 'estado': 'Aprobado', prefijo + 'fecha_documento': '2026-11-01',
                prefijo + 'sin_vencimiento': True,
            })
        respuesta = self.client.post(reverse('social_revisar', args=[solicitud.pk]), validaciones)
        self.assertRedirects(respuesta, reverse('panel_funcionario'))
        self.client.force_login(self.user)
        solicitud.refresh_from_db()

    def reservar(self, solicitud):
        respuesta = self.client.post(reverse('social_agenda', args=[solicitud.pk]), {
            'sede': self.sede.pk, 'turno': '2026-11-18|12:00:00',
        })
        cita = Cita.objects.get(solicitud=solicitud)
        self.assertRedirects(respuesta, reverse('social_ticket', args=[cita.pk]))
        return cita

    def test_estudio_documentos_agenda_borrador_y_error_de_generacion(self):
        from .models import AtencionSocial
        from .procuraduria import apta
        solicitud = self.iniciar(self.estudio)
        self.assertFalse(apta(solicitud))
        self.documentos_aprobados(solicitud)
        self.assertTrue(apta(solicitud))
        cita = self.reservar(solicitud)
        self.reservar(solicitud)
        self.assertEqual(Cita.objects.filter(solicitud=solicitud).count(), 1)
        self.client.force_login(self.admin)
        atender = reverse('social_atender', args=[cita.pk])
        datos = {
            'accion': 'finalizar', 'diagnostico': 'Diagnostico social de prueba', 'conclusion': 'Conclusion de prueba',
            'pago_realizado': True, 'importe': '100.00', 'fecha_pago': '2026-11-18', 'recibo': 'REC-1',
            'libro_gobierno': 'LIB-1', 'familia-TOTAL_FORMS': '0', 'familia-INITIAL_FORMS': '0',
        }
        with patch('ciudadanos.social_documentos.generar', side_effect=RuntimeError('Prueba de fallo controlado')):
            self.assertContains(self.client.post(atender, datos), 'El borrador está guardado')
        atencion = AtencionSocial.objects.get(cita=cita)
        self.assertIsNone(atencion.finalizada)
        cita.refresh_from_db()
        self.assertEqual(cita.estado, 'Programada')
        with patch('ciudadanos.social_documentos.generar', return_value=(b'WORD', b'%PDF-1.4')) as generar:
            self.assertRedirects(self.client.post(atender, datos), atender)
            self.assertRedirects(self.client.post(atender, datos), atender)
            self.assertEqual(generar.call_count, 1)
        atencion.refresh_from_db()
        self.assertEqual(atencion.version, 1)
        self.client.force_login(self.user)
        descarga = reverse('social_formato', args=[atencion.pk, 'docx'])
        self.assertEqual(self.client.get(descarga).status_code, 200)
        self.client.force_login(self.otro)
        self.assertEqual(self.client.get(descarga).status_code, 404)

    def test_psicologia_beneficiario_y_separacion_de_personas(self):
        from .models import PersonaSocial
        solicitud = self.iniciar(
            self.psico, persona='nueva', nombre='Menor de prueba', curp='MENORQA', fecha_nacimiento='2015-05-10', parentesco='Hijo',
        )
        self.assertEqual(solicitud.estado, 'Aprobado')
        self.assertFalse(solicitud.requisitos_sociales.exists())
        self.assertEqual(solicitud.persona_social.nombre, 'Menor de prueba')
        self.reservar(solicitud)
        self.client.force_login(self.otro)
        self.assertEqual(self.client.get(reverse('social_solicitud', args=[solicitud.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('iniciar_tramite', args=[self.psico.pk]),
                                        {'persona': solicitud.persona_social_id}).status_code, 404)
        self.assertEqual(PersonaSocial.objects.count(), 1)

    def test_modalidades_vigencia_y_reutilizacion(self):
        from .models import DocumentoSocial
        from .procuraduria import tipos_requeridos, tres_meses
        solicitud = self.iniciar(self.estudio, modalidad='judicial')
        self.assertIn('oficio_judicial', tipos_requeridos(solicitud))
        self.assertNotIn('solicitud_institucion', tipos_requeridos(solicitud))
        self.documentos_aprobados(solicitud)
        cita = self.reservar(solicitud)
        cita.estado = 'Atendida'
        cita.save(update_fields=['estado'])
        nueva = self.iniciar(self.estudio, modalidad='judicial')
        self.assertEqual(nueva.requisitos_sociales.count(), 4)
        self.assertEqual(DocumentoSocial.objects.count(), 4)
        self.assertEqual(nueva.estado, 'Aprobado')
        doc = nueva.requisitos_sociales.get(tipo='comprobante_domicilio').documento
        doc.fecha_documento = date(2026, 7, 1)
        doc.save()
        self.assertRedirects(self.client.get(reverse('social_agenda', args=[nueva.pk])),
                             reverse('social_solicitud', args=[nueva.pk]))
        self.assertEqual(tres_meses(date(2026, 1, 31)), date(2026, 4, 30))

    def test_cupo_y_permisos_especificos_del_personal(self):
        from django.contrib.auth.models import Permission
        from .models import TurnoSocial
        primera = self.iniciar(self.psico)
        self.reservar(primera)
        segunda = self.iniciar(self.psico, persona='nueva', nombre='Beneficiario', curp='BENEFQA', parentesco='Hijo')
        agenda = reverse('social_agenda', args=[segunda.pk])
        self.assertContains(self.client.post(agenda, {
            'sede': self.sede.pk, 'turno': '2026-11-18|12:00:00',
        }), 'ya no tiene cupo')
        self.assertFalse(Cita.objects.filter(solicitud=segunda).exists())
        self.client.post(agenda, {'sede': self.sede.pk, 'turno': '2026-11-18|03:01:00'})
        self.assertEqual(TurnoSocial.objects.count(), 1)
        atender = reverse('social_atender', args=[primera.cita.pk])
        self.assertEqual(self.client.get(atender).status_code, 403)
        self.otro.is_staff = True
        self.otro.save()
        self.otro.user_permissions.add(Permission.objects.get(codename='atender_socioeconomico'))
        self.client.force_login(self.otro)
        self.assertEqual(self.client.get(atender).status_code, 403)
        self.otro.user_permissions.add(Permission.objects.get(codename='atender_psicologia'))
        self.assertContains(self.client.get(atender), 'Consulta Psicológica')
        self.assertContains(self.client.get(reverse('panel_funcionario')), segunda.folio)

    def test_beca_correccion_y_precarga_clinica(self):
        from .models import ExpedienteClinico
        from .procuraduria import tipos_requeridos
        ExpedienteClinico.objects.create(
            ciudadano=self.user, edad=36,
            genero='Femenino', escolaridad='Licenciatura', estado_civil='Soltera', ocupacion='Estudiante',
        )
        solicitud = self.iniciar(self.estudio, modalidad='beca')
        self.assertEqual(solicitud.datos_sociales['escolaridad'], 'Licenciatura')
        self.assertIn('comprobante_estudios', tipos_requeridos(solicitud))
        self.documentos_aprobados(solicitud)
        enlace = solicitud.requisitos_sociales.get(tipo='comprobante_estudios')
        self.client.force_login(self.admin)
        validaciones = {}
        for e in solicitud.requisitos_sociales.all():
            prefijo = f'doc{e.documento_id}-'
            validaciones.update({prefijo + 'estado': 'Aprobado', prefijo + 'sin_vencimiento': True,
                                 prefijo + 'fecha_documento': '2026-11-01'})
        validaciones.update({f'doc{enlace.documento_id}-estado': 'Requiere corrección',
                             f'doc{enlace.documento_id}-observaciones': 'La boleta no es legible.'})
        self.client.post(reverse('social_revisar', args=[solicitud.pk]), validaciones)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, 'Requiere corrección')
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('social_solicitud', args=[solicitud.pk])), 'La boleta no es legible.')
        self.assertRedirects(self.client.get(reverse('social_agenda', args=[solicitud.pk])),
                             reverse('social_solicitud', args=[solicitud.pk]))
