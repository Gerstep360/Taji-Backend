from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Role, SystemPermission, User
from auditlog.models import AuditEvent
from auditlog.services import record_audit_event


class AuditLogProtectionTests(TestCase):
    """Pruebas de protección contra modificación y eliminación de registros de auditoría."""

    def setUp(self):
        self.role, _ = Role.objects.get_or_create(
            slug="auditor",
            defaults={"name": "Auditor", "is_active": True},
        )
        self.user = User.objects.create_user(
            email="auditor@taji.test",
            password="Password123!",
            first_name="Auditor",
            last_name="Test",
            role=self.role,
        )
        self.event = AuditEvent.objects.create(
            actor_user=self.user,
            action_code="test.action",
            resource_type="TestResource",
            resource_id="123",
            description="Evento de prueba inicial.",
            ip_address="127.0.0.1",
            user_agent="TestAgent/1.0",
        )

    def test_cannot_modify_existing_audit_event(self):
        """Verifica que un registro existente no pueda ser editado mediante save()."""
        self.event.description = "Intento de alteración maliciosa"
        with self.assertRaises(ValidationError) as ctx:
            self.event.save()
        self.assertIn("AuditEvent es append-only", str(ctx.exception))

        self.event.refresh_from_db()
        self.assertEqual(self.event.description, "Evento de prueba inicial.")

    def test_cannot_delete_individual_audit_event(self):
        """Verifica que un registro no pueda ser eliminado individualmente mediante delete()."""
        with self.assertRaises(ValidationError) as ctx:
            self.event.delete()
        self.assertIn("AuditEvent es append-only", str(ctx.exception))

        self.assertTrue(AuditEvent.objects.filter(pk=self.event.pk).exists())

    def test_cannot_bulk_update_audit_events(self):
        """Verifica que QuerySet.update() esté bloqueado y lance ValidationError."""
        with self.assertRaises(ValidationError) as ctx:
            AuditEvent.objects.filter(pk=self.event.pk).update(description="Alteración masiva")
        self.assertIn("AuditEvent es append-only", str(ctx.exception))

        self.event.refresh_from_db()
        self.assertEqual(self.event.description, "Evento de prueba inicial.")

    def test_cannot_bulk_delete_audit_events(self):
        """Verifica que QuerySet.delete() esté bloqueado y lance ValidationError."""
        with self.assertRaises(ValidationError) as ctx:
            AuditEvent.objects.all().delete()
        self.assertIn("AuditEvent es append-only", str(ctx.exception))

        self.assertTrue(AuditEvent.objects.filter(pk=self.event.pk).exists())


class AutomaticAuditLoggingTests(TestCase):
    """Pruebas de generación automática de registros de auditoría en acciones sensibles."""

    def setUp(self):
        self.client = APIClient()
        self.factory = RequestFactory()

        self.admin_role, _ = Role.objects.get_or_create(
            slug="administrador",
            defaults={"name": "Administrador", "is_active": True},
        )
        self.manage_roles_perm, _ = SystemPermission.objects.get_or_create(
            code="manage_roles",
            defaults={"name": "Gestionar roles", "module": "accounts", "is_active": True},
        )
        self.admin_role.permissions.add(self.manage_roles_perm)

        self.admin = User.objects.create_superuser(
            email="admin.audit@taji.test",
            password="AdminPassword123!",
            first_name="Super",
            last_name="Admin",
            role=self.admin_role,
            is_approved=True,
            is_active=True,
        )

    def test_record_audit_event_service(self):
        """Comprueba el servicio centralizado de registro de auditoría."""
        request = self.factory.post(
            "/api/v1/auth/login/",
            HTTP_X_FORWARDED_FOR="203.0.113.42, 192.168.1.1",
            HTTP_USER_AGENT="Mozilla/5.0 TajiMobile/1.0",
        )
        request.user = self.admin

        event = record_audit_event(
            action_code="custom.sensitive.action",
            resource_type="Document",
            resource_id="doc-99",
            description="Documento confidencial revisado.",
            request=request,
            after_data={"status": "approved"},
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.action_code, "custom.sensitive.action")
        self.assertEqual(event.actor_user, self.admin)
        self.assertEqual(event.ip_address, "203.0.113.42")
        self.assertEqual(event.user_agent, "Mozilla/5.0 TajiMobile/1.0")
        self.assertEqual(event.after_data, {"status": "approved"})

    def test_audit_login_success(self):
        """Verifica que un inicio de sesión exitoso genere automáticamente un AuditEvent."""
        initial_count = AuditEvent.objects.count()
        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": "admin.audit@taji.test", "password": "AdminPassword123!", "client": "web"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        event = AuditEvent.objects.filter(action_code="auth.login.success").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.actor_user, self.admin)
        self.assertIn("Inicio de sesión exitoso", event.description)
        self.assertEqual(AuditEvent.objects.count(), initial_count + 1)

    def test_audit_login_failed(self):
        """Verifica que un intento fallido de inicio de sesión genere automáticamente un AuditEvent."""
        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": "admin.audit@taji.test", "password": "WrongPassword!", "client": "web"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        event = AuditEvent.objects.filter(action_code="auth.login.failed").first()
        self.assertIsNotNone(event)
        self.assertIn("Intento fallido", event.description)

    def test_audit_role_permissions_update(self):
        """Verifica que la modificación de permisos de un rol genere automáticamente un AuditEvent."""
        self.client.force_authenticate(user=self.admin)
        target_role = Role.objects.create(slug="guardia", name="Guardia de Seguridad", is_active=True)
        view_perm, _ = SystemPermission.objects.get_or_create(
            code="view_announcements",
            defaults={"name": "Ver comunicados", "module": "announcements", "is_active": True},
        )

        response = self.client.patch(
            f"/api/v1/roles/{target_role.slug}/permissions/",
            {"permissions": ["view_announcements"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        event = AuditEvent.objects.filter(action_code="roles.permissions.updated").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.actor_user, self.admin)
        self.assertEqual(event.resource_type, "Role")
        self.assertEqual(event.resource_id, str(target_role.id))
        self.assertIn("Guardia de Seguridad", event.description)

    def test_audit_resident_review_approval(self):
        """Verifica que la aprobación de un residente pendiente genere automáticamente un AuditEvent."""
        self.client.force_authenticate(user=self.admin)
        residente_role, _ = Role.objects.get_or_create(slug="residente", defaults={"name": "Residente"})
        resident_user = User.objects.create_user(
            email="pendiente@taji.test",
            password="Password123!",
            first_name="Carlos",
            last_name="Pendiente",
            role=residente_role,
            is_approved=False,
            is_active=True,
        )

        response = self.client.patch(
            f"/api/v1/roles/residents/{resident_user.id}/review/",
            {"action": "approve"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        event = AuditEvent.objects.filter(action_code="residents.approval.reviewed").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.actor_user, self.admin)
        self.assertEqual(event.resource_id, str(resident_user.id))
        self.assertIn("aprobada", event.description)
