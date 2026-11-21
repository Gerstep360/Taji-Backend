import logging
from typing import Any, Dict, List, Optional
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from auditlog.services import record_audit_event
from notifications.models import Announcement, DeviceToken, Notification
from tenancy.context import TenantContext
from tenancy.models import TenantMembership

logger = logging.getLogger(__name__)


class FcmNotificationService:
    """
    Servicio desacoplado para el envío de notificaciones push móviles.
    Si firebase-admin no está configurado, opera en modo mock transparente sin fallar.
    """

    @classmethod
    def send_push_notification(
        cls,
        tokens: List[str],
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not tokens:
            return {"sent": 0, "failed": 0, "mode": "noop"}

        data_payload = {str(k): str(v) for k, v in (data or {}).items()}

        try:
            import firebase_admin
            from firebase_admin import messaging

            if not firebase_admin._apps:
                logger.info(
                    "FCM: firebase_admin no tiene app inicializada. Notificación push simulada para %d dispositivos.",
                    len(tokens),
                )
                return {"sent": len(tokens), "failed": 0, "mode": "mock_simulated"}

            message = messaging.MulticastMessage(
                notification=messaging.Notification(title=title, body=body),
                data=data_payload,
                tokens=tokens,
            )
            response = messaging.send_each_for_multicast(message)
            return {
                "sent": response.success_count,
                "failed": response.failure_count,
                "mode": "live",
            }
        except ImportError:
            logger.debug(
                "FCM: firebase_admin no está instalado. Notificación push despachada en modo mock a %d tokens.",
                len(tokens),
            )
            return {"sent": len(tokens), "failed": 0, "mode": "mock_installed_absent"}
        except Exception as exc:
            logger.warning("FCM: Error al despachar mensaje push: %s", exc)
            return {"sent": 0, "failed": len(tokens), "mode": "error", "error": str(exc)}


class NotificationDispatcherService:
    """
    Despachador de notificaciones in-app y push cuando se publica un comunicado en el condominio.
    """

    AUDIENCE_ROLE_MAP = {
        Announcement.Audience.ALL: None,  # Todos los miembros activos
        Announcement.Audience.RESIDENTS: ["residente", "copropietario", "inquilino"],
        Announcement.Audience.STAFF: ["seguridad", "guardia", "mantenimiento", "limpieza", "personal"],
        Announcement.Audience.SECURITY: ["seguridad", "guardia"],
        Announcement.Audience.MAINTENANCE: ["mantenimiento"],
        Announcement.Audience.DIRECTIVE: ["directiva", "admin", "administrador"],
    }

    @classmethod
    def get_audience_user_ids(cls, condominium_id: int, audience: str) -> List[int]:
        qs = TenantMembership.objects.filter(condominium_id=condominium_id, is_active=True)
        roles = cls.AUDIENCE_ROLE_MAP.get(audience)

        if roles:
            slug_q = Q(role__slug__in=roles)
            name_q = Q()
            for r in roles:
                name_q |= Q(role__name__icontains=r)
            qs = qs.filter(slug_q | name_q)

        return list(qs.values_list("user_id", flat=True).distinct())

    @classmethod
    def dispatch_for_announcement(
        cls,
        announcement: Announcement,
        condominium_id: int,
        actor_user=None,
        request=None,
    ) -> Dict[str, Any]:
        user_ids = cls.get_audience_user_ids(condominium_id, announcement.audience)
        if not user_ids:
            return {"notifications_created": 0, "push_sent": 0}

        now = timezone.now()
        notifications = [
            Notification(
                user_id=uid,
                notification_type="ANNOUNCEMENT",
                title=announcement.title,
                message=announcement.body[:250],
                resource_type="announcement",
                resource_id=str(announcement.pk),
                sent_at=now,
            )
            for uid in user_ids
        ]

        with transaction.atomic():
            created_notifications = Notification.objects.bulk_create(notifications)

        # Despacho de tokens de dispositivo push
        active_tokens = list(
            DeviceToken.objects.filter(user_id__in=user_ids, is_active=True).values_list(
                "token", flat=True
            )
        )

        push_result = FcmNotificationService.send_push_notification(
            tokens=active_tokens,
            title=f"[{announcement.get_priority_display().upper()}] {announcement.title}",
            body=announcement.body[:140],
            data={
                "type": "ANNOUNCEMENT",
                "announcement_id": str(announcement.pk),
                "priority": announcement.priority,
                "audience": announcement.audience,
            },
        )

        if actor_user:
            record_audit_event(
                action_code="ANNOUNCEMENT_NOTIFIED",
                resource_type="Announcement",
                resource_id=announcement.pk,
                actor_user=actor_user,
                request=request,
            )

        return {
            "notifications_created": len(created_notifications),
            "push_dispatched": push_result.get("sent", 0),
            "total_recipients": len(user_ids),
        }


class AnnouncementService:
    """
    Servicio de ciclo de vida de comunicados (publicación, archivado y control de estados).
    """

    @classmethod
    def publish(
        cls,
        announcement: Announcement,
        user,
        request=None,
    ) -> Announcement:
        announcement.status = Announcement.Status.PUBLISHED
        if not announcement.published_at:
            announcement.published_at = timezone.now()
        announcement.save(update_fields=["status", "published_at", "updated_at"])

        condominium_id = announcement.condominium_id or TenantContext.get_current_tenant_id()
        NotificationDispatcherService.dispatch_for_announcement(
            announcement=announcement,
            condominium_id=condominium_id,
            actor_user=user,
            request=request,
        )

        record_audit_event(
            action_code="ANNOUNCEMENT_PUBLISHED",
            resource_type="Announcement",
            resource_id=announcement.pk,
            actor_user=user,
            request=request,
        )
        return announcement

    @classmethod
    def archive(
        cls,
        announcement: Announcement,
        user,
        request=None,
    ) -> Announcement:
        announcement.status = Announcement.Status.ARCHIVED
        announcement.save(update_fields=["status", "updated_at"])

        record_audit_event(
            action_code="ANNOUNCEMENT_ARCHIVED",
            resource_type="Announcement",
            resource_id=announcement.pk,
            actor_user=user,
            request=request,
        )
        return announcement
