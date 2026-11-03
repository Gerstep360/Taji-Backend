import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from accounts.models import Role

admin_role = Role.objects.get(slug='administrador')
perms_list = sorted(list(admin_role.permissions.all().values_list('code', flat=True)))

print(f"\nTotal permisos: {len(perms_list)}")
print(f"manage_assets: {'manage_assets' in perms_list}")

if 'manage_assets' not in perms_list:
    print(f"\n✗ manage_assets NO ESTÁ")
    print("Permisos actuales:")
    for p in perms_list:
        print(f"  {p}")
