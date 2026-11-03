from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from auditlog.services import record_audit_event
from maintenance.models import Asset, AssetType
from security.qr import encode_image_base64, render_qr_image
from tenancy.context import TenantContext

from .permissions import CanAccessAssets, HasAssetsTenant, can_manage
from .serializers import AssetSerializer, AssetTypeSerializer
from .tenancy import tenant_assets

ASSET_QR_PAYLOAD_PREFIX = "TAJI-ASSET"


@method_decorator(never_cache, name="dispatch")
@extend_schema_view(
    list=extend_schema(tags=["Activos - CU23"], summary="Listar tipos de activo"),
    retrieve=extend_schema(tags=["Activos - CU23"], summary="Consultar un tipo de activo"),
    create=extend_schema(tags=["Activos - CU23"], summary="Crear tipo de activo"),
    update=extend_schema(tags=["Activos - CU23"], summary="Editar tipo de activo"),
    partial_update=extend_schema(tags=["Activos - CU23"], summary="Editar tipo de activo"),
)
class AssetTypeViewSet(viewsets.ModelViewSet):
    """
    Catálogo de tipos de activo (ascensores, bombas, extintores...).

    No está segmentado por condominio: es un clasificador compartido por toda
    la plataforma, igual que `incidents.PriorityLevel`.
    """

    serializer_class = AssetTypeSerializer
    permission_classes = [IsAuthenticated, CanAccessAssets]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ("code", "name", "description")
    ordering_fields = ("name", "code")
    ordering = ("name",)
    queryset = AssetType.objects.all()

    def _require_manager(self):
        if not can_manage(self.request.user):
            raise PermissionDenied("Solo la administración puede gestionar tipos de activo.")

    def create(self, request, *args, **kwargs):
        self._require_manager()
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        self._require_manager()
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        self._require_manager()
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        self._require_manager()
        asset_type = self.get_object()
        if asset_type.assets.exists():
            raise ValidationError(
                {"detail": "No se puede eliminar un tipo con activos registrados. Desactívalo."}
            )
        asset_type.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(never_cache, name="dispatch")
@extend_schema_view(
    list=extend_schema(tags=["Activos - CU23"], summary="Listar activos del condominio"),
    retrieve=extend_schema(tags=["Activos - CU23"], summary="Consultar un activo"),
    create=extend_schema(tags=["Activos - CU23"], summary="Registrar un activo"),
    update=extend_schema(tags=["Activos - CU23"], summary="Editar un activo"),
    partial_update=extend_schema(tags=["Activos - CU23"], summary="Editar un activo"),
)
class AssetViewSet(viewsets.ModelViewSet):
    serializer_class = AssetSerializer
    permission_classes = [IsAuthenticated, HasAssetsTenant, CanAccessAssets]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ("code", "name", "brand", "model", "serial_number")
    ordering_fields = ("code", "name", "status", "created_at")
    ordering = ("name",)

    def get_queryset(self):
        queryset = tenant_assets(TenantContext.get_current_tenant_id()).select_related(
            "asset_type", "sector"
        )
        status_param = self.request.query_params.get("status")
        asset_type_param = self.request.query_params.get("asset_type")
        sector_param = self.request.query_params.get("sector")
        if status_param:
            queryset = queryset.filter(status=status_param.upper())
        if asset_type_param:
            queryset = queryset.filter(asset_type_id=asset_type_param)
        if sector_param:
            queryset = queryset.filter(sector_id=sector_param)
        return queryset

    def _require_manager(self):
        if not can_manage(self.request.user):
            raise PermissionDenied("Solo la administración puede gestionar el inventario de activos.")

    def create(self, request, *args, **kwargs):
        self._require_manager()
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        self._require_manager()
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        self._require_manager()
        return super().partial_update(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save()
        record_audit_event(
            action_code="ASSET_CREATED",
            resource_type="Asset",
            resource_id=serializer.instance.pk,
            description=f"Alta de activo {serializer.instance.code}.",
            actor_user=self.request.user,
            after_data={"status": serializer.instance.status},
            request=self.request,
        )

    def perform_update(self, serializer):
        before_status = serializer.instance.status
        instance = serializer.save()
        record_audit_event(
            action_code="ASSET_UPDATED",
            resource_type="Asset",
            resource_id=instance.pk,
            description=f"Actualización de activo {instance.code}.",
            actor_user=self.request.user,
            before_data={"status": before_status},
            after_data={"status": instance.status},
            request=self.request,
        )

    def destroy(self, request, *args, **kwargs):
        self._require_manager()
        asset = self.get_object()
        previous_status = asset.status
        asset.status = Asset.Status.RETIRED
        asset.save(update_fields=("status", "updated_at"))
        record_audit_event(
            action_code="ASSET_RETIRED",
            resource_type="Asset",
            resource_id=asset.pk,
            description=f"Baja lógica de activo {asset.code}.",
            actor_user=request.user,
            before_data={"status": previous_status},
            after_data={"status": asset.status},
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=("get",), url_path="qr")
    def qr(self, request, pk=None):
        """CU24 consulta este mismo `qr_uuid`; aquí solo se genera la imagen para imprimir/mostrar."""
        asset = self.get_object()
        payload = f"{ASSET_QR_PAYLOAD_PREFIX}.{asset.qr_uuid.hex}"
        image, media_type = render_qr_image(payload)
        return Response(
            {
                "asset_id": asset.pk,
                "payload": payload,
                "image_base64": encode_image_base64(image, "svg"),
                "image_media_type": media_type,
            }
        )

    @action(detail=True, methods=("get",), url_path="history")
    def history(self, request, pk=None):
        asset = self.get_object()
        incidents = asset.incidents.order_by("-created_at")[:50]
        work_orders = asset.work_orders.order_by("-created_at")[:50]
        plans = asset.maintenance_plans.order_by("-next_due_at")
        return Response(
            {
                "asset_id": asset.pk,
                "incidents": [
                    {
                        "id": incident.pk,
                        "public_code": incident.public_code,
                        "title": incident.title,
                        "status": incident.status,
                        "created_at": incident.created_at,
                    }
                    for incident in incidents
                ],
                "work_orders": [
                    {
                        "id": order.pk,
                        "public_code": order.public_code,
                        "title": order.title,
                        "work_type": order.work_type,
                        "status": order.status,
                        "scheduled_for": order.scheduled_for,
                        "completed_at": order.completed_at,
                        "created_at": order.created_at,
                    }
                    for order in work_orders
                ],
                "maintenance_plans": [
                    {
                        "id": plan.pk,
                        "name": plan.name,
                        "frequency_days": plan.frequency_days,
                        "last_completed_at": plan.last_completed_at,
                        "next_due_at": plan.next_due_at,
                        "is_active": plan.is_active,
                    }
                    for plan in plans
                ],
            }
        )
