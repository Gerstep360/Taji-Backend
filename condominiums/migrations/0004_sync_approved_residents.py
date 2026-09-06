from django.db import migrations


def create_residents_for_approved_users(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Resident = apps.get_model("condominiums", "Resident")
    approved_users = User.objects.filter(
        role__slug="residente",
        is_approved=True,
        is_active=True,
        person__isnull=False,
    ).values_list("person_id", flat=True)
    Resident.objects.bulk_create(
        [Resident(person_id=person_id) for person_id in approved_users if person_id],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_user_is_approved"),
        ("condominiums", "0003_seed_condominium"),
    ]

    operations = [migrations.RunPython(create_residents_for_approved_users, migrations.RunPython.noop)]