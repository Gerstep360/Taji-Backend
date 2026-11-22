from django.utils import timezone
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from community.models import CommonArea, CommonAreaBlock, Reservation
from condominiums.models import Resident

from .services import ACTIVE_STATUSES, MAX_REASON


def _full_name(user):
    if not user:
        return ""
    person = getattr(user, "person", None)
    return getattr(person, "full_name", "") or user.email


def _primary_unit(resident):
    links = getattr(resident, "current_unit_links", None)
    if links is None:
        links = [link for link in resident.unit_links.all() if link.end_date is None]
    links = sorted(links, key=lambda link: (not link.is_primary, link.pk))
    return links[0].unit.code if links else ""


class ScheduleSerializer(serializers.Serializer):
    weekday = serializers.IntegerField()
    opens_at = serializers.TimeField(format="%H:%M")
    closes_at = serializers.TimeField(format="%H:%M")


@extend_schema_serializer(component_name="Cu27ReservableArea")
class AreaSerializer(serializers.ModelSerializer):
    sector_name = serializers.CharField(source="sector.name", read_only=True, default="")
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    schedules = serializers.SerializerMethodField()
    bookable = serializers.SerializerMethodField()
    upcoming_block = serializers.SerializerMethodField()

    class Meta:
        model = CommonArea
        fields = (
            "id", "name", "description", "sector", "sector_name", "capacity",
            "requires_approval", "status", "status_label", "bookable", "schedules",
            "upcoming_block",
        )

    def get_schedules(self, area):
        items = [s for s in area.schedules.all() if s.is_active]
        items.sort(key=lambda s: (s.weekday, s.opens_at))
        return ScheduleSerializer(items, many=True).data

    def get_bookable(self, area):
        return area.status == CommonArea.Status.AVAILABLE

    def get_upcoming_block(self, area):
        now = timezone.now()
        blocks = [b for b in area.blocks.all() if b.blocked_until > now]
        if not blocks:
            return None
        block = min(blocks, key=lambda b: b.blocked_from)
        return {
            "start": timezone.localtime(block.blocked_from).isoformat(),
            "end": timezone.localtime(block.blocked_until).isoformat(),
            "reason": block.reason,
        }


@extend_schema_serializer(component_name="Cu27Reservation")
class ReservationSerializer(serializers.ModelSerializer):
    common_area_name = serializers.CharField(source="common_area.name", read_only=True)
    resident_name = serializers.CharField(source="resident.person.full_name", read_only=True)
    resident_unit = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    decided_by_name = serializers.SerializerMethodField()
    cancelled_by_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    is_mine = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = Reservation
        fields = (
            "id", "common_area", "common_area_name", "resident", "resident_name",
            "resident_unit", "start_at", "end_at", "status", "status_label", "purpose",
            "approved_at", "decided_by_name", "rejection_reason", "cancelled_at",
            "cancelled_by_name", "cancellation_reason", "completed_at", "created_at",
            "created_by_name", "is_mine", "permissions",
        )
        read_only_fields = fields

    def _viewer(self):
        request = self.context.get("request")
        return getattr(request, "user", None)

    def get_resident_unit(self, obj):
        return _primary_unit(obj.resident)

    def get_decided_by_name(self, obj):
        return _full_name(obj.approved_by_user)

    def get_cancelled_by_name(self, obj):
        return _full_name(obj.cancelled_by_user)

    def get_created_by_name(self, obj):
        return _full_name(obj.created_by_user)

    def get_is_mine(self, obj):
        user = self._viewer()
        return bool(user and user.person_id and obj.resident.person_id == user.person_id)

    def get_permissions(self, obj):
        """Acciones disponibles para quien consulta (la API vuelve a validarlas)."""
        now = timezone.now()
        manager = bool(self.context.get("manager"))
        mine = self.get_is_mine(obj)
        active = obj.status in ACTIVE_STATUSES
        pending = obj.status == Reservation.Status.PENDING
        return {
            "approve": manager and pending and obj.start_at > now,
            "reject": manager and pending,
            "cancel": active and (
                (manager and obj.end_at > now) or (mine and obj.start_at > now)
            ),
            "complete": manager and obj.status == Reservation.Status.APPROVED and obj.start_at <= now,
        }


class ReservationCreateSerializer(serializers.Serializer):
    common_area = serializers.PrimaryKeyRelatedField(queryset=CommonArea.objects.none())
    resident = serializers.PrimaryKeyRelatedField(queryset=Resident.objects.none(), required=False, allow_null=True)
    start_at = serializers.DateTimeField()
    end_at = serializers.DateTimeField()
    purpose = serializers.CharField(max_length=MAX_REASON, required=False, allow_blank=True, default="")

    def __init__(self, *args, tenant_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["common_area"].queryset = CommonArea.objects.filter(condominium_id=tenant_id)
        self.fields["resident"].queryset = Resident.objects.all_tenants().filter(
            condominium_id=tenant_id, status=Resident.Status.ACTIVE
        )


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=MAX_REASON, required=False, allow_blank=True, default="")


class BlockCalendarSerializer(serializers.ModelSerializer):
    common_area_name = serializers.CharField(source="common_area.name", read_only=True)

    class Meta:
        model = CommonAreaBlock
        fields = ("id", "common_area", "common_area_name", "blocked_from", "blocked_until", "reason")


class ResidentOptionSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="person.full_name", read_only=True)
    unit = serializers.SerializerMethodField()

    class Meta:
        model = Resident
        fields = ("id", "full_name", "unit")

    def get_unit(self, obj):
        return _primary_unit(obj)
