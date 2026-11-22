"""Prueba opt-in de API REST → cola → NVIDIA real → revisión, sin datos reales.

TAJI_NVIDIA_LIVE_TEST=1 python manage.py test \
  paquetes.paquete3_incidencias_ia.cu22_analisis_ia.tests_live --settings=config.settings_test
La base y las evidencias son temporales. La clave se obtiene solo de settings/.env.
"""
import os
import json
from pathlib import Path
from unittest import skipUnless
from django.conf import settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken
from incidents.models import Incident, IncidentAIAnalysis
from paquetes.paquete3_incidencias_ia.cu18_registrar_incidencia.tests import IncidentFixtureMixin, MediaRootMixin, pdf
from django.core.files.uploadedfile import SimpleUploadedFile
from .tests_multimodal import photo_bytes
from .services import claim_job, process_job


@skipUnless(os.environ.get('TAJI_NVIDIA_LIVE_TEST') == '1', 'NVIDIA real requiere activación explícita; las pruebas normales no consumen API.')
class IncidentNvidiaLiveTests(MediaRootMixin, IncidentFixtureMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.build_fixture()

    def test_report_with_evidence_real_analysis_and_authorized_review(self):
        self.assertTrue(settings.NVIDIA['API_KEY'], 'Falta configurar la clave en .env.')
        token = str(AccessToken.for_user(self.resident_user))
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + token, HTTP_X_TENANT_ID=str(self.condo.pk))
        root = '/api/v1/paquete3/incidents/'
        options = self.client.get(root + 'options/')
        self.assertEqual(options.status_code, 200, options.data)
        self.assertIn(self.sector.pk, [row['id'] for row in options.data['sectors']])
        response = self.client.post(root, {
            'title': 'Incendio en el pasillo', 'description': 'Hay incendio en el pasillo y los niños están lejos y a salvo.',
            'category': self.plumbing.pk, 'sector': self.sector.pk,
            'evidences': [pdf('evidencia-sintetica.pdf')],
        }, format='multipart')
        self.assertEqual(response.status_code, 201, response.data)
        incident = Incident.objects.get(pk=response.data['id'])
        self.assertEqual(len(response.data['evidences']), 1)
        self.assertEqual(incident.ai_analyses.count(), 1)
        job = claim_job()
        self.assertIsNotNone(job)
        self.assertEqual(job.incident_id, incident.pk)
        result = process_job(job)
        self.assertEqual(result.execution_status, 'SUCCEEDED', (result.error_code, result.raw_output.get('prediction')))
        self.assertGreaterEqual(result.suggested_priority.rank, 3)
        self.assertIn('prediction', result.raw_output)
        incident.refresh_from_db()
        self.assertEqual(incident.category_id, self.plumbing.pk, 'Una propuesta no debe modificar la clasificación oficial.')
        original = result.raw_output.copy()
        path = root + incident.public_code + '/ai/'
        resident_view = self.client.get(path)
        self.assertEqual(resident_view.status_code, 200, resident_view.data)
        self.assertNotIn('original_prediction', resident_view.data['analyses'][0])
        self.assertFalse(resident_view.data['can_review'])
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + str(AccessToken.for_user(self.admin)), HTTP_X_TENANT_ID=str(self.condo.pk))
        review = self.client.post(path + str(result.pk) + '/review/', {
            'category': result.suggested_category_id, 'priority': result.suggested_priority_id,
            'reason': 'Verificación sintética de integración: se confirma el peligro presente.',
        }, format='json')
        self.assertEqual(review.status_code, 200, review.data)
        result.refresh_from_db(); incident.refresh_from_db()
        self.assertEqual(result.raw_output, original)
        self.assertEqual(incident.priority_id, result.suggested_priority_id)
        self.assertEqual(IncidentAIAnalysis.objects.filter(pk=result.pk, review_status='ACCEPTED').count(), 1)
        print(f'NVIDIA integrado: REST 201 -> SUCCEEDED ({result.duration_ms} ms) -> revision 200; originales conservados.')

    def test_real_omni_receives_uploaded_photo_with_text(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + str(AccessToken.for_user(self.resident_user)), HTTP_X_TENANT_ID=str(self.condo.pk))
        response = self.client.post('/api/v1/paquete3/incidents/', {
            'title': 'Evidencia visual sintética', 'description': 'Revisa la imagen adjunta. No se ha confirmado ningún peligro.',
            'category': self.plumbing.pk, 'sector': self.sector.pk,
            'evidences': [SimpleUploadedFile('evidencia.jpg', photo_bytes(), content_type='image/jpeg')],
        }, format='multipart')
        self.assertEqual(response.status_code, 201, response.data)
        incident = Incident.objects.get(pk=response.data['id'])
        job = incident.ai_analyses.get()
        self.assertEqual(len(job.input_snapshot['images']), 1, 'La foto debe guardarse antes de crear el snapshot IA.')
        result = process_job(claim_job())
        self.assertEqual(result.execution_status, 'SUCCEEDED', (result.error_code, result.raw_output.get('prediction')))
        self.assertEqual(result.model_name, 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning')
        self.assertEqual(result.raw_output['media'][0]['status'], 'sent')
        self.assertNotIn('data:image', str(result.input_snapshot))
        print(f'Omni foto + texto: POST 201 -> SUCCEEDED ({result.duration_ms} ms); imagen comprimida y metadatos eliminados.')

    def test_real_omni_quality_cases_after_safety_validation(self):
        cases = json.loads(Path(__file__).with_name('evaluation_cases.json').read_text(encoding='utf-8'))
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + str(AccessToken.for_user(self.resident_user)), HTTP_X_TENANT_ID=str(self.condo.pk))
        for case in cases:
            with self.subTest(case=case['id']):
                response = self.client.post('/api/v1/paquete3/incidents/', {'title': 'Reporte sintético', 'description': case['description'],
                    'category': self.plumbing.pk, 'sector': self.sector.pk}, format='json')
                self.assertEqual(response.status_code, 201, response.data)
                result = process_job(claim_job())
                self.assertEqual(result.execution_status, 'SUCCEEDED', (case['id'], result.error_code, result.raw_output.get('prediction')))
                self.assertIn(result.suggested_category.code, case['category_codes'])
                if 'min_priority_rank' in case: self.assertGreaterEqual(result.suggested_priority.rank, case['min_priority_rank'])
                if 'max_priority_rank' in case: self.assertLessEqual(result.suggested_priority.rank, case['max_priority_rank'])
                print(f"Omni calidad {case['id']}: categoria={result.suggested_category.code} prioridad={result.suggested_priority.code} tiempo_ms={result.duration_ms}")
