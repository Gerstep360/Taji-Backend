"""CU27 / T049: cierra reservas vencidas.

Uso (cron cada 15 minutos en producción):
    python manage.py cu27_cerrar_reservas
La API también ejecuta este cierre al listar, así que el cron es un respaldo.
"""
from django.core.management.base import BaseCommand

from paquetes.paquete5_servicios_comunidad.cu27_reservas_areas.services import sync_expired


class Command(BaseCommand):
    help = "Finaliza reservas aprobadas que ya terminaron y rechaza pendientes vencidas."

    def handle(self, *args, **options):
        completed, expired = sync_expired()
        self.stdout.write(self.style.SUCCESS(
            f"Reservas finalizadas: {completed}. Pendientes vencidas: {expired}."
        ))
