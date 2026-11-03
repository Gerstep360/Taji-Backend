import uuid as uuid_module

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from maintenance.models import Asset
from tenancy.context import TenantContext

from .permissions import CanScanAssets, HasAssetsTenant
from .serializers import AssetQRScanResponseSerializer, QRScanRequestSerializer
from paquetes.paquete4_activos_mantenimiento.cu23_gestionar_activos.tenancy import (
    tenant_assets,
)

ASSET_QR_PAYLOAD_PREFIX = "TAJI-ASSET"


class QRScanView(APIView):
    """
    CU24 — Escanear y consultar activos mediante código QR.

    El cliente escanea un código QR generado por CU23, extrae el payload
    "TAJI-ASSET.<uuid_hex>" y lo envía a este endpoint para consultar
    los datos del activo y su historial.
    """

    permission_classes = [IsAuthenticated, HasAssetsTenant, CanScanAssets]

    def get_queryset(self):
        """Retorna assets del condominio autorizado."""
        tenant_id = TenantContext.get_current_tenant_id()
        return tenant_assets(tenant_id)

    @extend_schema(
        tags=["QR Escaneo - CU24"],
        summary="Escanear código QR y consultar activo",
        request=QRScanRequestSerializer,
        responses={
            200: AssetQRScanResponseSerializer,
            400: {"description": "Formato de QR inválido"},
            404: {"description": "Activo no encontrado"},
        },
    )
    def post(self, request):
        """
        Valida el payload de un QR escaneado y retorna los datos del activo.

        Payload esperado: { "qr_payload": "TAJI-ASSET.<uuid_hex>" }

        Validaciones:
        - Prefijo correcto (TAJI-ASSET.)
        - UUID válido en hexadecimal
        - Asset existe en el condominio autorizado
        """
        serializer = QRScanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        qr_payload = serializer.validated_data["qr_payload"]
        uuid_hex = qr_payload.split(".", 1)[1]

        try:
            qr_uuid = uuid_module.UUID(hex=uuid_hex)
        except ValueError as e:
            raise ValidationError(f"UUID inválido: {str(e)}")

        try:
            asset = self.get_queryset().get(qr_uuid=qr_uuid)
        except Asset.DoesNotExist:
            raise NotFound("El código QR no corresponde a ningún activo del condominio.")

        asset_serializer = AssetQRScanResponseSerializer(asset)
        return Response(asset_serializer.data, status=status.HTTP_200_OK)
