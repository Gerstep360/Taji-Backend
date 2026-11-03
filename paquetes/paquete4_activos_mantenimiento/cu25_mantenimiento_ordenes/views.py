import os
import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from auditlog.services import record_audit_event
from condominiums.models import Staff
from incidents.models import PriorityLevel
from maintenance.models import (
    Asset,
    MaintenancePlan,
    Supplier,
    WorkOrder,
    WorkOrderAssignment,
    WorkOrderAttachment,
    WorkOrderCostItem,
    WorkOrderStatusHistory,
)
from tenancy.context import TenantContext
from .permissions import (
    CanAccessMaintenance,
    HasMaintenanceTenant,
    can_manage,
    worker_permissions,
)
from .serializers import (
    AssetOptionSerializer,
    MaintenancePlanSerializer,
    PriorityOptionSerializer,
    StaffOptionSerializer,
    SupplierSerializer,
    WorkOrderAssignmentInputSerializer,
    WorkOrderCostItemSerializer,
    WorkOrderSerializer,
    WorkOrderStatusInputSerializer,
)
from .tenancy import (
    current_tenant,
    tenant_assets,
    tenant_plans,
    tenant_suppliers,
    tenant_work_orders,
)


WORK_ORDER_TRANSITIONS = {
    WorkOrder.Status.PENDING: {WorkOrder.Status.ASSIGNED, WorkOrder.Status.CANCELLED},
    WorkOrder.Status.ASSIGNED: {
        WorkOrder.Status.IN_PROGRESS,
        WorkOrder.Status.CANCELLED,
    },
    WorkOrder.Status.IN_PROGRESS: {
        WorkOrder.Status.PAUSED,
        WorkOrder.Status.COMPLETED,
        WorkOrder.Status.CANCELLED,
    },
    WorkOrder.Status.PAUSED: {
        WorkOrder.Status.IN_PROGRESS,
        WorkOrder.Status.CANCELLED,
    },
    WorkOrder.Status.COMPLETED: set(),
    WorkOrder.Status.CANCELLED: set(),
}


def _record_status_change(order, user, new_status, notes, request):
    previous_status = order.status
    order.status = new_status
    fields = ["status", "updated_at"]
    now = timezone.now()
    if new_status == WorkOrder.Status.IN_PROGRESS and not order.started_at:
        order.started_at = now
        fields.append("started_at")
    if new_status == WorkOrder.Status.COMPLETED:
        order.completed_at = now
        fields.append("completed_at")
    if new_status == WorkOrder.Status.CANCELLED:
        active_assignment = order.assignments.filter(ended_at__isnull=True).first()
        if active_assignment:
            active_assignment.ended_at = now
            active_assignment.reason = notes.strip() or "Orden cancelada."
            active_assignment.save(update_fields=("ended_at", "reason"))
        order.current_assignee_staff = None
        order.supplier = None
        fields.extend(("current_assignee_staff", "supplier"))
    order.save(update_fields=fields)
    WorkOrderStatusHistory.objects.create(
        work_order=order,
        changed_by_user=user,
        from_status=previous_status,
        to_status=new_status,
        notes=notes.strip(),
    )
    if new_status == WorkOrder.Status.COMPLETED and order.maintenance_plan_id:
        plan = order.maintenance_plan
        plan.last_completed_at = now
        plan.next_due_at = now + timedelta(days=plan.frequency_days)
        plan.save(update_fields=("last_completed_at", "next_due_at"))
    record_audit_event(
        action_code="WORK_ORDER_STATUS_CHANGED",
        resource_type="WorkOrder",
        resource_id=order.pk,
        description=f"Orden {order.public_code}: {previous_status} → {new_status}.",
        actor_user=user,
        before_data={"status": previous_status},
        after_data={"status": new_status, "notes": notes.strip()},
        request=request,
    )


def _staff_for_user(user, tenant_id):
    if not getattr(user, "person_id", None):
        return None
    return Staff.objects.filter(
        person_id=user.person_id,
        condominium_id=tenant_id,
        status=Staff.Status.ACTIVE,
    ).first()


@method_decorator(never_cache, name="dispatch")
class MaintenanceAssetOptionsViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = AssetOptionSerializer
    permission_classes = [IsAuthenticated, HasMaintenanceTenant, CanAccessMaintenance]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ("code", "name", "sector__name")
    ordering_fields = ("code", "name", "status")
    ordering = ("name",)

    def get_queryset(self):
        return tenant_assets(TenantContext.get_current_tenant_id()).select_related(
            "asset_type", "sector"
        )


@method_decorator(never_cache, name="dispatch")
class MaintenanceStaffOptionsViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = StaffOptionSerializer
    permission_classes = [IsAuthenticated, HasMaintenanceTenant, CanAccessMaintenance]
    filter_backends = [filters.SearchFilter]
    search_fields = ("person__first_name", "person__last_name", "employee_code")

    def get_queryset(self):
        return Staff.objects.filter(
            condominium_id=TenantContext.get_current_tenant_id(),
            status=Staff.Status.ACTIVE,
            staff_type__in=(Staff.Type.MAINTENANCE, Staff.Type.ADMINISTRATION, Staff.Type.OTHER),
        ).select_related("person")


@method_decorator(never_cache, name="dispatch")
class MaintenancePriorityOptionsViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = PriorityOptionSerializer
    permission_classes = [IsAuthenticated, HasMaintenanceTenant, CanAccessMaintenance]
    queryset = PriorityLevel.objects.filter(is_active=True)
    ordering = ("rank",)


@method_decorator(never_cache, name="dispatch")
class MaintenancePlanViewSet(viewsets.ModelViewSet):
    serializer_class = MaintenancePlanSerializer
    permission_classes = [IsAuthenticated, HasMaintenanceTenant, CanAccessMaintenance]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ("next_due_at", "created_at", "name")
    ordering = ("next_due_at",)

    def get_queryset(self):
        queryset = tenant_plans(TenantContext.get_current_tenant_id()).select_related(
            "asset", "asset__sector"
        )
        asset_id = self.request.query_params.get("asset")
        active = self.request.query_params.get("active")
        if asset_id:
            queryset = queryset.filter(asset_id=asset_id)
        if active in ("true", "false"):
            queryset = queryset.filter(is_active=active == "true")
        return queryset

    def _require_manager(self):
        if not can_manage(self.request.user):
            raise PermissionDenied("Solo la administración puede gestionar planes preventivos.")

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
        plan = self.get_object()
        if plan.work_orders.filter(
            status__in=(WorkOrder.Status.PENDING, WorkOrder.Status.ASSIGNED,
                        WorkOrder.Status.IN_PROGRESS, WorkOrder.Status.PAUSED)
        ).exists():
            raise ValidationError(
                {"detail": "No se puede eliminar un plan con órdenes de trabajo abiertas."}
            )
        plan.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def perform_create(self, serializer):
        serializer.save()
        record_audit_event(
            action_code="MAINTENANCE_PLAN_CREATED",
            resource_type="MaintenancePlan",
            resource_id=serializer.instance.pk,
            actor_user=self.request.user,
            request=self.request,
        )


@method_decorator(never_cache, name="dispatch")
class MaintenanceSupplierViewSet(viewsets.ModelViewSet):
    serializer_class = SupplierSerializer
    permission_classes = [IsAuthenticated, HasMaintenanceTenant, CanAccessMaintenance]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ("name", "contact_name", "email", "specialty")
    ordering_fields = ("name", "status")
    ordering = ("name",)

    def get_queryset(self):
        queryset = tenant_suppliers(TenantContext.get_current_tenant_id())
        status_param = self.request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status=status_param.upper())
        return queryset

    def _require_manager(self):
        if not can_manage(self.request.user):
            raise PermissionDenied("Solo la administración puede gestionar proveedores.")

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
        supplier = self.get_object()
        supplier.status = Supplier.Status.INACTIVE
        supplier.save(update_fields=("status",))
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    list=extend_schema(tags=["Mantenimiento - CU25"], summary="Listar órdenes de trabajo"),
    retrieve=extend_schema(tags=["Mantenimiento - CU25"], summary="Consultar una orden"),
    create=extend_schema(tags=["Mantenimiento - CU25"], summary="Crear una orden de trabajo"),
    update=extend_schema(tags=["Mantenimiento - CU25"], summary="Editar una orden"),
    partial_update=extend_schema(tags=["Mantenimiento - CU25"], summary="Editar una orden"),
)
@method_decorator(never_cache, name="dispatch")
class WorkOrderViewSet(viewsets.ModelViewSet):
    serializer_class = WorkOrderSerializer
    permission_classes = [IsAuthenticated, HasMaintenanceTenant, CanAccessMaintenance]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = (
        "public_code",
        "title",
        "description",
        "asset__name",
        "asset__code",
        "supplier__name",
        "current_assignee_staff__person__first_name",
        "current_assignee_staff__person__last_name",
    )
    ordering_fields = ("created_at", "scheduled_for", "status", "work_type", "public_code")
    ordering = ("-created_at",)
    parser_classes = (JSONParser, FormParser, MultiPartParser)

    def get_queryset(self):
        tenant_id = TenantContext.get_current_tenant_id()
        queryset = tenant_work_orders(tenant_id).select_related(
            "asset",
            "asset__sector",
            "incident",
            "maintenance_plan",
            "supplier",
            "created_by_user",
            "current_assignee_staff__person",
            "priority",
        ).prefetch_related(
            "assignments__assigned_to_staff__person",
            "attachments",
            "cost_items",
            "status_history__changed_by_user__person",
        )

        if not can_manage(self.request.user):
            conditions = Q()
            staff = _staff_for_user(self.request.user, tenant_id)
            if staff:
                conditions |= Q(current_assignee_staff=staff)
            if self.request.user.email:
                conditions |= Q(supplier__email__iexact=self.request.user.email)
            queryset = queryset.filter(conditions)

        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status=params["status"].upper())
        if params.get("work_type"):
            queryset = queryset.filter(work_type=params["work_type"].upper())
        if params.get("asset"):
            queryset = queryset.filter(asset_id=params["asset"])
        if params.get("assignee"):
            queryset = queryset.filter(current_assignee_staff_id=params["assignee"])
        if params.get("date_from"):
            queryset = queryset.filter(scheduled_for__date__gte=params["date_from"])
        if params.get("date_to"):
            queryset = queryset.filter(scheduled_for__date__lte=params["date_to"])
        return queryset.distinct()

    def create(self, request, *args, **kwargs):
        if not can_manage(request.user):
            raise PermissionDenied("Solo la administración puede crear órdenes de trabajo.")
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if not can_manage(request.user):
            raise PermissionDenied("Solo la administración puede editar órdenes de trabajo.")
        if self.get_object().status in (
            WorkOrder.Status.COMPLETED,
            WorkOrder.Status.CANCELLED,
        ):
            raise ValidationError({"status": "No se puede editar una orden cerrada."})
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if not can_manage(request.user):
            raise PermissionDenied("Solo la administración puede editar órdenes de trabajo.")
        if self.get_object().status in (
            WorkOrder.Status.COMPLETED,
            WorkOrder.Status.CANCELLED,
        ):
            raise ValidationError({"status": "No se puede editar una orden cerrada."})
        return super().partial_update(request, *args, **kwargs)

    def perform_update(self, serializer):
        order = serializer.save()
        record_audit_event(
            action_code="WORK_ORDER_UPDATED",
            resource_type="WorkOrder",
            resource_id=order.pk,
            description=f"Orden {order.public_code} actualizada.",
            actor_user=self.request.user,
            after_data={
                "title": order.title,
                "asset_id": order.asset_id,
                "scheduled_for": (
                    order.scheduled_for.isoformat() if order.scheduled_for else None
                ),
                "estimated_cost": (
                    str(order.estimated_cost)
                    if order.estimated_cost is not None
                    else None
                ),
            },
            request=self.request,
        )

    def perform_create(self, serializer):
        tenant = current_tenant()
        order = serializer.save(
            condominium=tenant,
            created_by_user=self.request.user,
            public_code=f"OT-{timezone.now():%y%m%d}-{uuid.uuid4().hex[:6].upper()}",
        )
        WorkOrderStatusHistory.objects.create(
            work_order=order,
            changed_by_user=self.request.user,
            from_status="",
            to_status=order.status,
            notes="Orden creada.",
        )
        record_audit_event(
            action_code="WORK_ORDER_CREATED",
            resource_type="WorkOrder",
            resource_id=order.pk,
            description=f"Orden {order.public_code} creada.",
            actor_user=self.request.user,
            after_data={"status": order.status, "work_type": order.work_type},
            request=self.request,
        )

    def destroy(self, request, *args, **kwargs):
        if not can_manage(request.user):
            raise PermissionDenied("Solo la administración puede cancelar órdenes.")
        order = self.get_object()
        if order.status in (WorkOrder.Status.COMPLETED, WorkOrder.Status.CANCELLED):
            raise ValidationError({"status": "La orden ya está cerrada."})
        with transaction.atomic():
            order = WorkOrder.objects.all_tenants().select_for_update().get(pk=order.pk)
            _record_status_change(
                order,
                request.user,
                WorkOrder.Status.CANCELLED,
                "Cancelada por la administración.",
                request,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=("post",), url_path="assign")
    def assign(self, request, pk=None):
        if not can_manage(request.user):
            raise PermissionDenied("Solo la administración puede asignar órdenes.")
        order = self.get_object()
        serializer = WorkOrderAssignmentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        tenant_id = TenantContext.get_current_tenant_id()
        staff = None
        supplier = None
        if values.get("staff_id"):
            staff = Staff.objects.filter(
                pk=values["staff_id"],
                condominium_id=tenant_id,
                status=Staff.Status.ACTIVE,
                staff_type__in=(Staff.Type.MAINTENANCE, Staff.Type.ADMINISTRATION, Staff.Type.OTHER),
            ).select_related("person").first()
            if not staff:
                raise ValidationError({"staff_id": "El técnico no está activo en este condominio."})
        if values.get("supplier_id"):
            supplier = tenant_suppliers(tenant_id).filter(
                pk=values["supplier_id"], status=Supplier.Status.ACTIVE
            ).first()
            if not supplier:
                raise ValidationError(
                    {"supplier_id": "El proveedor no está activo en este condominio."}
                )
        if order.status in (WorkOrder.Status.COMPLETED, WorkOrder.Status.CANCELLED):
            raise ValidationError({"status": "No se puede asignar una orden cerrada."})

        with transaction.atomic():
            order = WorkOrder.objects.all_tenants().select_for_update().get(pk=order.pk)
            active_assignment = order.assignments.filter(ended_at__isnull=True).first()
            if active_assignment:
                active_assignment.ended_at = timezone.now()
                active_assignment.reason = values.get("reason", "").strip()
                active_assignment.save(update_fields=("ended_at", "reason"))
            if staff:
                WorkOrderAssignment.objects.create(
                    work_order=order,
                    assigned_to_staff=staff,
                    assigned_by_user=request.user,
                    reason=values.get("reason", "").strip(),
                )
            previous = order.status
            order.current_assignee_staff = staff
            order.supplier = supplier
            if order.status in (WorkOrder.Status.PENDING, WorkOrder.Status.ASSIGNED):
                order.status = WorkOrder.Status.ASSIGNED
            order.save(
                update_fields=(
                    "current_assignee_staff",
                    "supplier",
                    "status",
                    "updated_at",
                )
            )
            WorkOrderStatusHistory.objects.create(
                work_order=order,
                changed_by_user=request.user,
                from_status=previous,
                to_status=order.status,
                notes=values.get("reason", "").strip(),
            )
            record_audit_event(
                action_code="WORK_ORDER_ASSIGNED",
                resource_type="WorkOrder",
                resource_id=order.pk,
                actor_user=request.user,
                before_data={"status": previous},
                after_data={
                    "status": order.status,
                    "staff_id": staff.pk if staff else None,
                    "supplier_id": supplier.pk if supplier else None,
                    "reason": values.get("reason", "").strip(),
                },
                request=request,
            )
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=("post",), url_path="status")
    def change_status(self, request, pk=None):
        order = self.get_object()
        serializer = WorkOrderStatusInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        next_status = serializer.validated_data["status"]
        notes = serializer.validated_data.get("notes", "")
        is_manager = can_manage(request.user)
        permissions = worker_permissions(request.user)
        if not is_manager and "update_work_order_status" not in permissions:
            raise PermissionDenied("No tienes permiso para cambiar el estado de esta orden.")
        if not is_manager:
            staff = _staff_for_user(request.user, TenantContext.get_current_tenant_id())
            assigned_to_user = bool(staff and order.current_assignee_staff_id == staff.pk)
            supplier_user = bool(
                order.supplier_id
                and order.supplier.email
                and order.supplier.email.casefold() == request.user.email.casefold()
            )
            if not assigned_to_user and not supplier_user:
                raise PermissionDenied("Solo puedes actualizar una orden asignada a tu usuario.")
            if next_status not in (
                WorkOrder.Status.IN_PROGRESS,
                WorkOrder.Status.PAUSED,
                WorkOrder.Status.COMPLETED,
            ):
                raise ValidationError(
                    {"status": "El personal asignado solo puede iniciar, pausar o completar la orden."}
                )
        if next_status not in WORK_ORDER_TRANSITIONS[order.status]:
            raise ValidationError(
                {"status": f"No se permite cambiar de {order.status} a {next_status}."}
            )
        if (
            next_status == WorkOrder.Status.ASSIGNED
            and not order.current_assignee_staff_id
            and not order.supplier_id
        ):
            raise ValidationError(
                {"status": "Asigna un técnico o proveedor antes de marcar la orden como asignada."}
            )
        with transaction.atomic():
            locked = WorkOrder.objects.all_tenants().select_for_update().get(pk=order.pk)
            if next_status not in WORK_ORDER_TRANSITIONS[locked.status]:
                raise ValidationError(
                    {"status": f"No se permite cambiar de {locked.status} a {next_status}."}
                )
            _record_status_change(locked, request.user, next_status, notes, request)
        return Response(self.get_serializer(locked).data)

    @action(detail=True, methods=("post",), url_path="cost-items")
    def add_cost_item(self, request, pk=None):
        if not can_manage(request.user):
            raise PermissionDenied("Solo la administración puede registrar costos.")
        order = self.get_object()
        serializer = WorkOrderCostItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            item = serializer.save(work_order=order)
            _sync_actual_cost(order)
            record_audit_event(
                action_code="WORK_ORDER_COST_ADDED",
                resource_type="WorkOrder",
                resource_id=order.pk,
                actor_user=request.user,
                after_data={
                    "cost_item_id": item.pk,
                    "description": item.description,
                    "total": str(item.total),
                },
                request=request,
            )
        return Response(
            self.get_serializer(WorkOrder.objects.get(pk=order.pk)).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=("delete",),
        url_path=r"cost-items/(?P<item_id>[^/.]+)",
    )
    def delete_cost_item(self, request, pk=None, item_id=None):
        if not can_manage(request.user):
            raise PermissionDenied("Solo la administración puede editar costos.")
        order = self.get_object()
        item = order.cost_items.filter(pk=item_id).first()
        if not item:
            raise NotFound("No se encontró la partida de costo.")
        with transaction.atomic():
            item.delete()
            _sync_actual_cost(order)
        return Response(
            self.get_serializer(WorkOrder.objects.get(pk=order.pk)).data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=("post",),
        url_path="attachments",
        parser_classes=(MultiPartParser, FormParser),
    )
    def add_attachment(self, request, pk=None):
        order = self.get_object()
        if not can_manage(request.user):
            if "attach_work_evidence" not in worker_permissions(request.user):
                raise PermissionDenied("No tienes permiso para adjuntar evidencias.")
            staff = _staff_for_user(request.user, TenantContext.get_current_tenant_id())
            assigned = bool(staff and order.current_assignee_staff_id == staff.pk)
            supplier = bool(
                order.supplier_id
                and order.supplier.email
                and order.supplier.email.casefold() == request.user.email.casefold()
            )
            if not assigned and not supplier:
                raise PermissionDenied("Solo puedes adjuntar evidencias a una orden asignada.")

        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            raise ValidationError({"file": "Selecciona un archivo."})
        if uploaded_file.size > 20 * 1024 * 1024:
            raise ValidationError({"file": "El archivo no puede superar 20 MB."})
        extension = os.path.splitext(uploaded_file.name)[1].lower()
        allowed_types = {
            ".jpg": WorkOrderAttachment.Type.IMAGE,
            ".jpeg": WorkOrderAttachment.Type.IMAGE,
            ".png": WorkOrderAttachment.Type.IMAGE,
            ".webp": WorkOrderAttachment.Type.IMAGE,
            ".pdf": WorkOrderAttachment.Type.DOCUMENT,
            ".mp4": WorkOrderAttachment.Type.VIDEO,
        }
        file_type = allowed_types.get(extension)
        if not file_type:
            raise ValidationError(
                {"file": "Formatos permitidos: JPG, PNG, WEBP, PDF y MP4."}
            )
        stored_path = default_storage.save(
            f"maintenance/work-orders/{TenantContext.get_current_tenant_id()}/{uuid.uuid4().hex}{extension}",
            uploaded_file,
        )
        try:
            attachment = WorkOrderAttachment.objects.create(
                work_order=order,
                uploaded_by_user=request.user,
                file_path=stored_path,
                file_type=file_type,
                caption=str(request.data.get("caption", "")).strip()[:200],
            )
        except Exception:
            default_storage.delete(stored_path)
            raise
        record_audit_event(
            action_code="WORK_ORDER_EVIDENCE_ADDED",
            resource_type="WorkOrder",
            resource_id=order.pk,
            actor_user=request.user,
            after_data={"attachment_id": attachment.pk, "file_type": file_type},
            request=request,
        )
        return Response(
            self.get_serializer(WorkOrder.objects.get(pk=order.pk)).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=("get",), url_path="download-attachment")
    def download_attachment(self, request, pk=None):
        order = self.get_object()
        attachment_id = request.query_params.get("attachment_id")
        attachment = order.attachments.filter(pk=attachment_id).first()
        if not attachment:
            raise NotFound("No se encontró la evidencia solicitada.")
        if not can_manage(request.user):
            staff = _staff_for_user(request.user, TenantContext.get_current_tenant_id())
            assigned = bool(staff and order.current_assignee_staff_id == staff.pk)
            supplier = bool(
                order.supplier_id
                and order.supplier.email
                and order.supplier.email.casefold() == request.user.email.casefold()
            )
            if not assigned and not supplier:
                raise PermissionDenied("No puedes consultar evidencias de esta orden.")
        try:
            file_handle = default_storage.open(attachment.file_path, "rb")
        except FileNotFoundError as error:
            raise NotFound("El archivo de evidencia ya no está disponible.") from error
        response = FileResponse(file_handle, as_attachment=True)
        response["Content-Disposition"] = (
            f'attachment; filename="evidencia-{attachment.pk}{os.path.splitext(attachment.file_path)[1]}"'
        )
        return response


def _sync_actual_cost(order):
    cost_items = list(WorkOrderCostItem.objects.filter(work_order_id=order.pk))
    total = sum(
        (item.total for item in cost_items),
        Decimal("0.00"),
    )
    order.actual_cost = total if cost_items else None
    order.save(update_fields=("actual_cost", "updated_at"))
