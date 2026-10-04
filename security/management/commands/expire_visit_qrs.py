"""Marca como expiradas las autorizaciones de visita cuya ventana de vigencia ya Conclusionó."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from security.qr import expire_stale_authorizations


class Command(BaseCommand):
    help = (
        "Sincroniza el estado EXPIRED de las autorizaciones de visita cuya vigencia terminó, "
        "dejando sus QR inutilizables (RF-09 / T021). Pensado para ejecutarse periódicamente."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Informa cuántos registros se actualizarían sin modificar la base de datos.",
        )

    def handle(self, *args, **options):
        from security.models import VisitAuthorization

        now = timezone.now()

        if options.get("dry_run"):
            pending = (
                VisitAuthorization.objects.filter(
                    status__in=(
                        VisitAuthorization.Status.AUTHORIZED,
                        VisitAuthorization.Status.ACTIVE,
                    ),
                    valid_until__lte=now,
                ).count()
            )
            self.stdout.write(
                self.style.WARNING(f"{pending} autorización(es) a expirar (simulación).")
            )
            return

        updated = expire_stale_authorizations(now)
        self.stdout.write(
            self.style.SUCCESS(f"{updated} autorización(es) marcadas como EXPIRED.")
        )