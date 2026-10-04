"""Serializadores para CU10: Validar la autorización de visitante mediante QR."""

from rest_framework import serializers

from security.qr import normalize_scanned_value
from security.serializers import VisitAuthorizationSummarySerializer

# Claves que aceptan los distintos clientes de lector para el texto capturado.
_TOKEN_ALIASES = ("token", "code", "qr", "payload", "value")


class VisitQrValidationRequestSerializer(serializers.Serializer):
    """
    Datos del escaneo.

    `token` admite el payload completo (`TAJI1.<uuid>.<token>`), el token aislado
    o un deep link del aplicativo. Se aceptan también las claves `code`, `qr`,
    `payload` y `value` para no acoplar el contrato a un lector concreto.
    """

    token = serializers.CharField(max_length=512, allow_blank=False, trim_whitespace=True)
    notes = serializers.CharField(
        max_length=300, required=False, allow_blank=True, default="", write_only=True
    )
    device_id = serializers.CharField(
        max_length=80, required=False, allow_blank=True, allow_null=True, write_only=True
    )

    def to_internal_value(self, data):
        # Traduce cualquier alias conocido a la clave canónica `token`.
        if hasattr(data, "dict"):
            data = data.dict()
        if isinstance(data, dict) and not data.get("token"):
            for alias in _TOKEN_ALIASES:
                if alias != "token" and data.get(alias):
                    data = {**data, "token": data[alias]}
                    break
        return super().to_internal_value(data)


class AccessEventSerializer(serializers.Serializer):
    """Identificador del evento de acceso registrado por el escaneo."""

    id = serializers.IntegerField(read_only=True)
    event_type = serializers.CharField(read_only=True)
    validation_method = serializers.CharField(read_only=True)
    validation_result = serializers.CharField(read_only=True)
    occurred_at = serializers.DateTimeField(read_only=True)


class VisitQrValidationSerializer(serializers.Serializer):
    """
    Veredicto del escaneo (RF-10).

    Expone.valididad, vigencia, estado, visitante y unidad autorizante para que el
    guardia decida el ingreso, además del evento de acceso que quedó registrado.
    """

    valid = serializers.BooleanField(read_only=True)
    reason = serializers.CharField(read_only=True)
    message = serializers.CharField(read_only=True)
    checked_at = serializers.DateTimeField(read_only=True)
    authorization = VisitAuthorizationSummarySerializer(read_only=True, allow_null=True)
    access_event = AccessEventSerializer(read_only=True, allow_null=True)

    @staticmethod
    def normalized_token(raw: str) -> str:
        return normalize_scanned_value(raw)