import copy
from datetime import timedelta
from unittest.mock import patch
import httpx
from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError, PermissionDenied
from incidents.models import IncidentAIAnalysis, IncidentAIReview, PriorityLevel, RiskRule
from paquetes.paquete3_incidencias_ia.cu19_seguimiento_historial.tests import IncidentTrackingTestCase
from .provider import analyze, ProviderFailure
from .services import enqueue, claim_job, process_job, review_analysis
from .safety import evaluate

SERVICE = 'paquetes.paquete3_incidencias_ia.cu22_analisis_ia.services.analyze'


class AIProviderTests(SimpleTestCase):
    def setUp(self):
        self.config = self.settings(NVIDIA={**settings.NVIDIA, 'API_KEY': 'unit-test-key', 'ENABLED': True})
        self.config.enable()
        self.addCleanup(self.config.disable)

    def run_provider(self, response):
        transport = httpx.MockTransport(lambda request: response)
        return analyze({'description': 'Reporte sintético'}, [], [], transport=transport)

    def test_failures_are_classified_without_leaking_provider_body(self):
        for status, code in [(401,'authentication_failed'),(403,'authentication_failed'),(404,'model_unavailable'),(429,'rate_limited'),(500,'provider_unavailable'),(400,'provider_rejected')]:
            with self.subTest(status=status), self.assertRaises(ProviderFailure) as raised:
                self.run_provider(httpx.Response(status, text='unit-test-key'))
            self.assertEqual(raised.exception.code, code)
            self.assertNotIn('unit-test-key', str(raised.exception))

    def test_timeout_and_network_are_recoverable(self):
        for error, code in [(httpx.ReadTimeout('timeout'),'timeout'), (httpx.ConnectError('offline'),'connection_error')]:
            def handler(request):
                raise error
            with self.subTest(code=code), self.assertRaises(ProviderFailure) as raised:
                analyze({}, [], [], transport=httpx.MockTransport(handler))
            self.assertEqual(raised.exception.code, code)

    def test_malformed_and_truncated_outputs_are_rejected(self):
        for content, finish in [('not json','stop'), ('{}','length'), ('[]','stop'), ('{"confidence":NaN}','stop')]:
            with self.subTest(content=content), self.assertRaises(ProviderFailure):
                self.run_provider(httpx.Response(200, json={'choices':[{'finish_reason':finish,'message':{'content':content}}]}))

    def test_request_is_bounded_private_and_disables_thinking(self):
        def handler(request):
            import json
            body = json.loads(request.content)
            self.assertEqual(body['chat_template_kwargs'], {'enable_thinking':False})
            self.assertLessEqual(body['max_tokens'], 3000)
            self.assertNotIn('vecino@example.com', request.content.decode())
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]})
        result, _ = analyze({'description':'vecino@example.com, teléfono 76543210'}, [], [], transport=httpx.MockTransport(handler))
        self.assertEqual(result,{})

    def test_oversized_provider_response_is_rejected(self):
        with self.assertRaises(ProviderFailure) as raised:
            self.run_provider(httpx.Response(200, content=b'x'*128001))
        self.assertEqual(raised.exception.code,'response_too_large')


class IncidentAITests(IncidentTrackingTestCase):
    def setUp(self):
        cache.clear()
        self.incident = self._make_incident(title='Hay incendio y los niños están lejos')
        self.incident.description = 'Hay incendio y los niños están lejos'
        self.incident.save()
        self.auth()
        self.low = PriorityLevel.objects.get(code='LOW')
        self.prediction = {'category_code':self.category.code,'priority_code':'LOW','confidence':.85,'risk_score':10,
            'summary':'Incendio reportado con niños fuera del peligro.',
            'entities':[{'entity_type':'PERSON','text':'niños','context':'distant'}],
            'risks':[{'name':'Incendio','evidence':'incendio','context':'present'}],
            'recommendations':['Mantén distancia y avisa al equipo responsable.']}

    def finish(self, prediction=None):
        row = enqueue(self.incident,self.admin_user)
        job = claim_job()
        with patch(SERVICE,return_value=(prediction or copy.deepcopy(self.prediction),'original exacto')):
            return process_job(job)

    def test_safety_raises_proposal_but_never_changes_official_priority(self):
        previous = self.incident.priority_id
        row = self.finish()
        self.assertEqual(row.execution_status,'SUCCEEDED')
        self.assertEqual(row.suggested_priority.code,'HIGH')
        self.assertTrue(any(f['active'] for f in row.safety_findings))
        self.incident.refresh_from_db()
        self.assertEqual(self.incident.priority_id,previous)
        self.assertEqual(row.raw_output['prediction']['priority_code'],'LOW')

    def test_negations_drills_and_distant_children_are_contextual(self):
        rules = RiskRule.objects.filter(is_active=True)
        for text in ['No hay incendio. Los niños están lejos.','Simulacro de incendio en el pasillo.','Los niños están lejos.']:
            with self.subTest(text=text):
                _,floor,_ = evaluate(text,rules)
                self.assertEqual(floor,0)
        _,floor,_ = evaluate('No hay humo pero hay incendio y los niños están lejos.',rules)
        self.assertEqual(floor,3)
        _,floor,_ = evaluate('No hay fuego aquí pero hay fuego en el garaje.',rules)
        self.assertEqual(floor,3)
        _,floor,_ = evaluate('Hay niños atrapados en el ascensor.',rules)
        self.assertEqual(floor,4)

    def test_new_catalog_category_is_accepted_without_code_changes(self):
        from incidents.models import IncidentCategory
        category = IncidentCategory.objects.create(code='NEW_CATEGORY',name='Nueva categoría')
        row = self.finish({**self.prediction,'category_code':category.code})
        self.assertEqual(row.suggested_category,category)

    def test_unknown_catalog_and_invented_evidence_require_manual_review(self):
        for changes, expected in [({'category_code':'INVENTED'},'unknown_catalog_value'),
                                  ({'entities':[{'entity_type':'PLACE','text':'Lugar inventado','context':'present'}]},'ungrounded_evidence')]:
            with self.subTest(changes=changes):
                IncidentAIAnalysis.objects.all().delete()
                row = self.finish({**self.prediction, **changes})
                self.assertEqual(row.execution_status,'FAILED')
                self.assertEqual(row.error_code,expected)

    def test_failure_is_persisted_and_manual_correction_is_possible(self):
        row = enqueue(self.incident,self.admin_user)
        with patch(SERVICE,side_effect=ProviderFailure('timeout')):
            row = process_job(claim_job())
        self.assertEqual(row.error_code,'timeout')
        review_analysis(row,self.admin_user,self.category,self.priority,'Revisión presencial del incidente')
        self.assertEqual(IncidentAIReview.objects.count(),1)

    def test_review_preserves_original_and_records_correction(self):
        row = self.finish()
        original = copy.deepcopy(row.raw_output)
        review_analysis(row,self.admin_user,self.category,self.priority,'Revisé las señales y confirmé el peligro')
        row.refresh_from_db()
        self.assertEqual(row.raw_output,original)
        self.assertEqual(row.human_review.reviewer,self.admin_user)
        with self.assertRaises(ValidationError):
            review_analysis(row,self.admin_user,self.category,self.priority,'Una segunda revisión inválida')

    def test_unauthorized_and_unsafe_downgrade_are_rejected(self):
        row = self.finish()
        with self.assertRaises(PermissionDenied):
            review_analysis(row,self.resident_user,self.category,self.priority,'No tengo autorización')
        with self.assertRaises(ValidationError):
            review_analysis(row,self.admin_user,self.category,self.low,'No parece tan grave')
        review_analysis(row,self.admin_user,self.category,self.low,'Verificación presencial: era una falsa alarma confirmada.',True)

    def test_changed_report_cannot_apply_outdated_prediction(self):
        row = self.finish()
        self.incident.description = 'Ahora ocurrió otro problema'
        self.incident.save()
        with self.assertRaises(ValidationError):
            review_analysis(row,self.admin_user,self.category,self.priority,'Corregir con datos desactualizados')

    def test_queue_is_idempotent_and_stale_worker_recovers(self):
        one = enqueue(self.incident,self.admin_user)
        self.assertEqual(enqueue(self.incident,self.admin_user).pk,one.pk)
        job = claim_job()
        IncidentAIAnalysis.objects.filter(pk=job.pk).update(started_at=timezone.now()-timedelta(minutes=3))
        self.assertIsNone(claim_job())
        one.refresh_from_db()
        self.assertEqual(one.error_code,'worker_interrupted')

    def test_api_is_tenant_scoped_and_resident_cannot_request_analysis(self):
        url=f'/api/v1/paquete3/incidents/{self.incident.public_code}/ai/'
        self.auth(self.resident_user)
        self.assertEqual(self.client.post(url).status_code,403)
        self.assertEqual(self.client.get(url).status_code,200)
        self.incident.condominium=self.other_condo
        self.incident.save()
        self.assertEqual(self.client.get(url).status_code,404)

    def test_global_catalog_management_generates_code(self):
        url='/api/v1/paquete3/incident-ai/catalogs/categories/'
        self.assertEqual(self.client.post(url,{'name':'Nuevo tipo'}).status_code,403)
        self.admin_user.is_superuser=True
        self.admin_user.save()
        response=self.client.post(url,{'name':'Nuevo tipo'})
        self.assertEqual(response.status_code,201,response.data)
        self.assertTrue(response.data['code'].startswith('NUEVO-TIPO_'))
        self.assertEqual(self.client.patch(url, {'name':'Inválido'}).status_code,405)
        self.assertEqual(self.client.post(url+str(response.data['id'])+'/', {'name':'Inválido'}).status_code,405)
