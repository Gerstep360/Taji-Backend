import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from paquetes.paquete3_incidencias_ia.cu22_analisis_ia.services import claim_job, process_job


class Command(BaseCommand):
    help = 'CU22: trabajador ligero PostgreSQL → NVIDIA, una solicitud a la vez.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        try:
            while True:
                close_old_connections()
                job = claim_job()
                if job:
                    result = process_job(job)
                    self.stdout.write(f'analysis={result.pk} status={result.execution_status} duration_ms={result.duration_ms}')
                if options['once']:
                    break
                if not job:
                    time.sleep(2)
        except KeyboardInterrupt:
            pass
