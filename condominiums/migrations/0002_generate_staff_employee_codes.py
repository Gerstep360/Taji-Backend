from django.db import migrations
from django.db.models import Q


def generate_missing_codes(apps, schema_editor):
    Staff = apps.get_model("condominiums", "Staff")
    missing = Staff.objects.filter(Q(employee_code__isnull=True) | Q(employee_code=""))
    for staff in missing.iterator():
        base = f"PER-{staff.pk:05d}"
        candidate = base
        suffix = 1
        while Staff.objects.filter(employee_code=candidate).exclude(pk=staff.pk).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
        Staff.objects.filter(pk=staff.pk).update(employee_code=candidate)


class Migration(migrations.Migration):
    dependencies = [("condominiums", "0001_initial")]

    operations = [migrations.RunPython(generate_missing_codes, migrations.RunPython.noop)]
