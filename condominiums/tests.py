from datetime import date

from django.db.models.deletion import ProtectedError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Person, Role, SystemPermission, User

from .models import Condominium, Resident, ResidentUnit, Sector, Staff, Unit


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


class SectorApiTests(APITestCase):
    def setUp(self):
        permission, _ = SystemPermission.objects.get_or_create(
            code="manage_units",
            defaults={"name": "Gestionar unidades", "module": "condominiums"},
        )
        role, _ = Role.objects.get_or_create(
            slug="administrador", defaults={"name": "Administrador"}
        )
        role.permissions.add(permission)
        self.user = User.objects.create_user(
            email="admin.sectors@taji.test",
            password="ClaveSegura2026!",
            first_name="Ada",
            last_name="Admin",
            role=role,
        )
        self.client.force_authenticate(self.user)
        self.list_url = reverse("sector-list")
        self.condominium = Condominium.objects.first() or Condominium.objects.create(name="Taji")

    def test_create_sector_without_parent(self):
        response = self.client.post(
            self.list_url,
            {"code": "T1", "name": "Torre 1", "sector_type": Sector.Type.TOWER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertIsNone(response.data["parent"])
        self.assertIsNone(response.data["parent_name"])

    def test_create_sector_with_parent_resolves_parent_name(self):
        parent = Sector.objects.create(
            condominium=self.condominium, code="T2", name="Torre 2", sector_type=Sector.Type.TOWER
        )
        response = self.client.post(
            self.list_url,
            {"code": "T2-P1", "name": "Piso 1", "sector_type": Sector.Type.FLOOR, "parent": parent.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["parent_name"], "Torre 2")

    def test_sector_cannot_be_its_own_parent(self):
        sector = Sector.objects.create(
            condominium=self.condominium, code="T3", name="Torre 3", sector_type=Sector.Type.TOWER
        )
        response = self.client.patch(
            reverse("sector-detail", args=[sector.id]), {"parent": sector.id}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_supports_search_and_type_filter(self):
        Sector.objects.create(
            condominium=self.condominium, code="B1", name="Bloque Norte", sector_type=Sector.Type.BLOCK
        )
        Sector.objects.create(
            condominium=self.condominium, code="B2", name="Bloque Sur", sector_type=Sector.Type.BLOCK
        )

        response = self.client.get(self.list_url, {"search": "Norte", "sector_type": Sector.Type.BLOCK})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["pagination"]["total_items"], 1)
        self.assertEqual(response.data["results"][0]["name"], "Bloque Norte")

    def test_options_catalog(self):
        response = self.client.get(reverse("sector-options-catalog"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn({"value": Sector.Type.TOWER, "label": "Torre"}, response.data["sector_types"])

    def test_cannot_delete_sector_with_child_units(self):
        sector = Sector.objects.create(
            condominium=self.condominium, code="T4", name="Torre 4", sector_type=Sector.Type.TOWER
        )
        Unit.objects.create(code="U-501", unit_type=Unit.Type.APARTMENT, sector=sector)

        with self.assertRaises(ProtectedError):
            sector.delete()

    def test_user_without_manage_units_permission_is_forbidden(self):
        role = Role.objects.get(slug="directiva")
        other = User.objects.create_user(
            email="board.sectors@taji.test",
            password="ClaveSegura2026!",
            first_name="Dina",
            last_name="Directiva",
            role=role,
        )
        self.client.force_authenticate(other)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class UnitApiTests(APITestCase):
    def setUp(self):
        permission, _ = SystemPermission.objects.get_or_create(
            code="manage_units",
            defaults={"name": "Gestionar unidades", "module": "condominiums"},
        )
        role, _ = Role.objects.get_or_create(
            slug="administrador", defaults={"name": "Administrador"}
        )
        role.permissions.add(permission)
        self.user = User.objects.create_user(
            email="admin.units@taji.test",
            password="ClaveSegura2026!",
            first_name="Ada",
            last_name="Admin",
            role=role,
        )
        self.client.force_authenticate(self.user)
        self.list_url = reverse("unit-list")
        self.condominium = Condominium.objects.first() or Condominium.objects.create(name="Taji")
        self.sector = Sector.objects.create(
            condominium=self.condominium, code="T1", name="Torre 1", sector_type=Sector.Type.TOWER
        )

    def test_create_unit_without_sector(self):
        response = self.client.post(
            self.list_url, {"code": "U-001", "unit_type": Unit.Type.APARTMENT}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertIsNone(response.data["sector"])

    def test_create_unit_with_sector_resolves_sector_name(self):
        response = self.client.post(
            self.list_url,
            {"code": "U-002", "unit_type": Unit.Type.APARTMENT, "sector": self.sector.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["sector_name"], "Torre 1")

    def test_code_must_be_unique(self):
        Unit.objects.create(code="U-003", unit_type=Unit.Type.APARTMENT)
        response = self.client.post(
            self.list_url, {"code": "U-003", "unit_type": Unit.Type.HOUSE}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_supports_sector_filter(self):
        other_sector = Sector.objects.create(
            condominium=self.condominium, code="T2", name="Torre 2", sector_type=Sector.Type.TOWER
        )
        Unit.objects.create(code="U-101", unit_type=Unit.Type.APARTMENT, sector=self.sector)
        Unit.objects.create(code="U-201", unit_type=Unit.Type.APARTMENT, sector=other_sector)

        response = self.client.get(self.list_url, {"sector": self.sector.id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["pagination"]["total_items"], 1)
        self.assertEqual(response.data["results"][0]["code"], "U-101")

    def test_partial_update_changes_status(self):
        unit = Unit.objects.create(code="U-301", unit_type=Unit.Type.APARTMENT, sector=self.sector)
        response = self.client.patch(
            reverse("unit-detail", args=[unit.id]), {"status": Unit.Status.MAINTENANCE}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        unit.refresh_from_db()
        self.assertEqual(unit.status, Unit.Status.MAINTENANCE)

    def test_delete_unit(self):
        unit = Unit.objects.create(code="U-401", unit_type=Unit.Type.APARTMENT)
        response = self.client.delete(reverse("unit-detail", args=[unit.id]))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Unit.objects.filter(pk=unit.id).exists())

    def test_options_catalog(self):
        response = self.client.get(reverse("unit-options-catalog"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn({"value": Unit.Type.APARTMENT, "label": "Departamento"}, response.data["unit_types"])

    def test_user_without_manage_units_permission_is_forbidden(self):
        role = Role.objects.get(slug="directiva")
        other = User.objects.create_user(
            email="board.units@taji.test",
            password="ClaveSegura2026!",
            first_name="Dina",
            last_name="Directiva",
            role=role,
        )
        self.client.force_authenticate(other)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class ResidentUnitApiTests(APITestCase):
    def setUp(self):
        permission, _ = SystemPermission.objects.get_or_create(
            code="manage_residents",
            defaults={"name": "Gestionar residentes", "module": "condominiums"},
        )
        role, _ = Role.objects.get_or_create(
            slug="administrador", defaults={"name": "Administrador"}
        )
        role.permissions.add(permission)
        self.user = User.objects.create_user(
            email="admin.links@taji.test",
            password="ClaveSegura2026!",
            first_name="Ada",
            last_name="Admin",
            role=role,
        )
        self.client.force_authenticate(self.user)
        person = Person.objects.create(
            first_name="Residente", last_name="Activo", document_number="CU06-1"
        )
        self.resident = Resident.objects.create(person=person)
        self.unit = Unit.objects.create(code="CU06-1", unit_type=Unit.Type.APARTMENT)
        self.list_url = reverse("resident-unit-list")

    def test_create_association_returns_resident_and_unit_labels(self):
        response = self.client.post(
            self.list_url,
            {
                "resident": self.resident.id,
                "unit": self.unit.id,
                "relation_type": ResidentUnit.Relation.OWNER,
                "is_primary": True,
                "start_date": "2026-09-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["resident_name"], "Residente Activo")
        self.assertEqual(response.data["unit_code"], "CU06-1")
        self.assertEqual(response.data["relation_type_display"], "Propietario")

    def test_duplicate_active_association_is_rejected(self):
        ResidentUnit.objects.create(
            resident=self.resident,
            unit=self.unit,
            relation_type=ResidentUnit.Relation.TENANT,
        )
        response = self.client.post(
            self.list_url,
            {"resident": self.resident.id, "unit": self.unit.id, "relation_type": ResidentUnit.Relation.OWNER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_finishing_association_preserves_history_and_allows_new_link(self):
        link = ResidentUnit.objects.create(
            resident=self.resident,
            unit=self.unit,
            relation_type=ResidentUnit.Relation.TENANT,
            start_date="2026-01-01",
        )
        response = self.client.patch(
            reverse("resident-unit-detail", args=[link.id]),
            {"end_date": "2026-08-31"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(ResidentUnit.objects.filter(resident=self.resident, unit=self.unit).count(), 1)

        replacement = self.client.post(
            self.list_url,
            {
                "resident": self.resident.id,
                "unit": self.unit.id,
                "relation_type": ResidentUnit.Relation.OWNER,
                "start_date": "2026-09-01",
            },
            format="json",
        )
        self.assertEqual(replacement.status_code, status.HTTP_201_CREATED, replacement.data)

    def test_user_without_manage_residents_is_forbidden(self):
        role = Role.objects.get(slug="directiva")
        other = User.objects.create_user(
            email="board.links@taji.test",
            password="ClaveSegura2026!",
            first_name="Dina",
            last_name="Directiva",
            role=role,
        )
        self.client.force_authenticate(other)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)