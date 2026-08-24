from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken


from config.api import TajiPageNumberPagination
from .models import LoginAttempt,Person, Role, SystemPermission, User


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
        self.assertEqual(SystemPermission.objects.count(), 32)
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

