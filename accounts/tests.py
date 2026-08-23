from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core import mail
from django.test import override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from .models import LoginAttempt, Role, SystemPermission, User


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
        self.assertEqual(response.data["detail"], "Intento fallido. Te quedan 4 intentos.")

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
