from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tenancy.context import TenantContext

from .services import dashboard


class DashboardPeriodSerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)


class DashboardBucketSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    count = serializers.IntegerField(min_value=0)


class DashboardDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    count = serializers.IntegerField(min_value=0)


class DashboardDomainSerializer(serializers.Serializer):
    total = serializers.IntegerField(min_value=0)
    date_field = serializers.CharField()
    daily = DashboardDaySerializer(many=True)


class DashboardSecuritySerializer(DashboardDomainSerializer):
    entries = serializers.IntegerField(min_value=0)
    exits = serializers.IntegerField(min_value=0)
    denied = serializers.IntegerField(min_value=0)
    by_type = DashboardBucketSerializer(many=True)
    by_result = DashboardBucketSerializer(many=True)


class DashboardStatusSerializer(DashboardDomainSerializer):
    pending = serializers.IntegerField(min_value=0)
    by_status = DashboardBucketSerializer(many=True)


class DashboardIncidentsSerializer(DashboardStatusSerializer):
    resolved = serializers.IntegerField(min_value=0)
    by_priority = DashboardBucketSerializer(many=True)


class DashboardMaintenanceSerializer(DashboardStatusSerializer):
    in_progress = serializers.IntegerField(min_value=0)
    completed = serializers.IntegerField(min_value=0)
    overdue = serializers.IntegerField(min_value=0)


class DashboardReservationsSerializer(DashboardStatusSerializer):
    approved = serializers.IntegerField(min_value=0)
    rejected = serializers.IntegerField(min_value=0)
    cancelled = serializers.IntegerField(min_value=0)
    completed = serializers.IntegerField(min_value=0)
    by_area = DashboardBucketSerializer(many=True)


class DashboardContextSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=["condominium"])
    id = serializers.IntegerField()
    name = serializers.CharField()
    timezone = serializers.CharField()


class DashboardAppliedPeriodSerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    as_of = serializers.DateTimeField()


class DashboardResponseSerializer(serializers.Serializer):
    context = DashboardContextSerializer()
    period = DashboardAppliedPeriodSerializer()
    unit = serializers.ChoiceField(choices=["records"])
    security = DashboardSecuritySerializer()
    incidents = DashboardIncidentsSerializer()
    maintenance = DashboardMaintenanceSerializer()
    reservations = DashboardReservationsSerializer()
    has_data = serializers.BooleanField()


class CanConsultDashboard(BasePermission):
    message = "Selecciona un condominio activo con acceso administrativo."

    def has_permission(self, request, view):
        tenant = TenantContext.get_current_tenant()
        if not tenant or not tenant.is_active or TenantContext.is_global():
            return False
        if request.user.is_superuser:
            return bool(request.headers.get("X-Tenant-ID") or request.headers.get("X-Condominium-ID"))
        membership = TenantContext.get_current_membership()
        return bool(
            membership and membership.user_id == request.user.pk
            and membership.condominium_id == tenant.pk and membership.is_active
            and membership.role and membership.role.is_active
            and membership.role.slug.lower() in ("admin", "administrador", "superadmin")
        )


class DashboardView(APIView):
    permission_classes = [IsAuthenticated, CanConsultDashboard]

    @extend_schema(
        parameters=[DashboardPeriodSerializer],
        responses=DashboardResponseSerializer,
        tags=["CU30 - Dashboard"],
    )
    def get(self, request):
        parameters = DashboardPeriodSerializer(data=request.query_params)
        parameters.is_valid(raise_exception=True)
        metrics = dashboard(TenantContext.get_current_tenant(), **parameters.validated_data)
        response = Response(DashboardResponseSerializer(metrics).data)
        response["Cache-Control"] = "no-store"
        return response
