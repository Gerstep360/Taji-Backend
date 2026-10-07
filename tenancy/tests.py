"""Pruebas de Aislamiento y Multi-Tenancy (Sección 26 y 27 de multitenant_saas_optimizado.md)."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Person, Role
from condominiums.models import Condominium, Sector, Unit
from tenancy.context import TenantContext
from tenancy.models import TenantMembership
from tenancy.services import TenantProvisioningService

User = get_user_model()


class MultiTenantIsolationTests(TestCase):
    """
    Verifica que el aislamiento sea centralizado, automático y que ninguna operación
    pueda fugar o modificar datos entre tenants.
    """

    def setUp(self):
        TenantContext.clear()
        self.client = APIClient()

        # Roles
        self.role_admin = (
            Role.objects.filter(slug="administrador").first()
            or Role.objects.filter(slug="admin").first()
            or Role.objects.create(slug="administrador", name="Administrador")
        )
        self.role_resident = (
            Role.objects.filter(slug="residente").first()
            or Role.objects.filter(slug="resident").first()
            or Role.objects.create(slug="residente", name="Residente")
        )

        # Tenant A: Condominio Taji
        self.tenant_a = Condominium.objects.create(
            name="Condominio Taji",
            slug="taji",
            address="Av. Taji 100",
            is_active=True,
        )
        self.sector_a = Sector.objects.create(
            condominium=self.tenant_a,
            code="SEC-A",
            name="Torre Taji A",
        )
        self.unit_a1 = Unit.objects.create(
            sector=self.sector_a,
            code="A-101",
        )

        # Tenant B: Condominio Las Palmas
        self.tenant_b = Condominium.objects.create(
            name="Condominio Las Palmas",
            slug="las-palmas",
            address="Av. Palmas 200",
            is_active=True,
        )
        self.sector_b = Sector.objects.create(
            condominium=self.tenant_b,
            code="SEC-B",
            name="Torre Palmas B",
        )
        self.unit_b1 = Unit.objects.create(
            sector=self.sector_b,
            code="B-201",
        )

        # Usuario de Tenant A
        person_a = Person.objects.create(first_name="Juan", last_name="Taji", document_number="1001")
        self.user_a = User.objects.create_user(email="user_a@taji.app", password="Password123!", person=person_a, role=self.role_admin)
        self.membership_a = TenantMembership.objects.create(
            user=self.user_a,
            condominium=self.tenant_a,
            role=self.role_admin,
            is_default=True,
            is_active=True,
        )

        # Usuario de Tenant B
        person_b = Person.objects.create(first_name="Maria", last_name="Palmas", document_number="2002")
        self.user_b = User.objects.create_user(email="user_b@palmas.app", password="Password123!", person=person_b, role=self.role_admin)
        self.membership_b = TenantMembership.objects.create(
            user=self.user_b,
            condominium=self.tenant_b,
            role=self.role_admin,
            is_default=True,
            is_active=True,
        )

        # Superusuario de Plataforma SaaS
        person_super = Person.objects.create(first_name="Super", last_name="Admin", document_number="9999")
        self.superuser = User.objects.create_superuser(
            email="platform_admin@saas.app", password="Password123!", person=person_super, role=self.role_admin
        )

    def tearDown(self):
        TenantContext.clear()

    # -------------------------------------------------------------------------
    # TEST 1: Aislamiento automático a nivel de Data Access (Sección 6 y 7)
    # -------------------------------------------------------------------------
    def test_orm_queries_are_automatically_scoped_by_tenant_context(self):
        """Sector.objects y Unit.objects deben filtrarse por el tenant activo sin WHERE manual."""
        with TenantContext.for_tenant(self.tenant_a):
            sectors = list(Sector.objects.all())
            self.assertEqual(len(sectors), 1)
            self.assertEqual(sectors[0].id, self.sector_a.id)

            units = list(Unit.objects.all())
            self.assertEqual(len(units), 1)
            self.assertEqual(units[0].id, self.unit_a1.id)

        with TenantContext.for_tenant(self.tenant_b):
            sectors = list(Sector.objects.all())
            self.assertEqual(len(sectors), 1)
            self.assertEqual(sectors[0].id, self.sector_b.id)

            units = list(Unit.objects.all())
            self.assertEqual(len(units), 1)
            self.assertEqual(units[0].id, self.unit_b1.id)

    def test_global_mode_returns_all_tenants(self):
        """En modo global o all_tenants(), se pueden consultar todos los recursos."""
        with TenantContext.as_global():
            self.assertEqual(Sector.objects.count(), 2)
            self.assertEqual(Unit.objects.count(), 2)

        # Método explícito all_tenants()
        with TenantContext.for_tenant(self.tenant_a):
            self.assertEqual(Sector.objects.all_tenants().count(), 2)

    # -------------------------------------------------------------------------
    # TEST 2: Listado HTTP limitado al Tenant del usuario (Sección 27 - Test 3)
    # -------------------------------------------------------------------------
    def test_list_endpoint_returns_only_active_tenant_data(self):
        """GET /sectors/ con user_a debe devolver SOLO sectores de Tenant A."""
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get("/api/v1/sectors/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.data.get("results", response.data)
        returned_ids = [s["id"] for s in data]
        self.assertIn(self.sector_a.id, returned_ids)
        self.assertNotIn(self.sector_b.id, returned_ids)

    # -------------------------------------------------------------------------
    # TEST 3: Acceso a recurso de otro tenant devuelve 404 (Sección 27 - Test 1)
    # -------------------------------------------------------------------------
    def test_accessing_other_tenant_resource_returns_404(self):
        """User A intenta consultar Unit B1 de Tenant B -> debe recibir 404 Not Found."""
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get(f"/api/v1/units/{self.unit_b1.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # -------------------------------------------------------------------------
    # TEST 4: Modificación cruzada denegada (Sección 27 - Test 2)
    # -------------------------------------------------------------------------
    def test_cross_tenant_mutation_fails(self):
        """User A intenta modificar el sector del Tenant B -> debe recibir 404."""
        self.client.force_authenticate(user=self.user_a)
        response = self.client.patch(
            f"/api/v1/sectors/{self.sector_b.id}/",
            {"name": "Sector Hackeado"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Confirmar en base de datos que no se modificó
        self.sector_b.refresh_from_db()
        self.assertEqual(self.sector_b.name, "Torre Palmas B")

    # -------------------------------------------------------------------------
    # TEST 5: Protección contra Tenant Spoofing (Sección 3)
    # -------------------------------------------------------------------------
    def test_tenant_spoofing_via_header_is_forbidden(self):
        """User A envía HTTP_X_TENANT_ID hacia Tenant B -> 403 Forbidden."""
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get(
            "/api/v1/sectors/",
            HTTP_X_TENANT_ID=str(self.tenant_b.id),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["error"]["code"], "tenant_access_denied")

    # -------------------------------------------------------------------------
    # TEST 6: Aprovisionamiento atómico de Tenant (Sección 21)
    # -------------------------------------------------------------------------
    def test_tenant_provisioning_service_creates_complete_tenant(self):
        """TenantProvisioningService debe crear condominio, sector, unidad y membresía de admin."""
        person_c = Person.objects.create(first_name="Carlos", last_name="Nuevo", document_number="3003")
        admin_c = User.objects.create_user(
            email="admin_c@nuevo.app",
            password="Password123!",
            person=person_c,
            role=self.role_admin,
        )

        new_condo = TenantProvisioningService.provision_tenant(
            name="Condominio Los Pinos",
            slug="los-pinos",
            address="Calle 5 #456",
            admin_user=admin_c,
            max_units=100,
        )

        self.assertEqual(new_condo.name, "Condominio Los Pinos")
        self.assertEqual(new_condo.slug, "los-pinos")
        self.assertEqual(new_condo.sectors.count(), 1)
        self.assertTrue(Unit.objects.filter(sector__condominium=new_condo).exists())

        membership = TenantMembership.objects.filter(user=admin_c, condominium=new_condo).first()
        self.assertIsNotNone(membership)
        self.assertTrue(membership.is_default)

    # -------------------------------------------------------------------------
    # TEST 7: Cambio de Tenant para usuarios multi-condominio (Sección 2)
    # -------------------------------------------------------------------------
    def test_user_with_multiple_memberships_can_switch_tenant(self):
        """Un usuario que pertenece a dos condominios puede alternar su tenant activo."""
        # Asociar a user_a también a Tenant B
        TenantMembership.objects.create(
            user=self.user_a,
            condominium=self.tenant_b,
            role=self.role_resident,
            is_default=False,
            is_active=True,
        )

        self.client.force_authenticate(user=self.user_a)

        # 1. Consultar my-tenants
        resp = self.client.get("/api/v1/saas/my-tenants/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 2)

        # 2. Cambiar a Tenant B
        switch_resp = self.client.post(
            "/api/v1/saas/switch-tenant/",
            {"tenant_id": self.tenant_b.slug},
            format="json",
        )
        self.assertEqual(switch_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(switch_resp.data["active_tenant"]["id"], self.tenant_b.id)

    # -------------------------------------------------------------------------
    # TEST 8: Superusuario de plataforma en modo global (Sección 35)
    # -------------------------------------------------------------------------
    def test_superuser_platform_admin_views_all_tenants(self):
        """Platform Admin puede listar y gestionar todos los condominios del SaaS."""
        self.client.force_authenticate(user=self.superuser)
        resp = self.client.get("/api/v1/saas/tenants/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        returned_names = [t["name"] for t in resp.data.get("results", resp.data)]
        self.assertIn("Condominio Taji", returned_names)
        self.assertIn("Condominio Las Palmas", returned_names)

    # -------------------------------------------------------------------------
    # TEST 9: Planes SaaS públicos para la página de bienvenida y precios
    # -------------------------------------------------------------------------
    def test_public_subscription_plans_endpoint(self):
        """Cualquier visitante puede ver los planes y precios sin autenticación previa."""
        from tenancy.models import SubscriptionPlan
        SubscriptionPlan.objects.get_or_create(
            code="test-basic",
            defaults={"name": "Plan Básico Test", "price_bob": 100.00, "is_active": True, "order": 1}
        )
        response = self.client.get("/api/v1/saas/plans/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(len(response.data) >= 1)

    # -------------------------------------------------------------------------
    # TEST 10: Suscripción y Cuotas del Tenant activo
    # -------------------------------------------------------------------------
    def test_tenant_subscription_and_quotas_detail(self):
        """Un admin de condominio puede consultar su suscripción, días restantes y cuotas."""
        from tenancy.models import SubscriptionPlan
        plan, _ = SubscriptionPlan.objects.get_or_create(
            code="test-pro",
            defaults={"name": "Plan Pro Test", "price_bob": 300.00, "max_units": 100, "max_residents": 300}
        )
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get("/api/v1/saas/subscription/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("status", response.data)
        self.assertIn("max_units", response.data)
        self.assertIn("used_units", response.data)

    # -------------------------------------------------------------------------
    # TEST 11: Creación de Intent de Stripe y Confirmación en Sandbox
    # -------------------------------------------------------------------------
    def test_stripe_intent_and_sandbox_confirmation(self):
        """Flujo completo de checkout con Stripe (crear intent -> confirmar sandbox -> activar plan)."""
        from tenancy.models import SubscriptionPlan, TenantSubscription
        plan, _ = SubscriptionPlan.objects.get_or_create(
            code="test-premium",
            defaults={"name": "Plan Premium Test", "price_bob": 500.00, "max_units": 200, "max_residents": 600}
        )
        self.client.force_authenticate(user=self.user_a)

        # 1. Crear Intent
        intent_resp = self.client.post(
            "/api/v1/saas/checkout/create-intent/",
            {"plan_id": plan.id},
            format="json",
        )
        self.assertEqual(intent_resp.status_code, status.HTTP_200_OK)
        self.assertIn("payment_id", intent_resp.data)
        self.assertIn("client_secret", intent_resp.data)
        payment_id = intent_resp.data["payment_id"]

        # 2. Confirmar Sandbox (simulando pago exitoso en frontend)
        confirm_resp = self.client.post(
            "/api/v1/saas/checkout/confirm-sandbox/",
            {"payment_id": payment_id},
            format="json",
        )
        self.assertEqual(confirm_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(confirm_resp.data["status"], "APROBADO")

        # 3. Verificar que la suscripción del condominio esté ACTIVA con el nuevo plan
        sub = TenantSubscription.objects.get(condominium=self.tenant_a)
        self.assertEqual(sub.status, TenantSubscription.Status.ACTIVE)
        self.assertEqual(sub.plan.id, plan.id)
        self.tenant_a.refresh_from_db()
        self.assertEqual(self.tenant_a.max_units, 200)

    # -------------------------------------------------------------------------
    # TEST 12: Actualizar perfil de condominio por el admin
    # -------------------------------------------------------------------------
    def test_tenant_admin_can_update_condominium_profile(self):
        """El administrador de un condominio puede actualizar su dirección y teléfono."""
        self.client.force_authenticate(user=self.user_a)
        response = self.client.patch(
            "/api/v1/saas/my-condominium/",
            {"address": "Av. San Martín #456", "phone": "+591 3 3445566"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.tenant_a.refresh_from_db()
        self.assertEqual(self.tenant_a.address, "Av. San Martín #456")
        self.assertEqual(self.tenant_a.phone, "+591 3 3445566")

    # -------------------------------------------------------------------------
    # TEST 14: Onboarding público de Condominio con Administrador Activo
    # -------------------------------------------------------------------------
    def test_saas_condominium_onboarding_registers_active_admin_and_trial(self):
        """Un nuevo cliente registra su condominio: queda como Administrador aprobado y con prueba activa."""
        from tenancy.models import SubscriptionPlan
        SubscriptionPlan.objects.get_or_create(
            code="profesional",
            defaults={"name": "Plan Profesional", "price_bob": 350.00, "max_units": 120, "max_residents": 500}
        )

        payload = {
            "condominium_name": "Condominio Santa Cruz Real",
            "address": "Av. Bush #789",
            "phone": "+591 3 33221144",
            "admin_name": "Carlos Zambrana",
            "admin_document": "78945612",
            "admin_email": "czambrana@santacruzreal.app",
            "admin_phone": "+591 70011223",
            "admin_password": "SecurePassword123!",
            "plan_code": "profesional",
            "payment_method": "TRIAL",
        }

        # Request sin autenticar (público)
        self.client.force_authenticate(user=None)
        response = self.client.post("/api/v1/saas/onboarding/register/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("user", response.data)
        self.assertIn("condominium", response.data)
        self.assertIn("access", response.data)

        # Verificar que el usuario esté aprobado inmediatamente (sin esperar aprobación)
        user = User.objects.get(email="czambrana@santacruzreal.app")
        self.assertTrue(user.is_approved)
        self.assertTrue(user.is_active)
        self.assertEqual(user.role.slug, "administrador")

        # Verificar que el condominio esté creado y con membresía
        condo = Condominium.objects.get(name="Condominio Santa Cruz Real")
        membership = TenantMembership.objects.get(user=user, condominium=condo)
        self.assertTrue(membership.is_active)
        self.assertTrue(membership.is_default)
