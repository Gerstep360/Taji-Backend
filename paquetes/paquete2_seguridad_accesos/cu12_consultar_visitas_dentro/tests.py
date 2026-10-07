"""Pruebas para CU12: Consultar visitas y personas dentro."""

from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Person, Role, SystemPermission, User
from condominiums.models import Condominium, Resident, Sector, Staff, Unit
from security.models import AccessEvent, VisitAuthorization
from tenancy.models import TenantMembership


class VisitConsultationTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        # Permisos
        cls.perm_manage, _ = SystemPermission.objects.get_or_create(
            code="manage_visits", defaults={"name": "Gestionar visitas", "module": "security"}
        )
        cls.perm_validate, _ = SystemPermission.objects.get_or_create(
            code="validate_visits", defaults={"name": "Validar visitas", "module": "security"}
        )
        cls.perm_register_entry_exit, _ = SystemPermission.objects.get_or_create(
            code="register_entry_exit", defaults={"name": "Registrar ingresos/salidas", "module": "security"}
        )

        # Roles
        cls.role_admin, _ = Role.objects.get_or_create(
            slug="administrador", defaults={"name": "Administrador"}
        )
        cls.role_admin.permissions.add(cls.perm_manage, cls.perm_validate, cls.perm_register_entry_exit)

        cls.role_guard, _ = Role.objects.get_or_create(
            slug="seguridad", defaults={"name": "Personal de Seguridad"}
        )
        cls.role_guard.permissions.add(cls.perm_validate, cls.perm_register_entry_exit)

        cls.role_resident, _ = Role.objects.get_or_create(
            slug="residente", defaults={"name": "Residente"}
        )

        # Condominio y unidades
        cls.condo = Condominium.objects.create(name="Condominio Vista Verde")
        cls.sector = Sector.objects.create(condominium=cls.condo, code="SEC-A", name="Sector A")
        cls.unit = Unit.objects.create(sector=cls.sector, code="101-A", unit_type=Unit.Type.APARTMENT)

        # Personas y usuarios
        cls.admin_person = Person.objects.create(first_name="Admin", last_name="General")
        cls.admin_user = User.objects.create_user(
            email="admin.cu12@test.com", password="Password123!", role=cls.role_admin, person=cls.admin_person
        )
        TenantMembership.objects.create(user=cls.admin_user, condominium=cls.condo, role=cls.role_admin, is_active=True)

        cls.guard_person = Person.objects.create(first_name="Guardia", last_name="Turno")
        cls.guard_staff = Staff.objects.create(
            person=cls.guard_person, staff_type=Staff.Type.SECURITY, condominium=cls.condo
        )
        cls.guard_user = User.objects.create_user(
            email="guard.cu12@test.com", password="Password123!", role=cls.role_guard, person=cls.guard_person
        )
        TenantMembership.objects.create(user=cls.guard_user, condominium=cls.condo, role=cls.role_guard, is_active=True)

        cls.resident_person = Person.objects.create(first_name="Residente", last_name="Propietario")
        cls.resident = Resident.objects.create(person=cls.resident_person, condominium=cls.condo)
        cls.resident_user = User.objects.create_user(
            email="resident.cu12@test.com", password="Password123!", role=cls.role_resident, person=cls.resident_person
        )
        TenantMembership.objects.create(user=cls.resident_user, condominium=cls.condo, role=cls.role_resident, is_active=True)

        cls.visitor_person = Person.objects.create(
            first_name="Carlos", last_name="Visitante", document_number="8877665"
        )

        # Autorización de visita
        now = timezone.now()
        cls.auth_expected = VisitAuthorization.objects.create(
            visitor_person=cls.visitor_person,
            authorized_by_resident=cls.resident,
            unit=cls.unit,
            valid_from=now - timedelta(hours=1),
            valid_until=now + timedelta(hours=4),
            qr_expires_at=now + timedelta(hours=2),
            status=VisitAuthorization.Status.AUTHORIZED,
        )

        # Evento de acceso dentro
        cls.access_event = AccessEvent.objects.create(
            authorization=cls.auth_expected,
            unit=cls.unit,
            person=cls.visitor_person,
            guard_staff=cls.guard_staff,
            event_type=AccessEvent.Type.ENTRY,
            validation_result=AccessEvent.Result.APPROVED,
            occurred_at=now - timedelta(minutes=30),
        )

    def test_admin_can_query_expected_visits(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get("/api/v1/security/cu12/visits/?section=expected")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)

    def test_guard_can_query_inside_visits(self):
        self.client.force_authenticate(user=self.guard_user)
        response = self.client.get("/api/v1/security/cu12/visits/?section=inside")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)
        self.assertGreaterEqual(len(response.data["results"]), 1)

    def test_query_history_and_search_filter(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get("/api/v1/security/cu12/visits/?section=history&search=8877665")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data["results"]), 1)

    def test_invalid_section_rejected(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get("/api/v1/security/cu12/visits/?section=invalido")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("section", response.data["error"]["fields"])

    def test_unauthenticated_rejected(self):
        response = self.client.get("/api/v1/security/cu12/visits/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
