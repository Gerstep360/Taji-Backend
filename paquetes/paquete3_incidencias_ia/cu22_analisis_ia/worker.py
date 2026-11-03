"""Bucle compartido por desarrollo y el servicio separado de producción."""
from datetime import timedelta
import logging
import threading
import time
from uuid import uuid4
from django.db import DatabaseError, close_old_connections
from django.utils import timezone
from incidents.models import IncidentAIWorkerHeartbeat
from .services import claim_job, process_job

logger = logging.getLogger('taji.incidents.ai')
HEARTBEAT_TTL = 90
_dev_thread = None


def processor_status():
    last = IncidentAIWorkerHeartbeat.objects.order_by('-last_seen').values_list('last_seen', flat=True).first()
    available = bool(last and last >= timezone.now() - timedelta(seconds=HEARTBEAT_TTL))
    return {'available': available, 'last_seen': last,
            'message': 'Procesador conectado.' if available else 'El procesador IA está desconectado. El reporte está guardado; el servidor debe iniciar el trabajador IA.'}


def run_worker(*, once=False, log=None):
    worker_id = uuid4()
    next_heartbeat = 0
    database_error_logged = False
    try:
        while True:
            close_old_connections()
            try:
                if time.monotonic() >= next_heartbeat:
                    IncidentAIWorkerHeartbeat.objects.update_or_create(worker_id=worker_id, defaults={'last_seen': timezone.now()})
                    next_heartbeat = time.monotonic() + 15
                job = claim_job()
                if job:
                    result = process_job(job)
                    IncidentAIWorkerHeartbeat.objects.filter(worker_id=worker_id).update(last_seen=timezone.now())
                    if log:
                        log(f'analysis={result.pk} status={result.execution_status} duration_ms={result.duration_ms} error={result.error_code or "none"}')
                database_error_logged = False
            except DatabaseError:
                close_old_connections()
                if not database_error_logged:
                    logger.warning('Trabajador IA esperando disponibilidad de la base y sus migraciones.')
                    database_error_logged = True
                if once:
                    raise
                time.sleep(2)
                continue
            if once:
                break
            if not job:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            IncidentAIWorkerHeartbeat.objects.filter(worker_id=worker_id).update(last_seen=timezone.now() - timedelta(seconds=HEARTBEAT_TTL + 1))
        except DatabaseError:
            pass
        close_old_connections()


def start_development_worker():
    global _dev_thread
    if _dev_thread is not None and _dev_thread.is_alive():
        return
    def start():
        time.sleep(.5)
        run_worker(log=logger.info)
    _dev_thread = threading.Thread(target=start, name='taji-incident-ai', daemon=True)
    _dev_thread.start()
