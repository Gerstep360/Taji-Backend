import json
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .catalog import SOURCES, scoped_queryset

EXPORT_LIMIT = 10000


def tenant_zone(tenant):
    try:
        return ZoneInfo(getattr(tenant, "timezone", "America/La_Paz"))
    except (ZoneInfoNotFoundError, ValueError, AttributeError):
        return ZoneInfo("America/La_Paz")


def strip_accents(text):
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn").lower()


def build_query(data, tenant):
    """Construye y valida el queryset aislado para el reporte."""
    source_key = data["source"]
    source = SOURCES[source_key]
    columns = {column.key: column for column in source.columns}
    queryset = scoped_queryset(source_key, tenant.pk)

    for criterion in data.get("filters", []):
        field_name = criterion["field"]
        if field_name not in columns:
            continue
        column = columns[field_name]
        operator = criterion["operator"]
        value = str(criterion.get("value", "")).strip()
        path = column.path

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

        lookup = {
            "eq": "exact",
            "ne": "exact",
            "contains": "icontains",
            "gte": "gte",
            "lte": "lte",
        }.get(operator, "exact")
        condition = {f"{path}__{lookup}": value}
        queryset = queryset.exclude(**condition) if operator == "ne" else queryset.filter(**condition)

    ordering = data.get("ordering") or [
        {
            "field": source.ordering.lstrip("-"),
            "direction": "desc" if source.ordering.startswith("-") else "asc",
        }
    ]
    paths = [
        ("-" if item["direction"] == "desc" else "") + columns[item["field"]].path
        for item in ordering
        if item["field"] in columns
    ]
    queryset = queryset.order_by(*paths, "pk")

    requested_cols = data.get("columns") or list(source.defaults)
    selected_cols = [columns[key] for key in requested_cols if key in columns]
    if not selected_cols:
        selected_cols = [columns[key] for key in source.defaults if key in columns]

    return queryset, selected_cols


def rows_for(queryset, columns, tenant):
    """Generador que produce las filas formateadas y con zona horaria del condominio."""
    paths = list(dict.fromkeys(column.path for column in columns))
    for record in queryset.values(*paths).iterator(chunk_size=500):
        row = []
        for column in columns:
            value = record.get(column.path)
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


class VoiceReportService:
    """Servicio de inteligencia de voz para el Caso de Uso 31.
    
    Permite interpretar consultas y dictados por voz (en lenguaje natural o audio),
    transformándolas en parámetros de consulta estructurados, y generar la síntesis
    narrativa (guion hablado) para retroalimentación por voz.
    """

    @classmethod
    def parse_voice_query(cls, voice_text, tenant=None):
        """Interpreta un comando de voz y devuelve los parámetros estructurados."""
        raw_text = (voice_text or "").strip()
        normalized = strip_accents(raw_text)

        source = cls._detect_source(normalized)
        filters = cls._detect_filters(source, normalized, tenant)
        ordering = cls._detect_ordering(source, normalized)
        format_detected = cls._detect_format(normalized)
        title = f"Reporte por voz: {raw_text}" if raw_text else SOURCES[source].label

        return {
            "source": source,
            "columns": list(SOURCES[source].defaults),
            "filters": filters,
            "ordering": ordering,
            "title": title[:120],
            "format": format_detected,
            "raw_text": raw_text,
        }

    @classmethod
    def _detect_source(cls, normalized):
        if any(w in normalized for w in ("incidencia", "reclamo", "problema", "averia", "falla", "caso")):
            return "incidents"
        if any(w in normalized for w in ("residente", "vecino", "habitante", "propietario", "inquilino")):
            return "residents"
        if any(w in normalized for w in ("personal", "empleado", "trabajador", "limpieza", "conserje", "staff")):
            return "staff"
        if any(w in normalized for w in ("unidad", "departamento", "depto", "casa", "local", "inmueble")):
            return "units"
        if any(w in normalized for w in ("novedad", "bitacora", "alerta", "evento", "suceso")):
            return "logs"
        if any(w in normalized for w in ("entrega", "relevo", "consigna", "recepcion de turno")):
            return "handovers"
        if any(w in normalized for w in ("turno", "ronda", "guardia", "porteria")):
            return "shifts"
        return "incidents"

    @classmethod
    def _detect_filters(cls, source, normalized, tenant=None):
        filters = []
        today = timezone.localdate()

        # Detección de fechas
        if "hoy" in normalized:
            date_field = "created_at" if source == "incidents" else "occurred_at" if source == "logs" else "registered_at" if source == "residents" else "scheduled_start" if source == "shifts" else None
            if date_field:
                filters.append({"field": date_field, "operator": "gte", "value": today.isoformat()})
        elif "ayer" in normalized:
            yesterday = today - timedelta(days=1)
            date_field = "created_at" if source == "incidents" else "occurred_at" if source == "logs" else None
            if date_field:
                filters.append({"field": date_field, "operator": "gte", "value": yesterday.isoformat()})
        elif any(w in normalized for w in ("esta semana", "ultimos 7 dias", "ultimos dias")):
            week_ago = today - timedelta(days=7)
            date_field = "created_at" if source == "incidents" else "occurred_at" if source == "logs" else "scheduled_start" if source == "shifts" else None
            if date_field:
                filters.append({"field": date_field, "operator": "gte", "value": week_ago.isoformat()})
        elif any(w in normalized for w in ("este mes", "ultimo mes", "ultimos 30 dias")):
            month_ago = today - timedelta(days=30)
            date_field = "created_at" if source == "incidents" else "occurred_at" if source == "logs" else None
            if date_field:
                filters.append({"field": date_field, "operator": "gte", "value": month_ago.isoformat()})

        # Detección de estados en incidencias
        if source == "incidents":
            if any(w in normalized for w in ("pendiente", "reportada", "nueva", "abierta")):
                filters.append({"field": "status", "operator": "eq", "value": "REPORTED"})
            elif any(w in normalized for w in ("progreso", "atendiendo", "proceso")):
                filters.append({"field": "status", "operator": "eq", "value": "IN_PROGRESS"})
            elif any(w in normalized for w in ("resuelta", "resuelto", "solucionada", "cerrada")):
                filters.append({"field": "status", "operator": "eq", "value": "RESOLVED"})

            if any(w in normalized for w in ("alta", "urgente", "critica", "grave")):
                filters.append({"field": "priority", "operator": "contains", "value": "Alta"})
            elif any(w in normalized for w in ("media", "moderada")):
                filters.append({"field": "priority", "operator": "contains", "value": "Media"})
            elif any(w in normalized for w in ("baja", "leve")):
                filters.append({"field": "priority", "operator": "contains", "value": "Baja"})

        # Detección de estados en residentes o personal
        if source in ("residents", "staff"):
            if any(w in normalized for w in ("activo", "activos", "vigente", "vigentes")):
                filters.append({"field": "status", "operator": "eq", "value": "ACTIVE"})
            elif any(w in normalized for w in ("inactivo", "inactivos", "suspendido", "baja")):
                filters.append({"field": "status", "operator": "eq", "value": "INACTIVE"})

        # Detección de severidad en novedades / logs
        if source == "logs":
            if any(w in normalized for w in ("critica", "alta", "urgente", "grave")):
                filters.append({"field": "severity", "operator": "eq", "value": "HIGH"})
            elif any(w in normalized for w in ("media", "moderada")):
                filters.append({"field": "severity", "operator": "eq", "value": "MEDIUM"})
            elif any(w in normalized for w in ("baja", "informativa", "leve")):
                filters.append({"field": "severity", "operator": "eq", "value": "LOW"})

        return filters

    @classmethod
    def _detect_ordering(cls, source, normalized):
        source_obj = SOURCES[source]
        direction = "desc" if any(w in normalized for w in ("reciente", "recientes", "ultimo", "ultimos")) else "asc"
        base_field = source_obj.ordering.lstrip("-")
        return [{"field": base_field, "direction": direction}]

    @classmethod
    def _detect_format(cls, normalized):
        if "pdf" in normalized:
            return "pdf"
        if any(w in normalized for w in ("excel", "xlsx", "descargar excel", "hoja de calculo")):
            return "xlsx"
        if any(w in normalized for w in ("html", "imprimir", "pagina", "web")):
            return "html"
        if any(w in normalized for w in ("csv", "datos planos")):
            return "csv"
        return None

    @classmethod
    def generate_spoken_narrative(cls, source, total_count, filters=None, tenant_name=""):
        """Genera una narración hablada clara y fluida en español para sintetizador de voz."""
        source_label = SOURCES.get(source, SOURCES["incidents"]).label
        tenant_phrase = f" en el condominio {tenant_name}" if tenant_name else ""

        if total_count == 0:
            narrative = (
                f"No se encontraron registros para el reporte de {source_label}{tenant_phrase} "
                f"con los criterios solicitados."
            )
        elif total_count == 1:
            narrative = (
                f"Se encontró un registro en el reporte de {source_label}{tenant_phrase}. "
                f"Los datos están listos en pantalla para su consulta y exportación."
            )
        else:
            narrative = (
                f"Reporte de {source_label} generado exitosamente{tenant_phrase}. "
                f"Se encontraron un total de {total_count} registros coincidentes. "
                f"Puede revisarlos en la tabla o descargarlos en Excel o formato HTML."
            )

        if filters:
            narrative += f" Se aplicaron {len(filters)} filtros de búsqueda específicos."

        return narrative

    @classmethod
    def synthesize_speech_payload(cls, narrative_text):
        """Retorna la configuración necesaria para reproducción auditiva en Frontend/Móvil."""
        return {
            "text": narrative_text,
            "lang": "es-ES",
            "rate": 1.0,
            "pitch": 1.0,
            "enabled": True,
        }

