"""Serializadores para CU09: Generar y consultar el QR temporal de visita."""

from rest_framework import serializers

from security.models import VisitAuthorization
from security.qr import QR_IMAGE_FORMATS, encode_image_base64, render_qr_image
from security.serializers import VisitAuthorizationSummarySerializer


def resolve_image_format(request, default: str = "svg") -> str:
    """
    Normaliza el parámetro `image_format` de la query string a un formato soportado.

    No se usa `format` porque DRF reserva ese parámetro para la negociación de
    contenido: pedir `?format=png` sin un renderer PNG responde 404.
    """
    raw = str(request.query_params.get("image_format") or default).strip().lower()
    return raw if raw in QR_IMAGE_FORMATS else default


class VisitQrIssueRequestSerializer(serializers.Serializer):
    """
    Parámetros opcionales de la emisión del QR.

    `ttl_minutes` acota la vigencia del QR; el servicio la recorta además a la
    ventana real de la visita, de modo que nunca puede superarla.
    `force` rota un QR todavía vigente. Por defecto la emisión es idempotente y
    devuelve el QR existente, para no invalidar uno que el visitante ya recibió.
    """

    ttl_minutes = serializers.IntegerField(
        required=False, min_value=1, max_value=60 * 24, write_only=True
    )
    force = serializers.BooleanField(required=False, default=False, write_only=True)


class VisitQrSerializer(serializers.ModelSerializer):
    """
    Respuesta de CU09: estado del QR de la autorización.

    El token en claro solo existe en el instante de la emisión, por lo que
    `payload` e `image_base64` se completan únicamente en la respuesta de
    `POST .../qr/generate/`. La consulta (`GET .../qr/`) informa el estado de
    vigencia sin exponer el secreto, que es justamente lo que la hace segura:
    en la base de datos solo se guarda el SHA-256 del token.
    """

    authorization = VisitAuthorizationSummarySerializer(source="*", read_only=True)
    issued = serializers.SerializerMethodField()
    active = serializers.SerializerMethodField()
    payload = serializers.SerializerMethodField()
    expires_in_seconds = serializers.SerializerMethodField()
    image_format = serializers.SerializerMethodField()
    image_media_type = serializers.SerializerMethodField()
    image_base64 = serializers.SerializerMethodField()

    class Meta:
        model = VisitAuthorization
        fields = (
            "authorization",
            "issued",
            "active",
            "payload",
            "expires_in_seconds",
            "image_format",
            "image_media_type",
            "image_base64",
        )
        read_only_fields = fields

    def _payload(self):
        return self.context.get("payload")

    def _format(self) -> str:
        return self.context.get("image_format") or "svg"

    def get_issued(self, obj) -> bool:
        return obj.is_qr_issued()

    def get_active(self, obj) -> bool:
        return obj.is_qr_active()

    def get_payload(self, obj) -> str | None:
        return self._payload()

    def get_expires_in_seconds(self, obj) -> int:
        return obj.qr_seconds_remaining()

    def get_image_format(self, obj) -> str:
        return self._format()

    def get_image_media_type(self, obj) -> str:
        return "image/svg+xml" if self._format() == "svg" else "image/png"

    def get_image_base64(self, obj) -> str | None:
        payload = self._payload()
        if not payload:
            return None
        image, _media_type = render_qr_image(payload, self._format())
        return encode_image_base64(image, self._format())