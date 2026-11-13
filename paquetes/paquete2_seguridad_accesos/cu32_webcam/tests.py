import io
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework.test import APITestCase

from accounts.models import Role, User
from condominiums.models import Condominium
from security.models import DemoVehicle
from tenancy.models import TenantMembership


class WebcamTests(APITestCase):
    lookup = "/api/v1/security/cu32/plate/lookup/"
    read = "/api/v1/security/cu32/plate/read/"

    @classmethod
    def setUpTestData(cls):
        cls.tenant = Condominium.objects.create(name="Demo CU32")
        other = Condominium.objects.create(name="Otro condominio CU32")
        for slug in ("seguridad", "residente"):
            role = Role.objects.get(slug=slug)
            user = User.objects.create_user(
                email=f"{slug}@cu32.test", password="Local-Test-32!", role=role, is_approved=True,
            )
            TenantMembership.objects.create(user=user, condominium=cls.tenant, role=role, is_default=True)
            setattr(cls, slug, user)
        DemoVehicle.objects.create(condominium=cls.tenant, plate="AB01", description="Vehículo de prueba")
        DemoVehicle.objects.create(condominium=other, plate="CD02", description="No divulgar")

    def setUp(self):
        cache.clear()
        self.client.force_authenticate(self.seguridad)

    def test_registered_and_normalized(self):
        result = self.client.post(self.lookup, {"plate": " ab-01 "}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["vehicle"]["plate"], "AB01")
        self.assertEqual(result["Cache-Control"], "no-store")

    def test_foreign_and_unknown_are_indistinguishable(self):
        results = [self.client.post(self.lookup, {"plate": plate}, format="json") for plate in ("CD02", "EF03")]
        self.assertEqual([r.status_code for r in results], [200, 200])
        self.assertEqual([r.data for r in results], [{"registered": False, "vehicle": None}] * 2)

    def test_permission_required_on_both_endpoints(self):
        for user in (self.residente, None):
            self.client.force_authenticate(user)
            for url in (self.lookup, self.read):
                self.assertIn(self.client.post(url, {}).status_code, (401, 403))

    def test_bad_plate_and_bad_image(self):
        self.assertEqual(self.client.post(self.lookup, {"plate": "0/O!"}, format="json").status_code, 400)
        image = SimpleUploadedFile("bad.jpg", b"invalid", content_type="image/jpeg")
        self.assertEqual(self.client.post(self.read, {"image": image}, format="multipart").status_code, 400)

    @staticmethod
    def crop():
        buffer = io.BytesIO()
        Image.new("RGB", (200, 80), "white").save(buffer, "JPEG")
        return SimpleUploadedFile("crop.jpg", buffer.getvalue(), content_type="image/jpeg")

    @patch("paquetes.paquete2_seguridad_accesos.cu32_webcam.views.read_plate", return_value=None)
    def test_unreadable_does_not_invent_a_plate(self, reader):
        result = self.client.post(self.read, {"image": self.crop()}, format="multipart")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data, {"plate": None})
        reader.assert_called_once()

    @override_settings(NVIDIA={"ENABLED": False})
    def test_disabled_provider_returns_controlled_error(self):
        self.assertEqual(self.client.post(self.read, {"image": self.crop()}, format="multipart").status_code, 503)

    @patch("paquetes.paquete2_seguridad_accesos.cu32_webcam.views.read_plate", return_value="AB01")
    def test_ocr_is_throttled(self, reader):
        codes = [self.client.post(self.read, {"image": self.crop()}, format="multipart").status_code for _ in range(7)]
        self.assertEqual(codes, [200] * 6 + [429])
        self.assertEqual(reader.call_count, 6)
