"""Pruebas para CU16: Consultar auditoría y bitácora con filtros avanzados."""

from datetime import date, timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Person, Role, SystemPermission, User
from auditlog.models import AuditEvent


class Cu16AuditQueryTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        # Permiso y rol administrador
        cls.perm_audit, _ = SystemPermission.objects.get_or_create(
            code="audit.view", defaults={"name": "Ver auditoría", "module": "auditlog", "is_active": True}
        )
        cls.role_admin, _ = Role.objects.get_or_create(
            slug="administrador", defaults={"name": "Administrador", "is_active": True}
        )
        cls.role_admin.permissions.add(cls.perm_audit)

        cls.person_admin = Person.objects.create(first_name="Admin", last_name="Auditor")
        cls.admin_user = User.objects.create_user(
            email="admin.cu16@test.com", password="Password123!", role=cls.role_admin, person=cls.person_admin
        )

        cls.person_operator = Person.objects.create(first_name="Operador", last_name="Seguridad")
        cls.operator_user = User.objects.create_user(
            email="operador.cu16@test.com", password="Password123!", role=cls.role_admin, person=cls.person_operator
        )

        now = timezone.now()
        cls.event1 = AuditEvent.objects.create(
            actor_user=cls.operator_user,
            action_code="security.shift.opened",
            resource_type="SecurityShift",
            resource_id="1001",
            description="Turno abierto por operador.",
            occurred_at=now - timedelta(days=2),
        )
        cls.event2 = AuditEvent.objects.create(
            actor_user=cls.admin_user,
            action_code="security.shift.closed",
            resource_type="SecurityShift",
            resource_id="1002",
            description="Turno cerrado por admin.",
            occurred_at=now,
        )

    def test_filter_by_user_id(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(f"/api/v1/audit/?user_id={self.operator_user.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["actor_user"], self.operator_user.id)

    def test_filter_by_user_name_or_email(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get("/api/v1/audit/?user=operador")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertIn("Operador", results[0]["actor_name"])

    def test_filter_by_resource_type(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get("/api/v1/audit/?resource_type=SecurityShift")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertGreaterEqual(len(results), 2)

    def test_filter_by_date_range(self):
        self.client.force_authenticate(user=self.admin_user)
        today = date.today().isoformat()
        response = self.client.get(f"/api/v1/audit/?date_from={today}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["resource_id"], "1002")

    def test_invalid_date_format_validation(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get("/api/v1/audit/?date=fecha-invalida")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("date", response.data["error"]["fields"])

    def test_invalid_user_id_validation(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get("/api/v1/audit/?user_id=-5")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("user_id", response.data["error"]["fields"])
