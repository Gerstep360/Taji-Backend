"""Pruebas de Aislamiento y Multi-Tenancy (Sección 26 y 27 de multitenant_saas_optimizado.md)."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

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


class PlatformTenantsViewTests(APITestCase):
    """
    Consola global de tenants: listado de solo lectura para el Platform Admin.

    Caso independiente y no una subclase de `MultiTenantIsolationTests`: aquel
    comparte `setUpTestData` entre todos sus tests y algunos aprovisionan un
    tercer condominio, lo que haria que los conteos exactos de esta vista no
    fueran deterministas.
    """

    LIST_URL = "/api/v1/saas/platform/tenants/"
    SUMMARY_URL = "/api/v1/saas/platform/tenants/summary/"

    @classmethod
    def setUpTestData(cls):
        # Los roles ya los siembra `sync_rbac` en post_migrate, asi que se
        # recuperan en lugar de crearlos y chocar con el slug unico.
        cls.role_admin = Role.objects.get(slug="administrador")

        cls.tenant_a = Condominium.objects.create(name="Condominio Taji", status="ACTIVE")
        cls.tenant_b = Condominium.objects.create(name="Condominio Las Palmas", status="ACTIVE")
        cls.tenant_c = Condominium.objects.create(name="Complejo En Pausa", status="INACTIVE", is_active=False)

        cls.sector_a = Sector.objects.create(condominium=cls.tenant_a, code="A", name="Torre A")
        cls.sector_b = Sector.objects.create(condominium=cls.tenant_b, code="B", name="Torre B")
        Unit.objects.create(sector=cls.sector_a, code="A-101", unit_type=Unit.Type.APARTMENT)
        Unit.objects.create(sector=cls.sector_a, code="A-102", unit_type=Unit.Type.APARTMENT)
        Unit.objects.create(sector=cls.sector_b, code="B-201", unit_type=Unit.Type.APARTMENT)

        person_super = Person.objects.create(first_name="Super", last_name="Admin", document_number="9999")
        cls.superuser = User.objects.create_superuser(
            email="platform_admin@saas.app", password="Password123!", person=person_super, role=cls.role_admin
        )

        person_tenant = Person.objects.create(first_name="Admin", last_name="Local", document_number="8888")
        cls.tenant_admin = User.objects.create_user(
            email="admin_condo@saas.app",
            password="Password123!",
            person=person_tenant,
            role=cls.role_admin,
            is_approved=True,
        )
        TenantMembership.objects.create(
            user=cls.tenant_admin,
            condominium=cls.tenant_a,
            role=cls.role_admin,
            is_default=True,
            is_active=True,
        )

    def rows(self, response):
        return response.data.get("results", response.data)

    def by_name(self, response):
        return {row["name"]: row for row in self.rows(response)}

    # --- acceso ---------------------------------------------------------

    def test_superuser_sees_every_tenant(self):
        self.client.force_authenticate(user=self.superuser)

        response = self.client.get(self.LIST_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [row["name"] for row in self.rows(response)]
        self.assertIn("Condominio Taji", names)
        self.assertIn("Condominio Las Palmas", names)
        self.assertIn("Complejo En Pausa", names)

    def test_a_tenant_admin_cannot_see_the_platform_console(self):
        """El listado global no es lo mismo que `saas/tenants/`: exige Platform Admin."""
        self.client.force_authenticate(user=self.tenant_admin)

        response = self.client.get(self.LIST_URL)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_a_tenant_admin_cannot_read_the_summary_either(self):
        self.client.force_authenticate(user=self.tenant_admin)
        self.assertEqual(
            self.client.get(self.SUMMARY_URL).status_code, status.HTTP_403_FORBIDDEN
        )

    def test_anonymous_is_rejected(self):
        response = self.client.get(self.LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_the_endpoint_is_read_only(self):
        """No debe existir forma de crear o modificar tenants desde aquí."""
        self.client.force_authenticate(user=self.superuser)

        for method, url in (
            ("post", self.LIST_URL),
            ("put", self.LIST_URL),
            ("patch", self.LIST_URL),
            ("delete", f"{self.LIST_URL}{self.tenant_a.id}/"),
        ):
            response = getattr(self.client, method)(url, {}, format="json")
            self.assertIn(
                response.status_code,
                (status.HTTP_405_METHOD_NOT_ALLOWED, status.HTTP_404_NOT_FOUND),
                msg=f"{method.upper()} {url} deberia estar bloqueado",
            )

    # --- contenido ------------------------------------------------------

    def test_each_row_carries_identity_status_and_plan(self):
        self.client.force_authenticate(user=self.superuser)

        response = self.client.get(self.LIST_URL)

        row = self.by_name(response)["Condominio Taji"]
        self.assertEqual(row["id"], self.tenant_a.id)
        self.assertEqual(row["status"], "ACTIVE")
        self.assertTrue(row["is_active"])

        paused = self.by_name(response)["Complejo En Pausa"]
        self.assertEqual(paused["status"], "INACTIVE")
        self.assertFalse(paused["is_active"])

    def test_counts_are_computed_across_tenants(self):
        """Los contadores deben ignorar el aislamiento: es un listado global."""
        self.client.force_authenticate(user=self.superuser)

        rows = self.by_name(self.client.get(self.LIST_URL))

        self.assertEqual(rows["Condominio Taji"]["sectors_count"], 1)
        self.assertEqual(rows["Condominio Las Palmas"]["sectors_count"], 1)
        # Torre A tiene dos unidades y Torre B una.
        self.assertEqual(rows["Condominio Taji"]["units_count"], 2)
        self.assertEqual(rows["Condominio Las Palmas"]["units_count"], 1)

    def test_counts_are_not_confused_by_a_superuser_with_a_membership(self):
        """
        Regresión del aislamiento.

        `TenantResolver` solo activa el modo global cuando el superusuario no
        tiene membresías. Un admin de plataforma que además es miembro de un
        condominio queda con un tenant activo, y si la vista confiara en
        `TenantContext.is_global()` sus contadores saldrían en cero.
        """
        TenantMembership.objects.create(
            user=self.superuser,
            condominium=self.tenant_a,
            role=self.role_admin,
            is_default=True,
            is_active=True,
        )
        self.client.force_authenticate(user=self.superuser)

        rows = self.by_name(self.client.get(self.LIST_URL))

        self.assertEqual(rows["Condominio Taji"]["units_count"], 2)
        self.assertEqual(rows["Condominio Las Palmas"]["units_count"], 1)

    def test_membership_count_reflects_users_with_access(self):
        self.client.force_authenticate(user=self.superuser)

        rows = self.by_name(self.client.get(self.LIST_URL))

        self.assertEqual(rows["Condominio Taji"]["users_count"], 1)
        self.assertEqual(rows["Condominio Las Palmas"]["users_count"], 0)

    def test_a_tenant_without_subscription_is_reported_as_such(self):
        """No debe confundirse "sin plan" con "plan vencido"."""
        self.client.force_authenticate(user=self.superuser)

        row = self.by_name(self.client.get(self.LIST_URL))["Condominio Taji"]

        self.assertEqual(row["subscription_status"], "NO_SUBSCRIPTION")
        self.assertFalse(row["is_subscription_valid"])
        self.assertIsNone(row["days_left"])
        self.assertEqual(row["plan_name"], "")

    def test_subscription_details_are_included_when_present(self):
        from datetime import timedelta

        from django.utils import timezone as dj_timezone

        from tenancy.models import SubscriptionPlan, TenantSubscription

        plan = SubscriptionPlan.objects.create(
            code="basico", name="Esencial", price_bob=99, max_units=50
        )
        TenantSubscription.objects.create(
            condominium=self.tenant_a,
            plan=plan,
            status=TenantSubscription.Status.ACTIVE,
            current_period_end=dj_timezone.now() + timedelta(days=20),
        )
        self.client.force_authenticate(user=self.superuser)

        row = self.by_name(self.client.get(self.LIST_URL))["Condominio Taji"]

        self.assertEqual(row["plan_name"], "Esencial")
        self.assertEqual(row["subscription_status"], "ACTIVE")
        self.assertTrue(row["is_subscription_valid"])
        self.assertGreater(row["days_left"], 0)

    # --- filtros y resumen ----------------------------------------------

    def test_search_filters_by_name(self):
        self.client.force_authenticate(user=self.superuser)

        response = self.client.get(self.LIST_URL, {"search": "Palmas"})

        self.assertEqual([r["name"] for r in self.rows(response)], ["Condominio Las Palmas"])

    def test_filter_by_status(self):
        self.client.force_authenticate(user=self.superuser)

        response = self.client.get(self.LIST_URL, {"status": "INACTIVE"})

        self.assertEqual([r["name"] for r in self.rows(response)], ["Complejo En Pausa"])

    def test_filter_by_subscription_status_without_subscription(self):
        self.client.force_authenticate(user=self.superuser)

        response = self.client.get(self.LIST_URL, {"subscription_status": "NO_SUBSCRIPTION"})

        # Se compara contra la base y no contra un numero fijo: la migracion
        # `0003_seed_condominium` deja un condominio "Taji" en toda instalacion.
        self.assertEqual(len(self.rows(response)), Condominium.objects.count())

    def test_summary_totals_are_not_inflated_by_joins(self):
        """
        Regresión del fan-out de agregaciones.

        Al calcular totales sobre un queryset que ya tiene varios `Count` en
        joins distintos, `Count("id")` cuenta una fila por combinacion y el
        resultado puede superar el numero real de condominios.
        """
        self.client.force_authenticate(user=self.superuser)

        response = self.client.get(self.SUMMARY_URL)

        self.assertEqual(response.data["tenants"], Condominium.objects.count())
        self.assertEqual(response.data["active_tenants"], Condominium.objects.filter(is_active=True).count())
        self.assertEqual(response.data["units"], Unit.objects.count())
        self.assertEqual(
            response.data["active_tenants"] + response.data["inactive_tenants"],
            response.data["tenants"],
        )
        self.assertEqual(
            response.data["with_subscription"] + response.data["without_subscription"],
            response.data["tenants"],
        )

    def test_summary_totals_are_global_even_with_an_active_tenant(self):
        """Un admin con tenant activo debe seguir viendo el total de la plataforma."""
        TenantMembership.objects.create(
            user=self.superuser,
            condominium=self.tenant_a,
            role=self.role_admin,
            is_default=True,
            is_active=True,
        )
        self.client.force_authenticate(user=self.superuser)

        response = self.client.get(self.SUMMARY_URL)

        self.assertEqual(response.data["units"], Unit.objects.count())
        self.assertEqual(response.data["tenants"], Condominium.objects.count())

    def test_the_listing_does_not_run_one_query_per_tenant(self):
        """
        Los contadores vienen de anotaciones, no de una consulta por condominio.

        Con N tenants, la version ingenua haria 5N+1 consultas. Este test fija
        un techo para que nadie reintroduzca el N+1 al tocar la vista.
        """
        for index in range(6):
            condo = Condominium.objects.create(name=f"Edificio {index}", status="ACTIVE")
            sector = Sector.objects.create(condominium=condo, code=f"S{index}", name=f"S{index}")
            Unit.objects.create(sector=sector, code=f"U{index}", unit_type=Unit.Type.APARTMENT)

        self.client.force_authenticate(user=self.superuser)

        with self.assertNumQueries(4):
            # 1 resolver la membresia del admin, 1 total para paginar, 1 de
            # filas con los contadores agregados y 1 de la paginacion. Lo que
            # importa es que no crezca con el numero de condominios.
            self.client.get(self.LIST_URL)

    def test_ordering_is_accepted_and_unknown_fields_fall_back(self):
        self.client.force_authenticate(user=self.superuser)

        ok = self.client.get(self.LIST_URL, {"ordering": "-name"})
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        names = [r["name"] for r in self.rows(ok)]
        self.assertEqual(names, sorted(names, reverse=True))

        # Un campo no permitido no debe inyectar SQL ni romper la consulta.
        fallback = self.client.get(self.LIST_URL, {"ordering": "password"})
        self.assertEqual(fallback.status_code, status.HTTP_200_OK)
        fallback_names = [r["name"] for r in self.rows(fallback)]
        self.assertEqual(fallback_names, sorted(fallback_names))
