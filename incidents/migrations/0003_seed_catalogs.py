from django.db import migrations


PRIORITIES = (
    ("LOW", "Baja", 1, "0", "24.99", 1440),
    ("MEDIUM", "Media", 2, "25", "49.99", 480),
    ("HIGH", "Alta", 3, "50", "74.99", 120),
    ("CRITICAL", "Crítica", 4, "75", "100", 30),
)

CATEGORIES = (
    ("ELECTRICITY", "Electricidad", "MAINTENANCE"),
    ("PLUMBING", "Plomería", "MAINTENANCE"),
    ("SECURITY", "Seguridad", "SECURITY"),
    ("CLEANING", "Limpieza", "CLEANING"),
    ("ELEVATORS", "Ascensores", "MAINTENANCE"),
    ("GREEN_AREAS", "Áreas verdes", "MAINTENANCE"),
    ("POOL", "Piscina", "MAINTENANCE"),
    ("INFRASTRUCTURE", "Infraestructura", "MAINTENANCE"),
    ("EQUIPMENT", "Equipamiento", "MAINTENANCE"),
    ("COEXISTENCE", "Convivencia", "SECURITY"),
    ("OTHER", "Otro", "ADMINISTRATION"),
)


def seed_catalogs(apps, schema_editor):
    PriorityLevel = apps.get_model("incidents", "PriorityLevel")
    IncidentCategory = apps.get_model("incidents", "IncidentCategory")
    for code, name, rank, min_score, max_score, target_minutes in PRIORITIES:
        PriorityLevel.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "rank": rank,
                "min_score": min_score,
                "max_score": max_score,
                "target_minutes": target_minutes,
                "is_active": True,
            },
        )
    for code, name, staff_type in CATEGORIES:
        IncidentCategory.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "default_staff_type": staff_type,
                "is_active": True,
            },
        )


def unseed_catalogs(apps, schema_editor):
    apps.get_model("incidents", "PriorityLevel").objects.filter(
        code__in=[item[0] for item in PRIORITIES]
    ).delete()
    apps.get_model("incidents", "IncidentCategory").objects.filter(
        code__in=[item[0] for item in CATEGORIES]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("incidents", "0002_initial")]

    operations = [migrations.RunPython(seed_catalogs, unseed_catalogs)]