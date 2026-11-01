from django.core.management.base import BaseCommand
from notifications.models import Notification
from tenancy.context import TenantContext
from tenancy.models import TenantMembership
from paquetes.paquete3_incidencias_ia.cu21_ciclo_atencion.services import attention_alerts


class Command(BaseCommand):
    help = "T047: generar alertas de incidencias y mantenimiento (ejecutar periódicamente)."

    def handle(self, *args, **options):
        count = 0
        for membership in TenantMembership.objects.filter(is_active=True).select_related("user", "condominium"):
            user = membership.user
            if not user.is_active:
                continue
            with TenantContext.for_tenant(membership.condominium, membership):
                for alert in attention_alerts(user):
                    _, created = Notification.objects.get_or_create(
                        user=user, notification_type=alert["kind"],
                        resource_type="Incident" if alert["kind"].startswith("INCIDENT") else "MaintenancePlan",
                        resource_id=f'{alert["resource_id"]}:{alert["due_at"].isoformat()}',
                        defaults={"title": alert["title"][:160], "message": f'Fecha objetivo: {alert["due_at"].isoformat()}'},
                    )
                    count += created
        self.stdout.write(self.style.SUCCESS(f"Alertas nuevas: {count}"))
