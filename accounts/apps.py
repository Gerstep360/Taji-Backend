from django.apps import AppConfig
from django.db.models.signals import post_migrate


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "Cuentas y acceso"

    def ready(self):
        from . import schema  # noqa: F401
        from .rbac import sync_rbac

        post_migrate.connect(sync_rbac, sender=self, dispatch_uid="accounts.sync_rbac")


