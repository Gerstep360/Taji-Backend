from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Person, Role, SystemPermission, User
from condominiums.models import Condominium, Sector
from incidents.models import Incident
from maintenance.models import Asset, AssetType, MaintenancePlan, WorkOrder
from tenancy.models import TenantMembership


class CU23AssetApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manage_permission, _ = SystemPermission.objects.get_or_create(
            code="manage_assets", defaults={"name": "Gestionar activos del condominio"}
        )
        cls.view_permission, _ = SystemPermission.objects.get_or_create(
            code="view_general_status", defaults={"name": "Consultar el estado general"}
        )
        cls.admin_role, _ = Role.objects.get_or_create(
            slug="administrador", defaults={"name": "Administrador"}
        )
        cls.admin_role.permissions.add(cls.manage_permission)
        cls.directiva_role, _ = Role.objects.get_or_create(
            slug="directiva", defaults={"name": "Directiva"}
        )
        cls.directiva_role.permissions.add(cls.view_permission)
        cls.resident_role, _ = Role.objects.get_or_create(
            slug="residente", defaults={"name": "Residente"}
        )

        cls.condo = Condominium.objects.create(name="Condominio CU23")
        cls.other_condo = Condominium.objects.create(name="Otro condominio CU23")
        cls.sector = Sector.objects.create(condominium=cls.condo, code="A", name="Bloque A")
        cls.other_sector = Sector.objects.create(
            condominium=cls.other_condo, code="B", name="Bloque B"
        )

        cls.asset_type = AssetType.objects.create(code="BOMB-CU23", name="Bomba CU23")
        cls.asset = Asset.objects.create(
            asset_type=cls.asset_type,
            sector=cls.sector,
            code="BOM-001-CU23",
            name="Bomba de agua",
        )
        cls.other_asset = Asset.objects.create(
            asset_type=cls.asset_type,
            sector=cls.other_sector,
            code="BOM-002-CU23",
            name="Bomba de otro condominio",
        )

        cls.admin = cls._make_user("admin-cu23@example.test", "CU23 Admin", cls.admin_role)
        cls.directiva = cls._make_user(
            "directiva-cu23@example.test", "CU23 Directiva", cls.directiva_role
        )
        cls.resident = cls._make_user(
            "resident-cu23@example.test", "CU23 Residente", cls.resident_role
        )
        for user in (cls.admin, cls.directiva, cls.resident):
            TenantMembership.objects.create(
                user=user,
                condominium=cls.condo,
                role=user.role,
                is_default=True,
            )

    @staticmethod
    def _make_user(email, name, role):
        first, last = name.split(" ", 1)
        person = Person.objects.create(
            first_name=first,
            last_name=last,
            document_type=Person.DocumentType.CI,
            document_number=f"CU23-{email.split('@')[0]}",
        )
        return User.objects.create_user(
            email=email,
            password="SecurePassword-123!",
            person=person,
            role=role,
            is_approved=True,
        )

    def _create_asset(self, user=None, sector=None, **extra):
        self.client.force_authenticate(user=user or self.admin)
        payload = {
            "asset_type_id": self.asset_type.pk,
            "sector_id": (sector or self.sector).pk,
            "code": "ASC-001-CU23",
            "name": "Ascensor torre A",
            **extra,
        }
        return self.client.post(reverse("asset-list"), payload, format="json")

    def test_sector_queryset_is_resolved_per_request_not_at_module_import(self):
        from tenancy.context import TenantContext
        from .serializers import AssetSerializer
        TenantContext.set_current_tenant(self.condo)
        try:
            own = AssetSerializer().fields["sector_id"].queryset
            self.assertTrue(own.filter(pk=self.sector.pk).exists())
            self.assertFalse(own.filter(pk=self.other_sector.pk).exists())
            TenantContext.set_current_tenant(self.other_condo)
            other = AssetSerializer().fields["sector_id"].queryset
            self.assertTrue(other.filter(pk=self.other_sector.pk).exists())
            self.assertFalse(other.filter(pk=self.sector.pk).exists())
        finally:
            TenantContext.clear()

    def test_admin_creates_asset_scoped_to_tenant(self):
        response = self._create_asset()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        asset = Asset.objects.get(pk=response.data["id"])
        self.assertEqual(asset.sector_id, self.sector.pk)
        self.assertEqual(asset.status, Asset.Status.ACTIVE)
        self.assertTrue(response.data["qr_uuid"])

    def test_admin_cannot_create_asset_in_another_tenants_sector(self):
        response = self._create_asset(sector=self.other_sector)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_resident_cannot_create_asset(self):
        response = self._create_asset(user=self.resident)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_directiva_can_list_but_not_create(self):
        self.client.force_authenticate(user=self.directiva)

        listed = self.client.get(reverse("asset-list"))
        created = self._create_asset(user=self.directiva)

        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(created.status_code, status.HTTP_403_FORBIDDEN)

    def test_asset_list_never_returns_another_tenants_assets(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.get(reverse("asset-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {item["id"] for item in response.data.get("results", response.data)}
        self.assertIn(self.asset.pk, ids)
        self.assertNotIn(self.other_asset.pk, ids)

    def test_destroy_retires_asset_instead_of_deleting(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.delete(reverse("asset-detail", args=(self.asset.pk,)))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.Status.RETIRED)

    def test_qr_endpoint_returns_image_for_own_tenant_asset_only(self):
        self.client.force_authenticate(user=self.admin)

        own = self.client.get(reverse("asset-qr", args=(self.asset.pk,)))
        other = self.client.get(reverse("asset-qr", args=(self.other_asset.pk,)))

        self.assertEqual(own.status_code, status.HTTP_200_OK)
        self.assertIn("image_base64", own.data)
        self.assertEqual(other.status_code, status.HTTP_404_NOT_FOUND)

    def test_history_endpoint_aggregates_incident_work_order_and_plan(self):
        incident = Incident.objects.create(
            public_code="INC-CU23-1",
            condominium=self.condo,
            description="Fuga detectada",
            asset=self.asset,
        )
        work_order = WorkOrder.objects.create(
            public_code="OT-CU23-1",
            asset=self.asset,
            incident=incident,
            work_type=WorkOrder.Type.CORRECTIVE,
            title="Reparar bomba",
        )
        plan = MaintenancePlan.objects.create(
            asset=self.asset,
            name="Mantenimiento preventivo",
            frequency_days=30,
            next_due_at=work_order.created_at,
        )
        self.client.force_authenticate(user=self.admin)

        response = self.client.get(reverse("asset-history", args=(self.asset.pk,)))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {item["id"] for item in response.data["incidents"]}, {incident.pk}
        )
        self.assertEqual(
            {item["id"] for item in response.data["work_orders"]}, {work_order.pk}
        )
        self.assertEqual(
            {item["id"] for item in response.data["maintenance_plans"]}, {plan.pk}
        )

    def test_asset_type_crud_is_admin_only(self):
        payload = {"code": "EXT-CU23", "name": "Extintor"}

        resident_response = self.client.post(
            reverse("asset-type-list"), payload, format="json"
        )
        self.client.force_authenticate(user=self.resident)
        resident_response = self.client.post(
            reverse("asset-type-list"), payload, format="json"
        )
        self.client.force_authenticate(user=self.admin)
        admin_response = self.client.post(reverse("asset-type-list"), payload, format="json")

        self.assertEqual(resident_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(admin_response.status_code, status.HTTP_201_CREATED)
