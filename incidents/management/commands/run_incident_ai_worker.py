import time
from django.core.management.base import BaseCommand
from paquetes.paquete3_incidencias_ia.cu22_analisis_ia.worker import run_worker


class Command(BaseCommand):
    help = 'CU22: trabajador ligero PostgreSQL → NVIDIA, una solicitud a la vez.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        run_worker(once=options['once'], log=self.stdout.write)
