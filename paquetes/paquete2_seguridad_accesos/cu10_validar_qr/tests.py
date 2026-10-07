"""Pruebas para CU10 / T022: Validar la autorización de visitante mediante QR."""

from datetime import timedelta

from django.urls import resolve, reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Person, Role, SystemPermission, User
from auditlog.models import AuditEvent
from condominiums.models import Condominium, Resident, ResidentUnit, Sector, Staff, Unit
from security.models import AccessEvent, VisitAuthorization
from security.qr import issue_visit_qr


class VisitQrValidationBaseTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.perm_validate, _ = SystemPermission.objects.get_or_create(
            code="validate_visits", defaults={"name": "Validar visitas", "module": "security"}
        )
        cls.perm_register, _ = SystemPermission.objects.get_or_create(
            code="register_visits", defaults={"name": "Registrar visitas", "module": "security"}
        )
        cls.perm_manage, _ = SystemPermission.objects.get_or_create(
            code="manage_visits", defaults={"name": "Gestionar visitas", "module": "security"}
        )

        cls.role_guard, _ = Role.objects.get_or_create(
            slug="seguridad", defaults={"name": "Seguridad / Guardia"}
        )
        cls.role_guard.permissions.add(cls.perm_validate)

        cls.role_resident, _ = Role.objects.get_or_create(
            slug="residente", defaults={"name": "Copropietario / Residente"}
        )
        cls.role_resident.permissions.add(cls.perm_register)

        cls.role_admin, _ = Role.objects.get_or_create(
            slug="administrador", defaults={"name": "Administrador"}
        )
        cls.role_admin.permissions.add(cls.perm_manage, cls.perm_validate)

        cls.role_guest, _ = Role.objects.get_or_create(
            slug="invitado-sin-permisos", defaults={"name": "Invitado"}
        )

        cls.condo = Condominium.objects.create(name="Condominio Los Pinos")
        cls.sector = Sector.objects.create(
            condominium=cls.condo, code="TORRE-A", name="Torre A"
        )
        cls.unit = Unit.objects.create(
            sector=cls.sector, code="A-101", unit_type=Unit.Type.APARTMENT
        )

        # Residente autorizante
        cls.person_resident = Person.objects.create(
            first_name="Carlos", last_name="Mendoza", document_number="5544332"
        )
        cls.resident = Resident.objects.create(
            person=cls.person_resident, status=Resident.Status.ACTIVE
        )
        ResidentUnit.objects.create(
            resident=cls.resident,
            unit=cls.unit,
            relation_type=ResidentUnit.Relation.OWNER,
            is_primary=True,
        )

        # Guardia activo
        cls.person_guard = Person.objects.create(
            first_name="Luis", last_name="Roca", document_number="7711223"
        )
        cls.guard = Staff.objects.create(
            person=cls.person_guard,
            staff_type=Staff.Type.SECURITY,
            status=Staff.Status.ACTIVE,
        )
        cls.user_guard = User.objects.create_user(
            email="guardia@taji.test",
            password="ClaveSegura2026!",
            person=cls.person_guard,
            role=cls.role_guard,
            is_approved=True,
        )

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

        cls.person_resident_user = Person.objects.create(
            first_name="Residente", last_name="App", document_number="4455667"
        )
        Resident.objects.create(person=cls.person_resident_user)
        cls.user_resident = User.objects.create_user(
            email="residente@taji.test",
            password="ClaveSegura2026!",
            person=cls.person_resident_user,
            role=cls.role_resident,
            is_approved=True,
        )

        cls.user_no_perms = User.objects.create_user(
            email="sinpermiso@taji.test",
            password="ClaveSegura2026!",
            role=cls.role_guest,
            is_approved=True,
        )

    def setUp(self):
        self.validate_url = reverse("visit-qr-validate")

    def make_authorization(self, visitor_name="Mario Gómez", document="7700001", **overrides):
        now = timezone.now()
        visitor = Person.objects.create(
            first_name=visitor_name.split()[0],
            last_name=" ".join(visitor_name.split()[1:]),
            document_number=document,
        )
        defaults = {
            "visitor_person": visitor,
            "authorized_by_resident": self.resident,
            "unit": self.unit,
            "purpose": "Almuerzo familiar",
            "valid_from": now - timedelta(minutes=5),
            "valid_until": now + timedelta(hours=4),
            "qr_expires_at": now + timedelta(hours=4),
            "status": VisitAuthorization.Status.AUTHORIZED,
        }
        defaults.update(overrides)
        return VisitAuthorization.objects.create(**defaults)

    def issued_token(self, authorization):
        """Emite el QR y devuelve el texto exacto que el guardia escanearía."""
        from security.qr import build_payload

        authorization, token = issue_visit_qr(authorization)
        return build_payload(authorization.qr_uuid, token)


class VisitQrValidationSuccessTests(VisitQrValidationBaseTestCase):
    """RF-10: el guardia escanea y el sistema confirma vigencia, estado, visitante y unidad."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user_guard)

    def test_valid_qr_is_approved_and_returns_visit_details(self):
        authorization = self.make_authorization()
        payload = self.issued_token(authorization)

        response = self.client.post(self.validate_url, {"token": payload}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        body = response.data
        self.assertTrue(body["valid"])
        self.assertEqual(body["reason"], "VALID")

        detail = body["authorization"]
        self.assertEqual(detail["id"], authorization.id)
        self.assertEqual(detail["visitor"]["full_name"], "Mario Gómez")
        self.assertEqual(detail["unit_detail"]["code"], "A-101")
        self.assertEqual(detail["resident"]["full_name"], "Carlos Mendoza")
        self.assertIn("valid_from", detail)
        self.assertIn("valid_until", detail)
        self.assertIn("qr_expires_at", detail)

    def test_valid_qr_records_access_event_and_activates_authorization(self):
        authorization = self.make_authorization()
        payload = self.issued_token(authorization)

        response = self.client.post(self.validate_url, {"token": payload}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data["access_event"])

        authorization.refresh_from_db()
        self.assertEqual(authorization.status, VisitAuthorization.Status.ACTIVE)

        event = AccessEvent.objects.get(id=response.data["access_event"]["id"])
        self.assertEqual(event.authorization_id, authorization.id)
        self.assertEqual(event.guard_staff_id, self.guard.id)
        self.assertEqual(event.event_type, AccessEvent.Type.ENTRY)
        self.assertEqual(event.validation_method, AccessEvent.Method.QR)
        self.assertEqual(event.validation_result, AccessEvent.Result.APPROVED)

    def test_repeated_scan_is_idempotent_on_status(self):
        """Un reingreso válido no vuelve a activar ni duplica el cambio de estado."""
        authorization = self.make_authorization()
        payload = self.issued_token(authorization)

        first = self.client.post(self.validate_url, {"token": payload}, format="json")
        second = self.client.post(self.validate_url, {"token": payload}, format="json")

        self.assertTrue(first.data["valid"])
        self.assertTrue(second.data["valid"])

        authorization.refresh_from_db()
        self.assertEqual(authorization.status, VisitAuthorization.Status.ACTIVE)
        self.assertEqual(authorization.access_events.count(), 2)

    def test_plain_token_without_prefix_is_accepted(self):
        """Un lector que entrega solo el token también valida correctamente."""
        from security.qr import parse_payload

        authorization = self.make_authorization()
        payload = self.issued_token(authorization)
        token = parse_payload(payload).token

        response = self.client.post(self.validate_url, {"token": token}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["valid"])

    def test_deep_link_payload_is_accepted(self):
        authorization = self.make_authorization()
        payload = self.issued_token(authorization)

        response = self.client.post(
            self.validate_url, {"token": f"taji://visit/validate?code={payload}"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["valid"])

    def test_whitespace_from_scanner_is_tolerated(self):
        authorization = self.make_authorization()
        payload = self.issued_token(authorization)

        response = self.client.post(
            self.validate_url, {"token": f"  {payload}  "}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["valid"])

    def test_alternate_field_aliases_are_accepted(self):
        """Los clientes no están obligados a llamar al campo `token`."""
        authorization = self.make_authorization()
        payload = self.issued_token(authorization)

        for field in ("code", "qr", "payload"):
            response = self.client.post(self.validate_url, {field: payload}, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK, field)
            self.assertTrue(response.data["valid"], field)

    def test_admin_can_also_validate(self):
        self.client.force_authenticate(self.user_admin)
        authorization = self.make_authorization()
        payload = self.issued_token(authorization)

        response = self.client.post(self.validate_url, {"token": payload}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["valid"])


class VisitQrValidationRejectionTests(VisitQrValidationBaseTestCase):
    """Reglas de autorización: cada estado no permisivo se rechaza con su motivo."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user_guard)

    def test_unknown_token_is_rejected(self):
        response = self.client.post(
            self.validate_url, {"token": "TAJI1." + "0" * 32 + "." + "a" * 32}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["valid"])
        self.assertEqual(response.data["reason"], "NOT_FOUND")
        self.assertIsNone(response.data["authorization"])

    def test_malformed_token_is_rejected(self):
        response = self.client.post(
            self.validate_url, {"token": "no-es-un-qr-valido"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["valid"])
        self.assertEqual(response.data["reason"], "NOT_FOUND")

    def test_blank_token_returns_validation_error(self):
        response = self.client.post(self.validate_url, {"token": ""}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("token", response.data["error"]["fields"])

    def test_missing_token_returns_validation_error(self):
        response = self.client.post(self.validate_url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("token", response.data["error"]["fields"])

    def test_rotated_qr_is_rejected(self):
        """El QR emitido antes de una rotación ya no autoriza el ingreso (RF-09)."""
        authorization = self.make_authorization()
        old_payload = self.issued_token(authorization)

        issue_visit_qr(authorization)  # rota el QR

        response = self.client.post(self.validate_url, {"token": old_payload}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["valid"])
        self.assertEqual(response.data["reason"], "QR_ROTATED")

    def test_cancelled_authorization_is_rejected(self):
        authorization = self.make_authorization()
        payload = self.issued_token(authorization)
        VisitAuthorization.objects.filter(pk=authorization.pk).update(
            status=VisitAuthorization.Status.CANCELLED, cancelled_at=timezone.now()
        )

        response = self.client.post(self.validate_url, {"token": payload}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["valid"])
        self.assertEqual(response.data["reason"], "VISIT_CANCELLED")

    def test_finished_authorization_is_rejected(self):
        authorization = self.make_authorization()
        payload = self.issued_token(authorization)
        VisitAuthorization.objects.filter(pk=authorization.pk).update(
            status=VisitAuthorization.Status.FINISHED
        )

        response = self.client.post(self.validate_url, {"token": payload}, format="json")
        self.assertFalse(response.data["valid"])
        self.assertEqual(response.data["reason"], "VISIT_FINISHED")

    def test_expired_authorization_is_rejected(self):
        authorization = self.make_authorization()
        payload = self.issued_token(authorization)
        VisitAuthorization.objects.filter(pk=authorization.pk).update(
            status=VisitAuthorization.Status.EXPIRED
        )

        response = self.client.post(self.validate_url, {"token": payload}, format="json")
        self.assertFalse(response.data["valid"])
        self.assertEqual(response.data["reason"], "VISIT_EXPIRED")

    def test_visit_window_ended_is_rejected_and_persists_expired(self):
        authorization = self.make_authorization()
        payload = self.issued_token(authorization)

        past = timezone.now() - timedelta(hours=1)
        VisitAuthorization.objects.filter(pk=authorization.pk).update(
            valid_from=past - timedelta(hours=4),
            valid_until=past,
            qr_expires_at=past,
        )

        response = self.client.post(self.validate_url, {"token": payload}, format="json")
        self.assertFalse(response.data["valid"])
        self.assertEqual(response.data["reason"], "VISIT_WINDOW_ENDED")

        authorization.refresh_from_db()
        self.assertEqual(authorization.status, VisitAuthorization.Status.EXPIRED)

    def test_visit_not_yet_valid_is_rejected(self):
        authorization = self.make_authorization()
        payload = self.issued_token(authorization)

        future = timezone.now() + timedelta(hours=3)
        VisitAuthorization.objects.filter(pk=authorization.pk).update(
            valid_from=future,
            valid_until=future + timedelta(hours=4),
            qr_expires_at=future + timedelta(hours=4),
        )

        response = self.client.post(self.validate_url, {"token": payload}, format="json")
        self.assertFalse(response.data["valid"])
        self.assertEqual(response.data["reason"], "VISIT_NOT_YET_VALID")

    def test_expired_qr_is_rejected(self):
        """El QR vence aunque la visita siga vigente (RF-09)."""
        authorization = self.make_authorization()
        payload = self.issued_token(authorization)

        VisitAuthorization.objects.filter(pk=authorization.pk).update(
            qr_expires_at=timezone.now() - timedelta(minutes=1)
        )

        response = self.client.post(self.validate_url, {"token": payload}, format="json")
        self.assertFalse(response.data["valid"])
        self.assertEqual(response.data["reason"], "QR_EXPIRED")

    def test_inconsistent_qr_state_is_rejected(self):
        """
    Guarda defensiva: si el hash del token existe pero falta `qr_issued_at`,
    la fila quedó incompleta y el QR no debe autorizar el ingreso.
    """
        from security.qr import hash_token

        authorization = self.make_authorization()
        VisitAuthorization.objects.filter(pk=authorization.pk).update(
            qr_token_hash=hash_token("a" * 32), qr_issued_at=None
        )

        response = self.client.post(
            self.validate_url, {"token": "a" * 32}, format="json"
        )
        self.assertFalse(response.data["valid"])
        self.assertEqual(response.data["reason"], "QR_NOT_ISSUED")

    def test_cannot_validate_authorization_without_qr_token(self):
        """Si nunca se emitió QR no existe token que el guardia pueda escanear."""
        authorization = self.make_authorization()
        self.assertFalse(authorization.is_qr_issued())


class VisitQrValidationAuditTests(VisitQrValidationBaseTestCase):
    """Trazabilidad de los escaneos."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user_guard)

    def test_denied_scan_records_access_event_with_reason(self):
        authorization = self.make_authorization()
        payload = self.issued_token(authorization)
        VisitAuthorization.objects.filter(pk=authorization.pk).update(
            status=VisitAuthorization.Status.CANCELLED
        )

        response = self.client.post(
            self.validate_url, {"token": payload, "notes": "Visitante sin autorización"}, format="json"
        )
        self.assertFalse(response.data["valid"])

        event = AccessEvent.objects.get(id=response.data["access_event"]["id"])
        self.assertEqual(event.event_type, AccessEvent.Type.DENIED)
        self.assertEqual(event.validation_result, AccessEvent.Result.REJECTED)
        self.assertEqual(event.guard_staff_id, self.guard.id)
        self.assertEqual(event.notes, "Visitante sin autorización")

    def test_denied_scan_is_audited(self):
        authorization = self.make_authorization()
        payload = self.issued_token(authorization)
        VisitAuthorization.objects.filter(pk=authorization.pk).update(
            status=VisitAuthorization.Status.CANCELLED
        )

        self.client.post(self.validate_url, {"token": payload}, format="json")

        self.assertTrue(
            AuditEvent.objects.filter(
                action_code="VISIT_QR_VALIDATION_REJECTED",
                resource_type="VisitAuthorization",
                resource_id=str(authorization.pk),
            ).exists()
        )

    def test_unknown_token_does_not_write_access_events(self):
        """Un QR desconocido no debe poder usarse para llenar la tabla de eventos."""
        before = AccessEvent.objects.count()

        response = self.client.post(
            self.validate_url, {"token": "TAJI1." + "1" * 32 + "." + "b" * 32}, format="json"
        )

        self.assertFalse(response.data["valid"])
        self.assertIsNone(response.data["access_event"])
        self.assertEqual(AccessEvent.objects.count(), before)

    def test_approved_scan_is_not_duplicated_in_audit_log(self):
        """El ingreso aprobado ya queda en AccessEvent; no se duplica en auditoría."""
        authorization = self.make_authorization()
        payload = self.issued_token(authorization)

        self.client.post(self.validate_url, {"token": payload}, format="json")

        self.assertFalse(
            AuditEvent.objects.filter(
                action_code="VISIT_QR_VALIDATION_REJECTED",
                resource_id=str(authorization.pk),
            ).exists()
        )


class VisitQrValidationAccessControlTests(VisitQrValidationBaseTestCase):
    """Solo el personal autorizado puede validar ingresos."""

    def test_user_without_permission_is_forbidden(self):
        self.client.force_authenticate(self.user_no_perms)
        response = self.client.post(self.validate_url, {"token": "x" * 32}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_resident_cannot_validate_entries(self):
        """Registrar visitas no habilita para validar ingresos en portería."""
        self.client.force_authenticate(self.user_resident)
        response = self.client.post(self.validate_url, {"token": "x" * 32}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_is_unauthorized(self):
        response = self.client.post(self.validate_url, {"token": "x" * 32}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_suspended_guard_cannot_validate(self):
        """Un guardia con ficha suspendida pierde el acceso a portería."""
        self.client.force_authenticate(self.user_guard)
        self.guard.status = Staff.Status.SUSPENDED
        self.guard.save(update_fields=["status"])

        authorization = self.make_authorization()
        payload = self.issued_token(authorization)

        response = self.client.post(self.validate_url, {"token": payload}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_inactive_guard_cannot_validate(self):
        self.client.force_authenticate(self.user_guard)
        self.guard.status = Staff.Status.INACTIVE
        self.guard.save(update_fields=["status"])

        response = self.client.post(self.validate_url, {"token": "x" * 32}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_write_methods_are_not_allowed(self):
        """La vista solo implementa GET/POST; DRF responde 405."""
        self.client.force_authenticate(self.user_guard)
        response = self.client.delete(self.validate_url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class VisitQrValidationReasonsTests(VisitQrValidationBaseTestCase):
    def test_reasons_catalog(self):
        self.client.force_authenticate(self.user_guard)
        response = self.client.get(reverse("visit-qr-validation-reasons"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        reasons = {item["value"] for item in response.data["reasons"]}
        self.assertIn("NOT_FOUND", reasons)
        self.assertIn("QR_EXPIRED", reasons)
        self.assertIn("VISIT_CANCELLED", reasons)
        self.assertTrue(all(item["message"] for item in response.data["reasons"]))

    def test_reasons_require_permission(self):
        self.client.force_authenticate(self.user_no_perms)
        response = self.client.get(reverse("visit-qr-validation-reasons"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_package_and_root_urls_resolve_identically(self):
        root_match = resolve("/api/v1/visit-qr/validate/")
        pkg_match = resolve("/api/v1/paquete2/visit-qr/validate/")
        self.assertIs(root_match.func.cls, pkg_match.func.cls)