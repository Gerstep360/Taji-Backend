from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Role, SystemPermission, User
from accounts.rbac import (
    ADMIN_ONLY_PERMISSIONS,
    FORBIDDEN_PERMISSIONS_BY_ROLE,
    MANDATORY_PERMISSIONS_BY_ROLE,
)

PASSWORD = "TajiSeguro2026!"


class RoleManagementApiTests(APITestCase):
    """CU2: Gestionar Roles y Permisos."""

    ROLES_URL = "/api/v1/roles/"
    PERMS_URL = "/api/v1/roles/permissions/"

    def role_permissions_url(self, slug: str) -> str:
        return f"/api/v1/roles/{slug}/permissions/"

    def setUp(self):
        self.admin_role = Role.objects.get(slug="administrador")
        self.directiva_role = Role.objects.get(slug="directiva")
        self.residente_role = Role.objects.get(slug="residente")
        self.seguridad_role = Role.objects.get(slug="seguridad")
        self.mantenimiento_role = Role.objects.get(slug="mantenimiento")

        self.admin_user = User.objects.create_user(
            email="cu2_admin@example.com",
            password=PASSWORD,
            first_name="Admin",
            last_name="CU2",
            role=self.admin_role,
        )
        self.directiva_user = User.objects.create_user(
            email="cu2_directiva@example.com",
            password=PASSWORD,
            first_name="Dir",
            last_name="CU2",
            role=self.directiva_role,
        )
        self.residente_user = User.objects.create_user(
            email="cu2_residente@example.com",
            password=PASSWORD,
            first_name="Res",
            last_name="CU2",
            role=self.residente_role,
        )
        self.seguridad_user = User.objects.create_user(
            email="cu2_seguridad@example.com",
            password=PASSWORD,
            first_name="Seg",
            last_name="CU2",
            role=self.seguridad_role,
        )
        self.mantenimiento_user = User.objects.create_user(
            email="cu2_mantenimiento@example.com",
            password=PASSWORD,
            first_name="Mant",
            last_name="CU2",
            role=self.mantenimiento_role,
        )

    def _login(self, user: User) -> None:
        self.client.force_authenticate(user=user)

    # ------ Access control: only Administrador ------

    def test_admin_can_list_roles(self):
        self._login(self.admin_user)
        response = self.client.get(self.ROLES_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        slugs = [r["slug"] for r in response.data]
        self.assertIn("administrador", slugs)

    def test_directiva_cannot_access_cu2(self):
        self._login(self.directiva_user)
        self.assertEqual(self.client.get(self.ROLES_URL).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get(self.PERMS_URL).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.get(self.role_permissions_url("administrador")).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_residente_cannot_access_cu2(self):
        self._login(self.residente_user)
        self.assertEqual(self.client.get(self.ROLES_URL).status_code, status.HTTP_403_FORBIDDEN)

    def test_seguridad_cannot_access_cu2(self):
        self._login(self.seguridad_user)
        self.assertEqual(self.client.get(self.ROLES_URL).status_code, status.HTTP_403_FORBIDDEN)

    def test_mantenimiento_cannot_access_cu2(self):
        self._login(self.mantenimiento_user)
        self.assertEqual(self.client.get(self.ROLES_URL).status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_gets_401(self):
        self.assertEqual(self.client.get(self.ROLES_URL).status_code, status.HTTP_401_UNAUTHORIZED)

    # ------ Read operations ------

    def test_admin_can_list_all_permissions(self):
        self._login(self.admin_user)
        response = self.client.get(self.PERMS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = [p["code"] for p in response.data]
        self.assertIn("manage_roles", codes)
        self.assertIn("register_visits", codes)

    def test_admin_can_get_role_permissions(self):
        self._login(self.admin_user)
        response = self.client.get(self.role_permissions_url("seguridad"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["slug"], "seguridad")
        perm_codes = [p["code"] for p in response.data["permissions"]]
        self.assertIn("validate_visits", perm_codes)
        self.assertNotIn("register_visits", perm_codes)

    def test_nonexistent_role_returns_404(self):
        self._login(self.admin_user)
        response = self.client.get(self.role_permissions_url("rol-inexistente"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ------ Write: valid updates ------

    def test_admin_can_update_valid_role_permissions(self):
        self._login(self.admin_user)
        new_perms = ["validate_visits", "register_entry_exit"]
        response = self.client.patch(
            self.role_permissions_url("seguridad"),
            {"permissions": new_perms},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_codes = {p["code"] for p in response.data["permissions"]}
        self.assertEqual(returned_codes, set(new_perms))
        self.seguridad_role.refresh_from_db()
        db_codes = set(self.seguridad_role.permissions.values_list("code", flat=True))
        self.assertEqual(db_codes, set(new_perms))

    # ------ Write: business rule violations ------

    def test_cannot_assign_nonexistent_permission(self):
        """A2: Permiso inexistente rechazado."""
        self._login(self.admin_user)
        response = self.client.patch(
            self.role_permissions_url("seguridad"),
            {"permissions": ["validate_visits", "permiso_que_no_existe"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_grant_seguridad_register_visits(self):
        """A3: Seguridad no puede crear invitaciones (RN3)."""
        self._login(self.admin_user)
        response = self.client.patch(
            self.role_permissions_url("seguridad"),
            {"permissions": ["validate_visits", "register_visits"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("permissions", response.data["error"]["fields"])

    def test_cannot_grant_directiva_write_permission(self):
        """A4: Directiva no puede modificar usuarios (RN4)."""
        self._login(self.admin_user)
        response = self.client.patch(
            self.role_permissions_url("directiva"),
            {"permissions": ["view_reports", "manage_staff"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("permissions", response.data["error"]["fields"])

    def test_cannot_remove_manage_roles_from_administrador(self):
        """A5: Administrador no puede perder manage_roles (RN1)."""
        self._login(self.admin_user)
        all_except_manage_roles = list(
            SystemPermission.objects.filter(is_active=True)
            .exclude(code="manage_roles")
            .values_list("code", flat=True)
        )
        response = self.client.patch(
            self.role_permissions_url("administrador"),
            {"permissions": all_except_manage_roles},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("permissions", response.data["error"]["fields"])

    def test_cannot_grant_manage_roles_to_non_admin(self):
        """manage_roles es exclusivo del Administrador (RN1)."""
        self._login(self.admin_user)
        response = self.client.patch(
            self.role_permissions_url("directiva"),
            {"permissions": ["view_reports", "manage_roles"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_seguridad_cannot_get_employee_permissions(self):
        """RN2: Seguridad y Empleado tienen permisos separados."""
        self._login(self.admin_user)
        response = self.client.patch(
            self.role_permissions_url("seguridad"),
            {"permissions": ["validate_visits", "view_assigned_work_orders"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_mantenimiento_cannot_get_security_permissions(self):
        """RN2: Empleado operativo no puede tener permisos de portería."""
        self._login(self.admin_user)
        response = self.client.patch(
            self.role_permissions_url("mantenimiento"),
            {"permissions": ["view_assigned_work_orders", "validate_visits"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ------ Business rules on existing roles ------

    def test_residente_can_create_visits(self):
        """RN3: Residente tiene register_visits."""
        self.assertIn(
            "register_visits",
            self.residente_role.permissions.values_list("code", flat=True),
        )

    def test_seguridad_cannot_create_visits(self):
        """RN3: Seguridad no tiene register_visits."""
        self.assertNotIn(
            "register_visits",
            self.seguridad_role.permissions.values_list("code", flat=True),
        )

    def test_seguridad_can_validate_visits(self):
        """Seguridad puede validar visitas existentes."""
        self.assertIn(
            "validate_visits",
            self.seguridad_role.permissions.values_list("code", flat=True),
        )

    def test_directiva_can_view_reports(self):
        """RN4: Directiva puede consultar reportes."""
        self.assertIn(
            "view_reports",
            self.directiva_role.permissions.values_list("code", flat=True),
        )

    def test_directiva_cannot_modify_users(self):
        """RN4: Directiva no tiene manage_staff."""
        self.assertNotIn(
            "manage_staff",
            self.directiva_role.permissions.values_list("code", flat=True),
        )

    def test_direct_api_call_cannot_bypass_rbac(self):
        """Llamada directa a la API sin autenticación no puede saltarse RBAC."""
        response = self.client.patch(
            self.role_permissions_url("administrador"),
            {"permissions": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_directiva_cannot_read_roles_via_api(self):
        """URL directa del frontend no permite acceder al CU2 sin autorización."""
        self._login(self.directiva_user)
        response = self.client.get(self.ROLES_URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "permission_denied")


class ResidentApprovalTests(APITestCase):
    """RN6: Flujo de aprobación/rechazo de Residentes. Solo Administrador."""

    PENDING_URL = "/api/v1/roles/residents/pending/"

    def review_url(self, pk: int) -> str:
        return f"/api/v1/roles/residents/{pk}/review/"

    def setUp(self):
        self.admin_role = Role.objects.get(slug="administrador")
        self.residente_role = Role.objects.get(slug="residente")
        self.directiva_role = Role.objects.get(slug="directiva")

        self.admin_user = User.objects.create_user(
            email="cu2_approval_admin@example.com",
            password=PASSWORD,
            first_name="Admin",
            last_name="Approval",
            role=self.admin_role,
        )
        self.directiva_user = User.objects.create_user(
            email="cu2_approval_dir@example.com",
            password=PASSWORD,
            first_name="Dir",
            last_name="Approval",
            role=self.directiva_role,
        )
        self.pending_user = User.objects.create_user(
            email="pending_residente@example.com",
            password=PASSWORD,
            first_name="Pendiente",
            last_name="Residente",
            role=self.residente_role,
            is_approved=False,
        )

    def _login(self, user: User) -> None:
        self.client.force_authenticate(user=user)

    def test_unauthenticated_cannot_access_pending(self):
        """Sin autenticación → 401."""
        self.assertEqual(self.client.get(self.PENDING_URL).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_admin_cannot_list_pending_residents(self):
        """RN1: Directiva no puede listar residentes pendientes → 403."""
        self._login(self.directiva_user)
        self.assertEqual(self.client.get(self.PENDING_URL).status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_list_pending_residents(self):
        """RN6: Administrador puede listar residentes pendientes."""
        self._login(self.admin_user)
        resp = self.client.get(self.PENDING_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        emails = [u["email"] for u in resp.data]
        self.assertIn("pending_residente@example.com", emails)

    def test_admin_can_approve_resident(self):
        """RN6: Administrador aprueba Residente → is_approved=True."""
        self._login(self.admin_user)
        resp = self.client.patch(
            self.review_url(self.pending_user.pk),
            {"action": "approve"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.pending_user.refresh_from_db()
        self.assertTrue(self.pending_user.is_approved)
        self.assertTrue(self.pending_user.is_active)

    def test_approved_resident_gets_permissions(self):
        """RN6: Después de aprobar, el Residente obtiene permisos del rol."""
        self._login(self.admin_user)
        self.client.patch(self.review_url(self.pending_user.pk), {"action": "approve"}, format="json")
        self.pending_user.refresh_from_db()
        self.assertTrue(self.pending_user.has_system_permission("register_visits"))
        self.assertTrue(self.pending_user.has_system_permission("view_own_data"))

    def test_approved_resident_can_create_visits(self):
        """RN3: Residente aprobado tiene permiso register_visits."""
        self.pending_user.is_approved = True
        self.pending_user.save(update_fields=["is_approved", "updated_at"])
        self.assertTrue(self.pending_user.has_system_permission("register_visits"))

    def test_admin_can_reject_resident(self):
        """RN6: Administrador rechaza Residente → is_active=False."""
        self._login(self.admin_user)
        resp = self.client.patch(
            self.review_url(self.pending_user.pk),
            {"action": "reject"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.pending_user.refresh_from_db()
        self.assertFalse(self.pending_user.is_active)
        self.assertFalse(self.pending_user.is_approved)

    def test_rejected_user_has_no_effective_permissions(self):
        """RN6: Usuario rechazado no obtiene permisos."""
        self.pending_user.is_approved = False
        self.pending_user.is_active = False
        self.pending_user.save(update_fields=["is_approved", "is_active", "updated_at"])
        for perm in ["register_visits", "view_own_data", "reserve_areas"]:
            self.assertFalse(self.pending_user.has_system_permission(perm), perm)

    def test_non_admin_cannot_review_resident(self):
        """RN1: No Administrador recibe 403 al intentar aprobar."""
        self._login(self.directiva_user)
        resp = self.client.patch(
            self.review_url(self.pending_user.pk),
            {"action": "approve"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class InternalUserCreationTests(APITestCase):
    """RN7: Solo Administrador puede crear usuarios internos."""

    USERS_URL = "/api/v1/roles/users/"

    def setUp(self):
        self.admin_role = Role.objects.get(slug="administrador")
        self.residente_role = Role.objects.get(slug="residente")
        self.directiva_role = Role.objects.get(slug="directiva")

        self.admin_user = User.objects.create_user(
            email="cu2_create_admin@example.com",
            password=PASSWORD,
            first_name="Admin",
            last_name="Create",
            role=self.admin_role,
        )
        self.directiva_user = User.objects.create_user(
            email="cu2_create_dir@example.com",
            password=PASSWORD,
            first_name="Dir",
            last_name="Create",
            role=self.directiva_role,
        )

    def _login(self, user: User) -> None:
        self.client.force_authenticate(user=user)

    def test_admin_can_create_internal_user(self):
        """RN7: Administrador puede crear usuario interno con rol permitido."""
        self._login(self.admin_user)
        resp = self.client.post(
            self.USERS_URL,
            {
                "email": "nuevo_seguridad@example.com",
                "first_name": "Nuevo",
                "last_name": "Guardia",
                "role_slug": "seguridad",
                "password": PASSWORD,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email="nuevo_seguridad@example.com")
        self.assertEqual(user.role.slug, "seguridad")
        self.assertTrue(user.is_approved)

    def test_cannot_create_internal_user_with_residente_role(self):
        """RN5: El rol residente no es permitido en la creación de usuarios internos."""
        self._login(self.admin_user)
        resp = self.client.post(
            self.USERS_URL,
            {
                "email": "falso_residente@example.com",
                "first_name": "Falso",
                "last_name": "Residente",
                "role_slug": "residente",
                "password": PASSWORD,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_admin_cannot_create_internal_user(self):
        """RN1: No Administrador recibe 403 al intentar crear usuario interno."""
        self._login(self.directiva_user)
        resp = self.client.post(
            self.USERS_URL,
            {
                "email": "intento@example.com",
                "first_name": "Intento",
                "last_name": "Fallido",
                "role_slug": "seguridad",
                "password": PASSWORD,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
