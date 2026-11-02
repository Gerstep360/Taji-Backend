from django.db import migrations


# CU18 / T031: el catálogo de referencia incluye "Mantenimiento" como categoría
# general. Las categorías existentes (Infraestructura, Seguridad, Convivencia, ...)
# se respetan; solo se agrega la que faltaba, sin sobrescribir una existente.
CODE = "MAINTENANCE"


def seed_maintenance(apps, schema_editor):
    IncidentCategory = apps.get_model("incidents", "IncidentCategory")
    if IncidentCategory.objects.filter(code=CODE).exists():
        return
    if IncidentCategory.objects.filter(name="Mantenimiento").exists():
        return
    IncidentCategory.objects.create(
        code=CODE,
        name="Mantenimiento",
        description="Fallas o desgaste de instalaciones y equipos comunes.",
        default_staff_type="MAINTENANCE",
        is_active=True,
    )


def unseed_maintenance(apps, schema_editor):
    IncidentCategory = apps.get_model("incidents", "IncidentCategory")
    IncidentCategory.objects.filter(code=CODE, incidents__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("incidents", "0004_incident_condominium_sequence")]

    operations = [migrations.RunPython(seed_maintenance, unseed_maintenance)]
