from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Person, Role, User
from condominiums.models import Staff, Unit
from security.models import AccessEvent


class AccessEventApiTests(APITestCase):
    def setUp(self):
        self.security_role = Role.objects.get(slug="seguridad")
        self.person = Person.objects.create(
            first_name="Ana",
            last_name="Márquez",
            document_type=Person.DocumentType.CI,
            document_number="1234567",
            contact_email="ana@example.com",
        )
        guard_person = Person.objects.create(
            first_name="Miguel",
            last_name="Guardia",
            document_type=Person.DocumentType.CI,
            document_number="7654321",
        )
        self.guard_staff = Staff.objects.create(
            person=guard_person,
            employee_code="SEC-001",
            staff_type=Staff.Type.SECURITY,
            status=Staff.Status.ACTIVE,
        )
        self.guard_user = User.objects.create_user(
            email="guardia.cu11@example.com",
            password="TajiSeguro2026!",
            role=self.security_role,
            person=guard_person,
        )
        self.unit = Unit.objects.create(code="U-101", unit_type=Unit.Type.APARTMENT)

    def test_guard_can_register_access_event(self):
        self.client.force_authenticate(user=self.guard_user)
        payload = {
            "person_id": self.person.id,
            "guard_staff_id": self.guard_staff.id,
            "unit_id": self.unit.id,
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

    def test_guard_can_register_entry_exit_and_denied_without_losing_history(self):
        self.client.force_authenticate(user=self.guard_user)

        for event_type in (
            AccessEvent.Type.ENTRY,
            AccessEvent.Type.EXIT,
            AccessEvent.Type.DENIED,
        ):
            response = self.client.post(
                "/api/v1/security/access-events/",
                {
                    "person_id": self.person.id,
                    "guard_staff_id": self.guard_staff.id,
                    "unit_id": self.unit.id,
                    "event_type": event_type,
                    "validation_method": AccessEvent.Method.MANUAL,
                    **(
                        {"validation_result": AccessEvent.Result.APPROVED}
                        if event_type == AccessEvent.Type.DENIED
                        else {}
                    ),
                    "notes": f"Evento {event_type}",
                },
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(response.data["event_type"], event_type)

        events = AccessEvent.objects.order_by("occurred_at", "id")
        self.assertEqual(events.count(), 3)
        self.assertEqual(
            list(events.values_list("event_type", flat=True)),
            [AccessEvent.Type.ENTRY, AccessEvent.Type.EXIT, AccessEvent.Type.DENIED],
        )
        self.assertEqual(
            list(events.values_list("validation_result", flat=True)),
            [
                AccessEvent.Result.APPROVED,
                AccessEvent.Result.APPROVED,
                AccessEvent.Result.REJECTED,
            ],
        )

    def test_guard_can_list_recent_access_events(self):
        self.client.force_authenticate(user=self.guard_user)
        AccessEvent.objects.create(
            person=self.person,
            guard_staff=self.guard_staff,
            unit=self.unit,
            event_type=AccessEvent.Type.DENIED,
            validation_result=AccessEvent.Result.REJECTED,
            notes="Acceso bloqueado",
        )

        response = self.client.get("/api/v1/security/access-events/?event_type=DENIED")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"][0]["event_type"], AccessEvent.Type.DENIED)
        self.assertEqual(response.data["results"][0]["person"]["full_name"], "Ana Márquez")

    def test_guard_can_register_unregistered_visitor_without_creating_a_resident(self):
        self.client.force_authenticate(user=self.guard_user)
        initial_people = Person.objects.count()

        response = self.client.post(
            "/api/v1/security/access-events/",
            {
                "visitor_name": "Carlos Visitante",
                "visitor_document_number": "9988776",
                "unit_id": self.unit.id,
                "event_type": AccessEvent.Type.ENTRY,
                "validation_method": AccessEvent.Method.MANUAL,
                "notes": "Visita autorizada por teléfono",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        event = AccessEvent.objects.get(pk=response.data["id"])
        self.assertIsNone(event.person_id)
        self.assertEqual(event.visitor_name, "Carlos Visitante")
        self.assertEqual(event.visitor_document_number, "9988776")
        self.assertEqual(event.unit_id, self.unit.id)
        self.assertEqual(Person.objects.count(), initial_people)
        self.assertEqual(response.data["unit"]["code"], self.unit.code)

    def test_guard_can_search_people_and_active_units(self):
        self.client.force_authenticate(user=self.guard_user)

        people_response = self.client.get(
            "/api/v1/security/access-events/people/?search=Ana"
        )
        units_response = self.client.get(
            "/api/v1/security/access-events/units/?search=U-101"
        )

        self.assertEqual(people_response.status_code, status.HTTP_200_OK)
        self.assertEqual(people_response.data["results"][0]["id"], self.person.id)
        self.assertEqual(units_response.status_code, status.HTTP_200_OK)
        self.assertEqual(units_response.data["results"][0]["id"], self.unit.id)

    def test_unregistered_visitor_cannot_reenter_a_carnet_already_in_the_system(self):
        self.client.force_authenticate(user=self.guard_user)

        response = self.client.post(
            "/api/v1/security/access-events/",
            {
                "visitor_name": "Ana Márquez",
                "visitor_document_number": "1234567",
                "unit_id": self.unit.id,
                "event_type": AccessEvent.Type.ENTRY,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("visitor_document_number", response.data["error"]["fields"])

    def test_security_user_cannot_attribute_event_to_another_guard(self):
        self.client.force_authenticate(user=self.guard_user)
        other_person = Person.objects.create(first_name="Otro", last_name="Guardia")
        other_guard = Staff.objects.create(
            person=other_person,
            employee_code="SEC-002",
            staff_type=Staff.Type.SECURITY,
        )

        response = self.client.post(
            "/api/v1/security/access-events/",
            {
                "person_id": self.person.id,
                "guard_staff_id": other_guard.id,
                "unit_id": self.unit.id,
                "event_type": AccessEvent.Type.ENTRY,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["guard_staff_id"], self.guard_staff.id)

    def test_registered_access_event_cannot_be_edited_or_deleted(self):
        self.client.force_authenticate(user=self.guard_user)
        event = AccessEvent.objects.create(
            person=self.person,
            guard_staff=self.guard_staff,
            event_type=AccessEvent.Type.ENTRY,
        )
        event_url = f"/api/v1/security/access-events/{event.id}/"

        update_response = self.client.patch(
            event_url,
            {"event_type": AccessEvent.Type.EXIT},
            format="json",
        )
        delete_response = self.client.delete(event_url)

        self.assertEqual(update_response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(delete_response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        event.refresh_from_db()
        self.assertEqual(event.event_type, AccessEvent.Type.ENTRY)
