from datetime import date, time, timedelta
from uuid import uuid4

from django import forms
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from .models import Cita, Ciudadano, ExpedienteClinico, Solicitud, Tramite, TurnoMedico


class FichaClinicaForm(forms.ModelForm):
    @property
    def pasos(self):
        return [
            ('Identificación', [self[n] for n in ('edad', 'genero', 'estado_civil', 'ocupacion', 'escolaridad')]),
            ('Domicilio y contacto', [self[n] for n in (
                'lugar_origen', 'lugar_residencia', 'domicilio', 'telefono', 'tutor', 'parentesco',
            )]),
        ]

    def clean(self):
        datos = super().clean()
        edad = datos.get('edad')
        for campo in ('tutor', 'parentesco'):
            if edad is not None and edad < 18:
                if not datos.get(campo):
                    self.add_error(campo, 'Completa los datos del padre o tutor.')
            else:
                datos[campo] = ''
        return datos

    class Meta:
        model = ExpedienteClinico
        exclude = ('ciudadano', *ExpedienteClinico.CAMPOS_ANTECEDENTES)


@never_cache
def iniciar(request, tramite):
    usuario = request.user
    recurrente = ExpedienteClinico.objects.filter(ciudadano=usuario).exists()
    domicilio = ', '.join(filter(None, (
        ' '.join(filter(None, (usuario.calle, usuario.numero, usuario.mz_lt))),
        usuario.colonia, usuario.cp,
    )))
    ficha = FichaClinicaForm(
        request.POST if request.method == 'POST' else None,
        initial={'genero': usuario.genero, 'telefono': usuario.telefono_cel or usuario.telefono_casa,
                 'domicilio': domicilio},
    )
    if request.method == 'POST' and (recurrente or ficha.is_valid()):
        with transaction.atomic():
            Ciudadano.objects.select_for_update().get(pk=usuario.pk)
            if not ExpedienteClinico.objects.filter(ciudadano=usuario).exists():
                if not ficha.is_valid():
                    return render(request, 'ventanilla/cita_medica_inicio.html', {
                        'tramite': tramite, 'recurrente': False, 'ficha': ficha,
                    })
                expediente = ficha.save(commit=False)
                expediente.ciudadano = usuario
                expediente.save()

            solicitud = Solicitud.objects.filter(
                ciudadano=usuario, tramite=tramite, estado='Aprobado',
            ).filter(cita__isnull=True).first()
            if solicitud is None:
                ahora = timezone.localtime()
                cita = Cita.objects.filter(
                    ciudadano=usuario, tramite=tramite, estado='Programada',
                    solicitud__isnull=False,
                ).filter(
                    Q(fecha__gt=ahora.date()) | Q(fecha=ahora.date(), hora__gt=ahora.time())
                ).first()
                if cita:
                    return redirect('ticket_cita_medica', cita.solicitud_id)
                solicitud = Solicitud.objects.create(
                    ciudadano=usuario, tramite=tramite, estado='Aprobado',
                    folio=f'TRAM-{uuid4().hex[:15].upper()}',
                )
        return redirect('agendar_cita', solicitud.pk)

    return render(request, 'ventanilla/cita_medica_inicio.html', {
        'tramite': tramite, 'recurrente': recurrente, 'ficha': ficha,
    })


DIAS_AGENDA = 28


def _en_ventana(fecha, hora, ahora):
    return (
        ahora.date() <= fecha < ahora.date() + timedelta(days=DIAS_AGENDA)
        and (fecha, hora) > (ahora.date(), ahora.time())
    )


def _calendario(tramite, ahora):
    horarios = list(tramite.turnos_medicos.all())
    ocupados = set(Cita.objects.filter(
        tramite=tramite,
        fecha__gte=ahora.date(),
        fecha__lt=ahora.date() + timedelta(days=DIAS_AGENDA),
    ).exclude(estado__in=('Cancelada', 'Reprogramada')).values_list('fecha', 'hora'))
    inicio = ahora.date() - timedelta(days=ahora.weekday())
    dias = []
    for desplazamiento in range(35):
        fecha = inicio + timedelta(days=desplazamiento)
        turnos = [
            (turno.hora, (fecha, turno.hora) in ocupados)
            for turno in horarios
            if turno.dia_semana == fecha.weekday() and _en_ventana(fecha, turno.hora, ahora)
        ]
        dias.append({'fecha': fecha, 'turnos': turnos})
    return dias


def _reservar(solicitud, fecha, hora):
    with transaction.atomic():
        # Un bloqueo por trámite serializa las reservas, incluso para fechas sin citas todavía.
        Tramite.objects.select_for_update().get(pk=solicitud.tramite_id)
        solicitud = Solicitud.objects.select_for_update().get(pk=solicitud.pk)
        if Cita.objects.filter(solicitud=solicitud).exists():
            return True
        if solicitud.estado != 'Aprobado' or not _en_ventana(fecha, hora, timezone.localtime()):
            return False
        if not TurnoMedico.objects.filter(
            tramite_id=solicitud.tramite_id, dia_semana=fecha.weekday(), hora=hora,
        ).exists():
            return False
        if Cita.objects.filter(
            tramite_id=solicitud.tramite_id, fecha=fecha, hora=hora,
        ).exclude(estado__in=('Cancelada', 'Reprogramada')).exists():
            return False
        Cita.objects.create(
            solicitud=solicitud, ciudadano_id=solicitud.ciudadano_id,
            tramite_id=solicitud.tramite_id, fecha=fecha, hora=hora,
            folio_cita=f'CITA-{uuid4().hex[:15].upper()}',
        )
    return True


@never_cache
def agendar(request, solicitud):
    if Cita.objects.filter(solicitud=solicitud).exists():
        return redirect('ticket_cita_medica', solicitud.pk)
    if not ExpedienteClinico.objects.filter(ciudadano=request.user).exists():
        return redirect('iniciar_tramite', solicitud.tramite_id)

    error = ''
    if request.method == 'POST':
        try:
            fecha_texto, hora_texto = request.POST.get('turno', '').split('|')
            fecha, hora = date.fromisoformat(fecha_texto), time.fromisoformat(hora_texto)
            if hora.tzinfo is not None:
                raise ValueError
        except ValueError:
            error = 'Selecciona un turno de la lista.'
        else:
            if _reservar(solicitud, fecha, hora):
                messages.success(request, 'Tu cita médica quedó programada.')
                return redirect('ticket_cita_medica', solicitud.pk)
            error = 'Ese turno ya no está disponible. Selecciona otro horario.'

    return render(request, 'ventanilla/cita_medica_agenda.html', {
        'solicitud': solicitud, 'error': error,
        'dias': _calendario(solicitud.tramite, timezone.localtime()),
    })
