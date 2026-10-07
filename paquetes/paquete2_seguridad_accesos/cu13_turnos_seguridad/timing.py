"""Reglas horarias compartidas por las consultas y acciones de CU13."""

from datetime import timedelta

from security.models import SecurityShift


EARLY_START_MINUTES = 15


def start_allowed_at(shift):
    return shift.scheduled_start - timedelta(minutes=EARLY_START_MINUTES)


def start_block_reason(shift, now, other_open_shift_id=None):
    if shift.status != SecurityShift.Status.SCHEDULED:
        return "Solo se puede iniciar un turno PROGRAMADO."
    if now >= shift.scheduled_end:
        return "El horario de este turno ya finalizó; quedó sin iniciar."
    if now < start_allowed_at(shift):
        return "Puedes iniciar el turno desde 15 minutos antes de su hora programada."
    if other_open_shift_id:
        return "Este guardia ya tiene otro turno abierto. Debe cerrarlo antes de iniciar uno nuevo."
    return ""


def closing_timing(shift, closed_at):
    if closed_at < shift.scheduled_end:
        return "EARLY"
    if closed_at > shift.scheduled_end:
        return "LATE"
    return "ON_TIME"
