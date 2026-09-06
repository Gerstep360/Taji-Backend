from django.db import migrations


def seed_condominium(apps, schema_editor):
    Condominium = apps.get_model("condominiums", "Condominium")
    Condominium.objects.get_or_create(
        pk=1,
        defaults={"name": "Taji", "is_active": True},
    )


def unseed_condominium(apps, schema_editor):
    apps.get_model("condominiums", "Condominium").objects.filter(pk=1).delete()


class Migration(migrations.Migration):
    dependencies = [("condominiums", "0002_generate_staff_employee_codes")]

    operations = [migrations.RunPython(seed_condominium, unseed_condominium)]