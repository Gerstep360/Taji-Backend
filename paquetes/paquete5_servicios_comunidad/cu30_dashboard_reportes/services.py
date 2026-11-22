from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Count, F, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from community.models import Reservation
from incidents.models import Incident
from maintenance.models import WorkOrder
from security.models import AccessEvent


def period_bounds(date_from, date_to, zone, now):
    end = date_to or now.astimezone(zone).date()
    if not date(2, 1, 1) <= end < date(9999, 1, 1):
        raise ValidationError({"date_to": "Fecha fuera del rango permitido."})
    start = date_from or end - timedelta(days=29)
    if start < date(2, 1, 1) or end < start or (end - start).days >= 366:
        raise ValidationError({"date_from": "Indica un período válido de hasta 366 días."})
    return start, end, datetime.combine(start, time.min, zone), datetime.combine(
        end + timedelta(days=1), time.min, zone
    )


def consistent_tenant(tenant_id, *relations):
    scope = Q()
    for field, tenant_path in relations:
        scope &= Q(**{f"{field}__isnull": True}) | Q(**{tenant_path: tenant_id})
    return scope


def access_events(tenant_id):
    return AccessEvent.objects.filter(
        Q(unit__sector__condominium_id=tenant_id)
        | Q(authorization__unit__sector__condominium_id=tenant_id),
        consistent_tenant(
            tenant_id,
            ("unit", "unit__sector__condominium_id"),
            ("authorization", "authorization__unit__sector__condominium_id"),
            ("authorization", "authorization__authorized_by_resident__condominium_id"),
            ("guard_staff", "guard_staff__condominium_id"),
        ),
    ).filter(
        Q(unit__isnull=True) | Q(authorization__isnull=True) | Q(unit_id=F("authorization__unit_id"))
    )


def distribution(counts, choices):
    return [{"key": key, "label": str(label), "count": counts.get(key, 0)} for key, label in choices]


def summarize(queryset, field, choices, date_field, start, end, zone, **extra_counts):
    counts = queryset.aggregate(
        total=Count("pk"),
        **{key: Count("pk", filter=Q(**{field: key})) for key, _ in choices},
        **extra_counts,
    )
    rows = queryset.order_by().annotate(day=TruncDate(date_field, tzinfo=zone)).values("day")
    daily = {row["day"]: row["count"] for row in rows.annotate(count=Count("pk"))}
    days = (start + timedelta(days=offset) for offset in range((end - start).days + 1))
    return counts, {
        "total": counts["total"],
        "date_field": date_field,
        "by_status": distribution(counts, choices),
        "daily": [{"date": day, "count": daily.get(day, 0)} for day in days],
    }


def dashboard(tenant, date_from=None, date_to=None):
    now = timezone.now()
    try:
        zone = ZoneInfo(tenant.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        zone = timezone.get_default_timezone()
    start, end, lower, upper = period_bounds(date_from, date_to, zone, now)
    tenant_id = tenant.pk
    period = (start, end, zone)

    events = access_events(tenant_id).filter(occurred_at__gte=lower, occurred_at__lt=upper)
    counts, security = summarize(events, "event_type", AccessEvent.Type.choices, "occurred_at", *period)
    security["by_type"] = security.pop("by_status")
    types = AccessEvent.Type
    security.update(entries=counts[types.ENTRY], exits=counts[types.EXIT], denied=counts[types.DENIED])
    result_rows = events.order_by().values("validation_result").annotate(count=Count("pk"))
    security["by_result"] = distribution(
        {row["validation_result"]: row["count"] for row in result_rows}, AccessEvent.Result.choices
    )

    incidents = Incident.objects.filter(
        consistent_tenant(
            tenant_id,
            ("sector", "sector__condominium_id"),
            ("unit", "unit__sector__condominium_id"),
            ("asset", "asset__sector__condominium_id"),
            ("reporter_resident", "reporter_resident__condominium_id"),
            ("current_assignee_staff", "current_assignee_staff__condominium_id"),
        ),
        condominium_id=tenant_id, created_at__gte=lower, created_at__lt=upper,
    )
    status = Incident.Status
    counts, issues = summarize(incidents, "status", status.choices, "created_at", *period)
    issues.update(
        pending=sum(counts[key] for key in (status.REPORTED, status.REVIEWED, status.ASSIGNED, status.IN_PROGRESS)),
        resolved=counts[status.RESOLVED] + counts[status.CLOSED],
    )
    priorities = incidents.order_by("priority__rank", "priority_id").values(
        "priority__code", "priority__name"
    ).annotate(count=Count("pk"))
    issues["by_priority"] = [
        {"key": row["priority__code"] or "unassigned",
         "label": row["priority__name"] or "Sin prioridad", "count": row["count"]}
        for row in priorities
    ]

    orders = WorkOrder.objects.filter(
        consistent_tenant(
            tenant_id,
            ("incident", "incident__condominium_id"),
            ("asset", "asset__sector__condominium_id"),
            ("maintenance_plan", "maintenance_plan__asset__sector__condominium_id"),
            ("supplier", "supplier__condominium_id"),
            ("current_assignee_staff", "current_assignee_staff__condominium_id"),
        ),
        condominium_id=tenant_id, created_at__gte=lower, created_at__lt=upper,
    )
    status = WorkOrder.Status
    counts, maintenance = summarize(
        orders, "status", status.choices, "created_at", *period,
        overdue=Count("pk", filter=Q(
            scheduled_for__lt=now,
            status__in=(status.PENDING, status.ASSIGNED, status.IN_PROGRESS, status.PAUSED),
        )),
    )
    maintenance.update(
        pending=counts[status.PENDING] + counts[status.ASSIGNED],
        in_progress=counts[status.IN_PROGRESS] + counts[status.PAUSED],
        completed=counts[status.COMPLETED],
        overdue=counts["overdue"],
    )

    reservations = Reservation.objects.filter(
        consistent_tenant(tenant_id, ("common_area__sector", "common_area__sector__condominium_id")),
        common_area__condominium_id=tenant_id, resident__condominium_id=tenant_id,
        start_at__gte=lower, start_at__lt=upper,
    )
    status = Reservation.Status
    counts, bookings = summarize(reservations, "status", status.choices, "start_at", *period)
    bookings.update({key.value.lower(): counts[key] for key in status})
    areas = reservations.order_by("common_area__name", "common_area_id").values(
        "common_area_id", "common_area__name"
    ).annotate(count=Count("pk"))
    bookings["by_area"] = [
        {"key": str(row["common_area_id"]), "label": row["common_area__name"], "count": row["count"]}
        for row in areas
    ]

    return {
        "context": {"mode": "condominium", "id": tenant_id, "name": tenant.name, "timezone": str(zone)},
        "period": {"date_from": start, "date_to": end, "as_of": now},
        "unit": "records",
        "security": security,
        "incidents": issues,
        "maintenance": maintenance,
        "reservations": bookings,
        "has_data": any(section["total"] for section in (security, issues, maintenance, bookings)),
    }
