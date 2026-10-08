from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .catalog import SOURCES, scoped_queryset

EXPORT_LIMIT = 10000


def tenant_zone(tenant):
    try:
        return ZoneInfo(tenant.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("America/La_Paz")


def build_query(data, tenant):
    source = SOURCES[data["source"]]
    columns = {column.key: column for column in source.columns}
    queryset = scoped_queryset(data["source"], tenant.pk)
    for criterion in data["filters"]:
        column = columns[criterion["field"]]
        operator, value, path = criterion["operator"], criterion["value"].strip(), column.path
        if operator in ("is_empty", "not_empty"):
            empty = Q(**{f"{path}__isnull": True})
            if column.kind == "text":
                empty |= Q(**{path: ""})
            queryset = queryset.filter(empty) if operator == "is_empty" else queryset.exclude(empty)
            continue
        if column.kind in ("date", "datetime"):
            try:
                parsed = date.fromisoformat(value)
            except ValueError:
                raise ValidationError(f"{column.label}: utiliza una fecha válida AAAA-MM-DD.")
            if column.kind == "datetime":
                try:
                    start = datetime.combine(parsed, time.min, tenant_zone(tenant))
                    end = start + timedelta(days=1)
                except OverflowError:
                    raise ValidationError("La fecha está fuera del rango permitido.")
                if operator == "eq":
                    queryset = queryset.filter(**{f"{path}__gte": start, f"{path}__lt": end})
                elif operator == "gte":
                    queryset = queryset.filter(**{f"{path}__gte": start})
                else:
                    queryset = queryset.filter(**{f"{path}__lt": end})
                continue
            value = parsed
        elif column.kind == "number":
            try:
                value = int(value)
                if not -(2**31) <= value < 2**31:
                    raise ValueError
            except ValueError:
                raise ValidationError(f"{column.label}: utiliza un número entero válido.")
        lookup = {"eq": "exact", "ne": "exact", "contains": "icontains", "gte": "gte", "lte": "lte"}[operator]
        condition = {f"{path}__{lookup}": value}
        queryset = queryset.exclude(**condition) if operator == "ne" else queryset.filter(**condition)
    ordering = data["ordering"] or [{"field": source.ordering.lstrip("-"),
                                      "direction": "desc" if source.ordering.startswith("-") else "asc"}]
    paths = [("-" if item["direction"] == "desc" else "") + columns[item["field"]].path for item in ordering]
    # ID como desempate: páginas estables cuando los valores de orden coinciden.
    queryset = queryset.order_by(*paths, "pk")
    return queryset, [columns[key] for key in data["columns"]]


def rows_for(queryset, columns, tenant):
    paths = list(dict.fromkeys(column.path for column in columns))
    for record in queryset.values(*paths).iterator(chunk_size=500):
        row = []
        for column in columns:
            value = record[column.path]
            if value is None:
                value = ""
            elif column.kind == "choice":
                value = str(dict(column.choices).get(value, value))
            elif isinstance(value, datetime):
                value = timezone.localtime(value, tenant_zone(tenant)).strftime("%d/%m/%Y %H:%M")
            elif isinstance(value, date):
                value = value.strftime("%d/%m/%Y")
            row.append(value)
        yield row
