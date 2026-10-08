"""Vistas para CU10: Validar la autorización de visitante mediante QR (RF-10 / T022)."""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from auditlog.services import record_audit_event
from security.models import VisitQrScan
from security.qr import (
    QrRejection,
    normalize_scanned_value,
    register_access_event,
    register_scan_log,
    summarize_scans,
    validate_scanned_qr,
)
from security.serializers import GuardStaffSerializer

from .permissions import CanValidateVisitQr
from .serializers import (
    VisitQrScanListResponseSerializer,
    VisitQrScanListSerializer,
    VisitQrValidationRequestSerializer,
    VisitQrValidationSerializer,
    VisitQrScanSerializer,
)


@method_decorator(never_cache, name="dispatch")
class VisitQrValidationView(APIView):
    """
    Controlador para CU10 / T022 (RF-10).

    El personal de seguridad escanea el QR de la visita y el sistema devuelve el
    veredicto con la validez, la vigencia, el estado, el visitante y la unidad
    autorizante antes de permitir el ingreso.

    Dos registros complementarios quedan por cada escaneo:

    * `AccessEvent` responde "¿quién entró?". Solo se crea cuando el QR resuelve
      a una autorización real, aprobado o denegado.
    * `VisitQrScan` responde "¿cuántos escaneos hubo y cómo terminaron?". Incluye
      también los códigos QR desconocidos, que son los intentos fallidos que la
      portería necesita contabilizar. Un tope por actor evita que una cadena
      aleatoria pueda llenar la tabla.
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

        # Bitácora del guardia: incluye los códigos QR desconocidos, que en
        # AccessEvent no dejan rastro. Nunca altera el veredicto devuelto.
        scan = register_scan_log(
            evaluation,
            scanned_value=scanned,
            access_event=event,
            guard_staff=guard_staff,
            user=request.user,
            device_id=data.get("device_id", ""),
            ip_address=self._client_ip(request),
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
                "scan": scan,
            },
            context={"request": request},
        ).data

        # Un rechazo sigue siendo 200: describe un resultado de negocio válido,
        # no un fallo de la API. La app decide qué mostrar según `valid`.
        return Response(body, status=status.HTTP_200_OK)

    @staticmethod
    def _client_ip(request) -> str | None:
        """IP de origen, respetando `X-Forwarded-For` porque nginx es el frontal."""
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            return forwarded.split(",")[0].strip() or None
        return request.META.get("REMOTE_ADDR") or None

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
                "results": [
                    {"value": value, "label": label} for value, label in VisitQrScan.Result.choices
                ],
            },
            status=status.HTTP_200_OK,
        )


class VisitQrScanHistoryView(APIView):
    """
    Historial de escaneos del guardia (RF-10).

    A diferencia de `/security/access-events/`, que solo lista ingresos, este
    endpoint devuelve **todo** escaneo: los aprobados, los denegados y también
    los códigos QR inexistentes. Incluye los totales de la ventana consultada
    para que el tablero muestre cuánto se escaneó, cuánto pasó y cuánto falló
    sin una segunda llamada.
    """

    permission_classes = [IsAuthenticated, CanValidateVisitQr]

    MAX_PAGE_SIZE = 200
    DEFAULT_PAGE_SIZE = 25

    @extend_schema(
        tags=["Seguridad - Validación QR"],
        summary="Consultar el historial de escaneos QR",
        parameters=[
            OpenApiParameter("result", str, description="Filtra por resultado (VALID, REJECTED, NOT_FOUND)."),
            OpenApiParameter("reason", str, description="Filtra por código de motivo."),
            OpenApiParameter("guard_staff_id", int, description="Filtra por guardia."),
            OpenApiParameter("days", int, description="Ventana temporal en días (1-365, por defecto 7)."),
            OpenApiParameter("search", str, description="Busca por visitante, documento o motivo."),
            OpenApiParameter("page", int, description="Página (1-based)."),
            OpenApiParameter("page_size", int, description="Elementos por página (1-200)."),
        ],
        responses={status.HTTP_200_OK: VisitQrScanListResponseSerializer},
    )
    def get(self, request):
        queryset = self._filtered_queryset(request)
        summary = summarize_scans(queryset)

        try:
            page = max(int(request.query_params.get("page", 1)), 1)
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = int(request.query_params.get("page_size", self.DEFAULT_PAGE_SIZE))
        except (TypeError, ValueError):
            page_size = self.DEFAULT_PAGE_SIZE
        page_size = max(1, min(page_size, self.MAX_PAGE_SIZE))

        total = queryset.count()
        offset = (page - 1) * page_size
        rows = list(queryset[offset : offset + page_size])
        serializer = VisitQrScanListSerializer(rows, many=True)

        return Response(
            {
                "count": total,
                "page": page,
                "page_size": page_size,
                "total_pages": max((total + page_size - 1) // page_size, 1),
                "summary": summary,
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def _filtered_queryset(self, request):
        queryset = VisitQrScan.objects.select_related(
            "guard_staff__person", "authorization__visitor_person", "access_event"
        )

        try:
            days = int(request.query_params.get("days", 7))
        except (TypeError, ValueError):
            days = 7
        days = max(1, min(days, 365))
        queryset = queryset.filter(occurred_at__gte=timezone.now() - timedelta(days=days))

        result = request.query_params.get("result", "").strip().upper()
        if result:
            queryset = queryset.filter(result=result)

        reason = request.query_params.get("reason", "").strip().upper()
        if reason:
            queryset = queryset.filter(reason=reason)

        guard_staff_id = request.query_params.get("guard_staff_id", "").strip()
        if guard_staff_id:
            queryset = queryset.filter(guard_staff_id=guard_staff_id)

        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(visitor_name__icontains=search)
                | Q(visitor_document_number__icontains=search)
                | Q(reason__icontains=search)
                | Q(message__icontains=search)
            )

        return queryset.order_by("-occurred_at")


class VisitQrScanGuardsView(APIView):
    """Guardias que han escaneado, para poblar el filtro del historial."""

    permission_classes = [IsAuthenticated, CanValidateVisitQr]

    @extend_schema(
        tags=["Seguridad - Validación QR"],
        summary="Listar guardias con actividad de escaneo",
        responses={status.HTTP_200_OK: GuardStaffSerializer(many=True)},
    )
    def get(self, request):
        from condominiums.models import Staff

        staff_ids = (
            VisitQrScan.objects.exclude(guard_staff_id=None)
            .values_list("guard_staff_id", flat=True)
            .distinct()
        )
        results = Staff.objects.filter(id__in=staff_ids).select_related("person").order_by("person__last_name")
        return Response(GuardStaffSerializer(results, many=True).data)