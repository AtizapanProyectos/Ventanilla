from django.db import migrations


def actualizar_solicitudes(apps, schema_editor):
    Solicitud = apps.get_model('ciudadanos', 'Solicitud')
    alias = schema_editor.connection.alias
    solicitudes = Solicitud.objects.using(alias).filter(
        tramite__es_alta_proveedor=True, cita__isnull=True,
        estado__in=('Pendiente', 'En proceso', 'Rechazado'),
    ).select_related('tramite')
    for solicitud in solicitudes.iterator():
        datos = solicitud.datos_proveedor
        if not datos.get('rfc') or datos.get('tipo_persona') not in ('fisica', 'moral'):
            continue
        requisitos = solicitud.tramite.requisitos.using(alias).exclude(
            es_fotografia=True,
        ).exclude(tipo_documento='fotografias')
        ids = {
            r.pk for r in requisitos
            if (not r.aplica_persona or r.aplica_persona == datos['tipo_persona'])
            and (not r.requiere_representante or datos.get('tiene_representante'))
        }
        archivos = list(solicitud.archivos.using(alias).filter(
            requisito_id__in=ids,
        ).values_list('requisito_id', 'estado_validacion'))
        if ids and ids == {pk for pk, estado in archivos if estado == 'Aprobado'} and all(
            estado == 'Aprobado' for _, estado in archivos
        ):
            Solicitud.objects.using(alias).filter(pk=solicitud.pk).update(estado='Aprobado')


class Migration(migrations.Migration):
    dependencies = [('ciudadanos', '0014_procuraduria_social')]
    operations = [migrations.RunPython(actualizar_solicitudes, migrations.RunPython.noop)]
