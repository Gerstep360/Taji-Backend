from decimal import Decimal

from django.utils import timezone
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from accounts.models import User
from community.models import Agreement, AgreementAttachment, Assembly
from tenancy.context import TenantContext
from tenancy.models import TenantMembership

TERMINAL_AGREEMENT_STATUSES = (Agreement.Status.COMPLETED, Agreement.Status.CANCELLED)
OPEN_AGREEMENT_STATUSES = (Agreement.Status.PENDING, Agreement.Status.IN_PROGRESS, Agreement.Status.OVERDUE)
AGREEMENT_ASSEMBLY_STATUSES = (Assembly.Status.IN_PROGRESS, Assembly.Status.FINISHED)
ASSEMBLY_HEADER_FIELDS = ("title", "description", "scheduled_at", "location")


def _user_label(user):
    if not user:
        return ""
    person = getattr(user, "person", None)
    return (getattr(person, "full_name", "") or user.email) if person else user.email


class AssemblyPublicSerializer(serializers.ModelSerializer):
    """Vista de residentes: solo convocatoria, sin acta ni acuerdos."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Assembly
        fields = ("id", "title", "description", "scheduled_at", "location", "status", "status_display")
        read_only_fields = fields


@extend_schema_serializer(component_name="Cu29Assembly")
class AssemblySerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    agreements_count = serializers.SerializerMethodField()
    open_agreements_count = serializers.SerializerMethodField()

    class Meta:
        model = Assembly
        fields = (
            "id", "title", "description", "scheduled_at", "location", "status", "status_display",
            "minutes_text", "created_by_name", "agreements_count", "open_agreements_count",
            "created_at", "updated_at",
        )
        read_only_fields = ("status", "created_at", "updated_at")

    def get_created_by_name(self, obj):
        return _user_label(obj.created_by_user)

    def get_agreements_count(self, obj):
        value = getattr(obj, "agreements_total", None)
        return obj.agreements.count() if value is None else value

    def get_open_agreements_count(self, obj):
        value = getattr(obj, "agreements_open", None)
        if value is None:
            value = obj.agreements.filter(status__in=OPEN_AGREEMENT_STATUSES).count()
        return value

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("El título de la asamblea es obligatorio.")
        return value

    def validate(self, attrs):
        instance = self.instance
        if instance is None:
            when = attrs.get("scheduled_at")
            if when and when <= timezone.now():
                raise serializers.ValidationError({"scheduled_at": "La asamblea debe programarse en una fecha futura."})
            if attrs.get("minutes_text"):
                raise serializers.ValidationError({"minutes_text": "El acta se registra cuando la asamblea está en curso o finalizada."})
            return attrs

        changed_header = [f for f in ASSEMBLY_HEADER_FIELDS if f in attrs and attrs[f] != getattr(instance, f)]
        if changed_header and instance.status != Assembly.Status.SCHEDULED:
            raise serializers.ValidationError(
                "Solo se pueden editar los datos de una asamblea programada; después solo se registra el acta."
            )
        if "scheduled_at" in changed_header and attrs["scheduled_at"] <= timezone.now():
            raise serializers.ValidationError({"scheduled_at": "La asamblea debe programarse en una fecha futura."})
        if "minutes_text" in attrs and attrs["minutes_text"] != instance.minutes_text \
                and instance.status not in (Assembly.Status.IN_PROGRESS, Assembly.Status.FINISHED):
            raise serializers.ValidationError({"minutes_text": "El acta solo se registra con la asamblea en curso o finalizada."})
        return attrs


class AssemblyFinishSerializer(serializers.Serializer):
    minutes_text = serializers.CharField(trim_whitespace=True, min_length=10)


class AssemblyCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=200)


@extend_schema_serializer(component_name="Cu29Agreement")
class AgreementSerializer(serializers.ModelSerializer):
    assembly_title = serializers.CharField(source="assembly.title", read_only=True)
    responsible_user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True), required=False, allow_null=True
    )
    responsible_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    is_overdue = serializers.SerializerMethodField()
    attachments_count = serializers.SerializerMethodField()

    class Meta:
        model = Agreement
        fields = (
            "id", "assembly", "assembly_title", "title", "description",
            "responsible_user", "responsible_name", "due_at", "estimated_budget", "actual_cost",
            "status", "status_display", "is_overdue", "completed_at", "attachments_count",
            "created_at", "updated_at",
        )
        read_only_fields = ("status", "completed_at", "created_at", "updated_at")
        extra_kwargs = {
            "estimated_budget": {"min_value": Decimal("0")},
            "actual_cost": {"min_value": Decimal("0")},
        }

    def get_responsible_name(self, obj):
        return _user_label(obj.responsible_user)

    def get_is_overdue(self, obj):
        if obj.status == Agreement.Status.OVERDUE:
            return True
        return bool(obj.status in OPEN_AGREEMENT_STATUSES and obj.due_at and obj.due_at < timezone.now())

    def get_attachments_count(self, obj):
        value = getattr(obj, "attachments_total", None)
        return obj.attachments.count() if value is None else value

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("El título del acuerdo es obligatorio.")
        return value

    def validate_assembly(self, value):
        tenant = TenantContext.get_current_tenant_id()
        if value.condominium_id != tenant:
            raise serializers.ValidationError("La asamblea no pertenece a este condominio.")
        if value.status not in AGREEMENT_ASSEMBLY_STATUSES:
            raise serializers.ValidationError("Solo se registran acuerdos de asambleas en curso o finalizadas.")
        return value

    def validate_responsible_user(self, value):
        if value is None:
            return value
        tenant = TenantContext.get_current_tenant_id()
        is_member = TenantMembership.objects.filter(
            user=value, condominium_id=tenant, is_active=True
        ).exists()
        if not is_member:
            raise serializers.ValidationError("El responsable debe ser un miembro activo de este condominio.")
        return value

    def validate(self, attrs):
        instance = self.instance
        if instance is not None:
            if "assembly" in attrs and attrs["assembly"].pk != instance.assembly_id:
                raise serializers.ValidationError({"assembly": "No se puede mover un acuerdo a otra asamblea."})
            if instance.status in TERMINAL_AGREEMENT_STATUSES:
                raise serializers.ValidationError("Un acuerdo completado o cancelado ya no se puede editar.")

        now = timezone.now()
        due = attrs.get("due_at")
        if due and (instance is None or due != instance.due_at) and due <= now:
            raise serializers.ValidationError({"due_at": "El plazo debe ser una fecha futura."})

        status = instance.status if instance else Agreement.Status.PENDING
        actual = attrs.get("actual_cost", getattr(instance, "actual_cost", None))
        if actual is not None and status == Agreement.Status.PENDING:
            raise serializers.ValidationError(
                {"actual_cost": "Registra el costo real cuando el acuerdo esté en curso o completado."}
            )
        return attrs


class AgreementCompleteSerializer(serializers.Serializer):
    actual_cost = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False, allow_null=True)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=200)


class AgreementCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(trim_whitespace=True, min_length=3, max_length=200)


class AgreementStartSerializer(serializers.Serializer):
    comment = serializers.CharField(required=False, allow_blank=True, max_length=200)


class AgreementAttachmentSerializer(serializers.ModelSerializer):
    file_name = serializers.SerializerMethodField()
    uploaded_by_name = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = AgreementAttachment
        fields = ("id", "file_name", "description", "uploaded_by_name", "created_at", "download_url")
        read_only_fields = fields

    def get_file_name(self, obj):
        name = obj.file_path.rsplit("/", 1)[-1]
        return name.split("-", 1)[1] if "-" in name else name

    def get_uploaded_by_name(self, obj):
        return _user_label(obj.uploaded_by_user)

    def get_download_url(self, obj):
        return f"/api/v1/agreements/{obj.agreement_id}/attachments/{obj.pk}/download/"


class AgreementAttachmentUploadSerializer(serializers.Serializer):
    file = serializers.FileField(allow_empty_file=False)
    description = serializers.CharField(required=False, allow_blank=True, max_length=200)


class AgreementHistorySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    action_code = serializers.CharField()
    description = serializers.CharField()
    actor_name = serializers.CharField()
    occurred_at = serializers.DateTimeField()
    before_status = serializers.CharField(allow_null=True)
    after_status = serializers.CharField(allow_null=True)


class ResponsibleOptionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    role = serializers.CharField(allow_blank=True)
