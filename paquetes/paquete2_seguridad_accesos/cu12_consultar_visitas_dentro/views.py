from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from security.models import AccessEvent, VisitAuthorization
from security.views import CanRegisterAccessEvents
from tenancy.context import TenantContext
from tenancy.permissions import IsTenantMember
from ..cu08_visitantes.permissions import CanRegisterOrManageVisits
from .services import consultation


class VisitConsultationRowSerializer(serializers.Serializer):
    """Representación documental de registros de visitas y accesos consultados."""
    id = serializers.IntegerField(required=False)
    visitor_name = serializers.CharField(required=False)
    visitor_document_number = serializers.CharField(required=False)
    unit_code = serializers.CharField(required=False)
    status = serializers.CharField(required=False)


@extend_schema(
    tags=["Seguridad - Consultas Visitas"],
    summary="Consultar visitas programadas, activas, dentro e histórico",
    parameters=[
        OpenApiParameter(
            "section",
            str,
            default="expected",
            description="Sección a consultar: expected, active, finished, inside o history.",
        ),
        OpenApiParameter(
            "search",
            str,
            description="Búsqueda por nombre de visitante, documento o código de unidad.",
        ),
    ],
    responses={200: VisitConsultationRowSerializer(many=True)},
)
class VisitConsultationView(generics.GenericAPIView):
    serializer_class = VisitConsultationRowSerializer
    permission_classes = [IsAuthenticated, IsTenantMember, CanRegisterOrManageVisits | CanRegisterAccessEvents]
    action = "list"

    def get(self, request):
        section = request.query_params.get("section", "expected")
        if section not in ("expected", "active", "finished", "inside", "history"):
            raise ValidationError({"section": "Usa expected, active, finished, inside o history."})
        authorizations = VisitAuthorization.objects.select_related(
            "visitor_person", "authorized_by_resident__person", "unit__sector"
        )
        events = AccessEvent.objects.select_related(
            "person", "unit__sector", "guard_staff__person", "authorization__visitor_person", "authorization__unit__sector"
        )
        tenant = TenantContext.get_current_tenant()
        if tenant and not TenantContext.is_global():
            authorizations = authorizations.filter(unit__sector__condominium=tenant)
            events = events.filter(
                Q(unit__sector__condominium=tenant)
                | Q(unit__isnull=True, authorization__unit__sector__condominium=tenant)
            )
        user = request.user
        if not any(user.has_system_permission(p) for p in ("manage_visits", "validate_visits", "register_entry_exit")):
            resident = getattr(getattr(user, "person", None), "resident", None)
            authorizations = authorizations.filter(authorized_by_resident=resident) if resident else authorizations.none()
            events = events.filter(authorization__in=authorizations)
        rows = consultation(authorizations, events, section, timezone.now())
        search = request.query_params.get("search", "").strip().casefold()
        if search:
            rows = [row for row in rows if any(search in str(row.get(key, "")).casefold()
                    for key in ("visitor_name", "visitor_document_number", "unit_code"))]
        page = self.paginate_queryset(rows)
        return self.get_paginated_response(page)
