from datetime import time

from django.db import migrations


def habilitar_psicologia(apps, schema_editor):
    alias = schema_editor.connection.alias
    Tramite = apps.get_model('ciudadanos', 'Tramite')
    Sede = apps.get_model('ciudadanos', 'SedeSocial')
    Horario = apps.get_model('ciudadanos', 'HorarioSocial')
    for tramite in Tramite.objects.using(alias).filter(servicio_procuraduria='psicologia'):
        if Horario.objects.using(alias).filter(tramite=tramite).exists():
            continue
        sede, _ = Sede.objects.using(alias).get_or_create(
            nombre='Sistema Municipal DIF',
            defaults={'direccion': 'Atizapán de Zaragoza, Estado de México', 'activa': True},
        )
        for dia in range(5):
            Horario.objects.using(alias).get_or_create(
                tramite=tramite, sede=sede, dia=dia, inicio=time(9), fin=time(16),
                defaults={'duracion': 45, 'cupo': 1},
            )


class Migration(migrations.Migration):
    dependencies = [('ciudadanos', '0016_eliminacion_ciudadano_cascada')]
    operations = [migrations.RunPython(habilitar_psicologia, migrations.RunPython.noop)]
