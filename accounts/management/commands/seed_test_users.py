from django.core.management.base import BaseCommand

from accounts.models import Role, User

DEV_PASSWORD = "TajiTest2026!"

TEST_ACCOUNTS = [
    {
        "email": "admin@test.com",
        "role_slug": "administrador",
        "first_name": "Admin",
        "last_name": "Test",
        "label": "Administrador",
        "is_approved": True,
    },
    {
        "email": "directiva@test.com",
        "role_slug": "directiva",
        "first_name": "Directiva",
        "last_name": "Test",
        "label": "Directiva",
        "is_approved": True,
    },
    {
        "email": "residente@test.com",
        "role_slug": "residente",
        "first_name": "Residente",
        "last_name": "Test",
        "label": "Residente (aprobado)",
        "is_approved": True,  # aprobado para pruebas funcionales directas
    },
    {
        "email": "seguridad@test.com",
        "role_slug": "seguridad",
        "first_name": "Seguridad",
        "last_name": "Test",
        "label": "Seguridad / Guardia",
        "is_approved": True,
    },
    {
        "email": "empleado@test.com",
        # No existe rol "empleado" — se usa "mantenimiento" como rol representativo de empleado operativo.
        "role_slug": "mantenimiento",
        "first_name": "Empleado",
        "last_name": "Test",
        "label": "Mantenimiento (Empleado operativo)",
        "is_approved": True,
    },
]


class Command(BaseCommand):
    help = "Crea o actualiza las cuentas de prueba para cada rol del sistema. Idempotente."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("=== Cuentas de prueba ==="))

        roles = {r.slug: r for r in Role.objects.filter(is_active=True)}

        for spec in TEST_ACCOUNTS:
            email = spec["email"]
            role_slug = spec["role_slug"]
            role = roles.get(role_slug)

            if role is None:
                self.stdout.write(
                    self.style.ERROR(f"  SKIP  {email} — rol '{role_slug}' no encontrado.")
                )
                continue

            existing = User.objects.filter(email=email).first()

            if existing is not None:
                if existing.is_superuser:
                    self.stdout.write(
                        self.style.WARNING(f"  SKIP  {email} — es superusuario, no se toca.")
                    )
                    continue
                changed = False
                if existing.role_id != role.pk:
                    existing.role = role
                    changed = True
                if existing.is_approved != spec["is_approved"]:
                    existing.is_approved = spec["is_approved"]
                    changed = True
                if changed:
                    existing.save(update_fields=["role", "is_approved", "updated_at"])
                # Always reset to new password in dev
                existing.set_password(DEV_PASSWORD)
                existing.save(update_fields=["password", "updated_at"])
                action = "actualizado" if changed else "ya existía (contraseña sincronizada)"
                self.stdout.write(
                    self.style.SUCCESS(f"  OK    {email} | {spec['label']} | {action}")
                )
            else:
                User.objects.create_user(
                    email=email,
                    password=DEV_PASSWORD,
                    first_name=spec["first_name"],
                    last_name=spec["last_name"],
                    role=role,
                    is_superuser=False,
                    is_staff=False,
                    is_approved=spec["is_approved"],
                )
                self.stdout.write(
                    self.style.SUCCESS(f"  CREA  {email} | {spec['label']} | creado")
                )

        self.stdout.write("")
        self.stdout.write(f"Contraseña temporal: {DEV_PASSWORD}")
        self.stdout.write(
            self.style.WARNING(
                "AVISO: estas cuentas son solo para desarrollo. No usar en producción."
            )
        )
