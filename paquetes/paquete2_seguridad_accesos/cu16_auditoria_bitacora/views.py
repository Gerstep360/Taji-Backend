"""T028: filtros de consulta sobre la auditoría existente, sin escrituras."""

from django.db.models import Q, Value
from django.db.models.functions import Concat
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError

from auditlog.views import AuditEventListView


class Cu16AuditEventListView(AuditEventListView):
    """Conserva serializer, permisos, paginación y filtros de auditlog."""

    @extend_schema(
        tags=["Auditoría"],
        summary="Consultar auditoría y bitácora",
        parameters=[
            OpenApiParameter("search", str, description="Búsqueda general existente."),
            OpenApiParameter("category", str, description="Prefijo de categoría existente."),
            OpenApiParameter("action_code", str, description="Código exacto de acción."),
            OpenApiParameter("user_id", int, description="ID exacto del usuario actor."),
            OpenApiParameter("user", str, description="Nombre completo o email del actor (coincidencia parcial)."),
            OpenApiParameter("resource_type", str, description="Tipo exacto de recurso."),
            OpenApiParameter("resource_id", str, description="Identificador exacto del recurso."),
            OpenApiParameter("date", str, description="Fecha específica, YYYY-MM-DD."),
            OpenApiParameter("date_from", str, description="Fecha inicial inclusiva, YYYY-MM-DD."),
            OpenApiParameter("date_to", str, description="Fecha final inclusiva, YYYY-MM-DD."),
        ],
        description="Consulta de solo lectura. Las fechas utilizan la zona horaria actual del proyecto; los filtros se combinan.",
    )
    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params

        user_id = params.get("user_id", "").strip()
        if user_id:
            if len(user_id) > 19 or not user_id.isascii() or not user_id.isdigit() or not 0 < int(user_id) <= 9223372036854775807:
                raise ValidationError({"user_id": "Indica un ID de usuario entero positivo válido."})
            queryset = queryset.filter(actor_user_id=int(user_id))

        user = params.get("user", "").strip()
        if user:
            queryset = queryset.annotate(
                cu16_actor_name=Concat(
                    "actor_user__person__first_name", Value(" "), "actor_user__person__last_name"
                )
            ).filter(Q(actor_user__email__icontains=user) | Q(cu16_actor_name__icontains=user))

        for field in ("resource_type", "resource_id"):
            value = params.get(field, "").strip()
            if value:
                queryset = queryset.filter(**{field: value})

        dates = {}
        for field in ("date", "date_from", "date_to"):
            value = params.get(field, "").strip()
            if value:
                try:
                    parsed = parse_date(value)
                except ValueError:
                    parsed = None
                if parsed is None or parsed.isoformat() != value:
                    raise ValidationError({field: "Indica una fecha válida con formato YYYY-MM-DD."})
                dates[field] = parsed

        if dates.get("date_from") and dates.get("date_to") and dates["date_from"] > dates["date_to"]:
            raise ValidationError({"date_to": "La fecha final debe ser igual o posterior a la inicial."})
        for field, lookup in (("date", "exact"), ("date_from", "gte"), ("date_to", "lte")):
            if field in dates:
                queryset = queryset.filter(**{f"occurred_at__date__{lookup}": dates[field]})
        return queryset
