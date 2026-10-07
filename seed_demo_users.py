import os
import sys
import django

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth import get_user_model
from django.db.models import Q
from accounts.models import Person, Role

User = get_user_model()

print("\n[>] Creando/Verificando usuarios predeterminados de prueba en la BD...")

def get_or_create_role(slug, name, is_public=False):
    role = Role.objects.filter(Q(slug=slug) | Q(name=name)).first()
    if not role:
        role = Role.objects.create(slug=slug, name=name, is_public=is_public)
    return role

role_admin = get_or_create_role("admin", "Administrador")
role_resident = get_or_create_role("resident", "Residente", is_public=True)
role_guard = get_or_create_role("guard", "Guardia / Porteria")

def create_demo_user(email, first_name, last_name, doc_num, password, role=None, is_staff=False, is_superuser=False):
    person, _ = Person.objects.get_or_create(
        contact_email=email,
        defaults={
            "first_name": first_name,
            "last_name": last_name,
            "document_type": Person.DocumentType.CI,
            "document_number": doc_num,
        }
    )
    user = User.objects.filter(email=email).first()
    if not user:
        user = User.objects.create(
            email=email,
            person=person,
            role=role,
            is_staff=is_staff,
            is_superuser=is_superuser,
            is_approved=True
        )
    user.set_password(password)
    user.person = person
    user.role = role
    user.is_staff = is_staff
    user.is_superuser = is_superuser
    user.is_approved = True
    user.save()
    return user

# 1. Superusuario Admin
admin = create_demo_user("admin@taji.app", "Admin", "Sistema", "1111111", "Admin12345!", role=role_admin, is_staff=True, is_superuser=True)
print("  [+] Superusuario Admin: admin@taji.app | Clave: Admin12345!")

# 2. Usuario Residente
res = create_demo_user("residente@taji.app", "Juan", "Perez (Residente)", "2222222", "Residente12345!", role=role_resident)
print("  [+] Usuario Residente:  residente@taji.app | Clave: Residente12345!")

# 3. Usuario Guardia
guard = create_demo_user("guardia@taji.app", "Carlos", "Lopez (Guardia)", "3333333", "Guardia12345!", role=role_guard)
print("  [+] Usuario Guardia:    guardia@taji.app | Clave: Guardia12345!")

# 4. Crear Condominio, Sector y Unidades de prueba si no existen
from condominiums.models import Condominium, Sector, Unit, Resident, ResidentUnit

condo = Condominium.objects.first()
if not condo:
    condo = Condominium.objects.create(name="Condominio Taji", slug="taji", address="Av. Principal #123")
    print("  [+] Condominio principal creado.")
else:
    if not condo.slug:
        condo.slug = "taji"
        condo.save()

sector_a, _ = Sector.objects.get_or_create(
    code="SEC-A",
    defaults={"name": "Sector A", "condominium": condo, "sector_type": Sector.Type.TOWER}
)

unit_101, _ = Unit.objects.get_or_create(
    code="A-101",
    defaults={"unit_type": Unit.Type.APARTMENT, "status": Unit.Status.ACTIVE, "sector": sector_a, "floor_label": "Piso 1"}
)
unit_102, _ = Unit.objects.get_or_create(
    code="A-102",
    defaults={"unit_type": Unit.Type.APARTMENT, "status": Unit.Status.ACTIVE, "sector": sector_a, "floor_label": "Piso 1"}
)
print(f"  [+] Unidades de prueba listas: {unit_101.code}, {unit_102.code}")

# Vincular residente a Unidad A-101
resident_obj, _ = Resident.objects.get_or_create(
    person=res.person,
    defaults={"status": Resident.Status.ACTIVE}
)
ResidentUnit.objects.get_or_create(
    resident=resident_obj,
    unit=unit_101,
    defaults={"is_primary": True}
)
print(f"  [+] Residente '{res.email}' vinculado a la Unidad '{unit_101.code}'.")

# 5. Crear Membresías de Tenant SaaS (TenantMembership)
from tenancy.models import TenantMembership

TenantMembership.objects.get_or_create(
    user=admin,
    condominium=condo,
    defaults={"role": role_admin, "is_default": True, "is_active": True}
)
TenantMembership.objects.get_or_create(
    user=res,
    condominium=condo,
    defaults={"role": role_resident, "is_default": True, "is_active": True}
)
TenantMembership.objects.get_or_create(
    user=guard,
    condominium=condo,
    defaults={"role": role_guard, "is_default": True, "is_active": True}
)
print("  [+] Membresías SaaS de Tenant asociadas para Admin, Residente y Guardia.")

print("\n[SISTEMA] Todos los usuarios y datos de prueba han sido creados exitosamente.\n")

