from django.apps import AppConfig


class IncidentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "incidents"

    def ready(self):
        import os
        import sys
        from django.conf import settings
        if (settings.DEBUG and settings.NVIDIA.get('DEV_WORKER', True) and settings.NVIDIA['ENABLED']
                and 'runserver' in sys.argv and (os.environ.get('RUN_MAIN') == 'true' or '--noreload' in sys.argv)):
            from paquetes.paquete3_incidencias_ia.cu22_analisis_ia.worker import start_development_worker
            start_development_worker()
