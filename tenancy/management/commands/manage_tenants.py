"""
Comando de gestión CLI de Tenancy / Condominios y Usuarios para Taji SaaS.
Permite listar condominios y usuarios, vincular/cambiar tenants a usuarios,
promover a administradores, cambiar roles y sincronizar membresías.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from accounts.models import User, Role
from condominiums.models import Condominium
from tenancy.models import TenantMembership


class Command(BaseCommand):
    help = "Gestión CLI de Tenancy: asignar usuarios a condominios, roles y administradores."

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers(dest="subcommand", help="Subcomando de gestión")

        # 1. list
        subparsers.add_parser("list", help="Lista todos los condominios, usuarios y sus membresías activas")

        # 2. set_tenant
        p_tenant = subparsers.add_parser("set_tenant", help="Asigna o cambia el condominio/tenant de un usuario")
        p_tenant.add_argument("--email", required=True, help="Email del usuario")
        p_tenant.add_argument("--condo", required=True, help="ID o Slug del condominio")
        p_tenant.add_argument("--role", default=None, help="Slug del rol dentro del tenant (ej. 'administrador', 'residente')")
        p_tenant.add_argument("--default", action="store_true", default=True, help="Establecer como tenant predeterminado")

        # 3. set_role
        p_role = subparsers.add_parser("set_role", help="Cambia el rol de un usuario (global y en tenant)")
        p_role.add_argument("--email", required=True, help="Email del usuario")
        p_role.add_argument("--role", required=True, help="Slug del rol (ej. 'administrador', 'seguridad', 'residente')")
        p_role.add_argument("--condo", default=None, help="ID o Slug del condominio (opcional)")

        # 4. make_admin
        p_admin = subparsers.add_parser("make_admin", help="Promueve a un usuario a Administrador de Condominio y Staff")
        p_admin.add_argument("--email", required=True, help="Email del usuario")
        p_admin.add_argument("--condo", default=None, help="ID o Slug del condominio (opcional)")
        p_admin.add_argument("--superuser", action="store_true", help="Otorgar también permisos de Superusuario de plataforma")

        # 5. rename_condo
        p_rename = subparsers.add_parser("rename_condo", help="Actualiza el nombre y slug de un condominio")
        p_rename.add_argument("--id", type=int, required=True, help="ID del condominio")
        p_rename.add_argument("--name", required=True, help="Nuevo nombre (ej. 'Condominio Taji')")
        p_rename.add_argument("--slug", default=None, help="Nuevo slug (ej. 'condominio-taji')")

        # 6. create_condo
        p_create = subparsers.add_parser("create_condo", help="Crea un nuevo condominio en la arquitectura SaaS")
        p_create.add_argument("--name", required=True, help="Nombre del condominio (ej. 'Torres del Parque')")
        p_create.add_argument("--slug", default=None, help="Slug único (opcional)")
        p_create.add_argument("--address", default="", help="Dirección física")
        p_create.add_argument("--units", type=int, default=100, help="Máximo de unidades")
        p_create.add_argument("--residents", type=int, default=400, help="Máximo de residentes")

        # 7. sync_default
        p_sync = subparsers.add_parser("sync_default", help="Vincula todos los usuarios huérfanos a un condominio predeterminado")
        p_sync.add_argument("--condo", default="1", help="ID o Slug del condominio de destino (por defecto ID 1)")

    def handle(self, *args, **options):
        cmd = options.get("subcommand")
        if not cmd or cmd == "list":
            self._handle_list()
        elif cmd == "set_tenant":
            self._handle_set_tenant(options)
        elif cmd == "set_role":
            self._handle_set_role(options)
        elif cmd == "make_admin":
            self._handle_make_admin(options)
        elif cmd == "rename_condo":
            self._handle_rename_condo(options)
        elif cmd == "create_condo":
            self._handle_create_condo(options)
        elif cmd == "sync_default":
            self._handle_sync_default(options)
        else:
            raise CommandError(f"Subcomando desconocido '{cmd}'. Usa --help para ver las opciones disponibles.")

    def _get_condo(self, identifier):
        if not identifier:
            return None
        raw = str(identifier).strip()
        condo = None
        if raw.isdigit():
            condo = Condominium.objects.filter(pk=int(raw)).first()
        if not condo:
            condo = Condominium.objects.filter(slug__iexact=raw).first()
        if not condo:
            condo = Condominium.objects.filter(name__iexact=raw).first()
        if not condo:
            raise CommandError(f"Condominio no encontrado con identificador '{identifier}'.")
        return condo

    def _get_user(self, email):
        clean_email = (email or "").strip().lower()
        user = User.objects.filter(email__iexact=clean_email).first()
        if not user:
            raise CommandError(f"Usuario con correo '{email}' no encontrado en el sistema.")
        return user

    def _get_role(self, role_slug):
        if not role_slug:
            return None
        role = Role.objects.filter(slug__iexact=role_slug.strip()).first()
        if not role:
            role = Role.objects.filter(name__iexact=role_slug.strip()).first()
        if not role:
            valid = ", ".join(Role.objects.values_list("slug", flat=True))
            raise CommandError(f"Rol '{role_slug}' no encontrado. Roles válidos: {valid}")
        return role

    def _handle_list(self):
        self.stdout.write(self.style.SUCCESS("\n=== CONDOMINIOS / TENANTS EN EL SISTEMA ==="))
        condos = list(Condominium.objects.all())
        if not condos:
            self.stdout.write("  (No hay condominios registrados)")
        for c in condos:
            status_str = "ACTIVO" if c.is_active else "INACTIVO"
            members_count = c.tenant_memberships.count()
            self.stdout.write(f"  [{c.id}] {c.name} (slug: {c.slug}) - {status_str} | Miembros: {members_count}")

        self.stdout.write(self.style.SUCCESS("\n=== USUARIOS Y SU TENANT VINCULADO ==="))
        users = User.objects.select_related("role", "person").all().order_by("email")
        for u in users:
            memberships = list(TenantMembership.objects.filter(user=u).select_related("condominium", "role"))
            role_name = u.role.slug if u.role else "sin rol"
            super_str = " [SUPERUSER]" if u.is_superuser else ""
            staff_str = " [STAFF]" if u.is_staff else ""
            
            self.stdout.write(f"\n  * {u.email} | Rol Global: {role_name}{super_str}{staff_str}")
            if memberships:
                for m in memberships:
                    m_role = m.role.slug if m.role else "sin rol"
                    def_str = " (DEFAULT)" if m.is_default else ""
                    self.stdout.write(f"      |-- Condominio: [{m.condominium_id}] {m.condominium.name} -> Rol: {m_role}{def_str}")
            else:
                self.stdout.write(self.style.WARNING("      |-- [SIN TENANT ASIGNADO - USUARIO HUERFANO]"))
        self.stdout.write("")

    @transaction.atomic
    def _handle_set_tenant(self, options):
        user = self._get_user(options["email"])
        condo = self._get_condo(options["condo"])
        role_slug = options.get("role")
        role = self._get_role(role_slug) if role_slug else user.role

        is_default = options.get("default", True)
        if is_default:
            TenantMembership.objects.filter(user=user).update(is_default=False)

        membership, created = TenantMembership.objects.update_or_create(
            user=user,
            condominium=condo,
            defaults={
                "role": role,
                "is_active": True,
                "is_default": is_default,
            },
        )

        if role and user.role != role:
            user.role = role
            user.save(update_fields=["role"])

        action = "Vinculado a nuevo tenant" if created else "Actualizada membresia de tenant"
        self.stdout.write(self.style.SUCCESS(
            f"[OK] {action}: {user.email} -> [{condo.id}] {condo.name} con rol '{role.slug if role else 'None'}'."
        ))

    @transaction.atomic
    def _handle_set_role(self, options):
        user = self._get_user(options["email"])
        role = self._get_role(options["role"])
        condo_id = options.get("condo")

        user.role = role
        user.save(update_fields=["role"])

        if condo_id:
            condo = self._get_condo(condo_id)
            TenantMembership.objects.update_or_create(
                user=user,
                condominium=condo,
                defaults={"role": role, "is_active": True},
            )
        else:
            TenantMembership.objects.filter(user=user).update(role=role)

        self.stdout.write(self.style.SUCCESS(
            f"[OK] Rol actualizado para {user.email} a '{role.slug}' ({role.name})."
        ))

    @transaction.atomic
    def _handle_make_admin(self, options):
        user = self._get_user(options["email"])
        admin_role = Role.objects.filter(slug="administrador").first()
        if not admin_role:
            raise CommandError("El rol 'administrador' no existe en el sistema.")

        user.role = admin_role
        user.is_staff = True
        user.is_approved = True
        if options.get("superuser"):
            user.is_superuser = True
        user.save()

        condo_id = options.get("condo")
        if condo_id:
            condo = self._get_condo(condo_id)
        else:
            first_m = TenantMembership.objects.filter(user=user).first()
            condo = first_m.condominium if first_m else Condominium.objects.first()

        if condo:
            TenantMembership.objects.update_or_create(
                user=user,
                condominium=condo,
                defaults={"role": admin_role, "is_active": True, "is_default": True},
            )

        super_msg = " y Superusuario" if user.is_superuser else ""
        condo_msg = f" en [{condo.id}] {condo.name}" if condo else ""
        self.stdout.write(self.style.SUCCESS(
            f"[OK] {user.email} ahora es Administrador{super_msg}{condo_msg}."
        ))

    def _handle_rename_condo(self, options):
        condo = Condominium.objects.filter(pk=options["id"]).first()
        if not condo:
            raise CommandError(f"Condominio con ID {options['id']} no encontrado.")
        old_name = condo.name
        condo.name = options["name"].strip()
        if options.get("slug"):
            condo.slug = options["slug"].strip()
        condo.save()
        self.stdout.write(self.style.SUCCESS(
            f"[OK] Condominio [{condo.id}] renombrado: '{old_name}' -> '{condo.name}' (slug: '{condo.slug}')."
        ))

    @transaction.atomic
    def _handle_create_condo(self, options):
        name = options["name"].strip()
        slug = options.get("slug")
        if not slug:
            from django.utils.text import slugify
            slug = slugify(name)
        address = options.get("address", "")
        units = options.get("units", 100)
        residents = options.get("residents", 400)

        condo, created = Condominium.objects.get_or_create(
            slug=slug,
            defaults={
                "name": name,
                "address": address,
                "max_units": units,
                "max_residents": residents,
                "is_active": True,
            },
        )
        if not created:
            self.stdout.write(self.style.WARNING(f"El condominio con slug '{slug}' ya existe (ID: {condo.id}, Nombre: {condo.name})."))
        else:
            self.stdout.write(self.style.SUCCESS(f"[OK] Condominio '{condo.name}' creado exitosamente (ID: {condo.id}, slug: '{condo.slug}')."))

    @transaction.atomic
    def _handle_sync_default(self, options):
        condo = self._get_condo(options["condo"])
        self.stdout.write(f"Sincronizando usuarios huerfanos hacia [{condo.id}] {condo.name}...")

        res_role = Role.objects.filter(slug="residente").first()
        admin_role = Role.objects.filter(slug="administrador").first()

        synced_count = 0
        for user in User.objects.all():
            m = TenantMembership.objects.filter(user=user, condominium=condo).first()
            if not m:
                role = user.role or (admin_role if user.is_superuser or user.is_staff else res_role)
                TenantMembership.objects.create(
                    user=user,
                    condominium=condo,
                    role=role,
                    is_default=True,
                    is_active=True,
                )
                synced_count += 1
                self.stdout.write(f"  + Vinculado: {user.email} (rol: {role.slug if role else 'None'})")

        self.stdout.write(self.style.SUCCESS(
            f"[OK] Sincronizacion completada: {synced_count} usuario(s) vinculados a '{condo.name}'."
        ))
