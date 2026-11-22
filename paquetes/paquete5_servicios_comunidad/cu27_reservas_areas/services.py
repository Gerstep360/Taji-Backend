"""Reglas de negocio del CU27.

T049: ciclo de vida PENDIENTE -> APROBADA/RECHAZADA -> CANCELADA/COMPLETADA.
T050: no solapamiento. Doble barrera:
  1. Lógica: ``validate_slot`` revisa reservas activas, bloqueos y horarios con
     la fila del área bloqueada (``SELECT ... FOR UPDATE``), lo que serializa
     las solicitudes concurrentes sobre la misma área.
  2. PostgreSQL: la restricción ``ex_reservation_no_overlap`` (EXCLUDE USING
     gist, migración community 0003) rechaza cualquier cruce que logre pasar;
     el ``IntegrityError`` resultante se traduce a un error de negocio.
"""
from datetime import datetime, time, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from auditlog.services import record_audit_event
from community.models import CommonArea, CommonAreaBlock, Reservation

ACTIVE_STATUSES = (Reservation.Status.PENDING, Reservation.Status.APPROVED)
MIN_DURATION = timedelta(minutes=30)
MAX_DURATION = timedelta(hours=12)
MAX_ADVANCE = timedelta(days=180)
MAX_REASON = 240
EXPIRED_PENDING_REASON = "Vencida: no fue aprobada antes de su inicio."
CONFLICT_MESSAGE = "El horario ya está reservado o bloqueado. Elige otro horario."


# ---------------------------------------------------------------------------
# Utilidades de tiempo e intervalos
# ---------------------------------------------------------------------------
def local_day_bounds(day):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    end = timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min), tz)
    return start, end


def _merge(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def subtract_intervals(windows, busy):
    """Devuelve ``windows`` menos ``busy`` (ambos listas de tuplas [inicio, fin))."""
    busy = _merge(busy)
    free = []
    for w_start, w_end in windows:
        cursor = w_start
        for b_start, b_end in busy:
            if b_end <= cursor or b_start >= w_end:
                continue
            if b_start > cursor:
                free.append((cursor, b_start))
            cursor = max(cursor, b_end)
            if cursor >= w_end:
                break
        if cursor < w_end:
            free.append((cursor, w_end))
    return free


def schedule_windows(area, day):
    """Ventanas de atención del área para un día local.

    Sin horarios activos configurados el área se considera abierta todo el día
    (mismo criterio que la API comunitaria existente). Si tiene horarios pero
    ninguno para ese día de la semana, está cerrada.
    """
    day_start, day_end = local_day_bounds(day)
    schedules = list(area.schedules.filter(is_active=True))
    if not schedules:
        return [(day_start, day_end)], False
    tz = timezone.get_current_timezone()
    windows = []
    for schedule in schedules:
        if schedule.weekday != day.weekday():
            continue
        start = timezone.make_aware(datetime.combine(day, schedule.opens_at), tz)
        end = timezone.make_aware(datetime.combine(day, schedule.closes_at), tz)
        windows.append((start, end))
    return _merge(windows), True


# ---------------------------------------------------------------------------
# Validación de un horario (T050, capa lógica)
# ---------------------------------------------------------------------------
def overlapping_reservations(area, start, end, exclude_pk=None):
    qs = Reservation.objects.filter(
        common_area=area, status__in=ACTIVE_STATUSES, start_at__lt=end, end_at__gt=start
    )
    return qs.exclude(pk=exclude_pk) if exclude_pk else qs


def overlapping_blocks(area, start, end):
    return CommonAreaBlock.objects.filter(
        common_area=area, blocked_from__lt=end, blocked_until__gt=start
    )


def validate_slot(area, start, end, *, exclude_pk=None, now=None):
    now = now or timezone.now()
    if not start or not end:
        raise ValidationError({"start_at": "Indica la fecha y hora de inicio y fin."})
    if end <= start:
        raise ValidationError({"end_at": "La hora final debe ser posterior a la inicial."})
    if start <= now:
        raise ValidationError({"start_at": "Selecciona una fecha y hora futura."})
    if start > now + MAX_ADVANCE:
        raise ValidationError({"start_at": "Solo se puede reservar con hasta 180 días de anticipación."})
    duration = end - start
    if duration < MIN_DURATION:
        raise ValidationError({"end_at": "La reserva debe durar al menos 30 minutos."})
    if duration > MAX_DURATION:
        raise ValidationError({"end_at": "La reserva no puede durar más de 12 horas."})
    if area.status != CommonArea.Status.AVAILABLE:
        raise ValidationError({"common_area": "El área no está disponible para reservar."})

    local_start, local_end = timezone.localtime(start), timezone.localtime(end)
    windows, has_schedule = schedule_windows(area, local_start.date())
    same_day = local_start.date() == local_end.date() or (
        local_end.time() == time.min and local_end.date() == local_start.date() + timedelta(days=1)
        and not has_schedule
    )
    if not same_day or not any(w_start <= start and end <= w_end for w_start, w_end in windows):
        raise ValidationError({"start_at": "El horario está fuera de la disponibilidad del área."})

    if overlapping_blocks(area, start, end).exists():
        raise ValidationError({"non_field_errors": ["El área está bloqueada en ese horario."]})
    if overlapping_reservations(area, start, end, exclude_pk).exists():
        raise ValidationError({"non_field_errors": [CONFLICT_MESSAGE]})


# ---------------------------------------------------------------------------
# Disponibilidad (T121)
# ---------------------------------------------------------------------------
def _iso(value):
    return timezone.localtime(value).isoformat()


def compute_availability(area, day, *, viewer_person_id=None, manager=False, now=None):
    now = now or timezone.now()
    day_start, day_end = local_day_bounds(day)
    windows, has_schedule = schedule_windows(area, day)

    reservations = (
        Reservation.objects.filter(
            common_area=area, status__in=ACTIVE_STATUSES, start_at__lt=day_end, end_at__gt=day_start
        )
        .select_related("resident__person")
        .order_by("start_at")
    )
    blocks = overlapping_blocks(area, day_start, day_end).order_by("blocked_from")

    occupied = []
    for item in reservations:
        mine = bool(viewer_person_id and item.resident.person_id == viewer_person_id)
        entry = {
            "kind": "RESERVATION",
            "id": item.pk if (manager or mine) else None,
            "start": _iso(max(item.start_at, day_start)),
            "end": _iso(min(item.end_at, day_end)),
            "status": item.status,
            "mine": mine,
            "label": item.resident.person.full_name if manager else ("Tu reserva" if mine else "Reservado"),
        }
        occupied.append(entry)
    for block in blocks:
        occupied.append({
            "kind": "BLOCK",
            "id": None,
            "start": _iso(max(block.blocked_from, day_start)),
            "end": _iso(min(block.blocked_until, day_end)),
            "status": "BLOCKED",
            "mine": False,
            "label": block.reason or "Bloqueado",
        })
    occupied.sort(key=lambda entry: entry["start"])

    busy = [(r.start_at, r.end_at) for r in reservations] + [(b.blocked_from, b.blocked_until) for b in blocks]
    if now > day_start:
        busy.append((day_start, min(max(now, day_start), day_end)))
    free = [
        {"start": _iso(start), "end": _iso(end)}
        for start, end in subtract_intervals(windows, busy)
        if end - start >= MIN_DURATION
    ]

    reason = ""
    if area.status != CommonArea.Status.AVAILABLE:
        reason = "El área no está disponible para reservar."
    elif day_end <= now:
        reason = "La fecha ya pasó."
    elif day_start > now + MAX_ADVANCE:
        reason = "Solo se puede reservar con hasta 180 días de anticipación."
    elif not windows:
        reason = "El área no atiende este día."
    elif not free:
        reason = "No quedan horarios libres este día."

    return {
        "date": day.isoformat(),
        "area": {
            "id": area.pk,
            "name": area.name,
            "status": area.status,
            "requires_approval": area.requires_approval,
            "capacity": area.capacity,
        },
        "has_schedule": has_schedule,
        "is_open": bool(windows),
        "bookable": not reason,
        "reason": reason,
        "min_duration_minutes": int(MIN_DURATION.total_seconds() // 60),
        "max_duration_minutes": int(MAX_DURATION.total_seconds() // 60),
        "windows": [{"start": _iso(s), "end": _iso(e)} for s, e in windows],
        "occupied": occupied,
        "free": free,
    }


# ---------------------------------------------------------------------------
# Ciclo de vida (T049)
# ---------------------------------------------------------------------------
def _audit(action, reservation, actor, request, before=None, description=""):
    record_audit_event(
        action_code=f"CU27_RESERVATION_{action}",
        resource_type="Reservation",
        resource_id=reservation.pk,
        description=description,
        actor_user=actor,
        before_data={"status": before} if before else None,
        after_data={"status": reservation.status},
        request=request,
    )


def _clean_reason(reason, *, required, field):
    reason = (reason or "").strip()
    if required and len(reason) < 3:
        raise ValidationError({field: "Indica un motivo (mínimo 3 caracteres)."})
    if len(reason) > MAX_REASON:
        raise ValidationError({field: f"El motivo no puede superar {MAX_REASON} caracteres."})
    return reason


def _lock(reservation):
    """Bloquea el área y relee la reserva dentro de la transacción actual."""
    CommonArea.objects.select_for_update().filter(pk=reservation.common_area_id).first()
    return Reservation.objects.select_for_update().select_related("common_area").get(pk=reservation.pk)


def _save_guarded(reservation, fields):
    try:
        with transaction.atomic():
            reservation.save(update_fields=fields)
    except IntegrityError:
        raise ValidationError({"non_field_errors": [CONFLICT_MESSAGE]}) from None


@transaction.atomic
def create_reservation(*, area, resident, start, end, purpose, actor, manager, request=None):
    area = CommonArea.objects.select_for_update().get(pk=area.pk)
    validate_slot(area, start, end)
    now = timezone.now()
    approved = manager or not area.requires_approval
    reservation = Reservation(
        common_area=area,
        resident=resident,
        created_by_user=actor,
        start_at=start,
        end_at=end,
        purpose=(purpose or "").strip(),
        status=Reservation.Status.APPROVED if approved else Reservation.Status.PENDING,
        approved_by_user=actor if (approved and manager) else None,
        approved_at=now if approved else None,
    )
    try:
        with transaction.atomic():
            reservation.save()
    except IntegrityError:
        raise ValidationError({"non_field_errors": ["El horario acaba de ser reservado. Elige otro."]}) from None
    _audit("CREATED", reservation, actor, request)
    return reservation


@transaction.atomic
def approve_reservation(reservation, *, actor, request=None):
    reservation = _lock(reservation)
    if reservation.status != Reservation.Status.PENDING:
        raise ValidationError({"status": "Solo se pueden aprobar reservas pendientes."})
    if reservation.start_at <= timezone.now():
        raise ValidationError({"status": "La reserva ya comenzó; no puede aprobarse. Recházala."})
    validate_slot(reservation.common_area, reservation.start_at, reservation.end_at, exclude_pk=reservation.pk)
    before = reservation.status
    reservation.status = Reservation.Status.APPROVED
    reservation.approved_by_user, reservation.approved_at = actor, timezone.now()
    _save_guarded(reservation, ["status", "approved_by_user", "approved_at"])
    _audit("APPROVED", reservation, actor, request, before)
    return reservation


@transaction.atomic
def reject_reservation(reservation, *, actor, reason, request=None):
    reason = _clean_reason(reason, required=True, field="reason")
    reservation = _lock(reservation)
    if reservation.status != Reservation.Status.PENDING:
        raise ValidationError({"status": "Solo se pueden rechazar reservas pendientes."})
    before = reservation.status
    reservation.status = Reservation.Status.REJECTED
    reservation.approved_by_user, reservation.approved_at = actor, timezone.now()
    reservation.rejection_reason = reason
    reservation.save(update_fields=["status", "approved_by_user", "approved_at", "rejection_reason"])
    _audit("REJECTED", reservation, actor, request, before, reason)
    return reservation


@transaction.atomic
def cancel_reservation(reservation, *, actor, reason, manager, request=None):
    reservation = _lock(reservation)
    now = timezone.now()
    owner = bool(actor.person_id and reservation.resident.person_id == actor.person_id)
    if reservation.status not in ACTIVE_STATUSES:
        raise ValidationError({"status": "Esta reserva ya está cerrada."})
    if manager:
        if reservation.end_at <= now:
            raise ValidationError({"status": "La reserva ya terminó; finalízala en lugar de cancelarla."})
        reason = _clean_reason(reason, required=not owner, field="reason")
    else:
        if not owner:
            raise PermissionDenied("Solo puedes cancelar tus propias reservas.")
        if reservation.start_at <= now:
            raise ValidationError({"status": "Solo puedes cancelar tu reserva antes de que comience."})
        reason = _clean_reason(reason, required=False, field="reason")
    before = reservation.status
    reservation.status = Reservation.Status.CANCELLED
    reservation.cancelled_at, reservation.cancelled_by_user = now, actor
    reservation.cancellation_reason = reason
    reservation.save(update_fields=["status", "cancelled_at", "cancelled_by_user", "cancellation_reason"])
    _audit("CANCELLED", reservation, actor, request, before, reason)
    return reservation


@transaction.atomic
def complete_reservation(reservation, *, actor, request=None):
    reservation = _lock(reservation)
    if reservation.status != Reservation.Status.APPROVED:
        raise ValidationError({"status": "Solo se pueden finalizar reservas aprobadas."})
    if reservation.start_at > timezone.now():
        raise ValidationError({"status": "La reserva aún no comienza; cancélala si no se usará."})
    before = reservation.status
    reservation.status = Reservation.Status.COMPLETED
    reservation.completed_at = timezone.now()
    reservation.save(update_fields=["status", "completed_at"])
    _audit("COMPLETED", reservation, actor, request, before)
    return reservation


def sync_expired(tenant_id=None, *, now=None):
    """Cierra automáticamente las reservas vencidas.

    - APROBADA cuyo fin ya pasó  -> COMPLETADA.
    - PENDIENTE cuyo inicio ya pasó (no puede aprobarse) -> RECHAZADA.
    Devuelve ``(completadas, vencidas)``.
    """
    now = now or timezone.now()
    base = Reservation.objects.all()
    if tenant_id is not None:
        base = base.filter(common_area__condominium_id=tenant_id)
    completed = expired = 0
    with transaction.atomic():
        for item in base.filter(status=Reservation.Status.APPROVED, end_at__lte=now).select_for_update(of=("self",)):
            item.status, item.completed_at = Reservation.Status.COMPLETED, item.end_at
            item.save(update_fields=["status", "completed_at"])
            _audit("AUTO_COMPLETED", item, None, None, Reservation.Status.APPROVED)
            completed += 1
        for item in base.filter(status=Reservation.Status.PENDING, start_at__lte=now).select_for_update(of=("self",)):
            item.status, item.rejection_reason, item.approved_at = (
                Reservation.Status.REJECTED, EXPIRED_PENDING_REASON, now,
            )
            item.save(update_fields=["status", "rejection_reason", "approved_at"])
            _audit("EXPIRED", item, None, None, Reservation.Status.PENDING)
            expired += 1
    return completed, expired
