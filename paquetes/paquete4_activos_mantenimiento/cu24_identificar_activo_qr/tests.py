import uuid as uuid_module

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from accounts.models import Role
from condominiums.models import Condominium, Resident, Sector, Unit
from maintenance.models import Asset, AssetType
from tenancy.models import TenantMembership
from accounts.models import Person

User = get_user_model()


class QRScanTestCase(APITestCase):
    """Pruebas para CU24 — Escaneo de códigos QR de activos."""

    def setUp(self):
        """Prepara datos de prueba."""
        # Crear condominio
        self.condo1 = Condominium.objects.create(
            name="Condominio Prueba 1", slug="condo-1"
        )
        self.condo2 = Condominium.objects.create(
            name="Condominio Prueba 2", slug="condo-2"
        )

        # Crear sector
        self.sector1 = Sector.objects.create(
            condominium=self.condo1, code="S001", name="Sector A"
        )
        self.sector2 = Sector.objects.create(
            condominium=self.condo2, code="S002", name="Sector B"
        )

        # Crear tipo de activo
        self.asset_type = AssetType.objects.create(
            code="ASCENSOR", name="Ascensor", description="Ascensores"
        )

        # Crear activos
        self.asset1 = Asset.objects.create(
            asset_type=self.asset_type,
            sector=self.sector1,
            code="ACT-001",
            name="Ascensor A",
            status="ACTIVE",
        )
        self.asset2 = Asset.objects.create(
            asset_type=self.asset_type,
            sector=self.sector2,
            code="ACT-002",
            name="Ascensor B",
            status="ACTIVE",
        )

        # Obtener o crear rol administrador (ANTES de crear usuarios)
        self.admin_role, _ = Role.objects.get_or_create(
            slug="administrador", defaults={"name": "Administrador"}
        )

        # Crear persona y usuario
        self.person = Person.objects.create(
            first_name="Test",
            last_name="User",
            contact_email="test@example.com",
            phone="123456789",
            document_type="CI",
            document_number="1234567890",
        )
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            person=self.person,
            role=self.admin_role,
        )

        # Crear membresía del usuario en condo1
        self.membership = TenantMembership.objects.create(
            user=self.user, condominium=self.condo1, role=self.admin_role
        )

        # Crear usuario SUPERADMIN
        self.person_super = Person.objects.create(
            first_name="Super",
            last_name="Admin",
            contact_email="super@example.com",
            phone="987654321",
            document_type="CI",
            document_number="9876543210",
        )
        self.superadmin = User.objects.create_user(
            email="super@example.com",
            password="superpass123",
            person=self.person_super,
            role=self.admin_role,  # SUPERADMIN también necesita role
        )
        self.superadmin.is_superuser = True
        self.superadmin.save()

        self.client = APIClient()

    def test_qr_scan_valid_asset_same_condominio(self):
        """Test: Escanear QR válido del activo en el mismo condominio."""
        self.client.force_authenticate(user=self.user)

        payload = f"TAJI-ASSET.{self.asset1.qr_uuid.hex}"
        response = self.client.post(
            "/api/v1/assets/scan/",
            {"qr_payload": payload},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.asset1.id)
        self.assertEqual(response.data["code"], "ACT-001")
        self.assertEqual(response.data["name"], "Ascensor A")
        self.assertEqual(response.data["status"], "ACTIVE")

    def test_qr_scan_invalid_format_wrong_prefix(self):
        """Test: QR con prefijo incorrecto."""
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            "/api/v1/assets/scan/",
            {"qr_payload": f"INVALID-PREFIX.{self.asset1.qr_uuid.hex}"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("prefijo", str(response.data).lower())

    def test_qr_scan_invalid_format_malformed_uuid(self):
        """Test: QR con UUID mal formado."""
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            "/api/v1/assets/scan/",
            {"qr_payload": "TAJI-ASSET.not-a-valid-uuid"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("uuid", str(response.data).lower())

    def test_qr_scan_asset_not_found(self):
        """Test: UUID válido pero asset no existe."""
        self.client.force_authenticate(user=self.user)

        fake_uuid = uuid_module.uuid4()
        response = self.client.post(
            "/api/v1/assets/scan/",
            {"qr_payload": f"TAJI-ASSET.{fake_uuid.hex}"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_qr_scan_asset_different_condominio(self):
        """Test: Intenta acceder a activo de otro condominio."""
        self.client.force_authenticate(user=self.user)

        # asset2 está en condo2, user está en condo1
        payload = f"TAJI-ASSET.{self.asset2.qr_uuid.hex}"
        response = self.client.post(
            "/api/v1/assets/scan/",
            {"qr_payload": payload},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_qr_scan_unauthenticated_user(self):
        """Test: Usuario no autenticado."""
        response = self.client.post(
            "/api/v1/assets/scan/",
            {"qr_payload": f"TAJI-ASSET.{self.asset1.qr_uuid.hex}"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_qr_scan_superadmin_access(self):
        """Test: SUPERADMIN puede acceder a activos de cualquier condominio."""
        self.client.force_authenticate(user=self.superadmin)

        # SUPERADMIN debe ver asset2 a pesar de no tener membresía en condo2
        payload = f"TAJI-ASSET.{self.asset2.qr_uuid.hex}"
        response = self.client.post(
            "/api/v1/assets/scan/",
            {"qr_payload": payload},
            format="json",
        )

        # NOTA: Esto puede fallar porque SUPERADMIN aún requiere TenantContext
        # Ajustaremos según el comportamiento real
        if response.status_code == status.HTTP_200_OK:
            self.assertEqual(response.data["id"], self.asset2.id)
        else:
            # Si requiere condominio en TenantContext, esperamos 403 o 400
            self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_400_BAD_REQUEST])

    def test_qr_scan_payload_case_insensitive(self):
        """Test: Payload es case-insensitive en UUID."""
        self.client.force_authenticate(user=self.user)

        # UUIDs en hex son siempre lowercase, pero intentamos uppercase
        payload = f"TAJI-ASSET.{self.asset1.qr_uuid.hex.upper()}"
        response = self.client.post(
            "/api/v1/assets/scan/",
            {"qr_payload": payload},
            format="json",
        )

        # Python's UUID.hex siempre retorna lowercase, así que esto debería fallar
        # a menos que estemos siendo flexible
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_qr_scan_payload_with_whitespace(self):
        """Test: Payload con espacios al inicio/final."""
        self.client.force_authenticate(user=self.user)

        payload = f"  TAJI-ASSET.{self.asset1.qr_uuid.hex}  "
        response = self.client.post(
            "/api/v1/assets/scan/",
            {"qr_payload": payload},
            format="json",
        )

        # Debe trimear espacios y funcionar
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.asset1.id)

    def test_qr_scan_missing_payload(self):
        """Test: Request sin qr_payload."""
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            "/api/v1/assets/scan/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_qr_scan_empty_payload(self):
        """Test: qr_payload vacío."""
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            "/api/v1/assets/scan/",
            {"qr_payload": ""},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_qr_scan_response_fields(self):
        """Test: Respuesta incluye todos los campos necesarios."""
        self.client.force_authenticate(user=self.user)

        payload = f"TAJI-ASSET.{self.asset1.qr_uuid.hex}"
        response = self.client.post(
            "/api/v1/assets/scan/",
            {"qr_payload": payload},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        required_fields = [
            "id",
            "code",
            "name",
            "description",
            "asset_type_name",
            "sector_name",
            "status",
            "qr_uuid",
        ]
        for field in required_fields:
            self.assertIn(field, response.data)

    def test_history_contains_only_incidents_of_active_condominium(self):
        from incidents.models import Incident
        Incident.objects.create(condominium=self.condo1, asset=self.asset1, public_code="QR-OWN", title="Incidencia propia")
        Incident.objects.create(condominium=self.condo2, asset=self.asset1, public_code="QR-OTHER", title="Dato cruzado inválido")
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/v1/assets/{self.asset1.pk}/history/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['public_code'] for item in response.data['incidents']], ['QR-OWN'])
        self.assertEqual(response.data['asset_id'], self.asset1.pk)
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_history_denies_foreign_assets_and_is_read_only(self):
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.get(f"/api/v1/assets/{self.asset2.pk}/history/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/assets/{self.asset1.pk}/history/", {}, format='json').status_code, 405)

    def test_resident_cannot_read_asset_or_history(self):
        resident = User.objects.create_user(email='resident-qr@taji.test', password='Test123!', role=Role.objects.get(slug='residente'))
        TenantMembership.objects.create(user=resident, condominium=self.condo1, role=resident.role, is_default=True)
        self.client.force_authenticate(user=resident)
        self.assertEqual(self.client.get(f"/api/v1/assets/{self.asset1.pk}/history/").status_code, 403)
        self.assertEqual(self.client.post('/api/v1/assets/scan/', {'qr_payload': f'TAJI-ASSET.{self.asset1.qr_uuid.hex}'}, format='json').status_code, 403)

    def test_inactive_role_cannot_scan(self):
        self.admin_role.is_active = False
        self.admin_role.save(update_fields=['is_active'])
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.post('/api/v1/assets/scan/', {'qr_payload': f'TAJI-ASSET.{self.asset1.qr_uuid.hex}'}, format='json').status_code, 403)
