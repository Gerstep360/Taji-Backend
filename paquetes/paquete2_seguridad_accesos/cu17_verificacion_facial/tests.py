import base64
import io
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from accounts.models import User, Person
from condominiums.models import Resident
from security.models import BiometricReference, FaceVerification, AccessEvent
from paquetes.paquete2_seguridad_accesos.cu17_verificacion_facial.facial_engine import (
    extract_face_embedding,
    calculate_cosine_similarity,
    pack_embedding,
    unpack_embedding,
    MODEL_NAME,
    MODEL_VERSION,
)


def create_test_image_b64(color_fill=(120, 140, 200)):
    """Crea una imagen PNG sintética de prueba codificada en Base64."""
    if HAS_PIL:
        img = Image.new("RGB", (64, 64), color=color_fill)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")
    else:
        return "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def create_camera_capture_b64():
    """
    Data URL del tamaño de una captura real de cámara (640x480).

    Las pruebas históricas usaban PNG de 64x64, cuyo base64 cabe en 500
    caracteres. Por eso el bug de `varchar(500)` nunca apareció en CI: en
    PostgreSQL una captura real lanzaba `DataError` y la API respondía 503.
    """
    img = Image.new("RGB", (640, 480), color=(30, 90, 160))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")


class FaceVerificationTestCase(TestCase):
    """T075 (IA/Backend): Pruebas faciales de coincidencia, no coincidencia, revisión manual y enrolamiento."""

    def setUp(self):
        self.client = APIClient()
        self.admin_user = User.objects.create_superuser(
            email="admin.facial@taji.app",
            first_name="Admin",
            last_name="Facial",
            password="AdminPassword123!",
        )
        self.client.force_authenticate(user=self.admin_user)

        self.person = Person.objects.create(
            first_name="Juan",
            last_name="Pérez",
            document_number="12345678",
            document_type="CI",
        )
        self.resident = Resident.objects.create(
            person=self.person,
            status=Resident.Status.ACTIVE,
        )

    def test_t072_t073_engine_embedding_and_similarity(self):
        """T072 & T073: Procesamiento de imagen, embedding 512-float y cálculo de similitud de coseno."""
        img1 = create_test_image_b64((100, 100, 100))
        img2 = create_test_image_b64((100, 100, 100))

        ext1 = extract_face_embedding(img1)
        ext2 = extract_face_embedding(img2)

        self.assertTrue(ext1["success"])
        self.assertTrue(ext2["success"])
        v1 = ext1["embedding"]
        v2 = ext2["embedding"]

        self.assertEqual(len(v1), 512)
        self.assertEqual(len(v2), 512)

        # Prueba de empaquetado y desempaquetado de bytes
        packed = pack_embedding(v1)
        unpacked = unpack_embedding(packed)
        self.assertEqual(len(unpacked), 512)

        # Misma imagen debe dar similitud muy alta (>= 0.90)
        score = calculate_cosine_similarity(v1, v2)
        self.assertGreaterEqual(score, 0.90)

    def test_t029_t090_biometric_enrollment_and_versioning(self):
        """T029 & T090: Enrolamiento y versionado de referencias biométricas de residentes."""
        imgs_v1 = [create_test_image_b64((50 + i * 10, 50, 50)) for i in range(5)]
        imgs_v2 = [create_test_image_b64((200, 200 - i * 10, 200)) for i in range(5)]

        # 1. Enrolar Versión 1 con 5 fotos
        res1 = self.client.post(
            "/api/v1/security/cu17/biometrics/enroll/",
            {"resident_id": self.resident.id, "images": imgs_v1},
            format="json",
        )
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res1.data["is_active"])

        # 2. Enrolar Versión 2 (debe desactivar v1 y activar v2)
        res2 = self.client.post(
            "/api/v1/security/cu17/biometrics/enroll/",
            {"resident_id": self.resident.id, "images": imgs_v2},
            format="json",
        )
        self.assertEqual(res2.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res2.data["is_active"])

        # Verificar en base de datos que solo hay 1 versión activa y 2 totales
        active_refs = BiometricReference.objects.filter(resident=self.resident, is_active=True)
        total_refs = BiometricReference.objects.filter(resident=self.resident)
        self.assertEqual(active_refs.count(), 1)
        self.assertEqual(total_refs.count(), 2)

        # 3. Consultar historial de versiones del residente
        res_hist = self.client.get(
            f"/api/v1/security/cu17/biometrics/resident/{self.resident.id}/history/",
        )
        self.assertEqual(res_hist.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_hist.data), 2)

    def test_t030_t074_t075_face_match_and_human_confirmation(self):
        """T030, T074, T075: Pruebas de coincidencia (MATCH) y confirmación humana."""
        imgs_ref = [create_test_image_b64((150, 150, 150)) for _ in range(5)]
        # Enrolar referencia inicial
        self.client.post(
            "/api/v1/security/cu17/biometrics/enroll/",
            {"resident_id": self.resident.id, "images": imgs_ref},
            format="json",
        )

        # 1. Probar Match (Coincidencia)
        res_match = self.client.post(
            "/api/v1/security/cu17/face-verification/match/",
            {"captured_image": imgs_ref[0], "threshold": 0.45},
            format="json",
        )
        self.assertEqual(res_match.status_code, status.HTTP_200_OK)
        self.assertEqual(res_match.data["result"], "MATCH")
        self.assertGreaterEqual(res_match.data["similarity_score"], 0.45)
        self.assertEqual(res_match.data["matched_resident"]["id"], self.resident.id)

        # 2. Probar Confirmación Humana Positiva (human_confirmed = True)
        res_confirm = self.client.post(
            "/api/v1/security/cu17/face-verification/confirm/",
            {
                "captured_image": imgs_ref[0],
                "matched_resident_id": self.resident.id,
                "biometric_reference_id": res_match.data["biometric_reference_id"],
                "similarity_score": res_match.data["similarity_score"],
                "threshold": 0.70,
                "result": "MATCH",
                "human_confirmed": True,
                "create_access_event": True,
                "event_type": "ENTRY",
                "notes": "Confirmado por guardia en puerta principal",
            },
            format="json",
        )
        self.assertEqual(res_confirm.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res_confirm.data["human_confirmed"])
        self.assertIsNotNone(res_confirm.data["access_event"])

        # Verificar que se creó el evento de acceso
        access_events = AccessEvent.objects.filter(person=self.person)
        self.assertEqual(access_events.count(), 1)
        self.assertEqual(access_events.first().validation_method, AccessEvent.Method.FACE)

    def test_t075_face_rejection_human_confirmation(self):
        """T075: Prueba de rechazo manual en la confirmación humana (human_confirmed = False)."""
        img_captured = create_test_image_b64((10, 10, 10))

        res_reject = self.client.post(
            "/api/v1/security/cu17/face-verification/confirm/",
            {
                "captured_image": img_captured,
                "matched_resident_id": self.resident.id,
                "similarity_score": 0.45,
                "threshold": 0.70,
                "result": "NO_MATCH",
                "human_confirmed": False,
                "create_access_event": False,
                "notes": "Fotografía no corresponde al residente según guardia",
            },
            format="json",
        )
        self.assertEqual(res_reject.status_code, status.HTTP_201_CREATED)
        self.assertFalse(res_reject.data["human_confirmed"])
        self.assertIsNone(res_reject.data["access_event"])

    def test_match_persists_a_real_size_camera_capture(self):
        """
        Regresión del 503: una captura de cámara real excedía los 500 caracteres
        del campo y PostgreSQL rechazaba el INSERT con `DataError`, que el
        manejador global convertía en "503 La base de datos no está disponible".
        """
        capture = create_camera_capture_b64()
        self.assertGreater(len(capture), 500)

        response = self.client.post(
            "/api/v1/security/cu17/face-verification/match/",
            {"captured_image": capture, "threshold": 0.45},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        verification = FaceVerification.objects.get(id=response.data["verification_id"])
        self.assertEqual(verification.captured_image, capture)

    def test_confirm_persists_a_real_size_camera_capture(self):
        """La confirmación humana recibe la misma captura y también debe persistirla."""
        capture = create_camera_capture_b64()

        response = self.client.post(
            "/api/v1/security/cu17/face-verification/confirm/",
            {
                "captured_image": capture,
                "matched_resident_id": self.resident.id,
                "similarity_score": 0.62,
                "threshold": 0.70,
                "result": "REVIEW",
                "human_confirmed": True,
                "create_access_event": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(FaceVerification.objects.get().captured_image, capture)

    def test_enrollment_persists_a_real_size_reference_image(self):
        """
        Regresión del mismo bug en el enrolamiento: `reference_image` también
        estaba declarado como `varchar(500)` y recibía la data URL completa.

        Se verifica a nivel de columna porque el camino HTTP depende de que el
        detector facial acepte la foto; lo que se rompe aquí es el esquema.
        """
        capture = create_camera_capture_b64()
        self.assertGreater(len(capture), 500)

        reference = BiometricReference.objects.create(
            resident=self.resident,
            reference_image=capture,
            embedding=pack_embedding([0.1] * 512),
            embedding_dim=512,
            model_name=MODEL_NAME,
            model_version=MODEL_VERSION,
        )

        reference.refresh_from_db()
        self.assertEqual(reference.reference_image, capture)
