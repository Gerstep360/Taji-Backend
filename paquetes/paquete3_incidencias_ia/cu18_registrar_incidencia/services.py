"""Reglas de negocio para CU18: Registrar incidencia (T031, T032, T033)."""

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import date

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.utils.text import get_valid_filename
from rest_framework import status
from rest_framework.exceptions import APIException

from condominiums.models import Condominium, Resident, Sector, Unit
from incidents.models import Incident, IncidentAttachment, IncidentStatusHistory, PriorityLevel
from maintenance.models import Asset

logger = logging.getLogger("taji.incidents")


# --- T031: prioridad inicial ----------------------------------------------------
#
# Regla documentada: la prioridad inicial depende solo de la categoría.
# - Riesgo para personas o servicios críticos (Seguridad, Electricidad, Ascensores) -> Alta.
# - Molestias sin riesgo (Limpieza, Áreas verdes, Otro) -> Baja.
# - Cualquier otra categoría (incluidas las nuevas) -> Media.
# La prioridad "Crítica" nunca se asigna al registrar: queda para el triaje posterior.
# El cliente no puede enviar ni elevar la prioridad; el campo se ignora.
DEFAULT_PRIORITY_CODE = "MEDIUM"
CATEGORY_PRIORITY_RULES = {
    "SECURITY": "HIGH",
    "ELECTRICITY": "HIGH",
    "ELEVATORS": "HIGH",
    "CLEANING": "LOW",
    "GREEN_AREAS": "LOW",
    "OTHER": "LOW",
}


def priority_code_for(category):
    return CATEGORY_PRIORITY_RULES.get(category.code, DEFAULT_PRIORITY_CODE)


def resolve_initial_priority(category):
    active = PriorityLevel.objects.filter(is_active=True).exclude(code="CRITICAL")
    return (
        active.filter(code=priority_code_for(category)).first()
        or active.filter(code=DEFAULT_PRIORITY_CODE).first()
        or active.order_by("rank").first()
    )


# --- Alcance de datos por condominio y usuario -----------------------------------


def tenant_sectors(condominium):
    return Sector.objects.filter(condominium=condominium, is_active=True).order_by("code")


def tenant_assets(condominium):
    return (
        Asset.objects.filter(sector__condominium=condominium)
        .exclude(status=Asset.Status.RETIRED)
        .select_related("sector")
        .order_by("code")
    )


def selectable_units(condominium, user, full_scope):
    """Unidades del condominio; un residente solo ve sus asociaciones vigentes."""
    units = (
        Unit.objects.filter(sector__condominium=condominium)
        .exclude(status=Unit.Status.INACTIVE)
        .select_related("sector")
        .order_by("code")
    )
    if full_scope:
        return units
    if not user.person_id:
        return units.none()
    today = date.today()
    return units.filter(
        Q(resident_links__end_date__isnull=True) | Q(resident_links__end_date__gte=today),
        resident_links__start_date__lte=today,
        resident_links__resident__person_id=user.person_id,
        resident_links__resident__status=Resident.Status.ACTIVE,
    ).distinct()


def reporter_resident_for(condominium, user):
    if not user.person_id:
        return None
    return (
        Resident.objects.filter(person_id=user.person_id)
        .filter(Q(condominium=condominium) | Q(condominium__isnull=True))
        .first()
    )


def sector_contains(sector, candidate):
    """True si `candidate` es `sector` o uno de sus subsectores."""
    hops = 0
    while candidate is not None and hops < 32:
        if candidate.pk == sector.pk:
            return True
        candidate = candidate.parent
        hops += 1
    return False


# --- T033: validación de evidencias ----------------------------------------------

# Extensión -> (tipo de adjunto, MIME canónico). Solo imágenes y PDF.
ALLOWED_EVIDENCE_TYPES = {
    "jpg": (IncidentAttachment.Type.IMAGE, "image/jpeg"),
    "jpeg": (IncidentAttachment.Type.IMAGE, "image/jpeg"),
    "png": (IncidentAttachment.Type.IMAGE, "image/png"),
    "webp": (IncidentAttachment.Type.IMAGE, "image/webp"),
    "pdf": (IncidentAttachment.Type.DOCUMENT, "application/pdf"),
}
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def evidence_limits():
    return {
        "max_files": settings.INCIDENT_EVIDENCE_MAX_FILES,
        "max_bytes": settings.INCIDENT_EVIDENCE_MAX_BYTES,
    }


def evidence_rules():
    limits = evidence_limits()
    return {
        "field_name": "evidences",
        "max_files": limits["max_files"],
        "max_file_size_bytes": limits["max_bytes"],
        "allowed_extensions": sorted(ALLOWED_EVIDENCE_TYPES),
        "allowed_mime_types": sorted({mime for _, mime in ALLOWED_EVIDENCE_TYPES.values()}),
    }


def _signature_matches(extension, head):
    """Comprueba los bytes mágicos reales; nunca se confía en el content-type del cliente."""
    if extension in ("jpg", "jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if extension == "png":
        return head.startswith(_PNG_SIGNATURE) and head[12:16] == b"IHDR"
    if extension == "webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP" and head[12:15] == b"VP8"
    if extension == "pdf":
        return head.startswith(b"%PDF-")
    return False


def _image_decodes(upload):
    """Verificación estructural opcional con Pillow si está instalado."""
    try:
        from PIL import Image  # noqa: PLC0415 - dependencia opcional
    except ImportError:
        return True
    try:
        upload.seek(0)
        with Image.open(upload) as image:
            image.verify()
        return True
    except Exception:
        return False
    finally:
        upload.seek(0)


def sanitize_filename(raw_name, extension):
    base = os.path.basename(str(raw_name or "").replace("\\", "/"))
    stem = os.path.splitext(base)[0].replace(".", "_")
    try:
        stem = get_valid_filename(stem)
    except SuspiciousFileOperation:
        stem = ""
    stem = stem.strip("._-")[:80] or "evidencia"
    return f"{stem}.{extension}"


@dataclass(frozen=True)
class ValidatedEvidence:
    upload: object
    extension: str
    file_type: str
    safe_name: str


def validate_evidence(upload):
    """Devuelve (ValidatedEvidence, None) o (None, mensaje de error)."""
    raw_name = getattr(upload, "name", "") or ""
    label = os.path.basename(raw_name.replace("\\", "/")) or "archivo"
    extension = os.path.splitext(label)[1].lower().lstrip(".")
    if extension not in ALLOWED_EVIDENCE_TYPES:
        allowed = ", ".join(sorted(ALLOWED_EVIDENCE_TYPES))
        return None, f"'{label}': tipo de archivo no permitido. Formatos admitidos: {allowed}."
    size = getattr(upload, "size", None) or 0
    if size <= 0:
        return None, f"'{label}': el archivo está vacío."
    max_bytes = evidence_limits()["max_bytes"]
    if size > max_bytes:
        return None, f"'{label}': supera el tamaño máximo de {max_bytes} bytes."
    upload.seek(0)
    head = upload.read(32)
    upload.seek(0)
    if not _signature_matches(extension, head):
        return None, f"'{label}': el contenido no corresponde a un archivo .{extension} válido."
    file_type, _ = ALLOWED_EVIDENCE_TYPES[extension]
    if file_type == IncidentAttachment.Type.IMAGE and not _image_decodes(upload):
        return None, f"'{label}': la imagen está dañada o no es válida."
    return ValidatedEvidence(upload, extension, file_type, sanitize_filename(raw_name, extension)), None


def storage_file_name(path):
    """Nombre original saneado a partir de la ruta almacenada (`<uuid>-<nombre>`)."""
    base = os.path.basename(path or "")
    return base.split("-", 1)[1] if "-" in base else base


# --- T032 / T033: registro atómico ------------------------------------------------


class EvidenceStorageUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "No se pudo almacenar la evidencia. Intenta nuevamente."
    default_code = "evidence_storage_unavailable"


CODE_ATTEMPTS = 5


def _next_sequence(condominium_id):
    current = Incident.objects.filter(condominium_id=condominium_id).aggregate(
        value=Max("condominium_sequence")
    )["value"]
    return (current or 0) + 1


def format_public_code(condominium_id, sequence):
    return f"INC-{condominium_id}-{sequence:06d}"


def _insert_with_unique_code(condominium, fields):
    """
    Correlativo por condominio:
    1. Bloquea la fila del condominio (SELECT ... FOR UPDATE en PostgreSQL) para
       serializar los registros concurrentes del mismo tenant.
    2. Calcula MAX(correlativo) + 1.
    3. Inserta dentro de un savepoint; la restricción única
       (condominium, condominium_sequence) y la unicidad de `public_code` son la
       garantía final. Ante IntegrityError se reintenta con un nuevo número.
    """
    list(Condominium.objects.select_for_update().filter(pk=condominium.pk).values_list("pk", flat=True))
    for attempt in range(1, CODE_ATTEMPTS + 1):
        sequence = _next_sequence(condominium.pk)
        try:
            with transaction.atomic():
                return Incident.objects.create(
                    condominium=condominium,
                    condominium_sequence=sequence,
                    public_code=format_public_code(condominium.pk, sequence),
                    **fields,
                )
        except IntegrityError:
            if attempt == CODE_ATTEMPTS:
                raise
            logger.warning("Colisión de código de incidencia (condominio %s, intento %s).", condominium.pk, attempt)
    raise IntegrityError("No se pudo generar un código único de incidencia.")  # pragma: no cover


def _delete_quietly(storage, names):
    for name in names:
        try:
            storage.delete(name)
        except Exception:  # pragma: no cover - solo se registra
            logger.exception("No se pudo eliminar la evidencia huérfana %s", name)


def create_incident(*, condominium, reporter, reporter_resident, validated_data, evidences):
    """
    Crea la incidencia y sus evidencias en una sola transacción. Si algo falla,
    no queda ninguna fila y se eliminan los archivos ya escritos en el storage.
    """
    category = validated_data["category"]
    fields = {
        "reporter_user": reporter,
        "reporter_resident": reporter_resident,
        "sector": validated_data["sector"],
        "unit": validated_data.get("unit"),
        "asset": validated_data.get("asset"),
        "category": category,
        "priority": resolve_initial_priority(category),
        "title": validated_data.get("title", ""),
        "description": validated_data["description"],
        "status": Incident.Status.REPORTED,
    }
    storage = default_storage
    written = []
    try:
        with transaction.atomic():
            incident = _insert_with_unique_code(condominium, fields)
            IncidentStatusHistory.objects.create(
                incident=incident, changed_by_user=reporter, to_status=Incident.Status.REPORTED,
                comment="Incidencia registrada", changed_at=incident.created_at,
            )
            from django.conf import settings
            if settings.NVIDIA['ENABLED'] and settings.NVIDIA['AUTO_ANALYZE']:
                from paquetes.paquete3_incidencias_ia.cu22_analisis_ia.services import enqueue
                enqueue(incident, reporter, automatic=True)
            for evidence in evidences:
                target = f"incidents/{condominium.pk}/{incident.pk}/{uuid.uuid4().hex[:12]}-{evidence.safe_name}"
                evidence.upload.seek(0)
                try:
                    stored_name = storage.save(target, evidence.upload)
                except Exception as exc:
                    logger.exception("Fallo del storage al guardar evidencia de incidencia.")
                    raise EvidenceStorageUnavailable() from exc
                written.append(stored_name)
                IncidentAttachment.objects.create(
                    incident=incident,
                    uploaded_by_user=reporter,
                    file_path=stored_name,
                    file_type=evidence.file_type,
                )
    except Exception:
        _delete_quietly(storage, written)
        raise
    return incident
