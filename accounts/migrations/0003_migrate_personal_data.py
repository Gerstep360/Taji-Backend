from django.db import migrations


def migrate_user_data_to_person(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Person = apps.get_model("accounts", "Person")

    for user in User.objects.all():
        if not user.person:
            person = Person.objects.create(
                first_name=user.first_name,
                last_name=user.last_name,
                phone=user.phone,
                contact_email=user.email,
            )
            user.person = person
            user.save()
        else:
            person = user.person
            changed = False
            if not person.first_name:
                person.first_name = user.first_name
                changed = True
            if not person.last_name:
                person.last_name = user.last_name
                changed = True
            if not person.phone:
                person.phone = user.phone
                changed = True
            if not person.contact_email:
                person.contact_email = user.email
                changed = True
            if changed:
                person.save()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_systempermission_is_active_systempermission_module_and_more"),
    ]

    operations = [
        migrations.RunPython(migrate_user_data_to_person, reverse_code=migrations.RunPython.noop),
    ]
