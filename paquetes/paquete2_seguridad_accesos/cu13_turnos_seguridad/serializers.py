"""Serializadores para CU13: Gestionar turnos del personal de seguridad."""

from datetime import datetime, time
from django.utils import timezone
from rest_framework import serializers

from condominiums.models import Condominium, Staff
from security.models import SecurityShift
from .timing import closing_timing, start_allowed_at, start_block_reason


class SecurityShiftSerializer(serializers.ModelSerializer):
    guard_staff = serializers.PrimaryKeyRelatedField(
        queryset=Staff.objects.all(),
        required=False,
    )
    guard_name = serializers.SerializerMethodField(read_only=True)
    guard_employee_code = serializers.SerializerMethodField(read_only=True)
    condominium = serializers.PrimaryKeyRelatedField(
        queryset=Condominium.objects.all(),
        required=False,
        allow_null=True,
    )
    condominium_name = serializers.SerializerMethodField(read_only=True)
    timing = serializers.SerializerMethodField(read_only=True)
    
    # Aliases de compatibilidad para RF-13 / prompt
    fecha = serializers.DateField(required=False, write_only=True)
    hora_inicio_planificada = serializers.TimeField(required=False, write_only=True)
    hora_fin_planificada = serializers.TimeField(required=False, write_only=True)
    
    hora_apertura_real = serializers.DateTimeField(source="opened_at", read_only=True)
    hora_cierre_real = serializers.DateTimeField(source="closed_at", read_only=True)
    estado = serializers.CharField(source="status", read_only=True)
    observacion_administrativa = serializers.CharField(
        source="observation", required=False, allow_blank=True
    )

    class Meta:
        model = SecurityShift
        fields = (
            "id",
            "condominium",
            "condominium_name",
            "guard_staff",
            "guard_name",
            "guard_employee_code",
            "scheduled_start",
            "scheduled_end",
            "opened_at",
            "closed_at",
            "status",
            "opening_notes",
            "closing_notes",
            "observation",
            "observacion_administrativa",
            "fecha",
            "hora_inicio_planificada",
            "hora_fin_planificada",
            "hora_apertura_real",
            "hora_cierre_real",
            "estado",
            "created_by_user",
            "created_at",
            "updated_at",
            "timing",
        )
        read_only_fields = (
            "id",
            "opened_at",
            "closed_at",
            "status",
            "created_by_user",
            "created_at",
            "updated_at",
        )

    def get_guard_name(self, obj) -> str:
        if obj.guard_staff and obj.guard_staff.person:
            return obj.guard_staff.person.full_name
        return ""

    def get_guard_employee_code(self, obj) -> str:
        if obj.guard_staff:
            return obj.guard_staff.employee_code or ""
        return ""

    def get_condominium_name(self, obj) -> str:
        if obj.condominium:
            return obj.condominium.name
        return ""

    def get_timing(self, obj) -> dict:
        now = self.context.setdefault("shift_server_time", timezone.now())
        open_shifts = self.context.setdefault("guard_open_shifts", {})
        if obj.guard_staff_id not in open_shifts:
            open_shifts[obj.guard_staff_id] = SecurityShift.objects.filter(
                guard_staff_id=obj.guard_staff_id, status=SecurityShift.Status.OPEN
            ).values_list("id", flat=True).first()
        other_id = open_shifts[obj.guard_staff_id]
        if other_id == obj.pk:
            other_id = None
        reason = start_block_reason(obj, now, other_id)
        close_at = obj.closed_at or now
        return {
            "server_time": now.isoformat(),
            "start_allowed_at": start_allowed_at(obj).isoformat(),
            "can_start": not reason,
            "start_block_reason": reason,
            "other_open_shift_id": other_id,
            "is_overdue": obj.status == SecurityShift.Status.OPEN and now >= obj.scheduled_end,
            "is_missed": obj.status == SecurityShift.Status.SCHEDULED and now >= obj.scheduled_end,
            "closing_timing": closing_timing(obj, close_at),
            "close_reason_required": obj.status == SecurityShift.Status.OPEN
            and closing_timing(obj, now) != "ON_TIME",
        }

    def validate(self, attrs):
        # 1. Resolver fechas y horas si vienen como fecha + hora_inicio_planificada + hora_fin_planificada
        fecha = attrs.pop("fecha", None)
        hora_inicio = attrs.pop("hora_inicio_planificada", None)
        hora_fin = attrs.pop("hora_fin_planificada", None)

        if fecha and hora_inicio and hora_fin:
            # Construir datetimes con la timezone actual
            current_tz = timezone.get_current_timezone()
            dt_start = datetime.combine(fecha, hora_inicio)
            dt_end = datetime.combine(fecha, hora_fin)
            if timezone.is_naive(dt_start):
                dt_start = timezone.make_aware(dt_start, current_tz)
            if timezone.is_naive(dt_end):
                dt_end = timezone.make_aware(dt_end, current_tz)
            attrs["scheduled_start"] = dt_start
            attrs["scheduled_end"] = dt_end

        scheduled_start = attrs.get("scheduled_start", getattr(self.instance, "scheduled_start", None))
        scheduled_end = attrs.get("scheduled_end", getattr(self.instance, "scheduled_end", None))
        guard_staff = attrs.get("guard_staff", getattr(self.instance, "guard_staff", None))

        if not scheduled_start:
            raise serializers.ValidationError({"scheduled_start": "La fecha/hora de inicio es obligatoria."})
        if not scheduled_end:
            raise serializers.ValidationError({"scheduled_end": "La fecha/hora de finalización es obligatoria."})
        if not guard_staff:
            raise serializers.ValidationError({"guard_staff": "El guardia de seguridad es obligatorio."})

        # 2. Regla 1: Solo personal perteneciente al área SEGURIDAD puede ser asignado
        if guard_staff.staff_type != Staff.Type.SECURITY:
            raise serializers.ValidationError(
                {"guard_staff": "Solo el personal perteneciente al área SEGURIDAD puede ser asignado a un turno."}
            )

        # Regla adicional: Debe estar activo
        if guard_staff.status != Staff.Status.ACTIVE:
            raise serializers.ValidationError(
                {"guard_staff": "El personal de seguridad asignado debe estar en estado ACTIVO."}
            )

        # 3. Regla 6: Hora fin debe ser posterior a hora inicio
        if scheduled_end <= scheduled_start:
            raise serializers.ValidationError(
                {"scheduled_end": "La hora de finalización debe ser estrictamente posterior a la hora de inicio."}
            )

        # 4. Regla 7: No permitir solapamientos para un mismo guardia
        # [ex_start, ex_end] solapa con [start, end] ssi ex_start < end AND ex_end > start
        overlapping_qs = SecurityShift.objects.filter(
            guard_staff=guard_staff,
            scheduled_start__lt=scheduled_end,
            scheduled_end__gt=scheduled_start,
        ).exclude(status=SecurityShift.Status.CANCELLED)

        if self.instance:
            overlapping_qs = overlapping_qs.exclude(pk=self.instance.pk)

        if overlapping_qs.exists():
            raise serializers.ValidationError(
                {"detail": "Existe solapamiento de horario con otro turno registrado para este guardia de seguridad."}
            )

        # Use the same current-condominium convention as CU03 when the
        # scheduling client does not provide an association. Preserve existing
        # associations when updating a shift.
        if not attrs.get("condominium"):
            condominium = getattr(self.instance, "condominium", None)
            if condominium is None:
                condominium = Condominium.objects.filter(is_active=True).first()
            if condominium is None:
                raise serializers.ValidationError({
                    "condominium": "Configura un condominio activo antes de programar turnos."
                })
            attrs["condominium"] = condominium

        return attrs


class ShiftActionSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, default="")
