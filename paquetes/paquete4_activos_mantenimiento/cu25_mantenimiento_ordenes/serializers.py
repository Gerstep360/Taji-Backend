from rest_framework import serializers

from condominiums.models import Staff
from incidents.models import Incident, PriorityLevel
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
from .tenancy import tenant_assets, tenant_incidents, tenant_plans, tenant_suppliers


class AssetOptionSerializer(serializers.ModelSerializer):
    sector_name = serializers.CharField(source="sector.name", read_only=True, default="")
    asset_type_name = serializers.CharField(source="asset_type.name", read_only=True)

    class Meta:
        model = Asset
        fields = ("id", "code", "name", "status", "sector_name", "asset_type_name")


class StaffOptionSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="person.full_name", read_only=True)

    class Meta:
        model = Staff
        fields = ("id", "employee_code", "staff_type", "full_name")


class PriorityOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriorityLevel
        fields = ("id", "code", "name", "rank")


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = (
            "id",
            "name",
            "contact_name",
            "phone",
            "email",
            "specialty",
            "status",
            "notes",
        )
        read_only_fields = ("id",)

    def create(self, validated_data):
        validated_data["condominium_id"] = TenantContext.get_current_tenant_id()
        return super().create(validated_data)


class MaintenancePlanSerializer(serializers.ModelSerializer):
    asset_id = serializers.PrimaryKeyRelatedField(
        source="asset", queryset=Asset.objects.all()
    )
    asset_code = serializers.CharField(source="asset.code", read_only=True)
    asset_name = serializers.CharField(source="asset.name", read_only=True)

    class Meta:
        model = MaintenancePlan
        fields = (
            "id",
            "asset_id",
            "asset_code",
            "asset_name",
            "name",
            "description",
            "frequency_days",
            "last_completed_at",
            "next_due_at",
            "is_active",
            "created_at",
        )
        read_only_fields = ("id", "last_completed_at", "created_at")

    def validate_asset_id(self, asset):
        tenant_id = TenantContext.get_current_tenant_id()
        if not tenant_id or not tenant_assets(tenant_id).filter(pk=asset.pk).exists():
            raise serializers.ValidationError("El activo no pertenece al condominio actual.")
        return asset

    def validate_frequency_days(self, value):
        if value <= 0:
            raise serializers.ValidationError("La frecuencia debe ser mayor que cero.")
        return value


class WorkOrderAssignmentSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.CharField(
        source="assigned_to_staff.person.full_name", read_only=True
    )
    assigned_to_code = serializers.CharField(
        source="assigned_to_staff.employee_code", read_only=True, default=""
    )

    class Meta:
        model = WorkOrderAssignment
        fields = (
            "id",
            "assigned_to_staff",
            "assigned_to_name",
            "assigned_to_code",
            "assigned_by_user",
            "assigned_at",
            "ended_at",
            "reason",
        )


class WorkOrderAttachmentSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = WorkOrderAttachment
        fields = ("id", "file_type", "caption", "created_at", "download_url")

    def get_download_url(self, attachment):
        return f"/maintenance/orders/{attachment.work_order_id}/download-attachment/?attachment_id={attachment.pk}"


class WorkOrderCostItemSerializer(serializers.ModelSerializer):
    total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = WorkOrderCostItem
        fields = ("id", "description", "quantity", "unit_cost", "total", "created_at")
        read_only_fields = ("id", "total", "created_at")


class WorkOrderStatusHistorySerializer(serializers.ModelSerializer):
    changed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = WorkOrderStatusHistory
        fields = ("id", "from_status", "to_status", "notes", "changed_at", "changed_by_name")

    def get_changed_by_name(self, entry):
        person = getattr(entry.changed_by_user, "person", None)
        return person.full_name if person else ""


class WorkOrderSerializer(serializers.ModelSerializer):
    asset_id = serializers.PrimaryKeyRelatedField(
        source="asset",
        queryset=Asset.objects.all(),
        required=False,
        allow_null=True,
    )
    incident_id = serializers.PrimaryKeyRelatedField(
        source="incident",
        queryset=Incident.objects.all(),
        required=False,
        allow_null=True,
    )
    maintenance_plan_id = serializers.PrimaryKeyRelatedField(
        source="maintenance_plan",
        queryset=MaintenancePlan.objects.all(),
        required=False,
        allow_null=True,
    )
    priority_id = serializers.PrimaryKeyRelatedField(
        source="priority",
        queryset=PriorityLevel.objects.all(),
        required=False,
        allow_null=True,
    )
    asset_code = serializers.CharField(source="asset.code", read_only=True, default="")
    asset_name = serializers.CharField(source="asset.name", read_only=True, default="")
    incident_code = serializers.CharField(source="incident.public_code", read_only=True, default="")
    maintenance_plan_name = serializers.CharField(
        source="maintenance_plan.name", read_only=True, default=""
    )
    priority_name = serializers.CharField(source="priority.name", read_only=True, default="")
    supplier_id = serializers.IntegerField(read_only=True, allow_null=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default="")
    current_assignee_staff_id = serializers.IntegerField(read_only=True, allow_null=True)
    assignee_name = serializers.SerializerMethodField()
    assignments = WorkOrderAssignmentSerializer(many=True, read_only=True)
    attachments = WorkOrderAttachmentSerializer(many=True, read_only=True)
    cost_items = WorkOrderCostItemSerializer(many=True, read_only=True)
    status_history = WorkOrderStatusHistorySerializer(many=True, read_only=True)

    class Meta:
        model = WorkOrder
        fields = (
            "id",
            "public_code",
            "incident_id",
            "incident_code",
            "asset_id",
            "asset_code",
            "asset_name",
            "maintenance_plan_id",
            "maintenance_plan_name",
            "supplier_id",
            "supplier_name",
            "created_by_user",
            "current_assignee_staff_id",
            "assignee_name",
            "work_type",
            "priority_id",
            "priority_name",
            "title",
            "description",
            "status",
            "scheduled_for",
            "started_at",
            "completed_at",
            "estimated_cost",
            "actual_cost",
            "created_at",
            "updated_at",
            "assignments",
            "attachments",
            "cost_items",
            "status_history",
        )
        read_only_fields = (
            "id",
            "public_code",
            "created_by_user",
            "current_assignee_staff_id",
            "supplier_id",
            "status",
            "started_at",
            "completed_at",
            "actual_cost",
            "created_at",
            "updated_at",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tenant_id = TenantContext.get_current_tenant_id()
        self.fields["asset_id"].queryset = tenant_assets(tenant_id)
        self.fields["incident_id"].queryset = tenant_incidents(tenant_id)
        self.fields["maintenance_plan_id"].queryset = tenant_plans(tenant_id)

    def get_assignee_name(self, order) -> str:
        staff = order.current_assignee_staff
        return staff.person.full_name if staff and staff.person else ""

    def validate(self, attrs):
        tenant_id = TenantContext.get_current_tenant_id()
        asset = attrs.get("asset", getattr(self.instance, "asset", None))
        incident = attrs.get("incident", getattr(self.instance, "incident", None))
        plan = attrs.get(
            "maintenance_plan", getattr(self.instance, "maintenance_plan", None)
        )
        supplier = attrs.get("supplier", getattr(self.instance, "supplier", None))

        if not asset and not incident:
            raise serializers.ValidationError(
                {"asset_id": "Asocia la orden a un activo o a una incidencia."}
            )
        if asset and (
            not tenant_id or not tenant_assets(tenant_id).filter(pk=asset.pk).exists()
        ):
            raise serializers.ValidationError(
                {"asset_id": "El activo no pertenece al condominio actual."}
            )
        if incident and (
            not tenant_id
            or not tenant_incidents(tenant_id).filter(pk=incident.pk).exists()
        ):
            raise serializers.ValidationError(
                {"incident_id": "La incidencia no pertenece al condominio actual."}
            )
        if plan:
            if not tenant_id or not tenant_plans(tenant_id).filter(pk=plan.pk).exists():
                raise serializers.ValidationError(
                    {"maintenance_plan_id": "El plan no pertenece al condominio actual."}
                )
            if asset and plan.asset_id != asset.pk:
                raise serializers.ValidationError(
                    {"maintenance_plan_id": "El plan debe corresponder al activo seleccionado."}
                )
            if not asset:
                attrs["asset"] = plan.asset
        if supplier and (
            not tenant_id
            or not tenant_suppliers(tenant_id).filter(pk=supplier.pk).exists()
        ):
            raise serializers.ValidationError(
                {"supplier_id": "El proveedor no pertenece al condominio actual."}
            )
        return attrs


class WorkOrderAssignmentInputSerializer(serializers.Serializer):
    staff_id = serializers.IntegerField(required=False, min_value=1)
    supplier_id = serializers.IntegerField(required=False, min_value=1)
    reason = serializers.CharField(max_length=240, required=False, allow_blank=True)

    def validate(self, attrs):
        if bool(attrs.get("staff_id")) == bool(attrs.get("supplier_id")):
            raise serializers.ValidationError(
                "Debes indicar exactamente un técnico o un proveedor."
            )
        return attrs


class WorkOrderStatusInputSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=WorkOrder.Status.choices)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)
