import os
import django

os.environ.setdefault(DJANGO_SETTINGS_MODULE, config.settings)
django.setup()

from accounts.models import Role

admin_role = Role.objects.get(slug=administrador)
perms_list = sorted(list(admin_role.permissions.all().values_list(code, flat=True)))

print(fTotal
