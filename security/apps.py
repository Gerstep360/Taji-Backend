from django.apps import AppConfig


class SecurityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "security"

    def ready(self):
        import os
        import sys

        from django.conf import settings

        config = settings.TAJI_VISION
        if (settings.DEBUG and config['ENABLED'] and config['DEV_WORKER'] and 'runserver' in sys.argv
                and (os.environ.get('RUN_MAIN') == 'true' or '--noreload' in sys.argv)):
            from paquetes.paquete3_incidencias_ia.cu32_webcam.visual_worker import start_development_worker

            start_development_worker()
