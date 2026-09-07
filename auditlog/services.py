import logging
import uuid
from typing import Any, Optional

from django.http import HttpRequest

from .models import AuditEvent

logger = logging.getLogger(__name__)


def get_client_ip(request: Optional[HttpRequest]) -> Optional[str]:
    """Obtiene la dirección IP real del cliente considerando proxies inversos."""
    if not request:
        return None
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def get_user_agent(request: Optional[HttpRequest]) -> str:
    """Obtiene el User-Agent del cliente truncado a 500 caracteres."""
    if not request:
        return ""
    return str(request.META.get("HTTP_USER_AGENT", ""))[:500]


def get_request_id(request: Optional[HttpRequest]) -> Optional[uuid.UUID]:
    """Obtiene o infiere el UUID de correlación de la solicitud."""
    if not request:
        return None
    req_id_val = request.META.get("HTTP_X_REQUEST_ID") or getattr(request, "request_id", None)
    if req_id_val:
        try:
            return uuid.UUID(str(req_id_val))
        except (ValueError, AttributeError):
            pass
    return None


def record_audit_event(
    *,
    action_code: str,
    resource_type: str,
    resource_id: Optional[Any] = None,
    description: str = "",
    actor_user: Optional[Any] = None,
    before_data: Optional[dict] = None,
    after_data: Optional[dict] = None,
    request: Optional[HttpRequest] = None,
) -> Optional[AuditEvent]:
    """
    Registra de forma atómica y segura un evento en el log de auditoría inmutable.
    Nunca propaga excepciones que puedan interrumpir la operación de negocio.
    """
    try:
        actor = actor_user
        if actor is None and request and getattr(request, "user", None) and request.user.is_authenticated:
            actor = request.user

        ip = get_client_ip(request)
        ua = get_user_agent(request)
        req_id = get_request_id(request)

        return AuditEvent.objects.create(
            actor_user=actor,
            action_code=action_code[:80],
            resource_type=resource_type[:80],
            resource_id=str(resource_id)[:80] if resource_id is not None else None,
            description=description[:240],
            before_data=before_data,
            after_data=after_data,
            ip_address=ip,
            user_agent=ua,
            request_id=req_id,
        )
    except Exception as exc:
        logger.error(f"Error al registrar AuditEvent '{action_code}': {exc}", exc_info=True)
        return None
