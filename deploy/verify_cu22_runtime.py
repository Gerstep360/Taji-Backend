"""Prueba funcional productiva con fixture sintético que se elimina al terminar.

Ejecutar desde Django shell: from deploy.verify_cu22_runtime import run; run()
No imprime tokens, datos personales ni credenciales.
"""
import json
import time
from uuid import uuid4
import httpx
from django.db import close_old_connections
from accounts.models import User
from condominiums.models import Condominium
from incidents.models import Incident, IncidentAIAnalysis
from paquetes.paquete3_incidencias_ia.cu22_analisis_ia.services import enqueue
from rest_framework_simplejwt.tokens import AccessToken


def run():
    condo = Condominium.objects.create(name='Verificación temporal CU22 ' + uuid4().hex[:8])
    incident = None
    try:
        incident = Incident.objects.create(condominium=condo, title='Verificación técnica CU22',
            description='Hay incendio y los niños están lejos.')
        start = time.monotonic()
        job = enqueue(incident, None, automatic=True)
        queue_ms = round((time.monotonic()-start)*1000)
        deadline = time.monotonic()+70
        while time.monotonic() < deadline:
            close_old_connections()
            job.refresh_from_db()
            if job.execution_status in ('SUCCEEDED','FAILED'):
                break
            time.sleep(.5)
        if job.execution_status != 'SUCCEEDED':
            raise RuntimeError('El trabajador no completó la prueba: ' + job.error_code)
        if job.suggested_priority.rank < 3 or not job.raw_output.get('prediction'):
            raise RuntimeError('La prueba no conservó la predicción o la regla de seguridad.')
        health_times = []
        with httpx.Client(timeout=10) as client:
            for _ in range(5):
                before = time.monotonic()
                response = client.get('http://127.0.0.1:8000/api/v1/health/')
                response.raise_for_status()
                health_times.append(round((time.monotonic()-before)*1000))
            actor = User.objects.filter(is_superuser=True,is_active=True).first()
            if not actor:
                raise RuntimeError('No hay una cuenta global para verificar la lectura autorizada.')
            response = client.get(f'http://127.0.0.1:8000/api/v1/paquete3/incidents/{incident.public_code}/ai/',
                headers={'Authorization':'Bearer '+str(AccessToken.for_user(actor)),'X-Tenant-ID':str(condo.pk)})
            response.raise_for_status()
            if response.json()['analyses'][0]['execution_status'] != 'SUCCEEDED':
                raise RuntimeError('El endpoint no devolvió el análisis persistido.')
        result = {'queue_ms':queue_ms,'worker_duration_ms':job.duration_ms,
            'end_to_end_ms':round((time.monotonic()-start)*1000),
            'category':job.suggested_category.code,'priority':job.suggested_priority.code,
            'original_prediction_preserved':True,'authenticated_http_status':response.status_code,
            'health_response_ms':health_times,'synthetic_fixture_removed':True}
        print(json.dumps(result,ensure_ascii=False))
        return result
    finally:
        if incident:
            IncidentAIAnalysis.objects.filter(incident=incident).delete()
            incident.delete()
        condo.delete()
