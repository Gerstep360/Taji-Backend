"""
Servicios de QR temporal de visita (RF-09 / RF-10 · T021 / T022).

Este módulo concentra las reglas de negocio de los dos casos de uso para que
sean verificables de forma aislada, sin depender de la capa HTTP:

* RF-09 (T021): emisión, vigencia, expiración e invalidación del QR.
* RF-10 (T022): validación del QR escaneado y reglas de autorización de visita.

Decisiones de seguridad aplicadas aquí:

1. El contenido del QR es un **token opaco aleatorio** generado con
   ``secrets.token_urlsafe``. No contiene datos personales ni es adivinable.
2. En base de datos solo se persiste el **SHA-256** del token. Una filtración de
   la base de datos no permite clonar credenciales de acceso.
3. El token se compara en **tiempo constante** (``secrets.compare_digest``)
   para no filtrar información por tiempos de respuesta.
4. La validez nunca se decide solo por reloj: cada escaneo revalida estado,
   ventana de la visita y expiración del QR en el servidor.
"""

from __future__ import annotations

import base64
import hashlib
import io
import re
import secrets
import uuid as uuid_module
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import segno
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import AccessEvent, VisitAuthorization

# Versión del esquema contenido en el QR. Permite evolucionar el formato
# manteniendo la compatibilidad con los QR ya emitidos.
QR_PAYLOAD_PREFIX = "TAJI1"

# Formatos de imagen soportados por la API.
QR_IMAGE_FORMATS = ("svg", "png")

_QR_PAYLOAD_RE = re.compile(
    r"^TAJI(?P<version>\d+)\.(?P<uuid>[0-9a-f]{32})\.(?P<token>[A-Za-z0-9_-]{16,128})$"
)

# Parámetros de URL aceptados cuando el QR apunta a un deep link del aplicativo.
_DEEPLINK_PARAMS = ("code", "token", "v", "taji")


class VisitQrError(Exception):
    """Error de dominio al emitir o administrar el QR de una visita."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class QrRejection:
    """Motivos por los que un QR escaneado no autoriza el ingreso."""

    NOT_FOUND = "NOT_FOUND"
    QR_ROTATED = "QR_ROTATED"
    QR_NOT_ISSUED = "QR_NOT_ISSUED"
    QR_EXPIRED = "QR_EXPIRED"
    VISIT_NOT_YET_VALID = "VISIT_NOT_YET_VALID"
    VISIT_WINDOW_ENDED = "VISIT_WINDOW_ENDED"
    VISIT_CANCELLED = "VISIT_CANCELLED"
    VISIT_FINISHED = "VISIT_FINISHED"
    VISIT_EXPIRED = "VISIT_EXPIRED"
    STATUS_NOT_ALLOWED = "STATUS_NOT_ALLOWED"

    MESSAGES = {
        NOT_FOUND: "El código QR no corresponde a ninguna autorización de visita.",
        QR_ROTATED: "Este QR fue reemplazado por uno más reciente. Solicita el nuevo al residente.",
        QR_NOT_ISSUED: "La autorización aún no tiene un QR emitido. Solicítalo al residente.",
        QR_EXPIRED: "El código QR venció. Solicita un QR nuevo al residente.",
        VISIT_NOT_YET_VALID: "La visita aún no está vigente. Ingressa dentro del horario autorizado.",
        VISIT_WINDOW_ENDED: "El periodo de validez de la visita ya concluded.",
        VISIT_CANCELLED: "La autorización de visita fue cancelada.",
        VISIT_FINISHED: "La visita ya fue finalizada.",
        VISIT_EXPIRED: "La autorización de visita se encuentra vencida.",
        STATUS_NOT_ALLOWED: "La autorización de visita no se encuentra en un estado válido de ingreso.",
    }


@dataclass(frozen=True)
class ParsedQrCode:
    """Resultado de interpretar el texto escaneado."""

    qr_uuid: uuid_module.UUID | None
    token: str
    # `False` cuando el texto no usa el esquema TAJI y se trata como token plano.
    structured: bool = False


@dataclass
class QrEvaluation:
    """Resultado de evaluar un QR escaneado contra las reglas de autorización."""

    approved: bool
    reason: str
    message: str
    authorization: VisitAuthorization | None = None
    # Marca que el escaneo debe quedar registrado en AccessEvent.
    recordable: bool = True
    expired_authorization: bool = False
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Generación y hash de tokens
# ---------------------------------------------------------------------------


def _token_bytes() -> int:
    return max(16, int(getattr(settings, "VISIT_QR_TOKEN_BYTES", 24)))


def generate_token() -> str:
    """Genera un token opaco, aleatorio y URL-safe con entropía criptográfica."""
    return secrets.token_urlsafe(_token_bytes())


def hash_token(token: str) -> str:
    """Devuelve el SHA-256 hexadecimal del token; es el único valor que se persiste."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def build_payload(qr_uuid, token: str) -> str:
    """Construye el texto exacto que se codifica dentro del QR."""
    return f"{QR_PAYLOAD_PREFIX}.{uuid_module.UUID(str(qr_uuid)).hex}.{token}"


# ---------------------------------------------------------------------------
# Interpretación del texto escaneado
# ---------------------------------------------------------------------------


def normalize_scanned_value(raw: str) -> str:
    """
    Limpia el texto entregado por el lector.

    Acepta el payload completo, el token aislado, con espacios o saltos de línea
    añadidos por el lector, y también un deep link del aplicativo que transporte
    el código en la query string.
    """
    if raw is None:
        return ""

    value = str(raw).strip()
    # Algunos lectores agregan espacios o tabuladores alrededor de los puntos.
    value = re.sub(r"\s+", "", value)

    if "?" in value:
        query = parse_qs(urlparse(value).query)
        for key in _DEEPLINK_PARAMS:
            candidates = query.get(key)
            if candidates:
                value = candidates[0].strip()
                break

    return value


def parse_payload(raw: str) -> ParsedQrCode | None:
    """Interpreta el texto escaneado como payload TAJI o como token plano."""
    value = normalize_scanned_value(raw)
    if not value:
        return None

    match = _QR_PAYLOAD_RE.match(value)
    if match:
        qr_uuid = uuid_module.UUID(match.group("uuid"))
        return ParsedQrCode(qr_uuid=qr_uuid, token=match.group("token"), structured=True)

    # Token plano: se descarta cualquier entrada que no sea un token válido.
    if re.fullmatch(r"[A-Za-z0-9_-]{16,128}", value):
        return ParsedQrCode(qr_uuid=None, token=value, structured=False)

    return None


def resolve_authorization(raw: str):
    """
    Localiza la autorización a partir del texto escaneado.

    Devuelve ``(authorization, status)`` donde ``status`` es ``"FOUND"``,
    ``"QR_ROTATED"`` (el identificador existe pero el token ya fue reemplazado)
    o ``"NOT_FOUND"``.
    """
    parsed = parse_payload(raw)
    if parsed is None:
        return None, QrRejection.NOT_FOUND

    if parsed.structured and parsed.qr_uuid is not None:
        authorization = _authorization_queryset().filter(qr_uuid=parsed.qr_uuid).first()
        if authorization is None:
            return None, QrRejection.NOT_FOUND

        expected = authorization.qr_token_hash
        if not expected or not secrets.compare_digest(expected, hash_token(parsed.token)):
            return authorization, QrRejection.QR_ROTATED

        return authorization, "FOUND"

    authorization = _authorization_queryset().filter(
        qr_token_hash=hash_token(parsed.token)
    ).first()
    if authorization is None:
        return None, QrRejection.NOT_FOUND

    return authorization, "FOUND"


def _authorization_queryset():
    return VisitAuthorization.objects.select_related(
        "visitor_person",
        "authorized_by_resident__person",
        "unit__sector",
    )


# ---------------------------------------------------------------------------
# RF-09 · Emisión, vigencia y expiración del QR
# ---------------------------------------------------------------------------


def _resolve_ttl(authorization: VisitAuthorization, ttl_minutes: int | None, now: datetime) -> int:
    """Determina la vigencia efectiva del QR sin exceder `valid_until`."""
    default_ttl = int(getattr(settings, "VISIT_QR_TTL_MINUTES", 240))
    max_ttl = int(getattr(settings, "VISIT_QR_MAX_TTL_MINUTES", 1440))
    min_ttl = int(getattr(settings, "VISIT_QR_MIN_TTL_MINUTES", 5))

    requested = default_ttl if ttl_minutes is None else int(ttl_minutes)
    if requested < min_ttl:
        raise VisitQrError(
            "ttl_minutes",
            f"La vigencia del QR debe ser de al menos {min_ttl} minutos.",
        )
    if requested > max_ttl:
        raise VisitQrError(
            "ttl_minutes",
            f"La vigencia del QR no puede superar {max_ttl} minutos.",
        )

    available = int((authorization.valid_until - now).total_seconds() // 60)
    if available < min_ttl:
        raise VisitQrError(
            "visit_window_ended",
            "El periodo de validez de la visita no permite emitir un QR con vigencia útil.",
        )

    return min(requested, available, max_ttl)


def issue_visit_qr(
    authorization: VisitAuthorization,
    *,
    ttl_minutes: int | None = None,
    token: str | None = None,
    at: datetime | None = None,
):
    """
    Emite (o rota) el QR de una autorización y devuelve ``(authorization, token)``.

    Rotar genera un token nuevo, por lo que el hash del token anterior deja de
    coincidir y el QR previo queda inutilizable de inmediato. `qr_uuid` se
    mantiene estable: es el identificador público de la visita y no un secreto,
    y conservarlo permite distinguir "QR reemplazado" de "QR desconocido".
    """
    now = at or timezone.now()

    # El estado se valida ANTES que la ventana: es la causa estructural. Si una
    # visita está cancelada, ampliar el horario nunca habilita un QR, y reportar
    # "ventana no útil" induciría a pensar que basta con extender el periodo.
    if authorization.status in (
        VisitAuthorization.Status.CANCELLED,
        VisitAuthorization.Status.FINISHED,
        VisitAuthorization.Status.EXPIRED,
    ):
        raise VisitQrError(
            "status_not_allowed",
            f"No se puede emitir un QR para una autorización en estado "
            f"{authorization.get_status_display()}.",
        )

    ttl = _resolve_ttl(authorization, ttl_minutes, now)

    new_token = token or generate_token()
    new_expiry = min(now + timedelta(minutes=ttl), authorization.valid_until)

    with transaction.atomic():
        locked = VisitAuthorization.objects.select_for_update().get(pk=authorization.pk)
        locked.qr_token_hash = hash_token(new_token)
        locked.qr_issued_at = now
        locked.qr_expires_at = new_expiry
        locked.save(update_fields=["qr_token_hash", "qr_issued_at", "qr_expires_at"])

    # Refleja el cambio en la instancia que el llamador ya tenía cargada.
    authorization.qr_token_hash = hash_token(new_token)
    authorization.qr_issued_at = now
    authorization.qr_expires_at = new_expiry

    return authorization, new_token


# ---------------------------------------------------------------------------
# RF-09 · Renderizado de la imagen del QR
# ---------------------------------------------------------------------------


def _ecc_level() -> str:
    """Normaliza el nivel de corrección de errores al formato de segno (L/M/Q/H)."""
    raw = str(getattr(settings, "VISIT_QR_ECC", "medium")).strip().lower()
    aliases = {
        "l": "L",
        "low": "L",
        "m": "M",
        "medium": "M",
        "q": "Q",
        "quartile": "Q",
        "h": "H",
        "high": "H",
    }
    return aliases.get(raw, "M")


def render_qr_image(payload: str, image_format: str = "svg"):
    """Renderiza el QR y devuelve ``(bytes, content_type)``."""
    fmt = (image_format or "svg").strip().lower()
    if fmt not in QR_IMAGE_FORMATS:
        raise VisitQrError(
            "format", f"Formato no soportado. Usa uno de: {', '.join(QR_IMAGE_FORMATS)}."
        )

    scale = max(1, int(getattr(settings, "VISIT_QR_IMAGE_SCALE", 6)))
    qr = segno.make(payload, error=_ecc_level())

    buffer = io.BytesIO()
    if fmt == "svg":
        # El escritor de segno emite bytes; se decodifica para incrustar en JSON.
        qr.save(buffer, kind="svg", scale=scale, border=2, xmldecl=False, title=None)
        return buffer.getvalue().decode("utf-8"), "image/svg+xml"

    qr.save(buffer, kind="png", scale=scale, border=2)
    return buffer.getvalue(), "image/png"


def encode_image_base64(image: bytes | str, image_format: str) -> str:
    """Codifica la imagen del QR en base64 para incluirla dentro de una respuesta JSON."""
    raw = image.encode("utf-8") if isinstance(image, str) else image
    return base64.b64encode(raw).decode("ascii")


# ---------------------------------------------------------------------------
# RF-10 · Reglas de autorización sobre un QR escaneado
# ---------------------------------------------------------------------------


def evaluate_authorization(authorization: VisitAuthorization, at: datetime | None = None) -> QrEvaluation:
    """
    Aplica las reglas de autorización de visita sobre una autorización resuelta.

    El orden de evaluación va de lo más estructural a lo más temporal para que el
    motivo reportado al guardia sea el más accionable posible.
    """
    now = at or timezone.now()

    if authorization.status == VisitAuthorization.Status.CANCELLED:
        return QrEvaluation(
            approved=False,
            reason=QrRejection.VISIT_CANCELLED,
            message=QrRejection.MESSAGES[QrRejection.VISIT_CANCELLED],
            authorization=authorization,
        )

    if authorization.status == VisitAuthorization.Status.FINISHED:
        return QrEvaluation(
            approved=False,
            reason=QrRejection.VISIT_FINISHED,
            message=QrRejection.MESSAGES[QrRejection.VISIT_FINISHED],
            authorization=authorization,
        )

    if authorization.status == VisitAuthorization.Status.EXPIRED:
        return QrEvaluation(
            approved=False,
            reason=QrRejection.VISIT_EXPIRED,
            message=QrRejection.MESSAGES[QrRejection.VISIT_EXPIRED],
            authorization=authorization,
        )

    if authorization.valid_until <= now:
        return QrEvaluation(
            approved=False,
            reason=QrRejection.VISIT_WINDOW_ENDED,
            message=QrRejection.MESSAGES[QrRejection.VISIT_WINDOW_ENDED],
            authorization=authorization,
            expired_authorization=True,
        )

    if not authorization.is_qr_issued():
        return QrEvaluation(
            approved=False,
            reason=QrRejection.QR_NOT_ISSUED,
            message=QrRejection.MESSAGES[QrRejection.QR_NOT_ISSUED],
            authorization=authorization,
        )

    if authorization.qr_expires_at <= now:
        return QrEvaluation(
            approved=False,
            reason=QrRejection.QR_EXPIRED,
            message=QrRejection.MESSAGES[QrRejection.QR_EXPIRED],
            authorization=authorization,
        )

    if authorization.valid_from > now:
        return QrEvaluation(
            approved=False,
            reason=QrRejection.VISIT_NOT_YET_VALID,
            message=QrRejection.MESSAGES[QrRejection.VISIT_NOT_YET_VALID],
            authorization=authorization,
        )

    if authorization.status not in (
        VisitAuthorization.Status.AUTHORIZED,
        VisitAuthorization.Status.ACTIVE,
    ):
        return QrEvaluation(
            approved=False,
            reason=QrRejection.STATUS_NOT_ALLOWED,
            message=QrRejection.MESSAGES[QrRejection.STATUS_NOT_ALLOWED],
            authorization=authorization,
        )

    return QrEvaluation(
        approved=True,
        reason="VALID",
        message="Autorización de visita vigente. Ingreso permitido.",
        authorization=authorization,
    )


def validate_scanned_qr(raw: str, at: datetime | None = None) -> QrEvaluation:
    """Resuelve y valida en un solo paso el texto capturado por el lector."""
    now = at or timezone.now()
    authorization, status = resolve_authorization(raw)

    if status == QrRejection.NOT_FOUND:
        return QrEvaluation(
            approved=False,
            reason=QrRejection.NOT_FOUND,
            message=QrRejection.MESSAGES[QrRejection.NOT_FOUND],
            authorization=None,
            # Un token inexistente no genera AccessEvent: evita que alguien
            # pueda inundar la tabla escaneando cadenas inválidas.
            recordable=False,
        )

    if status == QrRejection.QR_ROTATED:
        return QrEvaluation(
            approved=False,
            reason=QrRejection.QR_ROTATED,
            message=QrRejection.MESSAGES[QrRejection.QR_ROTATED],
            authorization=authorization,
        )

    return evaluate_authorization(authorization, at=now)


# ---------------------------------------------------------------------------
# Registro de eventos de acceso
# ---------------------------------------------------------------------------


def register_access_event(
    evaluation: QrEvaluation,
    *,
    guard_staff=None,
    notes: str = "",
    at: datetime | None = None,
):
    """
    Persiste el escaneo en `AccessEvent` y activa la autorización cuando el
    ingreso fue aprobado.

    Solo se registran eventos cuando el QR se resolvió a una autorización real,
    de modo que un token inválido no pueda usarse para escribir en la base de datos.
    """
    if not evaluation.recordable or evaluation.authorization is None:
        return None

    authorization = evaluation.authorization
    now = at or timezone.now()

    with transaction.atomic():
        locked = VisitAuthorization.objects.select_for_update().get(pk=authorization.pk)

        event = AccessEvent.objects.create(
            authorization=locked,
            person=locked.visitor_person,
            guard_staff=guard_staff,
            event_type=(
                AccessEvent.Type.ENTRY if evaluation.approved else AccessEvent.Type.DENIED
            ),
            validation_method=AccessEvent.Method.QR,
            validation_result=(
                AccessEvent.Result.APPROVED
                if evaluation.approved
                else AccessEvent.Result.REJECTED
            ),
            occurred_at=now,
            notes=(notes or evaluation.reason)[:300],
        )

        changed = False

        # El ingreso consumió la visita: la autorización pasa a ACTIVA (idempotente).
        if evaluation.approved and locked.status == VisitAuthorization.Status.AUTHORIZED:
            locked.status = VisitAuthorization.Status.ACTIVE
            locked.save(update_fields=["status"])
            changed = True

        # La ventana de la visita terminó: se persiste para que el QR quede inutilizable.
        if evaluation.expired_authorization and locked.status in (
            VisitAuthorization.Status.AUTHORIZED,
            VisitAuthorization.Status.ACTIVE,
        ):
            locked.status = VisitAuthorization.Status.EXPIRED
            locked.save(update_fields=["status"])
            changed = True

        if changed:
            authorization.status = locked.status

    return event


# ---------------------------------------------------------------------------
# Mantenimiento de expiraciones
# ---------------------------------------------------------------------------


def expire_stale_authorizations(at: datetime | None = None) -> int:
    """
    Marca como EXPIRADAS las autorizaciones cuya ventana de visita ya Conclusionó.

    Complementa la comprobación en el momento del escaneo para que los listados y
    reportes reflejen el estado real sin depender de que seguridad lea cada QR.
    """
    now = at or timezone.now()
    return VisitAuthorization.objects.filter(
        status__in=(VisitAuthorization.Status.AUTHORIZED, VisitAuthorization.Status.ACTIVE),
        valid_until__lte=now,
    ).update(status=VisitAuthorization.Status.EXPIRED)


__all__ = [
    "QR_IMAGE_FORMATS",
    "QR_PAYLOAD_PREFIX",
    "ParsedQrCode",
    "QrEvaluation",
    "QrRejection",
    "VisitQrError",
    "build_payload",
    "encode_image_base64",
    "evaluate_authorization",
    "expire_stale_authorizations",
    "generate_token",
    "hash_token",
    "issue_visit_qr",
    "normalize_scanned_value",
    "parse_payload",
    "register_access_event",
    "render_qr_image",
    "resolve_authorization",
    "validate_scanned_qr",
]