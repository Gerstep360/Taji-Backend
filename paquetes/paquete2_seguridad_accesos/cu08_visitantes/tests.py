"""Pruebas para CU08 / T020: Registrar y autorizar visitantes."""

from datetime import timedelta

from django.urls import resolve, reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Person, Role, SystemPermission, User
from auditlog.models import AuditEvent
from condominiums.models import Condominium, Resident, ResidentUnit, Sector, Unit
from security.models import VisitAuthorization


class VisitAuthorizationBaseTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        # 1. Permisos del sistema
        cls.perm_register, _ = SystemPermission.objects.get_or_create(
            code="register_visits", defaults={"name": "Registrar visitas", "module": "security"}
        )
        cls.perm_manage, _ = SystemPermission.objects.get_or_create(
            code="manage_visits", defaults={"name": "Gestionar visitas", "module": "security"}
        )

        # 2. Roles
        cls.role_resident, _ = Role.objects.get_or_create(
            slug="residente", defaults={"name": "Copropietario / Residente"}
        )
        cls.role_resident.permissions.add(cls.perm_register)

        cls.role_admin, _ = Role.objects.get_or_create(
            slug="administrador", defaults={"name": "Administrador"}
        )
        cls.role_admin.permissions.add(cls.perm_manage, cls.perm_register)

        cls.role_guest, _ = Role.objects.get_or_create(
            slug="invitado-sin-permisos", defaults={"name": "Invitado"}
        )

        # 3. Condominio, Sector y Unidades
        cls.condo = Condominium.objects.create(name="Condominio Los Pinos")
        cls.sector = Sector.objects.create(
            condominium=cls.condo, code="TORRE-A", name="Torre A"
        )
        cls.unit_101 = Unit.objects.create(
            sector=cls.sector, code="A-101", unit_type=Unit.Type.APARTMENT
        )
        cls.unit_102 = Unit.objects.create(
            sector=cls.sector, code="A-102", unit_type=Unit.Type.APARTMENT
        )

        # 4. Persona y Residente 1
        cls.person_res1 = Person.objects.create(
            first_name="Carlos",
            last_name="Mendoza",
            document_type=Person.DocumentType.CI,
            document_number="5544332",
        )
        cls.user_res1 = User.objects.create_user(
            email="carlos.mendoza@taji.test",
            password="ClaveSegura2026!",
            person=cls.person_res1,
            role=cls.role_resident,
            is_approved=True,
        )
        cls.resident1 = Resident.objects.create(
            person=cls.person_res1, status=Resident.Status.ACTIVE
        )
        # Asociar Residente 1 a la Unidad A-101
        ResidentUnit.objects.create(
            resident=cls.resident1,
            unit=cls.unit_101,
            relation_type=ResidentUnit.Relation.OWNER,
            is_primary=True,
        )

        # 5. Persona y Residente 2
        cls.person_res2 = Person.objects.create(
            first_name="Beatriz",
            last_name="Salazar",
            document_type=Person.DocumentType.CI,
            document_number="9988776",
        )
        cls.user_res2 = User.objects.create_user(
            email="beatriz.salazar@taji.test",
            password="ClaveSegura2026!",
            person=cls.person_res2,
            role=cls.role_resident,
            is_approved=True,
        )
        cls.resident2 = Resident.objects.create(
            person=cls.person_res2, status=Resident.Status.ACTIVE
        )
        # Asociar Residente 2 a la Unidad A-102
        ResidentUnit.objects.create(
            resident=cls.resident2,
            unit=cls.unit_102,
            relation_type=ResidentUnit.Relation.TENANT,
            is_primary=True,
        )

        # 6. Administrador
        cls.person_admin = Person.objects.create(
            first_name="Admin",
            last_name="General",
            document_type=Person.DocumentType.CI,
            document_number="1122334",
        )
        cls.user_admin = User.objects.create_user(
            email="admin.taji@taji.test",
            password="ClaveSegura2026!",
            person=cls.person_admin,
            role=cls.role_admin,
            is_approved=True,
        )

        # 7. Usuario sin permisos
        cls.user_no_perms = User.objects.create_user(
            email="sinpermiso@taji.test",
            password="ClaveSegura2026!",
            role=cls.role_guest,
            is_approved=True,
        )

    def setUp(self):
        self.list_url = reverse("visit-authorization-list")


class VisitAuthorizationCreationTests(VisitAuthorizationBaseTestCase):
    def test_resident_registers_visit_authorization_successfully(self):
        """RF: El residente registra y autoriza anticipadamente una visita indicando visitante, unidad, motivo y periodo."""
        self.client.force_authenticate(self.user_res1)

        now = timezone.now()
        payload = {
            "visitor_first_name": "Mario",
            "visitor_last_name": "Gómez",
            "visitor_document_type": Person.DocumentType.CI,
            "visitor_document_number": "7766554",
            "visitor_phone": "71234567",
            "unit_id": self.unit_101.id,
            "purpose": "Almuerzo familiar de fin de semana",
            "valid_from": (now + timedelta(hours=1)).isoformat(),
            "valid_until": (now + timedelta(hours=6)).isoformat(),
            "notes": "Llegará en taxi",
        }

        response = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        # Verificar persistencia en base de datos
        auth_id = response.data["id"]
        auth = VisitAuthorization.objects.select_related("visitor_person", "authorized_by_resident", "unit").get(id=auth_id)

        self.assertEqual(auth.status, VisitAuthorization.Status.AUTHORIZED)
        self.assertEqual(auth.authorized_by_resident, self.resident1)
        self.assertEqual(auth.unit, self.unit_101)
        self.assertEqual(auth.purpose, "Almuerzo familiar de fin de semana")
        self.assertIsNotNone(auth.qr_uuid)
        self.assertEqual(auth.visitor_person.first_name, "Mario")
        self.assertEqual(auth.visitor_person.last_name, "Gómez")
        self.assertEqual(auth.visitor_person.document_number, "7766554")

        # Verificar auditoría
        audit_exists = AuditEvent.objects.filter(
            action_code="VISIT_AUTHORIZATION_CREATED",
            resource_type="VisitAuthorization",
            resource_id=str(auth.id),
        ).exists()
        self.assertTrue(audit_exists)

    def test_resident_cannot_authorize_for_unit_not_associated(self):
        """RN: El residente no puede emitir autorizaciones para unidades que no le correspondan activamente."""
        self.client.force_authenticate(self.user_res1)

        now = timezone.now()
        payload = {
            "visitor_first_name": "Pedro",
            "visitor_last_name": "Ramos",
            "unit_id": self.unit_102.id,  # Pertenece a Residente 2, no a Residente 1
            "purpose": "Visita no autorizada",
            "valid_from": (now + timedelta(hours=1)).isoformat(),
            "valid_until": (now + timedelta(hours=3)).isoformat(),
        }

        response = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("unit_id", response.data["error"]["fields"])

    def test_invalid_period_valid_until_before_valid_from(self):
        """RN: La fecha de fin debe ser posterior a la fecha de inicio."""
        self.client.force_authenticate(self.user_res1)

        now = timezone.now()
        payload = {
            "visitor_first_name": "Ana",
            "visitor_last_name": "López",
            "unit_id": self.unit_101.id,
            "valid_from": (now + timedelta(hours=5)).isoformat(),
            "valid_until": (now + timedelta(hours=2)).isoformat(),  # Invalido: menor a valid_from
        }

        response = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("valid_until", response.data["error"]["fields"])

    def test_invalid_period_in_the_past(self):
        """RN: El periodo de validez no puede estar en el pasado al momento de crear."""
        self.client.force_authenticate(self.user_res1)

        now = timezone.now()
        payload = {
            "visitor_first_name": "Ana",
            "visitor_last_name": "López",
            "unit_id": self.unit_101.id,
            "valid_from": (now - timedelta(days=2)).isoformat(),
            "valid_until": (now - timedelta(days=1)).isoformat(),  # En el pasado
        }

        response = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("valid_until", response.data["error"]["fields"])

    def test_reuse_existing_person_without_duplication(self):
        """RNF: Integridad y fuente única. Si la persona visitante ya existe por documento, se reutiliza."""
        existing_visitor = Person.objects.create(
            first_name="Valeria",
            last_name="Fernández",
            document_type=Person.DocumentType.CI,
            document_number="4455667",
            phone="78901234",
        )

        self.client.force_authenticate(self.user_res1)
        now = timezone.now()
        payload = {
            "visitor_first_name": "Valeria",
            "visitor_last_name": "Fernández",
            "visitor_document_type": Person.DocumentType.CI,
            "visitor_document_number": "4455667",
            "visitor_phone": "79998888",  # Teléfono actualizado
            "unit_id": self.unit_101.id,
            "purpose": "Trabajo de consultoría",
            "valid_from": (now + timedelta(hours=1)).isoformat(),
            "valid_until": (now + timedelta(hours=4)).isoformat(),
        }

        initial_person_count = Person.objects.count()
        response = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # No se debió crear una persona duplicada
        self.assertEqual(Person.objects.count(), initial_person_count)

        existing_visitor.refresh_from_db()
        self.assertEqual(existing_visitor.phone, "79998888")


class VisitAuthorizationIsolationAndAdministrationTests(VisitAuthorizationBaseTestCase):
    def setUp(self):
        super().setUp()
        now = timezone.now()

        # Visita 1 creada por Residente 1
        visitor1 = Person.objects.create(first_name="Visitante", last_name="Uno")
        self.auth1 = VisitAuthorization.objects.create(
            visitor_person=visitor1,
            authorized_by_resident=self.resident1,
            unit=self.unit_101,
            purpose="Visita de Residente 1",
            valid_from=now + timedelta(hours=1),
            valid_until=now + timedelta(hours=5),
            qr_expires_at=now + timedelta(hours=5),
            status=VisitAuthorization.Status.AUTHORIZED,
        )

        # Visita 2 creada por Residente 2
        visitor2 = Person.objects.create(first_name="Visitante", last_name="Dos")
        self.auth2 = VisitAuthorization.objects.create(
            visitor_person=visitor2,
            authorized_by_resident=self.resident2,
            unit=self.unit_102,
            purpose="Visita de Residente 2",
            valid_from=now + timedelta(hours=2),
            valid_until=now + timedelta(hours=6),
            qr_expires_at=now + timedelta(hours=6),
            status=VisitAuthorization.Status.AUTHORIZED,
        )

    def test_resident_only_sees_their_own_authorizations(self):
        """RN: Un residente solo puede listar y consultar las autorizaciones que él emitió."""
        self.client.force_authenticate(self.user_res1)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = [item["id"] for item in response.data["results"]]
        self.assertIn(self.auth1.id, ids)
        self.assertNotIn(self.auth2.id, ids)

        # Intento de ver detalle de la visita de otro residente devuelve 404
        detail_url_auth2 = reverse("visit-authorization-detail", kwargs={"pk": self.auth2.id})
        detail_resp = self.client.get(detail_url_auth2)
        self.assertEqual(detail_resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_admin_can_consult_and_filter_all_authorizations(self):
        """RF: La administración debe poder consultar y gestionar las autorizaciones registradas."""
        self.client.force_authenticate(self.user_admin)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = [item["id"] for item in response.data["results"]]
        self.assertIn(self.auth1.id, ids)
        self.assertIn(self.auth2.id, ids)

        # Filtrar por unidad
        filter_resp = self.client.get(self.list_url, {"unit": self.unit_101.id})
        self.assertEqual(filter_resp.status_code, status.HTTP_200_OK)
        filtered_ids = [item["id"] for item in filter_resp.data["results"]]
        self.assertIn(self.auth1.id, filtered_ids)
        self.assertNotIn(self.auth2.id, filtered_ids)

    def test_cancel_authorization_successfully(self):
        """RF: El residente o la administración pueden cancelar una autorización."""
        self.client.force_authenticate(self.user_res1)

        cancel_url = reverse("visit-authorization-cancel", kwargs={"pk": self.auth1.id})
        response = self.client.post(cancel_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.auth1.refresh_from_db()
        self.assertEqual(self.auth1.status, VisitAuthorization.Status.CANCELLED)
        self.assertIsNotNone(self.auth1.cancelled_at)

        # Cancelar de nuevo devuelve error de validación
        retry_response = self.client.post(cancel_url)
        self.assertEqual(retry_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthorized_user_is_forbidden(self):
        """RN: Usuario sin permisos de visitas no puede acceder a los endpoints."""
        self.client.force_authenticate(self.user_no_perms)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_options_catalog_endpoint(self):
        """Endpoint de catálogos para interfaces web y móvil."""
        self.client.force_authenticate(self.user_res1)

        options_url = reverse("visit-authorization-options")
        response = self.client.get(options_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("statuses", response.data)
        self.assertIn("document_types", response.data)

    def test_package_and_root_urls_resolve_identically(self):
        """Compatibilidad de rutas /api/v1/ y /api/v1/paquete2/."""
        root_match = resolve("/api/v1/visit-authorizations/")
        pkg_match = resolve("/api/v1/paquete2/visit-authorizations/")
        self.assertIs(root_match.func.cls, pkg_match.func.cls)
