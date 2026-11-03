from django.db import migrations


def baseline(apps, schema_editor):
    Incident = apps.get_model("incidents", "Incident")
    History = apps.get_model("incidents", "IncidentStatusHistory")
    for incident in Incident.objects.using(schema_editor.connection.alias).filter(status_history__isnull=True).iterator():
        History.objects.using(schema_editor.connection.alias).create(
            incident_id=incident.pk, from_status=None, to_status=incident.status,
            changed_at=incident.updated_at,
            comment="Estado existente al habilitar seguimiento; sin historial previo disponible.",
        )


class Migration(migrations.Migration):
    dependencies = [("incidents", "0005_seed_maintenance_category")]
    operations = [migrations.RunPython(baseline, migrations.RunPython.noop)]
