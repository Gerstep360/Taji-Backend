import base64
import os
from django.apps import apps
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4
import httpx
from PIL import Image
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from incidents.models import IncidentAttachment, IncidentAIWorkerHeartbeat, PriorityLevel
from paquetes.paquete3_incidencias_ia.cu18_registrar_incidencia.tests import MediaRootMixin
from paquetes.paquete3_incidencias_ia.cu19_seguimiento_historial.tests import IncidentTrackingTestCase
from .media import prepare_images
from .provider import analyze
from .services import enqueue, claim_job, process_job, review_analysis
from .worker import processor_status, run_worker


def photo_bytes():
    output = BytesIO()
    exif = Image.Exif(); exif[270] = 'private-camera-metadata'
    Image.new('RGB', (1800, 1000), 'red').save(output, format='JPEG', exif=exif)
    return output.getvalue()


class IncidentMultimodalTests(MediaRootMixin, IncidentTrackingTestCase):
    def setUp(self):
        self.incident = self._make_incident(title='Revisar evidencia del pasillo')
        self.auth()
        config = {**settings.NVIDIA, 'VISION_ENABLED': True, 'MAX_IMAGES': 2, 'IMAGE_MAX_EDGE': 640}
        override = self.settings(NVIDIA=config); override.enable(); self.addCleanup(override.disable)

    def attachment(self, name='fixture.jpg', content=None):
        path = default_storage.save(f'incidents/{self.incident.condominium_id}/{self.incident.pk}/' + uuid4().hex + name, ContentFile(content or photo_bytes()))
        return IncidentAttachment.objects.create(incident=self.incident, file_path=path, file_type='IMAGE')

    def prediction(self, attachment_id):
        return {'category_code': self.category.code, 'priority_code': 'LOW', 'confidence': .8, 'risk_score': 10,
                'summary': 'Observación visual pendiente de verificación.', 'entities': [],
                'risks': [{'name': 'Incendio', 'evidence': 'fuego visible', 'context': 'present', 'source': 'image', 'attachment_id': attachment_id}],
                'recommendations': ['Solicita atención al equipo competente.']}

    def prepare(self, job):
        return prepare_images(job.input_snapshot['images'], storage_prefix=f'incidents/{self.incident.condominium_id}/{self.incident.pk}/')

    def test_foreign_storage_paths_are_rejected_before_reading(self):
        with patch('paquetes.paquete3_incidencias_ia.cu22_analisis_ia.media.default_storage.open') as storage_open:
            images, manifest = prepare_images([{'id':42,'file_path':'incidents/999/999/private.jpg'},
                {'id':43,'file_path':'incidents/1/2/../../999/private.jpg'}], storage_prefix='incidents/1/2/')
            self.assertFalse(images)
            self.assertTrue(all(row['reason'] == 'outside_incident_storage' for row in manifest))
            storage_open.assert_not_called()

    def test_private_preview_is_inline_authenticated_and_incident_scoped(self):
        image = self.attachment()
        root = f'/api/v1/paquete3/incidents/{self.incident.public_code}/'
        path = root + f'attachments/{image.pk}/preview/'
        detail = self.client.get(root)
        self.assertEqual(detail.status_code, 200)
        from django.urls import reverse
        self.assertTrue(detail.data['attachments'][0]['preview_url'].endswith(reverse(
            'incident-tracking-preview-attachment', kwargs={'public_code':self.incident.public_code, 'attachment_id':image.pk})))
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/jpeg')
        self.assertTrue(response['Content-Disposition'].startswith('inline;'))
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(b''.join(response.streaming_content), photo_bytes())
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(path).status_code, 401)
        self.auth(self.resident_user)
        self.incident.condominium = self.other_condo; self.incident.save()
        self.assertEqual(self.client.get(path).status_code, 404)

    def test_preview_rejects_non_images_and_foreign_storage(self):
        root = f'/api/v1/paquete3/incidents/{self.incident.public_code}/attachments/'
        bad = self.attachment(name='bad.svg', content=b'<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.assertEqual(self.client.get(root + f'{bad.pk}/preview/').status_code, 404)
        bad.file_path = 'incidents/999/999/private.jpg'; bad.save()
        self.assertEqual(self.client.get(root + f'{bad.pk}/preview/').status_code, 404)
        bad.file_type = 'DOCUMENT'; bad.save()
        self.assertEqual(self.client.get(root + f'{bad.pk}/preview/').status_code, 404)

    def test_photo_is_bounded_reencoded_and_has_no_exif(self):
        image = self.attachment()
        job = enqueue(self.incident, self.admin_user)
        photos, manifest = self.prepare(job)
        self.assertEqual([row['id'] for row in photos], [image.pk])
        self.assertEqual(manifest[0]['status'], 'sent')
        body = base64.b64decode(photos[0]['data_url'].split(',', 1)[1])
        with Image.open(BytesIO(body)) as decoded:
            self.assertEqual(decoded.format, 'JPEG')
            self.assertLessEqual(max(decoded.size), 640)
            self.assertFalse(decoded.getexif())
        self.assertNotIn(b'private-camera-metadata', body)

    def test_images_over_limit_and_unreadable_files_are_reported_not_invented(self):
        self.attachment(content=b'not-an-image')
        for _ in range(3): self.attachment()
        job = enqueue(self.incident, self.admin_user)
        photos, manifest = self.prepare(job)
        self.assertEqual(len(photos), 2)
        self.assertEqual([r['reason'] for r in manifest if r['status'] == 'skipped'], ['unreadable_image', 'image_limit'])

    def test_nvidia_payload_contains_private_base64_not_storage_paths(self):
        image = self.attachment()
        job = enqueue(self.incident, self.admin_user)
        photos, _ = self.prepare(job)
        def handler(request):
            import json
            data = json.loads(request.content)
            parts = data['messages'][-1]['content']
            self.assertIsInstance(parts, list)
            self.assertTrue(any(p.get('image_url', {}).get('url', '').startswith('data:image/jpeg;base64,') for p in parts))
            self.assertNotIn('file_path', request.content.decode())
            self.assertNotIn(image.file_path, request.content.decode())
            self.assertFalse(data['chat_template_kwargs']['enable_thinking'])
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]})
        analyze(job.input_snapshot, [], [], images=photos, transport=httpx.MockTransport(handler))

    def test_visual_risk_keeps_provenance_and_cannot_lower_safety_silently(self):
        image = self.attachment()
        enqueue(self.incident, self.admin_user)
        with patch('paquetes.paquete3_incidencias_ia.cu22_analisis_ia.services.analyze', return_value=(self.prediction(image.pk), '{}')):
            result = process_job(claim_job())
        self.assertEqual(result.execution_status, 'SUCCEEDED', result.error_code)
        self.assertGreaterEqual(result.suggested_priority.rank, 3)
        self.assertEqual(result.raw_output['validated_prediction']['risks'][0]['attachment_id'], image.pk)
        self.assertEqual(result.raw_output['media'][0]['status'], 'sent')
        with self.assertRaises(ValidationError):
            review_analysis(result, self.admin_user, self.category, PriorityLevel.objects.get(code='LOW'), 'Reducir sin verificar la foto')

    def test_model_cannot_cite_a_photo_it_did_not_receive(self):
        enqueue(self.incident, self.admin_user)
        with patch('paquetes.paquete3_incidencias_ia.cu22_analisis_ia.services.analyze', return_value=(self.prediction(999999), '{}')):
            result = process_job(claim_job())
        self.assertEqual(result.error_code, 'ungrounded_image')

    def test_negated_visual_finding_does_not_raise_priority_just_from_its_name(self):
        image = self.attachment()
        prediction = self.prediction(image.pk)
        prediction['risks'][0].update(context='negated', evidence='No se aprecia fuego')
        enqueue(self.incident, self.admin_user)
        with patch('paquetes.paquete3_incidencias_ia.cu22_analisis_ia.services.analyze', return_value=(prediction, '{}')):
            result = process_job(claim_job())
        self.assertEqual(result.execution_status, 'SUCCEEDED', result.error_code)
        self.assertEqual(result.suggested_priority.code, 'LOW')
        self.assertEqual(result.risk_score, 0)

    def test_worker_status_distinguishes_offline_recent_and_stale(self):
        self.assertFalse(processor_status()['available'])
        row = IncidentAIWorkerHeartbeat.objects.create(worker_id=uuid4())
        self.assertTrue(processor_status()['available'])
        row.last_seen = timezone.now() - timedelta(seconds=100); row.save()
        self.assertFalse(processor_status()['available'])
        response = self.client.get(f'/api/v1/paquete3/incidents/{self.incident.public_code}/ai/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['processor']['available'])

    def test_once_worker_expires_its_heartbeat_on_exit(self):
        with patch('paquetes.paquete3_incidencias_ia.cu22_analisis_ia.worker.claim_job', return_value=None):
            run_worker(once=True)
        self.assertFalse(processor_status()['available'])

    def test_legacy_queued_job_is_upgraded_to_current_model_and_photos(self):
        image = self.attachment()
        row = enqueue(self.incident, self.admin_user)
        row.input_snapshot.pop('images'); row.model_name = 'old-model'; row.save()
        claimed = claim_job()
        self.assertEqual(claimed.model_name, settings.NVIDIA['MODEL'])
        self.assertEqual(claimed.input_snapshot['images'][0]['id'], image.pk)

    def test_development_autostart_is_limited_to_real_runserver_process(self):
        cases = [(['manage.py','test'], True, 'true', False), (['manage.py','migrate'], True, 'true', False),
                 (['manage.py','runserver'], False, 'true', False), (['manage.py','runserver'], True, 'false', False),
                 (['manage.py','runserver'], True, 'true', True), (['manage.py','runserver','--noreload'], True, 'false', True)]
        for argv, debug, run_main, expected in cases:
            with self.subTest(argv=argv, debug=debug, run_main=run_main), self.settings(DEBUG=debug), patch('sys.argv', argv), patch.dict(os.environ, {'RUN_MAIN':run_main}), patch('paquetes.paquete3_incidencias_ia.cu22_analisis_ia.worker.start_development_worker') as start:
                apps.get_app_config('incidents').ready()
                self.assertEqual(start.called, expected)
