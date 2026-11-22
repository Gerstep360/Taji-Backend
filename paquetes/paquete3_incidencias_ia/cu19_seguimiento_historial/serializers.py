"""Serializadores para CU19: Consultar seguimiento e historial de incidencia.

Incluye la representación de DTOs para listado (IncidenciaPageDTO), detalle completo
(DetalleIncidenciaDTO), historial cronológico de cambios de estado (T034), comentarios
públicos e internos (T037) y cálculo de fechas objetivo y SLA (T038).
"""

from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from accounts.models import User
from condominiums.models import Resident, Sector, Staff, Unit
from incidents.models import (
    Incident,
    IncidentAssignment,
    IncidentAttachment,
    IncidentCategory,
    IncidentComment,
    IncidentStatusHistory,
    PriorityLevel,
)
from .permissions import (
    can_change_incident_status,
    can_modify_target_date,
    can_view_internal_comments,
    can_post_internal_comments,
)


class AuthorUserSummarySerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="person.full_name", read_only=True, default="")
    role_name = serializers.CharField(source="role.name", read_only=True, default="")
    role_slug = serializers.CharField(source="role.slug", read_only=True, default="")

    class Meta:
        model = User
        fields = ("id", "email", "full_name", "role_name", "role_slug")


class StaffSummarySerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="person.full_name", read_only=True)
    staff_type_display = serializers.CharField(source="get_staff_type_display", read_only=True)

    class Meta:
        model = Staff
        fields = ("id", "employee_code", "full_name", "staff_type", "staff_type_display")


class ResidentSummarySerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="person.full_name", read_only=True)
    document_number = serializers.CharField(source="person.document_number", read_only=True)
    phone = serializers.CharField(source="person.phone", read_only=True)
    email = serializers.CharField(source="person.contact_email", read_only=True)

    class Meta:
        model = Resident
        fields = ("id", "full_name", "document_number", "phone", "email")


class SectorSummarySerializer(serializers.ModelSerializer):
    sector_type_display = serializers.CharField(source="get_sector_type_display", read_only=True)

    class Meta:
        model = Sector
        fields = ("id", "code", "name", "sector_type", "sector_type_display")


class UnitSummarySerializer(serializers.ModelSerializer):
    unit_type_display = serializers.CharField(source="get_unit_type_display", read_only=True)
    sector_name = serializers.CharField(source="sector.name", read_only=True, default="")

    class Meta:
        model = Unit
        fields = ("id", "code", "unit_type", "unit_type_display", "floor_label", "sector_name")


class CategorySummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = IncidentCategory
        fields = ("id", "code", "name", "default_staff_type")


class PrioritySummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = PriorityLevel
        fields = ("id", "code", "name", "rank", "target_minutes")


class IncidentStatusHistorySerializer(serializers.ModelSerializer):
    """T034: Serializador de historial de cambios de estado."""

    from_status_display = serializers.SerializerMethodField()
    to_status_display = serializers.CharField(source="get_to_status_display", read_only=True)
    changed_by = AuthorUserSummarySerializer(source="changed_by_user", read_only=True)

    class Meta:
        model = IncidentStatusHistory
        fields = (
            "id",
            "from_status",
            "from_status_display",
            "to_status",
            "to_status_display",
            "comment",
            "changed_at",
            "changed_by",
        )

    def get_from_status_display(self, obj) -> str:
        if not obj.from_status:
            return "Inicio"
        return dict(Incident.Status.choices).get(obj.from_status, obj.from_status)


class IncidentCommentSerializer(serializers.ModelSerializer):
    """T037: Serializador de comentarios públicos e internos."""

    visibility_display = serializers.CharField(source="get_visibility_display", read_only=True)
    author = AuthorUserSummarySerializer(source="author_user", read_only=True)

    class Meta:
        model = IncidentComment
        fields = ("id", "body", "visibility", "visibility_display", "created_at", "author")


class IncidentAssignmentSerializer(serializers.ModelSerializer):
    """Serializador de asignaciones históricas y vigentes de la incidencia."""

    assigned_to = StaffSummarySerializer(source="assigned_to_staff", read_only=True)
    assigned_by = AuthorUserSummarySerializer(source="assigned_by_user", read_only=True)
    is_active = serializers.SerializerMethodField()

    class Meta:
        model = IncidentAssignment
        fields = (
            "id",
            "assigned_to",
            "assigned_by",
            "assigned_at",
            "ended_at",
            "reason",
            "is_active",
        )

    def get_is_active(self, obj) -> bool:
        return obj.ended_at is None


class IncidentAttachmentSerializer(serializers.ModelSerializer):
    """Serializador de evidencias y adjuntos de incidencia."""

    file_type_display = serializers.CharField(source="get_file_type_display", read_only=True)
    uploaded_by = AuthorUserSummarySerializer(source="uploaded_by_user", read_only=True)
    file_url = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()

    def get_preview_url(self, obj) -> str | None:
        request = self.context.get('request')
        if not request or obj.file_type != IncidentAttachment.Type.IMAGE:
            return None
        from django.urls import reverse
        return request.build_absolute_uri(reverse('incident-tracking-preview-attachment', kwargs={
            'public_code':obj.incident.public_code, 'attachment_id':obj.pk,
        }))

    def get_file_url(self, obj) -> str | None:
        request = self.context.get("request")
        if not request:
            return None
        from django.urls import reverse
        return request.build_absolute_uri(reverse("incident-tracking-download-attachment", kwargs={
            "public_code": obj.incident.public_code, "attachment_id": obj.pk,
        }))

    class Meta:
        model = IncidentAttachment
        fields = (
            "id",
            "file_path",
            "file_url",
            "preview_url",
            "file_type",
            "file_type_display",
            "caption",
            "created_at",
            "uploaded_by",
        )


class IncidentListSerializer(serializers.ModelSerializer):
    """DTO para listado del Tablero de Incidencias (Paso 13 del diagrama)."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    category = CategorySummarySerializer(read_only=True)
    priority = PrioritySummarySerializer(read_only=True)
    sector = SectorSummarySerializer(read_only=True)
    unit = UnitSummarySerializer(read_only=True)
    current_assignee = StaffSummarySerializer(source="current_assignee_staff", read_only=True)
    reporter_user = AuthorUserSummarySerializer(read_only=True)
    reporter_resident = ResidentSummarySerializer(read_only=True)

    # T038 SLA y métricas temporales
    is_pending = serializers.BooleanField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    time_remaining_minutes = serializers.IntegerField(read_only=True)
    overdue_by_minutes = serializers.IntegerField(read_only=True)
    target_minutes = serializers.SerializerMethodField()

    # T034 Último cambio de estado (Paso 8-9)
    latest_status_change = serializers.SerializerMethodField()

    class Meta:
        model = Incident
        fields = (
            "id",
            "public_code",
            "title",
            "description",
            "status",
            "status_display",
            "category",
            "priority",
            "sector",
            "unit",
            "current_assignee",
            "reporter_user",
            "reporter_resident",
            "due_at",
            "resolved_at",
            "closed_at",
            "created_at",
            "updated_at",
            "is_pending",
            "is_overdue",
            "time_remaining_minutes",
            "overdue_by_minutes",
            "target_minutes",
            "latest_status_change",
        )

    def get_target_minutes(self, obj) -> int | None:
        return obj.priority.target_minutes if obj.priority else None

    def get_latest_status_change(self, obj) -> dict | None:
        history = getattr(obj, "status_history", None)
        latest = max(history.all(), key=lambda item: (item.changed_at, item.pk), default=None) if history else None
        if not latest:
            return None
        return {
            "from_status": latest.from_status,
            "to_status": latest.to_status,
            "to_status_display": latest.get_to_status_display(),
            "comment": latest.comment,
            "changed_at": latest.changed_at,
            "changed_by": latest.changed_by_user.person.full_name if latest.changed_by_user and latest.changed_by_user.person else "",
        }


class IncidentDetailSerializer(IncidentListSerializer):
    """DetalleIncidenciaDTO: Composición completa para seguimiento (Paso 40 del diagrama)."""

    status_history = serializers.SerializerMethodField()
    assignments = IncidentAssignmentSerializer(many=True, read_only=True)
    public_comments = serializers.SerializerMethodField()
    internal_comments = serializers.SerializerMethodField()
    attachments = IncidentAttachmentSerializer(many=True, read_only=True)

    can_view_internal_comments = serializers.SerializerMethodField()
    can_change_status = serializers.SerializerMethodField()
    can_modify_target_date = serializers.SerializerMethodField()
    can_post_internal_comments = serializers.SerializerMethodField()

    def get_can_post_internal_comments(self, obj) -> bool:
        request = self.context.get("request")
        return can_post_internal_comments(request.user) if request else False

    class Meta(IncidentListSerializer.Meta):
        fields = IncidentListSerializer.Meta.fields + (
            "status_history",
            "assignments",
            "public_comments",
            "internal_comments",
            "attachments",
            "can_view_internal_comments",
            "can_change_status",
            "can_modify_target_date",
            "can_post_internal_comments",
        )

    @extend_schema_field(IncidentStatusHistorySerializer(many=True))
    def get_status_history(self, obj):
        records = obj.status_history.select_related(
            "changed_by_user__person", "changed_by_user__role"
        ).order_by("changed_at", "id")
        return IncidentStatusHistorySerializer(records, many=True).data

    @extend_schema_field(IncidentCommentSerializer(many=True))
    def get_public_comments(self, obj):
        comments = obj.comments.filter(visibility=IncidentComment.Visibility.PUBLIC).select_related(
            "author_user__person", "author_user__role"
        ).order_by("created_at")
        return IncidentCommentSerializer(comments, many=True).data

    @extend_schema_field(IncidentCommentSerializer(many=True))
    def get_internal_comments(self, obj):
        request = self.context.get("request")
        user = request.user if request else None
        if not can_view_internal_comments(user):
            return []
        comments = obj.comments.filter(visibility=IncidentComment.Visibility.INTERNAL).select_related(
            "author_user__person", "author_user__role"
        ).order_by("created_at")
        return IncidentCommentSerializer(comments, many=True).data

    def get_can_view_internal_comments(self, obj) -> bool:
        request = self.context.get("request")
        return can_view_internal_comments(request.user) if request else False

    def get_can_change_status(self, obj) -> bool:
        request = self.context.get("request")
        return can_change_incident_status(request.user, obj, Incident.Status.RESOLVED) if request else False

    def get_can_modify_target_date(self, obj) -> bool:
        request = self.context.get("request")
        return can_modify_target_date(request.user) if request else False


class ChangeStatusRequestSerializer(serializers.Serializer):
    """T034: Solicitud de cambio de estado con comentario obligatorio u opcional."""

    status = serializers.ChoiceField(choices=Incident.Status.choices)
    comment = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class CreateCommentRequestSerializer(serializers.Serializer):
    """T037: Solicitud de creación de comentario público o interno."""

    body = serializers.CharField(required=True)
    visibility = serializers.ChoiceField(
        choices=IncidentComment.Visibility.choices,
        default=IncidentComment.Visibility.PUBLIC,
    )


class SetTargetDateRequestSerializer(serializers.Serializer):
    """T038: Solicitud de actualización de fecha objetivo de resolución."""

    due_at = serializers.DateTimeField(required=False, allow_null=True)
    target_minutes = serializers.IntegerField(required=False, min_value=1)

    def validate(self, attrs):
        if not attrs.get("due_at") and not attrs.get("target_minutes"):
            raise serializers.ValidationError("Debe indicar 'due_at' o 'target_minutes'.")
        return attrs


class CreateAttachmentRequestSerializer(serializers.Serializer):
    """Solicitud de registro de adjunto / evidencia fotográfica o documental."""

    file_path = serializers.CharField(max_length=500)
    file_type = serializers.ChoiceField(
        choices=IncidentAttachment.Type.choices, default=IncidentAttachment.Type.IMAGE
    )
    caption = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class IncidentFilterQuerySerializer(serializers.Serializer):
    """Parámetros de consulta y filtrado del Tablero de Incidencias."""

    search = serializers.CharField(required=False)
    status = serializers.CharField(required=False, help_text="Uno o varios estados separados por coma.")
    priority = serializers.CharField(required=False, help_text="Código (LOW, MEDIUM, HIGH, CRITICAL) o ID.")
    category = serializers.CharField(required=False, help_text="Código o ID de categoría.")
    sla_status = serializers.ChoiceField(
        choices=("overdue", "pending", "on_time", "resolved"),
        required=False,
        help_text="Filtro de SLA: vencidas (overdue), pendientes (pending), a tiempo (on_time), resueltas (resolved).",
    )
    is_overdue = serializers.BooleanField(required=False, default=None, allow_null=True, help_text="Filtrar específicamente si está vencida.")
    is_pending = serializers.BooleanField(required=False, default=None, allow_null=True, help_text="Filtrar solo pendientes.")
    scope = serializers.ChoiceField(
        choices=("GLOBAL", "PROPIAS", "ASIGNADAS", "IMPORTANTES"),
        required=False,
        help_text="Alcance de visualización.",
    )
    sector = serializers.IntegerField(required=False)
    unit = serializers.IntegerField(required=False)
    assignee = serializers.IntegerField(required=False)
    due_from = serializers.DateTimeField(required=False)
    due_to = serializers.DateTimeField(required=False)
    created_from = serializers.DateTimeField(required=False)
    created_to = serializers.DateTimeField(required=False)
    ordering = serializers.CharField(required=False, default="-created_at")

