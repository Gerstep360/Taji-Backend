from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, permissions
from rest_framework.permissions import BasePermission

from .models import AuditEvent
from .serializers import AuditEventSerializer


class CanViewAuditLog(BasePermission):
    message = "No tienes permiso para consultar los registros de auditoría del sistema."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return bool(
            user.is_superuser
            or user.has_system_permission("manage_roles")
            or user.has_system_permission("view_audit_log")
        )


class AuditEventListView(generics.ListAPIView):
    """Consulta la bitácora inmutable de eventos de auditoría del sistema."""

    serializer_class = AuditEventSerializer
    permission_classes = [permissions.IsAuthenticated, CanViewAuditLog]

    @extend_schema(
        tags=["Auditoría"],
        summary="Listar eventos de auditoría",
        description="Retorna el historial inmutable de acciones sensibles con filtros por categoría y búsqueda.",
        parameters=[
            OpenApiParameter("search", str, description="Filtro por acción, email, descripción o IP."),
            OpenApiParameter("category", str, description="Categoría: auth, roles, users, staff, condominium."),
            OpenApiParameter("action_code", str, description="Código exacto de acción."),
        ],
    )
    def get_queryset(self):
        qs = AuditEvent.objects.select_related("actor_user").all()

        search = self.request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(action_code__icontains=search)
                | Q(description__icontains=search)
                | Q(actor_user__email__icontains=search)
                | Q(ip_address__icontains=search)
                | Q(resource_type__icontains=search)
            )

        category = self.request.query_params.get("category", "").strip().lower()
        if category and category != "all":
            qs = qs.filter(action_code__startswith=f"{category}.")

        action_code = self.request.query_params.get("action_code", "").strip()
        if action_code:
            qs = qs.filter(action_code=action_code)

        return qs.order_by("-occurred_at")
