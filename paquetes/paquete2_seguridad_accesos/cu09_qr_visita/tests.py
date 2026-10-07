"""Pruebas para CU09 / T021: Generar y consultar el QR temporal de visita."""

import base64
from datetime import timedelta

from django.test import override_settings
from django.urls import resolve, reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Person, Role, SystemPermission, User
from auditlog.models import AuditEvent
from condominiums.models import Condominium, Resident, ResidentUnit, Sector, Unit
from security.models import VisitAuthorization
from security.qr import build_payload, hash_token, issue_visit_qr, parse_payload


class VisitQrBaseTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.perm_register, _ = SystemPermission.objects.get_or_create(
            code="register_visits", defaults={"name": "Registrar visitas", "module": "security"}
        )
        cls.perm_manage, _ = SystemPermission.objects.get_or_create(
            code="manage_visits", defaults={"name": "Gestionar visitas", "module": "security"}
        )

        cls.role_resident, _ = Role.objects.get_or_create(
            slug="residente", defaults={"name": "Copropietario / Residente"}
        )
        cls.role_resident.permissions.add(cls.perm_register)

        cls.role_admin, _ = Role.objects.get_or_create(
            slug="administrador", defaults={"name": "Administrador"}
        )
        cls.role_admin.permissions.add(cls.perm_manage)

        cls.role_guard, _ = Role.objects.get_or_create(
            slug="seguridad", defaults={"name": "Seguridad / Guardia"}
        )

        cls.role_guest, _ = Role.objects.get_or_create(
            slug="invitado-sin-permisos", defaults={"name": "Invitado"}
        )

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

        cls.person_res1 = Person.objects.create(
            first_name="Carlos", last_name="Mendoza", document_number="5544332"
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
        ResidentUnit.objects.create(
            resident=cls.resident1,
            unit=cls.unit_101,
            relation_type=ResidentUnit.Relation.OWNER,
            is_primary=True,
        )

        cls.person_res2 = Person.objects.create(
            first_name="Beatriz", last_name="Salazar", document_number="9988776"
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
        ResidentUnit.objects.create(
            resident=cls.resident2,
            unit=cls.unit_102,
            relation_type=ResidentUnit.Relation.TENANT,
            is_primary=True,
        )

        cls.person_admin = Person.objects.create(
            first_name="Admin", last_name="General", document_number="1122334"
        )
        cls.user_admin = User.objects.create_user(
            email="admin.taji@taji.test",
            password="ClaveSegura2026!",
            person=cls.person_admin,
            role=cls.role_admin,
            is_approved=True,
        )

        cls.user_no_perms = User.objects.create_user(
            email="sinpermiso@taji.test",
            password="ClaveSegura2026!",
            role=cls.role_guest,
            is_approved=True,
        )

        # Guard: rol sin ningún permiso de visitas, usado para probar el aislamiento.
        cls.user_guard = User.objects.create_user(
            email="guardia@taji.test",
            password="ClaveSegura2026!",
            role=cls.role_guard,
            is_approved=True,
        )

    def make_authorization(self, resident=None, unit=None, **overrides):
        now = timezone.now()
        seq = overrides.pop("seq", "00001")
        visitor = overrides.pop("visitor", None) or Person.objects.create(
            first_name="Mario", last_name="Gómez", document_number=f"77{seq}"
        )
        defaults = {
            "visitor_person": visitor,
            "authorized_by_resident": resident or self.resident1,
            "unit": unit or self.unit_101,
            "purpose": "Visita de prueba",
            "valid_from": now - timedelta(minutes=5),
            "valid_until": now + timedelta(hours=4),
            "qr_expires_at": now + timedelta(hours=4),
            "status": VisitAuthorization.Status.AUTHORIZED,
        }
        defaults.update(overrides)
        return VisitAuthorization.objects.create(**defaults)


class VisitQrGenerationTests(VisitQrBaseTestCase):
    """RF-09: generación de un QR único con vigencia limitada y fecha de expiración."""

    def test_resident_generates_qr_with_expiration_and_validity(self):
        self.client.force_authenticate(self.user_res1)
        authorization = self.make_authorization()

        response = self.client.post(
            reverse("visit-qr-generate", kwargs={"pk": authorization.pk})
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        body = response.data
        self.assertTrue(body["issued"])
        self.assertTrue(body["active"])
        self.assertFalse(body["rotated"])

        authorization.refresh_from_db()
        # Token persistido solo como hash: nunca en claro.
        self.assertIsNotNone(authorization.qr_token_hash)
        self.assertEqual(len(authorization.qr_token_hash), 64)
        self.assertIsNotNone(authorization.qr_issued_at)
        self.assertLess(authorization.qr_issued_at, authorization.qr_expires_at)
        self.assertLessEqual(authorization.qr_expires_at, authorization.valid_until)

        self.assertGreater(body["expires_in_seconds"], 0)
        self.assertEqual(body["payload"], build_payload(authorization.qr_uuid, self._token_of(body)))

    def test_qr_payload_and_image_are_returned(self):
        self.client.force_authenticate(self.user_res1)
        authorization = self.make_authorization()

        response = self.client.post(
            reverse("visit-qr-generate", kwargs={"pk": authorization.pk})
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        body = response.data
        payload = body["payload"]
        self.assertTrue(payload.startswith("TAJI1."))
        self.assertEqual(body["image_format"], "svg")
        self.assertEqual(body["image_media_type"], "image/svg+xml")

        decoded = base64.b64decode(body["image_base64"]).decode("utf-8")
        self.assertIn("<svg", decoded)

    def test_generated_qr_png_format(self):
        self.client.force_authenticate(self.user_res1)
        authorization = self.make_authorization()

        response = self.client.post(
            f"{reverse('visit-qr-generate', kwargs={'pk': authorization.pk})}?image_format=png"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["image_format"], "png")
        self.assertEqual(response.data["image_media_type"], "image/png")
        self.assertTrue(base64.b64decode(response.data["image_base64"]).startswith(b"\x89PNG"))

    def test_each_qr_token_is_unique(self):
        """El token del QR nunca se repite entre autorizaciones."""
        self.client.force_authenticate(self.user_res1)

        hashes = set()
        for index in range(5):
            authorization = self.make_authorization(seq=f"1000{index}")
            response = self.client.post(
                reverse("visit-qr-generate", kwargs={"pk": authorization.pk})
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            authorization.refresh_from_db()
            hashes.add(authorization.qr_token_hash)

        self.assertEqual(len(hashes), 5)

    def test_token_in_clear_is_never_persisted(self):
        """El texto del QR solo vive en la respuesta; en la BD queda su SHA-256."""
        self.client.force_authenticate(self.user_res1)
        authorization = self.make_authorization()

        response = self.client.post(
            reverse("visit-qr-generate", kwargs={"pk": authorization.pk})
        )
        token = self._token_of(response.data)

        authorization.refresh_from_db()
        self.assertNotEqual(authorization.qr_token_hash, token)
        self.assertEqual(authorization.qr_token_hash, hash_token(token))
        self.assertNotIn(token, authorization.qr_token_hash)

    def test_generation_is_idempotent_and_does_not_invalidate_current_qr(self):
        """Sin `force`, reemitir devuelve el QR vigente en vez de anularlo."""
        self.client.force_authenticate(self.user_res1)
        authorization = self.make_authorization()
        url = reverse("visit-qr-generate", kwargs={"pk": authorization.pk})

        first = self.client.post(url)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        authorization.refresh_from_db()
        first_hash = authorization.qr_token_hash

        second = self.client.post(url)
        self.assertEqual(second.status_code, status.HTTP_200_OK)

        authorization.refresh_from_db()
        self.assertEqual(authorization.qr_token_hash, first_hash)
        self.assertFalse(second.data["rotated"])

    def test_force_rotation_invalidates_previous_qr(self):
        """Con `force`, el QR anterior queda inutilizable (RF-09)."""
        self.client.force_authenticate(self.user_res1)
        authorization = self.make_authorization()
        url = reverse("visit-qr-generate", kwargs={"pk": authorization.pk})

        first = self.client.post(url)
        first_payload = first.data["payload"]
        first_token = parse_payload(first_payload).token
        authorization.refresh_from_db()
        first_hash = authorization.qr_token_hash

        second = self.client.post(url, {"force": True}, format="json")
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertTrue(second.data["rotated"])

        authorization.refresh_from_db()
        # El identificador público de la visita se mantiene; lo que rota es el token.
        self.assertNotEqual(authorization.qr_token_hash, first_hash)
        self.assertNotEqual(second.data["payload"], first_payload)
        self.assertNotEqual(parse_payload(second.data["payload"]).token, first_token)

    def test_audit_event_recorded_on_issue_and_rotation(self):
        self.client.force_authenticate(self.user_res1)
        authorization = self.make_authorization()
        url = reverse("visit-qr-generate", kwargs={"pk": authorization.pk})

        self.client.post(url)
        self.assertTrue(
            AuditEvent.objects.filter(
                action_code="VISIT_QR_ISSUED",
                resource_type="VisitAuthorization",
                resource_id=str(authorization.pk),
            ).exists()
        )

        self.client.post(url, {"force": True}, format="json")
        self.assertTrue(
            AuditEvent.objects.filter(
                action_code="VISIT_QR_ROTATED",
                resource_type="VisitAuthorization",
                resource_id=str(authorization.pk),
            ).exists()
        )

    @override_settings(VISIT_QR_TTL_MINUTES=60)
    def test_qr_expiry_is_capped_by_ttl_setting(self):
        self.client.force_authenticate(self.user_res1)
        # Visita abierta 4 horas: el QR debe durar solo 1 hora.
        authorization = self.make_authorization()

        response = self.client.post(
            reverse("visit-qr-generate", kwargs={"pk": authorization.pk})
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        authorization.refresh_from_db()
        self.assertLessEqual(
            authorization.qr_expires_at - authorization.qr_issued_at,
            timedelta(minutes=60) + timedelta(seconds=5),
        )

    @override_settings(VISIT_QR_TTL_MINUTES=60)
    def test_custom_ttl_respected_within_limits(self):
        self.client.force_authenticate(self.user_res1)
        authorization = self.make_authorization()

        response = self.client.post(
            reverse("visit-qr-generate", kwargs={"pk": authorization.pk}),
            {"ttl_minutes": 30},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        authorization.refresh_from_db()
        self.assertLessEqual(
            authorization.qr_expires_at - authorization.qr_issued_at,
            timedelta(minutes=30) + timedelta(seconds=5),
        )

    @override_settings(VISIT_QR_TTL_MINUTES=60, VISIT_QR_MAX_TTL_MINUTES=120)
    def test_ttl_above_maximum_is_rejected(self):
        self.client.force_authenticate(self.user_res1)
        authorization = self.make_authorization()

        response = self.client.post(
            reverse("visit-qr-generate", kwargs={"pk": authorization.pk}),
            {"ttl_minutes": 600},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("ttl_minutes", response.data["error"]["fields"])

    def test_cannot_generate_qr_for_visit_already_ended(self):
        """Una visita cuyo periodo ya Conclusionó no admite QR nuevo."""
        self.client.force_authenticate(self.user_res1)
        now = timezone.now()
        authorization = self.make_authorization(
            valid_from=now - timedelta(hours=3),
            valid_until=now - timedelta(hours=1),
            qr_expires_at=now - timedelta(hours=1),
        )

        response = self.client.post(
            reverse("visit-qr-generate", kwargs={"pk": authorization.pk})
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_generate_qr_for_cancelled_authorization(self):
        self.client.force_authenticate(self.user_res1)
        authorization = self.make_authorization(
            status=VisitAuthorization.Status.CANCELLED, cancelled_at=timezone.now()
        )

        response = self.client.post(
            reverse("visit-qr-generate", kwargs={"pk": authorization.pk})
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("status_not_allowed", response.data["error"]["fields"])

    def test_cancelled_authorization_reports_status_even_when_window_ended(self):
        """
        El estado es la causa estructural y debe ganar sobre la ventana vencida.

        Una autorización cancelada cuyo periodo además ya Conclusionó debe
        reportar `status_not_allowed`: informar "ventana no útil" induciría a
        pensar que basta con ampliar el horario, cuando la visita está cancelada
        y no se puede autorizar por más tiempo que se le dé.
        """
        self.client.force_authenticate(self.user_res1)
        now = timezone.now()
        authorization = self.make_authorization(
            status=VisitAuthorization.Status.CANCELLED,
            cancelled_at=now - timedelta(hours=2),
            valid_from=now - timedelta(days=2),
            valid_until=now - timedelta(days=1),
            qr_expires_at=now - timedelta(days=1),
        )

        response = self.client.post(
            reverse("visit-qr-generate", kwargs={"pk": authorization.pk})
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("status_not_allowed", response.data["error"]["fields"])

    def _token_of(self, body):
        return parse_payload(body["payload"]).token


class VisitQrConsultationTests(VisitQrBaseTestCase):
    """CU09: consulta del QR sin exponer el secreto en claro."""

    def setUp(self):
        super().setUp()
        self.authorization = self.make_authorization()

    def test_consult_reports_not_issued_before_generation(self):
        self.client.force_authenticate(self.user_res1)

        response = self.client.get(
            reverse("visit-qr-detail", kwargs={"pk": self.authorization.pk})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["issued"])
        self.assertIsNone(response.data["payload"])
        self.assertIsNone(response.data["image_base64"])

    def test_consult_reports_validity_and_expiration(self):
        self.client.force_authenticate(self.user_res1)
        self.client.post(reverse("visit-qr-generate", kwargs={"pk": self.authorization.pk}))

        response = self.client.get(
            reverse("visit-qr-detail", kwargs={"pk": self.authorization.pk})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["issued"])
        self.assertTrue(response.data["active"])
        self.assertGreater(response.data["expires_in_seconds"], 0)

        # La consulta nunca devuelve el contenido del QR.
        self.assertIsNone(response.data["payload"])
        self.assertIsNone(response.data["image_base64"])

        authorization_block = response.data["authorization"]
        self.assertIn("qr_expires_at", authorization_block)
        self.assertIn("visitor", authorization_block)
        self.assertIn("unit_detail", authorization_block)

    def test_consult_marks_qr_inactive_once_expired(self):
        self.client.force_authenticate(self.user_res1)
        self.client.post(reverse("visit-qr-generate", kwargs={"pk": self.authorization.pk}))

        expired_at = timezone.now() - timedelta(minutes=1)
        VisitAuthorization.objects.filter(pk=self.authorization.pk).update(qr_expires_at=expired_at)

        response = self.client.get(
            reverse("visit-qr-detail", kwargs={"pk": self.authorization.pk})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["issued"])
        self.assertFalse(response.data["active"])
        self.assertEqual(response.data["expires_in_seconds"], 0)

    def test_consult_marks_qr_inactive_when_visit_window_ended(self):
        """Al concluir la ventana, el QR queda inutilizable y se persiste EXPIRED."""
        self.client.force_authenticate(self.user_res1)
        self.client.post(reverse("visit-qr-generate", kwargs={"pk": self.authorization.pk}))

        now = timezone.now()
        VisitAuthorization.objects.filter(pk=self.authorization.pk).update(
            valid_until=now - timedelta(minutes=1), qr_expires_at=now - timedelta(minutes=1)
        )

        response = self.client.get(
            reverse("visit-qr-detail", kwargs={"pk": self.authorization.pk})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["active"])

        self.authorization.refresh_from_db()
        self.assertEqual(self.authorization.status, VisitAuthorization.Status.EXPIRED)


class VisitQrAccessControlTests(VisitQrBaseTestCase):
    """RN4: aislamiento de información y control por permiso."""

    def test_resident_cannot_manage_qr_of_another_resident(self):
        self.client.force_authenticate(self.user_res2)
        authorization = self.make_authorization(resident=self.resident1, unit=self.unit_101)

        url = reverse("visit-qr-detail", kwargs={"pk": authorization.pk})
        self.assertEqual(self.client.get(url).status_code, status.HTTP_404_NOT_FOUND)

        generate_url = reverse("visit-qr-generate", kwargs={"pk": authorization.pk})
        self.assertEqual(
            self.client.post(generate_url).status_code, status.HTTP_404_NOT_FOUND
        )

    def test_resident_manages_own_qr(self):
        self.client.force_authenticate(self.user_res2)
        authorization = self.make_authorization(resident=self.resident2, unit=self.unit_102)

        response = self.client.post(
            reverse("visit-qr-generate", kwargs={"pk": authorization.pk})
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_admin_can_consult_any_qr(self):
        self.client.force_authenticate(self.user_admin)
        authorization = self.make_authorization(resident=self.resident1, unit=self.unit_101)
        self.client.force_authenticate(self.user_res1)
        self.client.post(reverse("visit-qr-generate", kwargs={"pk": authorization.pk}))

        self.client.force_authenticate(self.user_admin)
        response = self.client.get(
            reverse("visit-qr-detail", kwargs={"pk": authorization.pk})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["issued"])

    def test_user_without_permission_is_forbidden(self):
        self.client.force_authenticate(self.user_no_perms)
        authorization = self.make_authorization()

        self.assertEqual(
            self.client.get(
                reverse("visit-qr-detail", kwargs={"pk": authorization.pk})
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(
                reverse("visit-qr-generate", kwargs={"pk": authorization.pk})
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_security_staff_cannot_issue_qr(self):
        """Validar (CU10) no habilita para emitir (CU09)."""
        self.client.force_authenticate(self.user_guard)
        authorization = self.make_authorization()

        response = self.client.post(
            reverse("visit-qr-generate", kwargs={"pk": authorization.pk})
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_is_unauthorized(self):
        authorization = self.make_authorization()
        response = self.client.get(
            reverse("visit-qr-detail", kwargs={"pk": authorization.pk})
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unknown_authorization_returns_404(self):
        self.client.force_authenticate(self.user_admin)
        response = self.client.get(reverse("visit-qr-detail", kwargs={"pk": 999999}))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_package_and_root_urls_resolve_identically(self):
        root_match = resolve("/api/v1/visit-qr/1/")
        pkg_match = resolve("/api/v1/paquete2/visit-qr/1/")
        self.assertIs(root_match.func.cls, pkg_match.func.cls)


class ExpireVisitQrsCommandTests(VisitQrBaseTestCase):
    """El barrido deja inutilizables los QR de visitas vencidas."""

    def test_command_expires_stale_authorizations(self):
        now = timezone.now()
        stale = self.make_authorization(
            valid_from=now - timedelta(hours=4),
            valid_until=now - timedelta(hours=2),
            qr_expires_at=now - timedelta(hours=2),
        )
        alive = self.make_authorization(seq="99999")

        from django.core.management import call_command

        call_command("expire_visit_qrs", stdout=None)

        stale.refresh_from_db()
        alive.refresh_from_db()
        self.assertEqual(stale.status, VisitAuthorization.Status.EXPIRED)
        self.assertEqual(alive.status, VisitAuthorization.Status.AUTHORIZED)

    def test_command_dry_run_does_not_modify(self):
        now = timezone.now()
        stale = self.make_authorization(
            valid_from=now - timedelta(hours=4),
            valid_until=now - timedelta(hours=2),
            qr_expires_at=now - timedelta(hours=2),
        )

        from django.core.management import call_command

        call_command("expire_visit_qrs", "--dry-run", stdout=None)

        stale.refresh_from_db()
        self.assertEqual(stale.status, VisitAuthorization.Status.AUTHORIZED)


class IssueVisitQrServiceTests(VisitQrBaseTestCase):
    """Pruebas del servicio de dominio, sin pasar por HTTP."""

    def test_issue_keeps_uuid_and_rotates_token(self):
        authorization = self.make_authorization()
        previous_uuid = authorization.qr_uuid
        previous_hash = authorization.qr_token_hash

        authorization, token = issue_visit_qr(authorization)

        # `qr_uuid` es el identificador público de la visita y no rota.
        self.assertEqual(authorization.qr_uuid, previous_uuid)
        self.assertNotEqual(authorization.qr_token_hash, previous_hash)
        self.assertEqual(authorization.qr_token_hash, hash_token(token))
        self.assertTrue(authorization.is_qr_issued())
        self.assertTrue(authorization.is_qr_active())

        authorization.refresh_from_db()
        self.assertEqual(authorization.qr_token_hash, hash_token(token))

    def test_issue_respects_visit_window_upper_bound(self):
        now = timezone.now()
        authorization = self.make_authorization(
            valid_from=now - timedelta(minutes=1),
            valid_until=now + timedelta(minutes=10),
            qr_expires_at=now + timedelta(minutes=10),
        )

        # Se piden 240 minutos pero la visita solo admite 10.
        authorization, _token = issue_visit_qr(authorization, ttl_minutes=240)

        self.assertLessEqual(authorization.qr_expires_at, authorization.valid_until)