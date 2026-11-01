"""Pruebas para CU18: Registrar incidencia (T031, T032, T033)."""

import io
import shutil
import tempfile
import threading
from datetime import date, timedelta
from pathlib import Path
from unittest import mock, skipUnless

from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import Person, Role, SystemPermission, User
from auditlog.models import AuditEvent
from condominiums.models import Condominium, Resident, ResidentUnit, Sector, Unit
from incidents.models import Incident, IncidentAttachment, IncidentCategory, PriorityLevel
from maintenance.models import Asset, AssetType
from tenancy.models import TenantMembership

from . import services


URL = "/api/v1/incidents/"
ALIAS_URL = "/api/v1/paquete3/incidents/"

def _image_bytes(fmt, fallback):
    """Imagen real con Pillow si está instalado (el servicio la verifica); si no, firma mínima."""
    try:
        from PIL import Image
    except ImportError:
        return fallback
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buffer, format=fmt)
    return buffer.getvalue()


JPEG_BYTES = _image_bytes(
    "JPEG", b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 64 + b"\xff\xd9"
)
PNG_BYTES = _image_bytes(
    "PNG", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00" + b"\x00" * 32
)
TRUNCATED_PNG = PNG_BYTES[:40]
PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
EXE_BYTES = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff" + b"\x00" * 64


def jpg(name="foto.jpg", content=JPEG_BYTES):
    return SimpleUploadedFile(name, content, content_type="image/jpeg")


def png(name="foto.png"):
    return SimpleUploadedFile(name, PNG_BYTES, content_type="image/png")


def pdf(name="informe.pdf"):
    return SimpleUploadedFile(name, PDF_BYTES, content_type="application/pdf")


def make_user(slug, name, *, condo=None, active=True):
    role, _ = Role.objects.get_or_create(slug=slug, defaults={"name": slug})
    person = Person.objects.create(first_name=name, last_name="Prueba", document_number=f"doc-{name}")
    user = User.objects.create_user(
        email=f"{name}@taji.test", password="Password123!", person=person, role=role,
        is_approved=True, is_active=active,
    )
    if condo is not None:
        TenantMembership.objects.create(user=user, condominium=condo, role=role, is_default=True)
    return user


def grant(slug, code):
    role = Role.objects.get(slug=slug)
    permission, _ = SystemPermission.objects.get_or_create(code=code, defaults={"name": code})
    role.permissions.add(permission)


class IncidentFixtureMixin:
    """Datos comunes: dos condominios aislados con sectores, unidades y activos."""

    @classmethod
    def build_fixture(cls):
        cls.condo = Condominium.objects.create(name="Bosque", slug="bosque")
        cls.other_condo = Condominium.objects.create(name="Flores", slug="flores")

        cls.admin = make_user("administrador", "admin", condo=cls.condo)
        cls.resident_user = make_user("residente", "resident", condo=cls.condo)
        cls.guard = make_user("seguridad", "guard", condo=cls.condo)
        cls.cleaner = make_user("limpieza", "cleaner", condo=cls.condo)
        cls.outsider = make_user("residente", "outsider", condo=cls.other_condo)

        cls.sector = Sector.objects.create(condominium=cls.condo, code="A", name="Torre A")
        cls.sector_b = Sector.objects.create(condominium=cls.condo, code="B", name="Torre B")
        cls.inactive_sector = Sector.objects.create(condominium=cls.condo, code="X", name="Cerrado", is_active=False)
        cls.other_sector = Sector.objects.create(condominium=cls.other_condo, code="A", name="Torre A")

        cls.unit = Unit.objects.create(sector=cls.sector, code="A-101")
        cls.unit_unlinked = Unit.objects.create(sector=cls.sector, code="A-102")
        cls.unit_b = Unit.objects.create(sector=cls.sector_b, code="B-201")
        cls.other_unit = Unit.objects.create(sector=cls.other_sector, code="F-101")

        cls.resident = Resident.objects.create(condominium=cls.condo, person=cls.resident_user.person)
        ResidentUnit.objects.create(resident=cls.resident, unit=cls.unit, relation_type="OWNER", is_primary=True)
        ResidentUnit.objects.create(
            resident=cls.resident, unit=cls.unit_b, relation_type="TENANT",
            start_date=date.today() - timedelta(days=60), end_date=date.today() - timedelta(days=1),
        )

        asset_type = AssetType.objects.create(code="ELEV", name="Ascensor")
        cls.asset = Asset.objects.create(asset_type=asset_type, sector=cls.sector, code="ASC-1", name="Ascensor 1")
        cls.retired_asset = Asset.objects.create(
            asset_type=asset_type, sector=cls.sector, code="ASC-0", name="Ascensor viejo", status="RETIRED"
        )
        cls.other_asset = Asset.objects.create(asset_type=asset_type, sector=cls.other_sector, code="ASC-F", name="Ascensor F")

        cls.plumbing = IncidentCategory.objects.get(code="PLUMBING")
        cls.security = IncidentCategory.objects.get(code="SECURITY")
        cls.inactive_category = IncidentCategory.objects.create(code="OLD", name="Obsoleta", is_active=False)
        cls.critical = PriorityLevel.objects.get(code="CRITICAL")


class MediaRootMixin:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_dir = tempfile.mkdtemp(prefix="taji-cu18-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_dir)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        shutil.rmtree(cls._media_dir, ignore_errors=True)
        super().tearDownClass()

    def stored_files(self):
        return [p for p in Path(self._media_dir).rglob("*") if p.is_file()]


class IncidentCreateTests(MediaRootMixin, IncidentFixtureMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.build_fixture()

    def setUp(self):
        for path in self.stored_files():
            path.unlink()

    def payload(self, **extra):
        data = {
            "description": "  Hay una fuga de agua en el pasillo.  ",
            "category": self.plumbing.pk,
            "sector": self.sector.pk,
        }
        data.update(extra)
        return data

    def post(self, user, data, fmt="multipart", **headers):
        self.client.force_authenticate(user=user)
        return self.client.post(URL, data, format=fmt, **headers)

    def assert_rejected(self, response, status_code, field=None):
        self.assertEqual(response.status_code, status_code, getattr(response, "data", None))
        if field:
            self.assertIn(field, response.data["error"]["fields"])
        self.assertEqual(Incident.objects.count(), 0)
        self.assertEqual(IncidentAttachment.objects.count(), 0)
        self.assertEqual(self.stored_files(), [])

    # --- T032: registro básico -------------------------------------------------

    def test_resident_creates_incident_with_server_controlled_fields(self):
        before = timezone.now()
        response = self.post(self.resident_user, self.payload(
            unit=self.unit.pk, asset=self.asset.pk, title="  Fuga  ",
            reporter_user=self.admin.pk, reporter=self.admin.pk, condominium=self.other_condo.pk,
            status="CLOSED", public_code="HACK-1", priority=self.critical.pk, id=9999,
            created_at="2000-01-01T00:00:00Z",
        ))
        self.assertEqual(response.status_code, 201, response.data)
        incident = Incident.objects.get(pk=response.data["id"])
        self.assertNotEqual(incident.pk, 9999)
        self.assertEqual(incident.reporter_user, self.resident_user)
        self.assertEqual(incident.reporter_resident, self.resident)
        self.assertEqual(incident.condominium, self.condo)
        self.assertEqual(incident.status, Incident.Status.REPORTED)
        self.assertNotEqual(incident.public_code, "HACK-1")
        self.assertTrue(incident.public_code.startswith(f"INC-{self.condo.pk}-"))
        self.assertEqual(incident.priority.code, "MEDIUM")
        self.assertEqual(incident.description, "Hay una fuga de agua en el pasillo.")
        self.assertEqual(incident.title, "Fuga")
        self.assertEqual((incident.sector, incident.unit, incident.asset), (self.sector, self.unit, self.asset))
        self.assertGreaterEqual(incident.created_at, before)
        self.assertGreaterEqual(incident.updated_at, before)

        body = response.data
        self.assertEqual(body["public_code"], incident.public_code)
        self.assertEqual(body["status"], "REPORTED")
        self.assertEqual(body["status_display"], "Reportada")
        self.assertEqual(body["condominium"], self.condo.pk)
        self.assertEqual(body["reporter"]["id"], self.resident_user.pk)
        self.assertEqual(body["category"]["code"], "PLUMBING")
        self.assertEqual(body["priority"]["code"], "MEDIUM")
        self.assertEqual(body["sector"]["id"], self.sector.pk)
        self.assertEqual(body["unit"]["id"], self.unit.pk)
        self.assertEqual(body["asset"]["id"], self.asset.pk)
        self.assertEqual(body["evidences"], [])
        self.assertIn("created_at", body)
        self.assertIn("updated_at", body)
        self.assertTrue(AuditEvent.objects.filter(action_code="INCIDENT_REPORTED", resource_id=str(incident.pk)).exists())

    def test_json_body_is_accepted_without_evidences(self):
        response = self.post(self.resident_user, self.payload(), fmt="json")
        self.assertEqual(response.status_code, 201, response.data)

    def test_optional_fields_can_be_omitted(self):
        response = self.post(self.resident_user, self.payload())
        self.assertEqual(response.status_code, 201, response.data)
        incident = Incident.objects.get(pk=response.data["id"])
        self.assertIsNone(incident.unit)
        self.assertIsNone(incident.asset)
        self.assertEqual(incident.title, "")
        self.assertIsNone(response.data["unit"])
        self.assertIsNone(response.data["asset"])

    def test_alias_route_under_paquete3(self):
        self.client.force_authenticate(user=self.resident_user)
        response = self.client.post(ALIAS_URL, self.payload(), format="multipart")
        self.assertEqual(response.status_code, 201, response.data)

    def test_codes_are_unique_and_sequential_per_condominium(self):
        codes = [self.post(self.resident_user, self.payload()).data["public_code"] for _ in range(5)]
        self.assertEqual(len(set(codes)), 5)
        self.assertEqual(codes[0], f"INC-{self.condo.pk}-000001")
        self.assertEqual(codes[-1], f"INC-{self.condo.pk}-000005")

    def test_code_generation_retries_when_a_concurrent_writer_took_the_number(self):
        first = self.post(self.resident_user, self.payload()).data
        real_next = services._next_sequence
        calls = {"n": 0}

        def stale_then_real(condominium_id):
            calls["n"] += 1
            # Simula una lectura obsoleta: otro escritor ya ocupó el número 1.
            return 1 if calls["n"] == 1 else real_next(condominium_id)

        with mock.patch.object(services, "_next_sequence", side_effect=stale_then_real):
            second = self.post(self.resident_user, self.payload())
        self.assertEqual(second.status_code, 201, second.data)
        self.assertNotEqual(second.data["public_code"], first["public_code"])
        self.assertEqual(calls["n"], 2)
        self.assertEqual(Incident.objects.count(), 2)

    # --- T031: prioridad inicial -----------------------------------------------

    def test_initial_priority_comes_from_category_rule_not_from_client(self):
        response = self.post(self.resident_user, self.payload(category=self.security.pk, priority=self.critical.pk))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["priority"]["code"], "HIGH")
        response = self.post(self.resident_user, self.payload(priority_code="CRITICAL"))
        self.assertEqual(response.data["priority"]["code"], "MEDIUM")
        self.assertFalse(Incident.objects.filter(priority=self.critical).exists())

    # --- Validaciones -----------------------------------------------------------

    def test_blank_description_is_rejected(self):
        for value in ("", "    "):
            self.assert_rejected(self.post(self.resident_user, self.payload(description=value)), 400, "description")
        data = self.payload()
        data.pop("description")
        self.assert_rejected(self.post(self.resident_user, data), 400, "description")

    def test_unknown_or_inactive_category_is_rejected(self):
        self.assert_rejected(self.post(self.resident_user, self.payload(category=987654)), 400, "category")
        self.assert_rejected(self.post(self.resident_user, self.payload(category=self.inactive_category.pk)), 400, "category")
        data = self.payload()
        data.pop("category")
        self.assert_rejected(self.post(self.resident_user, data), 400, "category")

    def test_invalid_location_is_rejected(self):
        for sector_id in (987654, self.other_sector.pk, self.inactive_sector.pk):
            self.assert_rejected(self.post(self.resident_user, self.payload(sector=sector_id)), 400, "sector")
        data = self.payload()
        data.pop("sector")
        self.assert_rejected(self.post(self.resident_user, data), 400, "sector")

    def test_resident_cannot_link_units_not_associated_with_them(self):
        for unit_id in (self.unit_unlinked.pk, self.other_unit.pk, 987654):
            self.assert_rejected(self.post(self.resident_user, self.payload(unit=unit_id)), 400, "unit")
        # La asociación finalizada ya no autoriza.
        self.assert_rejected(self.post(self.resident_user, self.payload(unit=self.unit_b.pk, sector=self.sector_b.pk)), 400, "unit")

    def test_unit_must_belong_to_selected_location(self):
        self.assert_rejected(self.post(self.admin, self.payload(unit=self.unit_b.pk)), 400, "unit")

    def test_admin_may_link_any_unit_of_the_condominium(self):
        response = self.post(self.admin, self.payload(unit=self.unit_unlinked.pk))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["reporter"]["id"], self.admin.pk)

    def test_asset_from_another_condominium_or_retired_is_rejected(self):
        for asset_id in (self.other_asset.pk, self.retired_asset.pk, 987654):
            self.assert_rejected(self.post(self.resident_user, self.payload(asset=asset_id)), 400, "asset")

    # --- Permisos ---------------------------------------------------------------

    def test_anonymous_is_rejected(self):
        self.client.force_authenticate(user=None)
        self.assert_rejected(self.client.post(URL, self.payload(), format="multipart"), 401)

    def test_admin_is_allowed(self):
        self.assertEqual(self.post(self.admin, self.payload()).status_code, 201)

    def test_guard_allowed_only_with_report_permission(self):
        self.assert_rejected(self.post(self.guard, self.payload()), 403)
        grant("seguridad", "report_incidents")
        response = self.post(self.guard, self.payload(unit=self.unit_unlinked.pk))
        self.assertEqual(response.status_code, 201, response.data)

    def test_role_without_permission_is_forbidden(self):
        self.assert_rejected(self.post(self.cleaner, self.payload()), 403)

    def test_membership_without_role_is_forbidden(self):
        TenantMembership.objects.filter(user=self.resident_user).update(role=None)
        self.assert_rejected(self.post(self.resident_user, self.payload()), 403)

    def test_inactive_user_is_rejected(self):
        inactive = make_user("residente", "inactive", condo=self.condo)
        token = str(AccessToken.for_user(inactive))
        User.objects.filter(pk=inactive.pk).update(is_active=False)
        inactive.refresh_from_db()
        self.assert_rejected(self.post(inactive, self.payload()), 403)
        self.client.force_authenticate(user=None)
        response = self.client.post(URL, self.payload(), format="multipart", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assert_rejected(response, 401)

    def test_unapproved_user_is_forbidden(self):
        pending = make_user("residente", "pending", condo=self.condo)
        User.objects.filter(pk=pending.pk).update(is_approved=False)
        pending.refresh_from_db()
        self.assert_rejected(self.post(pending, self.payload()), 403)

    def test_user_of_another_condominium_cannot_report_into_it(self):
        self.assert_rejected(self.post(self.outsider, self.payload()), 400, "sector")
        self.assert_rejected(self.post(self.outsider, self.payload(), HTTP_X_TENANT_ID=str(self.condo.pk)), 403)

    def test_bearer_token_flow_works(self):
        token = str(AccessToken.for_user(self.resident_user))
        client = APIClient()
        response = client.post(URL, self.payload(), format="multipart", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 201, response.content)

    # --- T033: evidencias ---------------------------------------------------------

    def test_photos_and_document_are_stored_and_associated(self):
        response = self.post(self.resident_user, self.payload(evidences=[jpg(), png(), pdf()]))
        self.assertEqual(response.status_code, 201, response.data)
        incident = Incident.objects.get(pk=response.data["id"])
        attachments = list(incident.attachments.order_by("id"))
        self.assertEqual([a.file_type for a in attachments], ["IMAGE", "IMAGE", "DOCUMENT"])
        self.assertTrue(all(a.uploaded_by_user_id == self.resident_user.pk for a in attachments))
        self.assertEqual(len(self.stored_files()), 3)
        storage = FileSystemStorage()
        for attachment in attachments:
            self.assertTrue(attachment.file_path.startswith(f"incidents/{self.condo.pk}/{incident.pk}/"))
            self.assertTrue(storage.exists(attachment.file_path))
        with storage.open(attachments[2].file_path, "rb") as handle:
            self.assertEqual(handle.read(), PDF_BYTES)
        evidences = response.data["evidences"]
        self.assertEqual([e["file_name"] for e in evidences], ["foto.jpg", "foto.png", "informe.pdf"])
        self.assertEqual([e["file_type"] for e in evidences], ["IMAGE", "IMAGE", "DOCUMENT"])

    def test_filename_is_sanitized(self):
        response = self.post(self.resident_user, self.payload(evidences=[jpg("../../etc/mi foto<>.JPG")]))
        self.assertEqual(response.status_code, 201, response.data)
        path = IncidentAttachment.objects.get().file_path
        self.assertNotIn("..", path)
        self.assertNotIn(" ", path)
        self.assertTrue(path.endswith(".jpg"))
        self.assertTrue(Path(self._media_dir).resolve() in self.stored_files()[0].resolve().parents)

    def test_empty_file_is_rejected(self):
        self.assert_rejected(self.post(self.resident_user, self.payload(evidences=[jpg(content=b"")])), 400, "evidences")

    @override_settings(INCIDENT_EVIDENCE_MAX_BYTES=50)
    def test_file_too_big_is_rejected(self):
        self.assert_rejected(self.post(self.resident_user, self.payload(evidences=[jpg()])), 400, "evidences")

    def test_forbidden_extensions_are_rejected(self):
        for name, content in (("virus.exe", EXE_BYTES), ("script.sh", b"#!/bin/sh\necho hi"),
                              ("pagina.html", b"<html></html>"), ("sinextension", JPEG_BYTES)):
            upload = SimpleUploadedFile(name, content, content_type="image/jpeg")
            self.assert_rejected(self.post(self.resident_user, self.payload(evidences=[upload])), 400, "evidences")

    def test_spoofed_content_is_rejected(self):
        cases = (
            SimpleUploadedFile("foto.jpg", EXE_BYTES, content_type="image/jpeg"),
            SimpleUploadedFile("foto.exe.jpg", EXE_BYTES, content_type="image/jpeg"),
            SimpleUploadedFile("doc.pdf", JPEG_BYTES, content_type="application/pdf"),
            SimpleUploadedFile("foto.png", JPEG_BYTES, content_type="image/png"),
        )
        for upload in cases:
            self.assert_rejected(self.post(self.resident_user, self.payload(evidences=[upload])), 400, "evidences")

    def test_corrupted_image_is_rejected_when_pillow_is_available(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow no está instalado; solo se validan los bytes mágicos.")
        upload = SimpleUploadedFile("foto.png", TRUNCATED_PNG, content_type="image/png")
        self.assert_rejected(self.post(self.resident_user, self.payload(evidences=[upload])), 400, "evidences")

    def test_valid_file_mixed_with_invalid_one_creates_nothing(self):
        upload = SimpleUploadedFile("foto.jpg", EXE_BYTES, content_type="image/jpeg")
        self.assert_rejected(self.post(self.resident_user, self.payload(evidences=[jpg(), upload])), 400, "evidences")

    @override_settings(INCIDENT_EVIDENCE_MAX_FILES=2)
    def test_too_many_files_are_rejected(self):
        self.assert_rejected(self.post(self.resident_user, self.payload(evidences=[jpg(), png(), pdf()])), 400, "evidences")

    def test_storage_failure_rolls_back_incident_and_deletes_written_files(self):
        real_save = FileSystemStorage.save
        calls = {"n": 0}

        def flaky_save(storage, name, content, max_length=None):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("disco lleno")
            return real_save(storage, name, content, max_length=max_length)

        with mock.patch.object(FileSystemStorage, "save", autospec=True, side_effect=flaky_save):
            response = self.post(self.resident_user, self.payload(evidences=[jpg(), png()]))
        self.assertEqual(calls["n"], 2)
        self.assert_rejected(response, 503)
        self.assertEqual(response.data["error"]["code"], "service_unavailable")

    def test_database_failure_after_files_written_deletes_files(self):
        with mock.patch.object(IncidentAttachment.objects, "create", side_effect=RuntimeError("fallo")):
            response = self.post(self.resident_user, self.payload(evidences=[jpg()]))
        self.assertEqual(response.status_code, 500)
        self.assert_rejected(response, 500)


class IncidentCatalogTests(IncidentFixtureMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.build_fixture()

    def get(self, user, path):
        self.client.force_authenticate(user=user)
        return self.client.get(f"{URL}{path}")

    def test_categories_catalog_lists_active_categories_with_reference_set(self):
        response = self.get(self.resident_user, "categories/")
        self.assertEqual(response.status_code, 200, response.data)
        names = {item["name"] for item in response.data}
        self.assertTrue({"Infraestructura", "Mantenimiento", "Seguridad", "Convivencia"} <= names)
        self.assertNotIn("Obsoleta", names)
        security = next(item for item in response.data if item["code"] == "SECURITY")
        self.assertEqual(security["default_priority"]["code"], "HIGH")

    def test_priorities_catalog_is_ordered_by_rank(self):
        response = self.get(self.resident_user, "priorities/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["code"] for item in response.data], ["LOW", "MEDIUM", "HIGH", "CRITICAL"])

    def test_options_are_scoped_to_tenant_and_resident_units(self):
        response = self.get(self.resident_user, "options/")
        self.assertEqual(response.status_code, 200, response.data)
        sector_ids = {item["id"] for item in response.data["sectors"]}
        self.assertEqual(sector_ids, {self.sector.pk, self.sector_b.pk})
        self.assertEqual([item["id"] for item in response.data["units"]], [self.unit.pk])
        self.assertEqual({item["id"] for item in response.data["assets"]}, {self.asset.pk})
        rules = response.data["evidence_rules"]
        self.assertEqual(rules["field_name"], "evidences")
        self.assertIn("jpg", rules["allowed_extensions"])
        self.assertIn("pdf", rules["allowed_extensions"])
        self.assertIn("categories", response.data)
        self.assertIn("priorities", response.data)

    def test_admin_options_include_all_condominium_units(self):
        response = self.get(self.admin, "options/")
        self.assertEqual({item["id"] for item in response.data["units"]}, {self.unit.pk, self.unit_unlinked.pk, self.unit_b.pk})

    def test_catalogs_require_permission(self):
        for path in ("categories/", "priorities/", "options/"):
            self.assertEqual(self.get(self.cleaner, path).status_code, 403)
            self.client.force_authenticate(user=None)
            self.assertEqual(self.client.get(f"{URL}{path}").status_code, 401)

    def test_no_list_or_detail_endpoints_are_exposed(self):
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.client.get(URL).status_code, 405)


@skipUnless(connection.vendor == "postgresql", "La concurrencia real de filas requiere PostgreSQL.")
class IncidentCodeConcurrencyTests(TransactionTestCase):
    """Creación simultánea: los códigos públicos nunca colisionan."""

    def test_parallel_creation_produces_unique_codes(self):
        condo = Condominium.objects.create(name="Paralelo")
        sector = Sector.objects.create(condominium=condo, code="P", name="P")
        category = IncidentCategory.objects.filter(is_active=True).first()
        user = make_user("residente", "parallel", condo=condo)
        errors, barrier = [], threading.Barrier(8)

        def worker():
            try:
                barrier.wait()
                services.create_incident(
                    condominium=condo, reporter=user, reporter_resident=None,
                    validated_data={"description": "x", "category": category, "sector": sector}, evidences=[],
                )
            except Exception as exc:  # pragma: no cover - se informa abajo
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        codes = list(Incident.objects.filter(condominium=condo).values_list("public_code", flat=True))
        self.assertEqual(len(codes), 8)
        self.assertEqual(len(set(codes)), 8)
