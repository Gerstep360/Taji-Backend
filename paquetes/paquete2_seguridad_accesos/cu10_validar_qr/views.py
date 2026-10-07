"""Vistas para CU10: Validar la autorización de visitante mediante QR (RF-10 / T022)."""

from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from auditlog.services import record_audit_event
from security.qr import (
    QrRejection,
    normalize_scanned_value,
    register_access_event,
    validate_scanned_qr,
)

from .permissions import CanValidateVisitQr
from .serializers import VisitQrValidationRequestSerializer, VisitQrValidationSerializer


@method_decorator(never_cache, name="dispatch")
class VisitQrValidationView(APIView):
    """
    Controlador para CU10 / T022 (RF-10).

    El personal de seguridad escanea el QR de la visita y el sistema devuelve el
    veredicto con la validez, la vigencia, el estado, el visitante y la unidad
    autorizante antes de permitir el ingreso.

    Todo escaneo que resuelva a una autorización real queda registrado en
    `AccessEvent`, tanto aprobado como denegado, para poder auditar los ingresos.
    Un QR desconocido no genera evento: evita que alguien inunde la base de datos
    escaneando cadenas inválidas.
    """

    permission_classes = [IsAuthenticated, CanValidateVisitQr]

    @extend_schema(
        tags=["Seguridad - Validación QR"],
        summary="Validar el QR de una visita",
        description=(
            "Valida el QR escaneado en portería. Comprueba que el código exista, que no haya "
            "sido rotado, que la autorización no esté cancelada, finalizada ni vencida, que la "
            "visita esté dentro de su ventana y que el QR no haya expirado. Un ingreso aprobado "
            "deja la autorización en estado ACTIVA y registra un AccessEvent de entrada; un "
            "rechazo registra el intento denegado con su motivo."
        ),
        request=VisitQrValidationRequestSerializer,
        responses={status.HTTP_200_OK: VisitQrValidationSerializer},
    )
    def post(self, request):
        payload_serializer = VisitQrValidationRequestSerializer(data=request.data)
        payload_serializer.is_valid(raise_exception=True)
        data = payload_serializer.validated_data

        scanned = normalize_scanned_value(data["token"])
        now = timezone.now()

        evaluation = validate_scanned_qr(scanned, at=now)
        guard_staff = getattr(getattr(request.user, "person", None), "staff", None)

        event = register_access_event(
            evaluation,
            guard_staff=guard_staff,
            notes=data.get("notes", ""),
            at=now,
        )

        self._audit(request, evaluation, data, now)

        body = VisitQrValidationSerializer(
            {
                "valid": evaluation.approved,
                "reason": evaluation.reason,
                "message": evaluation.message,
                "checked_at": now,
                "authorization": evaluation.authorization,
                "access_event": event,
            },
            context={"request": request},
        ).data

        # Un rechazo sigue siendo 200: describe un resultado de negocio válido,
        # no un fallo de la API. La app decide qué mostrar según `valid`.
        return Response(body, status=status.HTTP_200_OK)

    def _audit(self, request, evaluation, data, now):
        """Audita el escaneo. Solo los rechazos, para no duplicar los accesos aprobados."""
        if evaluation.approved:
            return

        resource_id = evaluation.authorization.id if evaluation.authorization else None
        resource_type = "VisitAuthorization" if resource_id else "VisitQr"

        record_audit_event(
            action_code="VISIT_QR_VALIDATION_REJECTED",
            resource_type=resource_type,
            resource_id=resource_id,
            description=evaluation.message,
            actor_user=request.user,
            after_data={
                "reason": evaluation.reason,
                "checked_at": now.isoformat(),
                "device_id": data.get("device_id") or None,
            },
            request=request,
        )


class VisitQrValidationReasonsView(APIView):
    """Catálogo de motivos de rechazo para que la app no codifique strings."""

    permission_classes = [IsAuthenticated, CanValidateVisitQr]

    @extend_schema(
        tags=["Seguridad - Validación QR"],
        summary="Consultar los motivos de rechazo de una validación",
        responses={status.HTTP_200_OK: dict},
    )
    def get(self, request):
        return Response(
            {
                "reasons": [
                    {"value": reason, "message": message}
                    for reason, message in QrRejection.MESSAGES.items()
                ],
                "verdicts": [
                    {"value": "VALID", "label": "Vigente"},
                    {"value": "REJECTED", "label": "No autoriza el ingreso"},
                ],
            },
            status=status.HTTP_200_OK,
        )