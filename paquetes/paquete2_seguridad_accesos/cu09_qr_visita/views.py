"""Vistas para CU09: Generar y consultar el QR temporal de visita (RF-09 / T021)."""

from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from auditlog.services import record_audit_event
from security.models import VisitAuthorization
from security.qr import VisitQrError, build_payload, issue_visit_qr

from .permissions import CanIssueVisitQr
from .serializers import VisitQrIssueRequestSerializer, VisitQrSerializer, resolve_image_format


@method_decorator(never_cache, name="dispatch")
class VisitQrViewSet(viewsets.ViewSet):
    """
    Controlador para CU09 / T021 (RF-09):

    - Emisión del QR con vigencia acotada a la ventana de la visita.
    - Consulta del estado de vigencia y expiración del QR.
    - Invalidación inmediata del QR anterior al rotarlo.
    - Registro de auditoría de cada emisión.

    La imagen del QR se entrega dentro de la respuesta de emisión, en SVG o PNG.
    No hay un endpoint aparte de descarga porque el token en claro solo existe en
    ese instante: reconstruirlo después exigiría almacenarlo en claro.
    """

    permission_classes = [IsAuthenticated, CanIssueVisitQr]
    lookup_value_regex = "[0-9]+"

    def get_queryset(self):
        return VisitAuthorization.objects.select_related(
            "visitor_person",
            "authorized_by_resident__person",
            "unit__sector",
        )

    def _get_authorization(self):
        """
        Resuelve la autorización aplicando el aislamiento de información (RN4).

        Al residente se le acota el queryset a sus propias autorizaciones, de modo
        que el QR de otro residente responde 404 y no 403: no conviene confirmar
        siquiera la existencia de visitas ajenas.
        """
        user = self.request.user
        queryset = self.get_queryset()

        if not user.has_system_permission("manage_visits"):
            resident = getattr(getattr(user, "person", None), "resident", None)
            if resident is None:
                raise NotFound("No se encontró la autorización de visita solicitada.")
            queryset = queryset.filter(authorized_by_resident=resident)

        authorization = queryset.filter(pk=self.kwargs.get("pk")).first()
        if authorization is None:
            raise NotFound("No se encontró la autorización de visita solicitada.")

        self.check_object_permissions(self.request, authorization)
        return authorization

    @extend_schema(
        tags=["Seguridad - QR de visita"],
        summary="Consultar el QR de una visita",
        description=(
            "Informa si la autorización tiene un QR emitido y si continúa vigente, con su "
            "fecha de expiración y los segundos restantes. Por seguridad no devuelve el "
            "contenido del QR: ese dato solo existe mientras se emite el código."
        ),
        responses={status.HTTP_200_OK: VisitQrSerializer},
    )
    def retrieve(self, request, pk=None):
        authorization = self._get_authorization()
        # Se refresca el estado antes de responder para que un QR vencido no figure activo.
        _expire_if_window_ended(authorization)

        serializer = VisitQrSerializer(
            authorization, context={"request": request, "payload": None, "image_format": "svg"}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Seguridad - QR de visita"],
        summary="Generar el QR temporal de una visita",
        description=(
            "Emite el QR de la autorización con vigencia limitada y fecha de expiración. "
            "Es idempotente: si ya existe un QR vigente lo devuelve sin rotarlo, de modo que "
            "el código que el visitante ya tiene no se invalida. Envía `force=true` para "
            "rotarlo y anular el anterior. La respuesta incluye el contenido del QR y su "
            "imagen lista para mostrar o compartir (`image_format=svg|png`)."
        ),
        parameters=[
            OpenApiParameter(
                "image_format",
                str,
                description="Formato de la imagen: svg (por defecto) o png.",
            )
        ],
        request=VisitQrIssueRequestSerializer,
        responses={
            status.HTTP_200_OK: VisitQrSerializer,
            status.HTTP_201_CREATED: VisitQrSerializer,
        },
    )
    @action(detail=True, methods=["post"], url_path="generate")
    def generate(self, request, pk=None):
        authorization = self._get_authorization()
        _expire_if_window_ended(authorization)

        request_serializer = VisitQrIssueRequestSerializer(data=request.data or {})
        request_serializer.is_valid(raise_exception=True)
        options = request_serializer.validated_data

        image_format = resolve_image_format(request)
        force = bool(options.get("force"))

        # Emisión idempotente: se respeta el QR vigente salvo que se exija rotarlo.
        # El token en claro no está disponible aquí, así que se informa issued=True
        # y el cliente vuelve a invocar generate para obtener la imagen.
        if not force and authorization.is_qr_issued() and authorization.is_qr_active():
            return Response(
                self._qr_response(authorization, request, payload=None, rotated=False),
                status=status.HTTP_200_OK,
            )

        was_issued = authorization.is_qr_issued()
        before_data = None
        if was_issued:
            before_data = {
                "qr_issued_at": authorization.qr_issued_at.isoformat(),
                "qr_expires_at": authorization.qr_expires_at.isoformat(),
            }

        try:
            authorization, token = issue_visit_qr(
                authorization, ttl_minutes=options.get("ttl_minutes")
            )
        except VisitQrError as exc:
            raise ValidationError({exc.code: [exc.message]}) from exc

        record_audit_event(
            action_code="VISIT_QR_ISSUED" if not was_issued else "VISIT_QR_ROTATED",
            resource_type="VisitAuthorization",
            resource_id=authorization.id,
            description=(
                f"QR {'emitido' if not was_issued else 'rotado'} para la visita de "
                f"{authorization.visitor_person.full_name} en la unidad {authorization.unit.code}."
            ),
            actor_user=request.user,
            before_data=before_data,
            after_data={
                "qr_uuid": str(authorization.qr_uuid),
                "qr_issued_at": authorization.qr_issued_at.isoformat(),
                "qr_expires_at": authorization.qr_expires_at.isoformat(),
                "status": authorization.status,
            },
            request=request,
        )

        payload = build_payload(authorization.qr_uuid, token)
        return Response(
            self._qr_response(authorization, request, payload=payload, rotated=was_issued),
            status=status.HTTP_200_OK if was_issued else status.HTTP_201_CREATED,
        )

    def _qr_response(self, authorization, request, payload, rotated: bool):
        serializer = VisitQrSerializer(
            authorization,
            context={
                "request": request,
                "payload": payload,
                "image_format": resolve_image_format(request),
            },
        )
        data = dict(serializer.data)
        data["rotated"] = rotated
        return data


def _expire_if_window_ended(authorization: VisitAuthorization) -> bool:
    """
    Persiste el estado EXPIRED cuando la ventana de la visita ya Conclusionó.

    Garantiza que el QR quede inutilizable en la base de datos y no solo en la
    respuesta, sin depender de que alguien escanee el código.
    """
    if authorization.status in (
        VisitAuthorization.Status.AUTHORIZED,
        VisitAuthorization.Status.ACTIVE,
    ) and authorization.valid_until <= timezone.now():
        authorization.status = VisitAuthorization.Status.EXPIRED
        authorization.save(update_fields=["status"])
        return True
    return False