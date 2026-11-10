from datetime import date, datetime, time
from io import BytesIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import Permission
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from pypdf import PdfReader

from .models import (
    Cita, Ciudadano, ConsultaClinica, Direccion, DocumentoClinico, ExpedienteClinico,
    Solicitud, Tramite, TurnoMedico,
)


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class RegistroTests(TestCase):
    def test_registro_activa_y_abre_sesion_sin_correo(self):
        respuesta = self.client.post(reverse('registro'), {
            'curp': 'PACIENTE3', 'email': 'paciente3@example.com', 'nombre': 'Paciente',
            'paterno': 'Prueba', 'materno': '', 'password': 'Prueba-123', 'password-conf': 'Prueba-123',
            'cp': '01234', 'colonia': 'Colonia sin catálogo', 'mz': 'Mz 2 Lt 4',
        })
        self.assertRedirects(respuesta, reverse('inicio'))
        usuario = Ciudadano.objects.get(pk='PACIENTE3')
        self.assertTrue(usuario.is_active)
        self.assertFalse(usuario.is_staff)
        self.assertEqual(usuario.colonia, 'Colonia sin catálogo')
        self.assertEqual(usuario.mz_lt, 'Mz 2 Lt 4')
        self.assertEqual(self.client.session['_auth_user_id'], usuario.pk)
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
        self.assertContains(self.client.post(self.inicio, {}), 'Ficha clínica de primera vez')
        self.assertContains(self.client.post(self.inicio, {**self.ficha, 'edad': 12}), 'datos del padre o tutor')
        self.assertFalse(Solicitud.objects.exists())
        primera = self.client.post(self.inicio, self.ficha)
        solicitud = Solicitud.objects.get(ciudadano=self.ciudadano)
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
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse('panel_funcionario')), 'data-clinical-modal')
        self.assertContains(self.client.get(detalle), 'Motivo de atención', count=1)
        self.assertContains(self.client.post(detalle, {}), 'Revisa los campos marcados')
        captura = {
            'padecimiento_actual': 'Motivo de prueba', 'diagnostico': 'Análisis de prueba',
            'acciones_linea_vida': 'Acción de prueba', 'pronostico': 'Resolución de prueba',
            'medico': 'Personal de prueba', 'cedula_profesional': '1234567',
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
        self.assertEqual(documento.generado_por, self.staff)
        self.assertContains(self.client.get(historia), documento.nombre)
        pdf = PdfReader(BytesIO(documento.contenido))
        self.assertEqual(len(pdf.pages), 3)
        self.assertIn('Motivo de prueba', pdf.pages[0].extract_text())
        self.assertIn(f'EXP-{expediente.pk}', pdf.pages[0].extract_text())
        self.assertIn('Registro cardiovascular de prueba', pdf.pages[0].extract_text())
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
