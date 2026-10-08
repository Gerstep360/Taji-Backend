"""Serializadores para CU10: Validar la autorización de visitante mediante QR."""

from rest_framework import serializers

from security.models import VisitQrScan
from security.qr import normalize_scanned_value
from security.serializers import (
    GuardStaffSerializer,
    VisitAuthorizationSummarySerializer,
)

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

    class Meta:
        ref_name = "QrAccessEvent"

    id = serializers.IntegerField(read_only=True)
    event_type = serializers.CharField(read_only=True)
    validation_method = serializers.CharField(read_only=True)
    validation_result = serializers.CharField(read_only=True)
    occurred_at = serializers.DateTimeField(read_only=True)


class VisitQrScanSerializer(serializers.ModelSerializer):
    """
    Identificador del escaneo registrado en la bitácora de la portería.

    Se devuelve junto al veredicto para que el cliente pueda confirmar que el
    intento quedó registrado, incluso cuando fue denegado.
    """

    result_display = serializers.CharField(source="get_result_display", read_only=True)

    class Meta:
        model = VisitQrScan
        ref_name = "VisitQrScanRef"
        fields = ("id", "result", "result_display", "reason", "occurred_at")


class VisitQrScanListSerializer(serializers.ModelSerializer):
    """Fila del historial de escaneos que ve el guardia en el tablero de portería."""

    result_display = serializers.CharField(source="get_result_display", read_only=True)
    guard_staff = GuardStaffSerializer(read_only=True)
    authorization_id = serializers.IntegerField(read_only=True)
    unit_code = serializers.SerializerMethodField()
    visitor_name = serializers.SerializerMethodField()
    visitor_document_number = serializers.SerializerMethodField()

    class Meta:
        model = VisitQrScan
        ref_name = "VisitQrScanList"
        fields = (
            "id",
            "result",
            "result_display",
            "reason",
            "message",
            "occurred_at",
            "authorization_id",
            "visitor_name",
            "visitor_document_number",
            "unit_code",
            "guard_staff",
            "device_id",
            "notes",
        )

    def get_visitor_name(self, obj) -> str:
        # Se prefiere el nombre copiado al escanear: sobrevive aunque la
        # autorización se elimine después y evita un JOIN por fila.
        if obj.visitor_name:
            return obj.visitor_name
        visitor = getattr(obj.authorization, "visitor_person", None)
        return visitor.full_name if visitor else ""

    def get_visitor_document_number(self, obj) -> str:
        if obj.visitor_document_number:
            return obj.visitor_document_number
        visitor = getattr(obj.authorization, "visitor_person", None)
        return (visitor.document_number or "") if visitor else ""

    def get_unit_code(self, obj) -> str:
        unit = getattr(obj.authorization, "unit", None)
        return unit.code if unit else ""


class VisitQrScanListResponseSerializer(serializers.Serializer):
    """Paginado del historial con los totales de la ventana consultada."""

    count = serializers.IntegerField(read_only=True)
    page = serializers.IntegerField(read_only=True)
    page_size = serializers.IntegerField(read_only=True)
    total_pages = serializers.IntegerField(read_only=True)
    summary = serializers.SerializerMethodField()
    results = VisitQrScanListSerializer(many=True, read_only=True)

    def get_summary(self, obj) -> dict:
        return obj["summary"]


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
    scan = VisitQrScanSerializer(read_only=True, allow_null=True)

    @staticmethod
    def normalized_token(raw: str) -> str:
        return normalize_scanned_value(raw)