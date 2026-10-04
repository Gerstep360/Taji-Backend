from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Person, Role, User
from condominiums.models import Staff, Unit
from security.models import AccessEvent


class AccessEventApiTests(APITestCase):
    def setUp(self):
        self.security_role = Role.objects.get(slug="seguridad")
        self.guard_user = User.objects.create_user(
            email="guardia.cu11@example.com",
            password="TajiSeguro2026!",
            role=self.security_role,
        )
        self.person = Person.objects.create(
            first_name="Ana",
            last_name="Márquez",
            document_type=Person.DocumentType.CI,
            document_number="1234567",
            contact_email="ana@example.com",
        )
        self.guard_staff = Staff.objects.create(
            person=self.person,
            employee_code="SEC-001",
            staff_type=Staff.Type.SECURITY,
            status=Staff.Status.ACTIVE,
        )
        self.unit = Unit.objects.create(code="U-101", unit_type=Unit.Type.APARTMENT)

    def test_guard_can_register_access_event(self):
        self.client.force_authenticate(user=self.guard_user)
        payload = {
            "person_id": self.person.id,
            "guard_staff_id": self.guard_staff.id,
            "event_type": AccessEvent.Type.ENTRY,
            "validation_method": AccessEvent.Method.MANUAL,
            "validation_result": AccessEvent.Result.APPROVED,
            "occurred_at": timezone.now().isoformat(),
            "notes": "Ingreso autorizado por portería",
        }

        response = self.client.post("/api/v1/security/access-events/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["event_type"], AccessEvent.Type.ENTRY)
        self.assertEqual(AccessEvent.objects.count(), 1)

    def test_guard_can_list_recent_access_events(self):
        self.client.force_authenticate(user=self.guard_user)
        AccessEvent.objects.create(
            person=self.person,
            guard_staff=self.guard_staff,
            event_type=AccessEvent.Type.DENIED,
            validation_result=AccessEvent.Result.REJECTED,
            notes="Acceso bloqueado",
        )

        response = self.client.get("/api/v1/security/access-events/?event_type=DENIED")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"][0]["event_type"], AccessEvent.Type.DENIED)
        self.assertEqual(response.data["results"][0]["person"]["full_name"], "Ana Márquez")
