from django.db.models import CharField, OuterRef, Q, Subquery
from django.db.models.functions import Cast
from django.utils import timezone
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from auditlog.services import record_audit_event
from notifications.models import Announcement, DeviceToken, Notification
from tenancy.context import TenantContext
from tenancy.permissions import IsTenantMember

from .permissions import CanManageAnnouncements, CanViewCommunityAnnouncements, has_announcement_permission
from .serializers import AnnouncementSerializer, DeviceTokenSerializer, NotificationSerializer
from .services import AnnouncementService


class AnnouncementViewSet(viewsets.ModelViewSet):
    """
    CRUD completo y ciclo de vida de comunicados por audiencia y prioridad (CU28 / T051).
    Aislado estrictamente por tenant y protegido por RBAC.
    """

    serializer_class = AnnouncementSerializer
    permission_classes = [IsAuthenticated, CanViewCommunityAnnouncements]
    filter_backends = [filters.SearchFilter]
    search_fields = ("title", "body")

    def _is_manager(self) -> bool:
        return has_announcement_permission(self.request.user, "manage_announcements")

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Announcement.objects.none()

        tenant = TenantContext.get_current_tenant()
        if not tenant or not tenant.is_active:
            return Announcement.objects.none()

        qs = Announcement.objects.filter(condominium_id=tenant.pk).select_related(
            "created_by_user"
        )

        # Si tiene permisos de administración, puede ver todos los comunicados y filtrar por estado/audiencia/prioridad
        if self._is_manager():
            audience = self.request.query_params.get("audience")
            priority = self.request.query_params.get("priority")
            st = self.request.query_params.get("status")

            if audience:
                qs = qs.filter(audience=audience)
            if priority:
                qs = qs.filter(priority=priority)
            if st:
                qs = qs.filter(status=st)

            return qs.order_by("-published_at", "-created_at")

        # Usuarios regulares (residentes, personal, directiva): solo ven comunicados publicados y vigentes
        now = timezone.now()
        member = TenantContext.get_current_membership()
        role_slug = (member.role.slug if member and member.role else "").lower()

        audiences = [Announcement.Audience.ALL]
        if role_slug in ("residente", "copropietario", "inquilino"):
            audiences.append(Announcement.Audience.RESIDENTS)
        elif role_slug in ("seguridad", "guardia"):
            audiences.extend([Announcement.Audience.SECURITY, Announcement.Audience.STAFF])
        elif role_slug in ("mantenimiento",):
            audiences.extend([Announcement.Audience.MAINTENANCE, Announcement.Audience.STAFF])
        elif role_slug in ("limpieza", "personal"):
            audiences.append(Announcement.Audience.STAFF)
        elif role_slug in ("directiva", "admin", "administrador"):
            audiences.extend(
                [
                    Announcement.Audience.DIRECTIVE,
                    Announcement.Audience.RESIDENTS,
                    Announcement.Audience.STAFF,
                ]
            )

        return (
            qs.filter(status=Announcement.Status.PUBLISHED, audience__in=audiences)
            .filter(Q(published_at__isnull=True) | Q(published_at__lte=now))
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .order_by("-published_at", "-created_at")
        )

    def perform_create(self, serializer):
        if not self._is_manager():
            raise PermissionDenied("No tienes permiso para crear comunicados.")

        tenant_id = TenantContext.get_current_tenant_id()
        is_published = serializer.validated_data.get("status") == Announcement.Status.PUBLISHED
        if is_published and not serializer.validated_data.get("published_at"):
            serializer.validated_data["published_at"] = timezone.now()

        instance = serializer.save(
            condominium_id=tenant_id,
            created_by_user=self.request.user,
        )

        if is_published:
            AnnouncementService.publish(instance, self.request.user, self.request)
        else:
            record_audit_event(
                action_code="ANNOUNCEMENT_CREATED",
                resource_type="Announcement",
                resource_id=instance.pk,
                actor_user=self.request.user,
                request=self.request,
            )

    def perform_update(self, serializer):
        if not self._is_manager():
            raise PermissionDenied("No tienes permiso para modificar comunicados.")

        prev_status = serializer.instance.status
        new_status = serializer.validated_data.get("status", prev_status)

        if new_status == Announcement.Status.PUBLISHED and not serializer.validated_data.get(
            "published_at", serializer.instance.published_at
        ):
            serializer.validated_data["published_at"] = timezone.now()

        instance = serializer.save()

        if prev_status != Announcement.Status.PUBLISHED and new_status == Announcement.Status.PUBLISHED:
            AnnouncementService.publish(instance, self.request.user, self.request)
        else:
            record_audit_event(
                action_code="ANNOUNCEMENT_UPDATED",
                resource_type="Announcement",
                resource_id=instance.pk,
                actor_user=self.request.user,
                request=self.request,
            )

    def destroy(self, request, *args, **kwargs):
        if not self._is_manager():
            raise PermissionDenied("No tienes permiso para archivar comunicados.")

        instance = self.get_object()
        AnnouncementService.archive(instance, request.user, request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        if not self._is_manager():
            raise PermissionDenied("No tienes permiso para publicar comunicados.")

        instance = self.get_object()
        published_instance = AnnouncementService.publish(instance, request.user, request)
        return Response(self.get_serializer(published_instance).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        if not self._is_manager():
            raise PermissionDenied("No tienes permiso para archivar comunicados.")

        instance = self.get_object()
        archived_instance = AnnouncementService.archive(instance, request.user, request)
        return Response(self.get_serializer(archived_instance).data)


class DeviceTokenViewSet(viewsets.GenericViewSet):
    """
    Registro y gestión de tokens de dispositivos móviles y web para notificaciones push (T052).
    """

    serializer_class = DeviceTokenSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token_str = serializer.validated_data["token"]
        platform_str = serializer.validated_data.get("platform", DeviceToken.Platform.ANDROID)
        is_active = serializer.validated_data.get("is_active", True)

        device, created = DeviceToken.objects.update_or_create(
            token=token_str,
            defaults={
                "user": request.user,
                "platform": platform_str,
                "is_active": is_active,
                "last_seen_at": timezone.now(),
            },
        )

        return Response(
            DeviceTokenSerializer(device).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Centro de notificaciones de usuario: listado, recuento y marcado de leídas (T052 / T123).
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated, CanViewCommunityAnnouncements]

    def _scoped(self):
        tenant_id = TenantContext.get_current_tenant_id()
        if getattr(self, "swagger_fake_view", False) or tenant_id is None:
            return Notification.objects.none()
        related = Announcement.objects.filter(condominium_id=tenant_id).annotate(
            notification_id=Cast("pk", CharField())
        ).filter(notification_id=OuterRef("resource_id"))
        return Notification.objects.filter(user=self.request.user).annotate(
            announcement_priority=Subquery(related.values("priority")[:1]),
            announcement_audience=Subquery(related.values("audience")[:1]),
        ).filter(~Q(resource_type__iexact="announcement") | Q(announcement_priority__isnull=False))

    def get_queryset(self):
        qs = self._scoped()
        unread = self.request.query_params.get("unread")
        if unread in ("true", "1", "True"):
            qs = qs.filter(read_at__isnull=True)

        return qs.order_by("-created_at")

    @action(detail=True, methods=["post", "patch"])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        if not notification.read_at:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])

        return Response(self.get_serializer(notification).data)

    @action(detail=False, methods=["post", "patch"])
    def mark_all_read(self, request):
        updated_count = self._scoped().filter(read_at__isnull=True).update(read_at=timezone.now())

        return Response({"marked_read": updated_count})

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        count = self._scoped().filter(read_at__isnull=True).count()
        return Response({"unread_count": count})
