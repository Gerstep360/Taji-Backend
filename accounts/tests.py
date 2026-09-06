from django.conf import settings
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from config.api import TajiPageNumberPagination
from condominiums.models import Resident, ResidentUnit, Unit
from .models import LoginAttempt, Person, Role, SystemPermission, User
from .rbac import ROLE_DEFINITIONS


PASSWORD = "TajiSeguro2026!"


class AuthApiTests(APITestCase):
    def setUp(self):
        self.role = Role.objects.get(slug="residente")
        self.user = User.objects.create_user(
            email="ana@example.com",
            password=PASSWORD,
            first_name="Ana",
            last_name="Rojas",
            role=self.role,
        )

    def test_rbac_catalog_is_seeded(self):
        self.assertEqual(Role.objects.count(), 7)
        self.assertEqual(SystemPermission.objects.count(), 33)
        self.assertTrue(self.role.is_public)
        self.assertFalse(Role.objects.get(slug="administrador").is_public)

    def test_public_registration_always_assigns_resident_role(self):
        response = self.client.post(
            "/api/v1/auth/register/",
            {
                "email": "nuevo@example.com",
                "first_name": "Nuevo",
                "last_name": "Residente",
                "phone": "+59170000000",
                "password": PASSWORD,
                "password_confirm": PASSWORD,
                "role": "administrador",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(User.objects.get(email="nuevo@example.com").role.slug, "residente")

    def test_registration_rejects_duplicate_email_case_insensitively(self):
        response = self.client.post(
            "/api/v1/auth/register/",
            {
                "email": "ANA@example.com",
                "first_name": "Otra",
                "last_name": "Persona",
                "password": PASSWORD,
                "password_confirm": PASSWORD,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertEqual(
            response.data["error"]["fields"]["email"],
            [
                "Este correo ya tiene una cuenta. Inicia sesión o recupera tu "
                "contraseña."
            ],
        )

    def test_registration_validation_has_uniform_field_errors(self):
        response = self.client.post(
            "/api/v1/auth/register/",
            {
                "email": "correo-invalido",
                "first_name": "A",
                "last_name": "",
                "phone": "abc",
                "password": "corta",
                "password_confirm": "distinta",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "error": {
                    "code": "validation_error",
                    "message": "Revisa los campos indicados.",
                    "fields": response.data["error"]["fields"],
                }
            },
        )
        self.assertTrue(
            {"email", "first_name", "last_name", "phone", "password"}.issubset(
                response.data["error"]["fields"]
            )
        )

    def test_mobile_login_returns_tokens_and_bearer_opens_profile(self):
        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": "ANA@example.com", "password": PASSWORD, "client": "mobile"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        access = response.data["tokens"]["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        me = self.client.get("/api/v1/auth/me/")
        self.assertEqual(me.status_code, status.HTTP_200_OK)
        self.assertEqual(me.data["user"]["role"]["slug"], "residente")

    def test_me_includes_resident_units_and_linked_residents(self):
        linked_person = Person.objects.create(first_name="Luis", last_name="Vinculado")
        linked_resident = Resident.objects.create(person=linked_person)
        resident = Resident.objects.create(person=self.user.person)
        unit = Unit.objects.create(code="ME-001", unit_type=Unit.Type.APARTMENT)
        ResidentUnit.objects.create(
            resident=resident,
            unit=unit,
            relation_type=ResidentUnit.Relation.OWNER,
            is_primary=True,
        )
        ResidentUnit.objects.create(
            resident=linked_resident,
            unit=unit,
            relation_type=ResidentUnit.Relation.FAMILY,
        )
        self.client.force_authenticate(self.user)

        response = self.client.get("/api/v1/auth/me/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["resident_units"][0]["unit_code"], "ME-001")
        self.assertEqual(response.data["resident_units"][0]["is_primary"], True)
        self.assertEqual(response.data["linked_residents"][0]["full_name"], "Luis Vinculado")

    def test_web_login_uses_httponly_cookies_and_no_tokens_in_body(self):
        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": self.user.email, "password": PASSWORD, "client": "web"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("tokens", response.data)
        self.assertTrue(response.cookies["taji_access"]["httponly"])
        self.assertTrue(response.cookies["taji_refresh"]["httponly"])
        me = self.client.get("/api/v1/auth/me/")
        self.assertEqual(me.status_code, status.HTTP_200_OK)

    def test_refresh_rotates_and_blacklists_previous_token(self):
        refresh = str(RefreshToken.for_user(self.user))
        first = self.client.post(
            "/api/v1/auth/refresh/",
            {"refresh": refresh, "client": "mobile"},
            format="json",
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertIn("refresh", first.data["tokens"])
        reused = self.client.post(
            "/api/v1/auth/refresh/",
            {"refresh": refresh, "client": "mobile"},
            format="json",
        )
        self.assertEqual(reused.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_blacklists_mobile_refresh(self):
        refresh = str(RefreshToken.for_user(self.user))
        response = self.client.post("/api/v1/auth/logout/", {"refresh": refresh}, format="json")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        renewed = self.client.post(
            "/api/v1/auth/refresh/", {"refresh": refresh, "client": "mobile"}, format="json"
        )
        self.assertEqual(renewed.status_code, status.HTTP_401_UNAUTHORIZED)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_forgot_password_is_generic_and_sends_only_for_existing_user(self):
        existing = self.client.post(
            "/api/v1/auth/forgot-password/", {"email": self.user.email}, format="json"
        )
        missing = self.client.post(
            "/api/v1/auth/forgot-password/", {"email": "missing@example.com"}, format="json"
        )
        self.assertEqual(existing.data["message"], missing.data["message"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("uid=", mail.outbox[0].body)

    def test_password_reset_changes_password_and_invalidates_token(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        response = self.client.post(
            "/api/v1/auth/reset-password/",
            {
                "uid": uid,
                "token": token,
                "password": "NuevaClave2026!",
                "password_confirm": "NuevaClave2026!",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NuevaClave2026!"))
        reused = self.client.post(
            "/api/v1/auth/reset-password/",
            {
                "uid": uid,
                "token": token,
                "password": "OtraClave2026!",
                "password_confirm": "OtraClave2026!",
            },
            format="json",
        )
        self.assertEqual(reused.status_code, status.HTTP_400_BAD_REQUEST)

    def test_wrong_credentials_return_generic_error(self):
        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": self.user.email, "password": "incorrecta", "client": "mobile"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error"]["code"], "authentication_failed")
        self.assertNotIn("email", response.data["error"]["message"].lower())

    def test_unknown_email_keeps_generic_login_error(self):
        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": "missing@example.com", "password": "incorrecta", "client": "mobile"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            response.data["detail"],
            "Usuario no encontrado o no registrado. Regístrate para continuar.",
        )

    def test_fifth_failed_login_locks_account_for_thirty_minutes(self):
        cache.clear()
        payload = {"email": self.user.email, "password": "incorrecta", "client": "web"}

        for attempt in range(4):
            response = self.client.post("/api/v1/auth/login/", payload, format="json")
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED, attempt)

        fifth = self.client.post("/api/v1/auth/login/", payload, format="json")
        self.assertEqual(fifth.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(fifth["Retry-After"], "1800")

        self.assertEqual(fifth.data["error"]["code"], "throttled")
        valid = self.client.post(
            "/api/v1/auth/login/",
            {"email": self.user.email, "password": PASSWORD, "client": "web"},
            format="json",
        )
        self.assertEqual(valid.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(LoginAttempt.objects.filter(user=self.user, was_successful=False).count(), 5)

    def test_openapi_and_swagger_are_available(self):
        schema = self.client.get("/api/v1/openapi/")
        docs = self.client.get("/api/v1/docs/")
        self.assertEqual(schema.status_code, status.HTTP_200_OK)
        self.assertEqual(docs.status_code, status.HTTP_200_OK)
        self.assertIn(b"/api/v1/auth/register/", schema.content)
        self.assertIn(b"RegisterResponse", schema.content)

    def test_unknown_api_route_has_uniform_error(self):
        response = self.client.get("/api/v1/auth/no-existe/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_default_pagination_contract(self):
        request = Request(
            APIRequestFactory().get("/api/v1/items/?page=2&page_size=2")
        )
        paginator = TajiPageNumberPagination()
        page = paginator.paginate_queryset(list(range(5)), request)
        response = paginator.get_paginated_response(page)
        self.assertEqual(response.data["results"], [2, 3])
        metadata = response.data["pagination"]
        self.assertEqual(metadata["page"], 2)
        self.assertEqual(metadata["page_size"], 2)
        self.assertEqual(metadata["total_items"], 5)
        self.assertEqual(metadata["total_pages"], 3)

    def test_lan_origin_is_accepted_in_debug(self):
        response = self.client.options(
            "/api/v1/auth/register/",
            HTTP_ORIGIN="http://192.168.50.77:4200",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        )
        self.assertEqual(
            response.headers["access-control-allow-origin"],
            "http://192.168.50.77:4200",
        )

    def test_registration_creates_user_and_person(self):
        response = self.client.post(
            "/api/v1/auth/register/",
            {
                "email": "test_person@example.com",
                "first_name": "Juan",
                "last_name": "Perez",
                "phone": "70001234",
                "password": PASSWORD,
                "password_confirm": PASSWORD,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("user", response.data)
        self.assertEqual(response.data["user"]["first_name"], "Juan")
        self.assertEqual(response.data["user"]["last_name"], "Perez")
        self.assertEqual(response.data["user"]["phone"], "70001234")

        user = User.objects.get(email="test_person@example.com")
        self.assertIsNotNone(user.person)
        self.assertEqual(user.person.first_name, "Juan")
        self.assertEqual(user.person.last_name, "Perez")
        self.assertEqual(user.person.phone, "70001234")

    def test_full_name_property_works(self):
        self.assertEqual(self.user.full_name, "Ana Rojas")

    def test_create_user_and_createsuperuser_managers(self):
        u = User.objects.create_user(
            email="manager_user@example.com",
            password=PASSWORD,
            first_name="User",
            last_name="Manager",
            phone="789",
            role=self.role,
        )
        self.assertIsNotNone(u.person)
        self.assertEqual(u.person.first_name, "User")
        self.assertEqual(u.person.last_name, "Manager")
        self.assertEqual(u.person.phone, "789")

        su = User.objects.create_superuser(
            email="superuser_manager@example.com",
            password=PASSWORD,
            first_name="Super",
            last_name="User",
        )
        self.assertTrue(su.is_superuser)
        self.assertTrue(su.is_staff)
        self.assertIsNotNone(su.person)
        self.assertEqual(su.person.first_name, "Super")
        self.assertEqual(su.person.last_name, "User")

    def test_updating_personal_data_modifies_person(self):
        self.user.person.first_name = "Ana Maria"
        self.user.person.save()

        self.assertEqual(self.user.first_name, "Ana Maria")

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Ana Maria")

    def test_merged_backend_configuration_is_present(self):
        expected_apps = {
            "accounts.apps.AccountsConfig",
            "condominiums.apps.CondominiumsConfig",
            "auditlog.apps.AuditlogConfig",
            "security.apps.SecurityConfig",
            "incidents.apps.IncidentsConfig",
            "maintenance.apps.MaintenanceConfig",
            "community.apps.CommunityConfig",
            "notifications.apps.NotificationsConfig",
        }
        self.assertTrue(expected_apps.issubset(settings.INSTALLED_APPS))
        self.assertEqual(
            settings.DATABASES["default"]["ENGINE"],
            "django.db.backends.postgresql",
        )
        self.assertEqual(
            settings.REST_FRAMEWORK["EXCEPTION_HANDLER"],
            "config.api.taji_exception_handler",
        )
        self.assertEqual(
            settings.REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"],
            "drf_spectacular.openapi.AutoSchema",
        )

    def test_initial_roles_fixture_matches_the_merged_rbac_catalog(self):
        call_command("loaddata", "initial_roles", verbosity=0)
        self.assertEqual(Role.objects.count(), len(ROLE_DEFINITIONS))
        self.assertEqual(SystemPermission.objects.count(), 33)
        for slug, definition in ROLE_DEFINITIONS.items():
            role = Role.objects.get(slug=slug)
            self.assertEqual(role.name, definition["name"])
            self.assertEqual(
                set(role.permissions.values_list("code", flat=True)),
                set(definition["permissions"]),
            )

    def test_manage_roles_permission_exists_in_catalog(self):
        self.assertTrue(SystemPermission.objects.filter(code="manage_roles").exists())
        admin_role = Role.objects.get(slug="administrador")
        self.assertIn("manage_roles", admin_role.permissions.values_list("code", flat=True))

    def test_admin_keeps_all_merged_models_and_secure_user_admin(self):
        for model in (Person, Role, SystemPermission, User, LoginAttempt):
            self.assertIn(model, admin.site._registry)
        self.assertIsInstance(admin.site._registry[User], BaseUserAdmin)

        superuser = User.objects.create_superuser(
            email="admin@example.com", password=PASSWORD
        )
        self.client.force_login(superuser)
        for name in (
            "admin:index",
            "admin:accounts_person_changelist",
            "admin:accounts_user_changelist",
            "admin:accounts_user_add",
            "admin:accounts_loginattempt_changelist",
        ):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)


class RegistrationSecurityTests(APITestCase):
    """
    RN5–RN7: El registro público solo crea Residentes pendientes.
    No puede escalarse a ningún otro rol.
    """

    REGISTER_URL = "/api/v1/auth/register/"
    BASE_PAYLOAD = {
        "email": "nuevo_residente@test.com",
        "first_name": "Nuevo",
        "last_name": "Residente",
        "password": PASSWORD,
        "password_confirm": PASSWORD,
    }

    def setUp(self):
        cache.clear()  # Reset throttle counters between tests

    def test_public_registration_creates_pending_user(self):
        """RN5: El registro público crea usuario con is_approved=False."""
        resp = self.client.post(self.REGISTER_URL, self.BASE_PAYLOAD, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email="nuevo_residente@test.com")
        self.assertFalse(user.is_approved)
        self.assertEqual(user.role.slug, "residente")

    def test_pending_user_has_no_effective_permissions(self):
        """RN5: Usuario pendiente no tiene permisos efectivos, independientemente del rol."""
        self.client.post(self.REGISTER_URL, self.BASE_PAYLOAD, format="json")
        user = User.objects.get(email="nuevo_residente@test.com")
        for perm in ["register_visits", "view_own_data", "reserve_areas"]:
            self.assertFalse(user.has_system_permission(perm), perm)

    def test_pending_user_cannot_create_invitations(self):
        """RN5 + RN3: Usuario pendiente no puede crear invitaciones (register_visits)."""
        self.client.post(self.REGISTER_URL, self.BASE_PAYLOAD, format="json")
        user = User.objects.get(email="nuevo_residente@test.com")
        self.assertFalse(user.has_system_permission("register_visits"))

    def test_pending_user_cannot_access_cu2(self):
        """RN5: Usuario pendiente autenticado recibe 403 en endpoint de CU2."""
        self.client.post(self.REGISTER_URL, self.BASE_PAYLOAD, format="json")
        user = User.objects.get(email="nuevo_residente@test.com")
        self.client.force_authenticate(user=user)
        self.assertEqual(self.client.get("/api/v1/roles/").status_code, status.HTTP_403_FORBIDDEN)

    def test_public_registration_ignores_role_administrador(self):
        """RN5: Enviar role=administrador no escala privilegios."""
        payload = {**self.BASE_PAYLOAD, "role": "administrador", "email": "escalada1@test.com"}
        self.client.post(self.REGISTER_URL, payload, format="json")
        user = User.objects.filter(email="escalada1@test.com").first()
        if user:
            self.assertEqual(user.role.slug, "residente")
            self.assertFalse(user.is_approved)

    def test_public_registration_ignores_role_directiva(self):
        """RN5: Enviar role=directiva no escala privilegios."""
        payload = {**self.BASE_PAYLOAD, "role": "directiva", "email": "escalada2@test.com"}
        self.client.post(self.REGISTER_URL, payload, format="json")
        user = User.objects.filter(email="escalada2@test.com").first()
        if user:
            self.assertEqual(user.role.slug, "residente")
            self.assertFalse(user.is_approved)

    def test_public_registration_ignores_role_seguridad(self):
        """RN5: Enviar role=seguridad no escala privilegios."""
        payload = {**self.BASE_PAYLOAD, "role": "seguridad", "email": "escalada3@test.com"}
        self.client.post(self.REGISTER_URL, payload, format="json")
        user = User.objects.filter(email="escalada3@test.com").first()
        if user:
            self.assertEqual(user.role.slug, "residente")
            self.assertFalse(user.is_approved)

    def test_public_registration_ignores_role_mantenimiento(self):
        """RN5: Enviar role=mantenimiento no escala privilegios."""
        payload = {**self.BASE_PAYLOAD, "role": "mantenimiento", "email": "escalada4@test.com"}
        self.client.post(self.REGISTER_URL, payload, format="json")
        user = User.objects.filter(email="escalada4@test.com").first()
        if user:
            self.assertEqual(user.role.slug, "residente")
            self.assertFalse(user.is_approved)
