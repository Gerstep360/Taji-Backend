from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from reports.serializers import CriterionSerializer, SortSerializer

from .report_catalog import SOURCES
from .services import period_bounds

FORMATS = ("xlsx", "csv", "html", "pdf")
EXPORT_LIMITS = {"xlsx": 5000, "csv": 5000, "html": 5000, "pdf": 1000}
LOOKUPS = {"eq": "exact", "ne": "exact", "contains": "icontains"}


class StrictFieldsMixin:
    def to_internal_value(self, data):
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError({
                "non_field_errors": "La solicitud contiene campos desconocidos.",
            })
        return super().to_internal_value(data)


class IsoDateField(serializers.DateField):
    def to_internal_value(self, value):
        parsed = super().to_internal_value(value)
        if isinstance(value, str) and parsed.isoformat() != value:
            raise serializers.ValidationError("Usa fechas en formato AAAA-MM-DD.")
        return parsed


class ReportCriterion(StrictFieldsMixin, CriterionSerializer):
    pass


class ReportSort(StrictFieldsMixin, SortSerializer):
    pass


class ReportQuery(StrictFieldsMixin, serializers.Serializer):
    source = serializers.ChoiceField(choices=tuple(SOURCES))
    columns = serializers.ListField(child=serializers.CharField(), min_length=1, max_length=12, required=False)
    filters = ReportCriterion(many=True, max_length=10, required=False, default=list)
    ordering = ReportSort(many=True, max_length=3, required=False, default=list)
    date_from = IsoDateField(required=False)
    date_to = IsoDateField(required=False)
    title = serializers.CharField(max_length=120, allow_blank=True, required=False, default="")
    page = serializers.IntegerField(min_value=1, max_value=1000000, required=False, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False, default=25)


class ReportExportQuery(ReportQuery):
    format = serializers.ChoiceField(choices=FORMATS)


def tenant_zone(tenant):
    try:
        return ZoneInfo(tenant.timezone)
    except (ValueError, ZoneInfoNotFoundError):
        return timezone.get_default_timezone()


def filter_by_column(queryset, column, operator, value, zone):
    path = column.path
    if operator in ("is_empty", "not_empty"):
        empty = Q(**{f"{path}__isnull": True})
        if column.kind == "text":
            empty |= Q(**{path: ""})
        return queryset.filter(empty) if operator == "is_empty" else queryset.exclude(empty)

    if not value or (column.kind == "choice" and value not in dict(column.choices)):
        raise serializers.ValidationError({"filters": "El filtro contiene un valor inválido."})
    if column.kind == "datetime":
        try:
            day = date.fromisoformat(value)
        except ValueError:
            raise serializers.ValidationError({"filters": "Usa fechas en formato AAAA-MM-DD."}) from None
        if day.isoformat() != value or not date(2, 1, 1) <= day < date(9999, 1, 1):
            raise serializers.ValidationError({"filters": "Fecha de filtro inválida."})
        start = datetime.combine(day, time.min, zone)
        end = datetime.combine(day + timedelta(days=1), time.min, zone)
        if operator != "lte":
            queryset = queryset.filter(**{f"{path}__gte": start})
        if operator != "gte":
            queryset = queryset.filter(**{f"{path}__lt": end})
        return queryset

    criterion = {f"{path}__{LOOKUPS[operator]}": value}
    return queryset.exclude(**criterion) if operator == "ne" else queryset.filter(**criterion)


def prepare_report(data, source, tenant):
    columns = {column.key: column for column in source.columns}
    selected = data.get("columns", list(columns))
    if len(set(selected)) != len(selected) or not set(selected) <= columns.keys():
        raise serializers.ValidationError({"columns": "Selecciona columnas permitidas sin repetir."})
    ordering = data["ordering"] or [{"field": source.date_field, "direction": "desc"}]
    keys = [item["field"] for item in ordering]
    if len(set(keys)) != len(keys) or not set(keys) <= columns.keys():
        raise serializers.ValidationError({"ordering": "Selecciona columnas de orden válidas sin repetir."})

    zone = tenant_zone(tenant)
    start, end, lower, upper = period_bounds(data.get("date_from"), data.get("date_to"), zone, timezone.now())
    queryset = source.scoped(tenant.pk).filter(
        **{f"{source.date_field}__gte": lower, f"{source.date_field}__lt": upper}
    )
    for criterion in data["filters"]:
        column = columns.get(criterion["field"])
        operator = criterion["operator"]
        if column is None or operator not in column.operators:
            raise serializers.ValidationError({"filters": "El filtro contiene una columna u operador inválido."})
        queryset = filter_by_column(queryset, column, operator, criterion["value"].strip(), zone)

    paths = [
        ("-" if item["direction"] == "desc" else "") + columns[item["field"]].path
        for item in ordering
    ]
    return queryset.order_by(*paths, "pk"), [columns[key] for key in selected], {
        "date_from": start, "date_to": end, "timezone": str(zone),
    }
