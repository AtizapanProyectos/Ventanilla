from datetime import date, datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    Cita, Ciudadano, ConsultaClinica, Direccion, DocumentoClinico, ExpedienteClinico,
    Solicitud, Tramite, TurnoMedico,
)


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
        self.assertNotContains(self.client.get(agenda), self.turno)
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
