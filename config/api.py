from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from math import ceil
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, IntegrityError
from rest_framework import status
from rest_framework.exceptions import ErrorDetail, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


logger = logging.getLogger("taji.api")


class TajiPageNumberPagination(PageNumberPagination):
    """Paginación estable para todos los listados futuros de Taji."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        page_size = self.page.paginator.per_page
        total_items = self.page.paginator.count
        return Response(
            {
                "pagination": {
                    "page": self.page.number,
                    "page_size": page_size,
                    "total_items": total_items,
                    "total_pages": ceil(total_items / page_size) if page_size else 0,
                    "next": self.get_next_link(),
                    "previous": self.get_previous_link(),
                },
                "results": data,
            }
        )


def taji_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Convierte cualquier error de la API a un contrato JSON predecible."""

    if isinstance(exc, DjangoValidationError):
        detail = getattr(exc, "message_dict", None) or {
            "non_field_errors": list(exc.messages)
        }
        exc = ValidationError(detail)

    response = drf_exception_handler(exc, context)
    if response is None:
        if isinstance(exc, IntegrityError):
            response = Response(status=status.HTTP_409_CONFLICT)
            raw_detail: Any = "El recurso entra en conflicto con información existente."
        elif isinstance(exc, DatabaseError):
            response = Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)
            raw_detail = "La base de datos no está disponible temporalmente."
        else:
            logger.exception(
                "Error no controlado en la API",
                exc_info=(type(exc), exc, exc.__traceback__),
                extra={"view": context.get("view")},
            )
            response = Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            raw_detail = "Ocurrió un error interno. Intenta nuevamente."
    else:
        raw_detail = response.data

    fields = _validation_fields(raw_detail)
    code = _error_code(exc, response.status_code, fields)
    message = _error_message(raw_detail, response.status_code, bool(fields))
    payload: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if fields:
        payload["error"]["fields"] = fields
    response.data = payload
    response.content_type = "application/json"
    return response


def _validation_fields(detail: Any) -> dict[str, list[str]]:
    if not isinstance(detail, Mapping):
        return {}
    fields: dict[str, list[str]] = {}
    for key, value in detail.items():
        if key == "detail":
            continue
        messages = _messages(value)
        if messages:
            fields[str(key)] = messages
    return fields


def _messages(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        result: list[str] = []
        for nested in value.values():
            result.extend(_messages(nested))
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        result = []
        for nested in value:
            result.extend(_messages(nested))
        return result
    if isinstance(value, (str, ErrorDetail)):
        return [str(value)]
    return []


def _error_code(exc: Exception, status_code: int, fields: dict[str, list[str]]) -> str:
    if fields:
        return "validation_error"
    if isinstance(exc, IntegrityError) or status_code == status.HTTP_409_CONFLICT:
        return "conflict"
    return {
        status.HTTP_400_BAD_REQUEST: "bad_request",
        status.HTTP_401_UNAUTHORIZED: "authentication_failed",
        status.HTTP_403_FORBIDDEN: "permission_denied",
        status.HTTP_404_NOT_FOUND: "not_found",
        status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
        status.HTTP_429_TOO_MANY_REQUESTS: "throttled",
        status.HTTP_503_SERVICE_UNAVAILABLE: "service_unavailable",
    }.get(status_code, "internal_error")


def _error_message(detail: Any, status_code: int, has_fields: bool) -> str:
    if has_fields:
        return "Revisa los campos indicados."
    if isinstance(detail, Mapping):
        candidate = detail.get("detail") or detail.get("message")
        if isinstance(candidate, (str, ErrorDetail)):
            return str(candidate)
    if isinstance(detail, Sequence) and not isinstance(detail, (str, bytes, bytearray)):
        if detail:
            return str(detail[0])
    if isinstance(detail, (str, ErrorDetail)):
        return str(detail)
    return {
        status.HTTP_401_UNAUTHORIZED: "Debes iniciar sesión.",
        status.HTTP_403_FORBIDDEN: "No tienes permiso para realizar esta acción.",
        status.HTTP_404_NOT_FOUND: "No se encontró el recurso solicitado.",
        status.HTTP_429_TOO_MANY_REQUESTS: "Demasiados intentos. Espera antes de continuar.",
    }.get(status_code, "No se pudo completar la solicitud.")
