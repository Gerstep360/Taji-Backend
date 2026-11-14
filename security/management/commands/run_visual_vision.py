"""Worker separado del servidor HTTP y del clasificador de incidencias CU22."""
from django.core.management.base import BaseCommand

from paquetes.paquete3_incidencias_ia.cu32_webcam.visual_worker import run_worker


class Command(BaseCommand):
    help = 'Procesa la cola de observaciones de webcam. Ejecutar un worker por instalación.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        run_worker(once=options['once'])
