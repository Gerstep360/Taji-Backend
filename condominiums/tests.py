from datetime import date

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Person, Role, SystemPermission, User

from .models import Staff


class StaffApiTests(APITestCase):
    def setUp(self):
        permission, _ = SystemPermission.objects.get_or_create(
            code="manage_staff",
            defaults={"name": "Gestionar personal", "module": "condominiums"},
        )
        role, _ = Role.objects.get_or_create(
            slug="administrador", defaults={"name": "Administrador"}
        )
        role.permissions.add(permission)
        self.user = User.objects.create_user(
            email="admin.staff@taji.test",
            password="ClaveSegura2026!",
            first_name="Ada",
            last_name="Admin",
            role=role,
        )
        self.client.force_authenticate(self.user)
        self.list_url = reverse("staff-list")
        self.payload = {
            "first_name": "Lucía",
            "last_name": "Mamani",
            "document_type": Person.DocumentType.CI,
            "document_number": "8450012",
            "document_complement": "LP",
            "phone": "76543210",
            "contact_email": "lucia@example.com",
            "birth_date": "1993-04-12",
            "employee_code": "SEG-999",  # El backend debe ignorar códigos enviados por clientes.
            "staff_type": Staff.Type.SECURITY,
            "hire_date": "2026-08-01",
            "end_date": None,
            "status": Staff.Status.ACTIVE,
            "notes": "Turno nocturno",
        }

    def test_create_staff_persists_person_and_assignment_atomically(self):
        response = self.client.post(self.list_url, self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        staff = Staff.objects.select_related("person").get()
        self.assertEqual(staff.employee_code, f"PER-{staff.id:05d}")
        self.assertNotEqual(staff.employee_code, self.payload["employee_code"])
        self.assertEqual(staff.staff_type, Staff.Type.SECURITY)
        self.assertEqual(staff.person.first_name, "Lucía")
        self.assertEqual(response.data["full_name"], "Lucía Mamani")
        self.assertEqual(response.data["staff_type_display"], "Seguridad")

    def test_list_supports_search_area_status_order_and_pagination(self):
        first = self._create_staff("LIM-001", Staff.Type.CLEANING, "Rosa", "Flores")
        self._create_staff("SEG-009", Staff.Type.SECURITY, "Mario", "López")

        response = self.client.get(
            self.list_url,
            {
                "search": "Rosa",
                "staff_type": Staff.Type.CLEANING,
                "status": Staff.Status.ACTIVE,
                "ordering": "person__last_name",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["pagination"]["total_items"], 1)
        self.assertEqual(response.data["results"][0]["id"], first.id)

    def test_options_are_served_by_backend_catalogs(self):
        response = self.client.get(reverse("staff-options-catalog"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(
            {"value": Staff.Type.MAINTENANCE, "label": "Mantenimiento"},
            response.data["staff_types"],
        )
        self.assertIn(
            {"value": Person.DocumentType.CI, "label": "Cédula de identidad"},
            response.data["document_types"],
        )

    def test_partial_update_changes_person_and_staff(self):
        staff = self._create_staff("MAN-002", Staff.Type.MAINTENANCE, "Luis", "Pérez")

        response = self.client.patch(
            reverse("staff-detail", args=[staff.id]),
            {
                "phone": "70000001",
                "staff_type": Staff.Type.ADMINISTRATION,
                "status": Staff.Status.SUSPENDED,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        staff.refresh_from_db()
        staff.person.refresh_from_db()
        self.assertEqual(staff.person.phone, "70000001")
        self.assertEqual(staff.staff_type, Staff.Type.ADMINISTRATION)
        self.assertEqual(staff.status, Staff.Status.SUSPENDED)

    def test_invalid_work_period_returns_field_error(self):
        payload = {
            **self.payload,
            "document_number": "9999999",
            "hire_date": "2026-09-10",
            "end_date": "2026-09-01",
            "status": Staff.Status.INACTIVE,
        }
        response = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn("end_date", response.data["error"]["fields"])

    def test_end_date_is_only_allowed_for_inactive_staff(self):
        response = self.client.post(
            self.list_url,
            {**self.payload, "document_number": "9999998", "end_date": "2026-09-01"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("end_date", response.data["error"]["fields"])

    def test_delete_removes_staff_but_preserves_person_source(self):
        staff = self._create_staff("ADM-003", Staff.Type.ADMINISTRATION, "Eva", "Ríos")
        person_id = staff.person_id

        response = self.client.delete(reverse("staff-detail", args=[staff.id]))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Staff.objects.filter(pk=staff.id).exists())
        self.assertTrue(Person.objects.filter(pk=person_id).exists())

    def test_user_without_manage_staff_permission_is_forbidden(self):
        role = Role.objects.get(slug="directiva")
        other = User.objects.create_user(
            email="board@taji.test",
            password="ClaveSegura2026!",
            first_name="Dina",
            last_name="Directiva",
            role=role,
        )
        self.client.force_authenticate(other)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "permission_denied")

    def test_openapi_documents_staff_contract(self):
        self.client.force_authenticate(user=None)
        response = self.client.get("/api/v1/openapi/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(b"/api/v1/staff/", response.content)

    def _create_staff(self, code, staff_type, first_name, last_name):
        person = Person.objects.create(
            first_name=first_name,
            last_name=last_name,
            document_number=None,
        )
        return Staff.objects.create(
            person=person,
            employee_code=code,
            staff_type=staff_type,
            hire_date=date(2026, 1, 1),
        )
