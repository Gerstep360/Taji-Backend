from django.core.management.base import BaseCommand

from accounts.rbac import sync_rbac


class Command(BaseCommand):
    help = "Crea o actualiza los roles y permisos base de Taji."

    def handle(self, *args, **options):
        sync_rbac()
        self.stdout.write(self.style.SUCCESS("Roles y permisos sincronizados."))
