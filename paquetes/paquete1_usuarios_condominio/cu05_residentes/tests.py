"""
Pruebas de las credenciales de acceso entregadas al registrarse un residente.

Cubre el flujo completo de alto: se crea la cuenta, se emite una contraseña
temporal que obliga a cambiarla, y se envía la invitación por correo con el
enlace de activación. También verifica el caso que en producción pasaba
desapercibido: el SMTP sin configurar, que antes se reportaba como "correo
enviado" sin salir nunca nada.
"""

from django.core import mail
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.invitations import generate_temporary_password, is_smtp_configured
from accounts.models import Person, Role, SystemPermission, User
from condominiums.models import Condominium
from tenancy.context import TenantContext
from tenancy.models import TenantMembership


class ResidentInvitationBaseTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.perm_manage, _ = SystemPermission.objects.get_or_create(
            code="manage_residents", defaults={"name": "Gestionar residentes", "module": "users"}
        )
        cls.role_admin, _ = Role.objects.get_or_create(
            slug="administrador", defaults={"name": "Administrador"}
        )
        cls.role_admin.permissions.add(cls.perm_manage)

        cls.role_resident, _ = Role.objects.get_or_create(
            slug="residente", defaults={"name": "Residente"}
        )

        cls.condo = Condominium.objects.create(name="Condominio Los Pinos")

        cls.person_admin = Person.objects.create(
            first_name="Admin", last_name="General", document_number="1122334"
        )
        cls.user_admin = User.objects.create_user(
            email="admin@taji.test",
            password="ClaveSegura2026!",
            person=cls.person_admin,
            role=cls.role_admin,
            is_approved=True,
        )
        TenantMembership.objects.create(
            user=cls.user_admin,
            condominium=cls.condo,
            role=cls.role_admin,
            is_active=True,
            is_default=True,
        )

    def setUp(self):
        self.list_url = reverse("resident-list")
        self.tenant_scope = TenantContext.for_tenant(self.condo)
        self.tenant_scope.__enter__()
        self.addCleanup(self.tenant_scope.__exit__, None, None, None)
        mail.outbox = []

    @staticmethod
    def payload(email="residente@taji.test", document="9988776", **extra):
        data = {
            "first_name": "Sofía",
            "last_name": "Reyes",
            "document_type": "CI",
            "document_number": document,
            "phone": "70000000",
            "contact_email": email,
            "status": "ACTIVE",
        }
        data.update(extra)
        return data

    def create_resident(self, **extra):
        """Registra un residente y deja al administrador autenticado."""
        self.client.force_authenticate(self.user_admin)
        return self.client.post(self.list_url, self.payload(**extra), format="json")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ResidentInvitationTests(ResidentInvitationBaseTestCase):
    def test_creating_a_resident_creates_the_account_with_a_temporary_password(self):
        response = self.create_resident()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = User.objects.get(email="residente@taji.test")
        self.assertTrue(user.must_change_password)
        self.assertTrue(user.has_usable_password())
        self.assertEqual(user.role.slug, "residente")

    def test_the_temporary_password_actually_lets_the_resident_log_in(self):
        """La clave entregada por correo no es decorativa: debe autenticar."""
        self.create_resident()
        temporary_password = extract_temporary_password(mail.outbox[-1])

        self.client.force_authenticate(None)
        response = self.client.post(
            reverse("accounts:login"),
            {"email": "residente@taji.test", "password": temporary_password, "client": "web"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["must_change_password"])

    def test_login_reports_that_a_password_change_is_required(self):
        self.create_resident()
        temporary_password = extract_temporary_password(mail.outbox[-1])

        self.client.force_authenticate(None)
        response = self.client.post(
            reverse("accounts:login"),
            {"email": "residente@taji.test", "password": temporary_password, "client": "web"},
            format="json",
        )

        self.assertTrue(response.data["must_change_password"])
        self.assertTrue(response.data["user"]["must_change_password"])
        self.assertIn("contraseña temporal", response.data["message"])

    def test_invitation_email_carries_both_the_link_and_the_temporary_password(self):
        self.create_resident()

        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn("Condominio Los Pinos", mail.outbox[0].subject)
        # Enlace de activación para que defina su propia clave.
        self.assertIn("invite=1", body)
        # Clave temporal para poder entrar el mismo día.
        self.assertIn("Contraseña temporal", body)

    def test_response_never_exposes_the_temporary_password(self):
        """La clave solo viaja por correo, nunca en la respuesta de la API."""
        response = self.create_resident()

        invitation = response.data["invitation"]
        self.assertNotIn(extract_temporary_password(mail.outbox[-1]), str(response.data))
        # Solo se informa que se emitió, nunca su valor.
        self.assertNotIn("temporary_password", invitation)
        self.assertTrue(invitation["temporary_password_issued"])
        self.assertTrue(invitation["email_sent"])

    def test_membership_is_created_for_the_new_resident(self):
        self.create_resident()

        user = User.objects.get(email="residente@taji.test")
        self.assertTrue(
            TenantMembership.objects.filter(user=user, condominium=self.condo).exists()
        )

    def test_resident_without_email_is_created_without_credentials(self):
        response = self.create_resident(email="")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(User.objects.filter(email="").exists())
        self.assertEqual(mail.outbox, [])

    def test_the_temporary_password_is_never_returned_to_the_operator(self):
        """La UI solo necesita saber que se emitió, no cuál fue."""
        response = self.create_resident()

        self.assertTrue(response.data["invitation"]["temporary_password_issued"])
        self.assertNotIn("temporary_password", response.data["invitation"])


class ResidentInvitationWithoutSmtpTests(ResidentInvitationBaseTestCase):
    """Sin SMTP configurado el correo no sale: hay que decirlo, no tragárselo."""

    def setUp(self):
        super().setUp()
        # Es exactamente el estado del VPS: backend de consola por defecto.
        self.override = override_settings(
            EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend"
        )
        self.override.enable()
        self.addCleanup(self.override.disable)

    def test_console_backend_is_detected_as_not_configured(self):
        self.assertFalse(is_smtp_configured())

    def test_resident_is_created_even_though_the_email_cannot_be_sent(self):
        response = self.create_resident()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(email="residente@taji.test").exists())

    def test_the_response_says_the_email_was_not_sent(self):
        response = self.create_resident()

        self.assertFalse(response.data["invitation"]["email_sent"])
        self.assertIn("SMTP", response.data["invitation"]["detail"])

    def test_resend_invitation_reports_the_failure_instead_of_faking_success(self):
        resident_response = self.create_resident()
        resident_id = resident_response.data["id"]

        self.client.force_authenticate(self.user_admin)
        response = self.client.post(
            reverse("resident-resend-invitation", args=[resident_id]), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(response.data["error"]["code"], "email_delivery_failed")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ResendInvitationTests(ResidentInvitationBaseTestCase):
    def setUp(self):
        super().setUp()

    def test_resending_activates_an_account_and_sends_the_link(self):
        resident_id = self.create_resident().data["id"]
        user = User.objects.get(email="residente@taji.test")
        mail.outbox = []

        response = self.client.post(
            reverse("resident-resend-invitation", args=[resident_id]), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["email_sent"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("invite=1", mail.outbox[0].body)

        # Una cuenta que ya cambió su clave no debe verla reemplazada.
        user.refresh_from_db()
        self.assertFalse(response.data["temporary_password_issued"])

    def test_resending_without_email_is_rejected(self):
        resident_id = self.create_resident(email="").data["id"]

        response = self.client.post(
            reverse("resident-resend-invitation", args=[resident_id]), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_user_without_permission_cannot_resend(self):
        resident_id = self.create_resident().data["id"]
        self.client.force_authenticate(User.objects.create_user(
            email="sinpermiso@taji.test",
            password="ClaveSegura2026!",
            role=Role.objects.get_or_create(
                slug="invitado-sin-permisos", defaults={"name": "Invitado"}
            )[0],
            is_approved=True,
        ))

        response = self.client.post(
            reverse("resident-resend-invitation", args=[resident_id]), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TemporaryPasswordGeneratorTests(APITestCase):
    def test_password_meets_the_project_password_validators(self):
        """Debe superar MinimumLength(10), NumericPassword y CommonPassword."""
        from django.contrib.auth import password_validation

        for _ in range(50):
            password = generate_temporary_password()
            self.assertGreaterEqual(len(password), 10)
            try:
                password_validation.validate_password(password)
            except Exception as exc:  # noqa: BLE001
                self.fail(f"Contraseña temporal inválida: {password} ({exc})")

    def test_password_is_not_repeated(self):
        generated = {generate_temporary_password() for _ in range(50)}
        self.assertEqual(len(generated), 50)

    def test_password_contains_every_required_class(self):
        password = generate_temporary_password()
        self.assertTrue(any(c.islower() for c in password))
        self.assertTrue(any(c.isupper() for c in password))
        self.assertTrue(any(c.isdigit() for c in password))
        self.assertTrue(any(not c.isalnum() for c in password))


def extract_temporary_password(message) -> str:
    """
    Recupera la clave temporal del correo para poder probar el inicio de sesión.

    Se relee el texto en vez de interceptar `set_password`: así la prueba
    verifica lo que el residente realmente recibe en su bandeja.
    """
    lines = [line.strip() for line in message.body.splitlines()]
    for index, line in enumerate(lines):
        if line.startswith("Contraseña temporal"):
            for candidate in lines[index + 1 :]:
                if candidate:
                    return candidate
    raise AssertionError("No se encontró la contraseña temporal en el correo.")
