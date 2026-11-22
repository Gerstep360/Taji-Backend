import io
import json
import uuid
import subprocess
from datetime import timedelta
from pathlib import Path
from shutil import which
from tempfile import TemporaryDirectory
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APITestCase

from accounts.models import Role, User
from condominiums.models import Condominium, Sector
from incidents.models import Incident
from security.models import VisualObservation, VisualQuota
from tenancy.models import TenantMembership

from .visual_jobs import claim, expire, process, purge
from .visual_provider import ProviderError

CONFIG = {**settings.TAJI_VISION, 'ENABLED': True, 'COSMOS_MODE': 'off', 'FALLBACK_VERIFIED': True,
          'FALLBACK_KEY': 'mock-key', 'FALLBACK_VIDEO_VERIFIED': False,
          'INTERVAL': 40, 'SESSION_BURST': 3, 'SESSION_PER_HOUR': 20}
PROVIDER = __package__ + '.visual_jobs.request_visual'


def sample(action='record'):
    return json.dumps({'description': 'El automóvil parece salir', 'visible_entities': ['automóvil rojo'],
                       'new_or_changed': 'Sale del cuadro', 'interpretation': 'Movimiento',
                       'uncertainty': 'Lejos', 'relevance_reason': 'Para registro', 'suggested_action': action})


@override_settings(TAJI_VISION=CONFIG)
class VisualVisionTests(APITestCase):
    base = '/api/v1/paquete3/cu32/vision/'

    @classmethod
    def setUpTestData(cls):
        cls.tenant = Condominium.objects.create(name='Visión')
        cls.other = Condominium.objects.create(name='Otro tenant')
        cls.sector = Sector.objects.create(condominium=cls.tenant, name='Entrada', code='EN')
        cls.foreign_sector = Sector.objects.create(condominium=cls.other, name='Otra entrada', code='OT')
        for name, role, tenant in [('guard', 'seguridad', cls.tenant), ('admin', 'administrador', cls.tenant),
                                   ('foreign', 'administrador', cls.other), ('resident', 'residente', cls.tenant)]:
            role = Role.objects.get(slug=role)
            user = User.objects.create_user(email=f'{name}@vision.test', role=role, is_approved=True)
            TenantMembership.objects.create(user=user, condominium=tenant, role=role, is_default=True)
            setattr(cls, name, user)

    def setUp(self):
        self.client.force_authenticate(self.guard)
        VisualQuota.objects.create(pk=1, worker_seen_at=timezone.now())

    def start(self, evidence=False):
        response = self.client.post(self.base + 'sessions/', {'sector': self.sector.pk, 'keep_evidence': evidence}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data['id']

    def send(self, session, window=None, *, valid=True, mode='image'):
        jpeg = io.BytesIO()
        Image.new('RGB', (40, 30), 'red').save(jpeg, 'JPEG')
        media = SimpleUploadedFile('scene.jpg', jpeg.getvalue() if valid else b'not an image', content_type='image/jpeg')
        return self.client.post(self.base + f'sessions/{session}/windows/',
                                {'window': window or uuid.uuid4(), 'mode': mode, 'media': media}, format='multipart')

    def queue(self, session):
        result = self.send(session)
        self.assertEqual(result.status_code, 202, result.data)
        return result.data['id']

    def detail(self, job):
        return self.base + f'observations/{job}/'

    def work(self, answer=None, error=None):
        with patch(PROVIDER, return_value=(answer or sample(), 'mock-omni', 700), side_effect=error) as provider:
            job = claim(timezone.now())
            self.assertIsNotNone(job)
            process(*job)
            provider.assert_called_once()
        return VisualObservation.objects.get(pk=job[0])

    def test_permissions_and_foreign_sector(self):
        settings_response = self.client.get(self.base + 'settings/')
        self.assertEqual(settings_response.data['modes'], ['image'])
        self.assertEqual([s['id'] for s in settings_response.data['sectors']], [self.sector.pk])
        bad = self.client.post(self.base + 'sessions/', {'sector': self.foreign_sector.pk}, format='json')
        self.assertEqual(bad.status_code, 400)
        self.client.force_authenticate(self.resident)
        self.assertEqual(self.client.get(self.base + 'observations/').status_code, 403)

    def test_validate_media_cancel_and_idempotency(self):
        session, window = self.start(), uuid.uuid4()
        self.assertEqual(self.send(session, valid=False).status_code, 400)
        self.assertEqual(self.send(session, mode='video').status_code, 503)
        first = self.send(session, window)
        self.assertEqual(first.status_code, 202, first.data)
        self.assertEqual(self.send(session, window).data['id'], first.data['id'])
        self.assertEqual(self.send(session).status_code, 409)
        self.assertEqual(self.client.post(self.base + f'sessions/{session}/stop/', {}).status_code, 204)
        self.assertIsNone(claim(timezone.now()))
        job = VisualObservation.objects.get(pk=first.data['id'])
        self.assertEqual(job.status, 'cancelled')
        self.assertIsNone(job.payload)

    def test_review_keep_prediction_context_and_evidence_permissions(self):
        for code, tenant, reporter in [('OWN', self.tenant, self.guard), ('OTHER', self.other, self.guard),
                                       ('PRIVATE', self.tenant, self.admin)]:
            Incident.objects.create(public_code=code, condominium=tenant, reporter_user=reporter,
                                    sector=self.sector if tenant == self.tenant else self.foreign_sector,
                                    title='Automóvil rojo', description='Un automóvil rojo en la entrada')
        job = self.queue(self.start(evidence=True))
        processed = self.work()
        self.assertEqual(processed.status, 'succeeded')
        self.assertIsNone(processed.payload)
        self.assertEqual(processed.description, 'automóvil rojo')
        self.assertEqual(processed.prediction['interpretation'], '')
        self.assertEqual(processed.prediction['new_or_changed'], '')
        self.assertEqual([item['code'] for item in self.client.get(self.detail(job)).data['context_matches']], ['OWN'])
        self.assertEqual(self.client.get(self.detail(job) + 'evidence/')['Content-Type'], 'image/jpeg')
        self.assertEqual(self.client.post(self.detail(job) + 'review/', {'decision': 'confirmed'}).status_code, 403)
        self.client.force_authenticate(self.foreign)
        self.assertEqual(self.client.get(self.detail(job)).status_code, 404)
        self.assertEqual(self.client.get(self.detail(job) + 'evidence/').status_code, 404)
        self.assertEqual(self.client.get(self.base + 'observations/').data['count'], 0)
        self.client.force_authenticate(self.admin)
        review = self.client.post(self.detail(job) + 'review/', {'decision': 'proposed', 'note': 'Verificar manualmente'})
        self.assertEqual(review.status_code, 200, review.data)
        self.assertEqual(review.data['review_status'], 'proposed')
        self.assertEqual(review.data['description'], processed.description)
        self.assertEqual(Incident.objects.count(), 3)
        search = self.client.get(self.base + 'observations/', {'q': 'automóvil rojo', 'review': 'proposed'})
        self.assertEqual(search.data['count'], 1)
        self.assertEqual(self.client.get(self.base + 'observations/', {'open_related': 'true'}).data['count'], 1)
        Incident.objects.filter(public_code='OWN').update(status=Incident.Status.CLOSED)
        self.assertEqual(self.client.get(self.base + 'observations/', {'open_related': 'true'}).data['count'], 0)
        purge(timezone.now() + timedelta(days=CONFIG['RETENTION_DAYS'] + 1))
        self.assertEqual(self.client.get(self.detail(job) + 'evidence/').status_code, 404)

    def test_empty_duplicates_and_burst_limit(self):
        session = self.start()
        for offset, answer, state in ((130, sample(), 'succeeded'), (80, sample(), 'skipped'), (0, sample('ignore'), 'skipped')):
            job = self.queue(session)
            self.assertEqual(self.work(answer).status, state)
            VisualObservation.objects.filter(pk=job).update(received_at=timezone.now() - timedelta(seconds=offset))
        VisualObservation.objects.filter(pk=job).update(received_at=timezone.now() - timedelta(seconds=42))
        limited = self.send(session)
        self.assertEqual(limited.status_code, 429, limited.data)
        self.assertGreater(int(limited['Retry-After']), 60)
        self.assertEqual(self.client.get(self.base + 'observations/').data['count'], 1)

    def test_provider_failure_and_expired_payload(self):
        session = self.start()
        self.queue(session)
        failed = self.work(error=ProviderError('timeout'))
        self.assertEqual(failed.status, 'failed')
        self.assertEqual(failed.provider_error, 'timeout')
        self.assertIsNone(failed.payload)
        VisualObservation.objects.filter(pk=failed.pk).update(received_at=timezone.now() - timedelta(minutes=2))
        waiting = self.queue(session)
        expire(timezone.now() + timedelta(minutes=1))
        self.assertIsNone(VisualObservation.objects.get(pk=waiting).payload)
        self.assertEqual(self.client.get(self.detail(waiting)).data['provider_status'], 'queue_expired')

    @skipUnless(which('ffmpeg') and which('ffprobe'), 'requiere FFmpeg y ffprobe para el MP4 sintético')
    @override_settings(TAJI_VISION={**CONFIG, 'FALLBACK_VIDEO_VERIFIED': True, 'FFMPEG': 'ffmpeg', 'FFPROBE': 'ffprobe'})
    def test_fragmented_browser_video_is_remuxed_and_queued(self):
        from security.models import VisualSession

        session = self.start()
        VisualSession.objects.filter(pk=session).update(started_at=timezone.now() - timedelta(seconds=10))
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=s=160x90:r=4:d=6',
                            '-an', '-c:v', 'libx264', '-movflags', 'frag_keyframe+empty_moov', str(path)],
                           check=True, capture_output=True, timeout=10)
            video = path.read_bytes()
        self.assertIn(b'moof', video)
        result = self.client.post(self.base + f'sessions/{session}/windows/', {'window': uuid.uuid4(),
            'mode': 'video', 'media': SimpleUploadedFile('source.mp4', video, content_type='video/mp4')}, format='multipart')
        self.assertEqual(result.status_code, 202, result.data)
        _, payload = claim(timezone.now())
        self.assertNotIn(b'moof', payload)
        self.assertLess(payload.index(b'moov'), payload.index(b'mdat'))
