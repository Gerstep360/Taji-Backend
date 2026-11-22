from pathlib import PurePosixPath

from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from auditlog.models import AuditEvent
from community.models import Agreement, AgreementAttachment, Assembly
from tenancy.context import TenantContext
from tenancy.models import TenantMembership

from . import services
from .permissions import AssemblyTenantMember, CanTrackAgreements, can_manage, can_track
from .serializers import (
    OPEN_AGREEMENT_STATUSES,
    AgreementAttachmentSerializer,
    AgreementAttachmentUploadSerializer,
    AgreementCancelSerializer,
    AgreementCompleteSerializer,
    AgreementHistorySerializer,
    AgreementSerializer,
    AgreementStartSerializer,
    ResponsibleOptionSerializer,
    AssemblyCancelSerializer,
    AssemblyFinishSerializer,
    AssemblyPublicSerializer,
    AssemblySerializer,
    _user_label,
)

ASSEMBLY_TAG = ["Asambleas - CU29"]
AGREEMENT_TAG = ["Acuerdos - CU29"]


def _require_manager(request):
    if not can_manage(request.user):
        raise PermissionDenied("Solo la administración puede gestionar asambleas y acuerdos.")


def _snapshot(obj, *fields):
    return {name: str(getattr(obj, name)) if getattr(obj, name) is not None else None for name in fields}


@method_decorator(never_cache, name="dispatch")
@extend_schema_view(
    list=extend_schema(
        tags=ASSEMBLY_TAG, summary="Listar asambleas",
        parameters=[OpenApiParameter("status", str, description="SCHEDULED, IN_PROGRESS, FINISHED o CANCELLED")],
    ),
    retrieve=extend_schema(tags=ASSEMBLY_TAG, summary="Consultar una asamblea"),
    create=extend_schema(tags=ASSEMBLY_TAG, summary="Programar una asamblea"),
    partial_update=extend_schema(tags=ASSEMBLY_TAG, summary="Editar datos o acta de una asamblea"),
)
class AssemblyViewSet(viewsets.ModelViewSet):
    """Asambleas del condominio. Admin gestiona; Directiva consulta; residentes ven solo las programadas."""

    permission_classes = [IsAuthenticated, AssemblyTenantMember]
    http_method_names = ["get", "post", "patch", "head", "options"]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ("title", "description", "location")
    ordering_fields = ("scheduled_at", "created_at", "title")
    ordering = ("-scheduled_at",)

    def get_serializer_class(self):
        if self.action in ("finish",):
            return AssemblyFinishSerializer
        if self.action in ("cancel",):
            return AssemblyCancelSerializer
        if self.action == "agreements":
            return AgreementSerializer
        if can_track(self.request.user):
            return AssemblySerializer
        return AssemblyPublicSerializer

    def create(self, request, *args, **kwargs):
        _require_manager(request)
        return super().create(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        _require_manager(request)
        return super().partial_update(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Assembly.objects.none()
        qs = Assembly.objects.filter(condominium_id=TenantContext.get_current_tenant_id())
        if not can_track(self.request.user):
            qs = qs.filter(status=Assembly.Status.SCHEDULED)
        wanted = self.request.query_params.get("status")
        if wanted and self.action == "list":
            qs = qs.filter(status=wanted.upper())
        return qs.select_related("created_by_user__person").annotate(
            agreements_total=Count("agreements", distinct=True),
            agreements_open=Count("agreements", filter=Q(agreements__status__in=OPEN_AGREEMENT_STATUSES), distinct=True),
        )

    def perform_create(self, serializer):
        _require_manager(self.request)
        assembly = serializer.save(
            condominium_id=TenantContext.get_current_tenant_id(),
            created_by_user=self.request.user,
        )
        services.audit(self.request, assembly, "ASSEMBLY_CREATED", after=_snapshot(assembly, "status", "scheduled_at"),
                       description=f"Asamblea programada: {assembly.title}")

    def perform_update(self, serializer):
        _require_manager(self.request)
        before = _snapshot(serializer.instance, "title", "scheduled_at", "location")
        assembly = serializer.save()
        services.audit(self.request, assembly, "ASSEMBLY_UPDATED", before=before,
                       after=_snapshot(assembly, "title", "scheduled_at", "location"),
                       description="Asamblea actualizada")

    def _transition(self, request, allowed_from, to_status, action_code, description, **updates):
        _require_manager(request)
        tenant = TenantContext.get_current_tenant_id()
        with transaction.atomic():
            try:
                assembly = Assembly.objects.select_for_update().get(pk=self.kwargs["pk"], condominium_id=tenant)
            except Assembly.DoesNotExist:
                raise Http404 from None
            if assembly.status not in allowed_from:
                raise ValidationError(
                    f"No se puede pasar de «{assembly.get_status_display()}» a «{dict(Assembly.Status.choices)[to_status]}»."
                )
            before = _snapshot(assembly, "status")
            assembly.status = to_status
            for name, value in updates.items():
                setattr(assembly, name, value)
            assembly.save()
        services.audit(request, assembly, action_code, before=before, after=_snapshot(assembly, "status"),
                       description=description)
        return Response(AssemblySerializer(assembly, context=self.get_serializer_context()).data)

    @extend_schema(tags=ASSEMBLY_TAG, summary="Iniciar la asamblea", request=None, responses=AssemblySerializer)
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        return self._transition(request, (Assembly.Status.SCHEDULED,), Assembly.Status.IN_PROGRESS,
                                "ASSEMBLY_STARTED", "Asamblea iniciada")

    @extend_schema(tags=ASSEMBLY_TAG, summary="Finalizar la asamblea y registrar el acta",
                   request=AssemblyFinishSerializer, responses=AssemblySerializer)
    @action(detail=True, methods=["post"])
    def finish(self, request, pk=None):
        _require_manager(request)
        payload = AssemblyFinishSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return self._transition(request, (Assembly.Status.IN_PROGRESS,), Assembly.Status.FINISHED,
                                "ASSEMBLY_FINISHED", "Asamblea finalizada con acta",
                                minutes_text=payload.validated_data["minutes_text"])

    @extend_schema(tags=ASSEMBLY_TAG, summary="Cancelar la asamblea",
                   request=AssemblyCancelSerializer, responses=AssemblySerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        _require_manager(request)
        payload = AssemblyCancelSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        reason = payload.validated_data.get("reason", "")
        return self._transition(request, (Assembly.Status.SCHEDULED, Assembly.Status.IN_PROGRESS),
                                Assembly.Status.CANCELLED, "ASSEMBLY_CANCELLED",
                                f"Asamblea cancelada. {reason}".strip())

    @extend_schema(tags=ASSEMBLY_TAG, summary="Acuerdos de una asamblea", responses=AgreementSerializer(many=True))
    @action(detail=True, methods=["get"])
    def agreements(self, request, pk=None):
        if not can_track(request.user):
            raise PermissionDenied("Solo la administración y la directiva pueden consultar los acuerdos.")
        assembly = self.get_object()
        services.mark_overdue_agreements(TenantContext.get_current_tenant_id())
        qs = assembly.agreements.select_related("assembly", "responsible_user__person").annotate(
            attachments_total=Count("attachments")
        ).order_by("due_at", "id")
        return Response(AgreementSerializer(qs, many=True, context=self.get_serializer_context()).data)


@method_decorator(never_cache, name="dispatch")
@extend_schema_view(
    list=extend_schema(
        tags=AGREEMENT_TAG, summary="Listar acuerdos",
        parameters=[
            OpenApiParameter("assembly", int, description="Filtrar por asamblea"),
            OpenApiParameter("status", str, description="PENDING, IN_PROGRESS, COMPLETED, OVERDUE o CANCELLED"),
            OpenApiParameter("responsible", int, description="Filtrar por responsable (id de usuario)"),
        ],
    ),
    retrieve=extend_schema(tags=AGREEMENT_TAG, summary="Consultar un acuerdo"),
    create=extend_schema(tags=AGREEMENT_TAG, summary="Registrar un acuerdo"),
    partial_update=extend_schema(tags=AGREEMENT_TAG, summary="Editar un acuerdo"),
)
class AgreementViewSet(viewsets.ModelViewSet):
    """Acuerdos de asamblea con responsable, plazo, presupuesto, costo y seguimiento."""

    serializer_class = AgreementSerializer
    permission_classes = [IsAuthenticated, AssemblyTenantMember, CanTrackAgreements]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ("title", "description")
    ordering_fields = ("due_at", "created_at", "status")
    ordering = ("due_at", "id")

    def create(self, request, *args, **kwargs):
        _require_manager(request)
        return super().create(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        _require_manager(request)
        return super().partial_update(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Agreement.objects.none()
        tenant = TenantContext.get_current_tenant_id()
        services.mark_overdue_agreements(tenant)
        qs = Agreement.objects.filter(assembly__condominium_id=tenant).select_related(
            "assembly", "responsible_user__person"
        ).annotate(attachments_total=Count("attachments", distinct=True))
        params = self.request.query_params
        if self.action == "list":
            if params.get("assembly", "").isdigit():
                qs = qs.filter(assembly_id=int(params["assembly"]))
            if params.get("responsible", "").isdigit():
                qs = qs.filter(responsible_user_id=int(params["responsible"]))
            if params.get("status"):
                qs = qs.filter(status=params["status"].upper())
        return qs

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE")

    def perform_create(self, serializer):
        _require_manager(self.request)
        agreement = serializer.save()
        services.audit(self.request, agreement, "AGREEMENT_CREATED", after=_snapshot(agreement, "status", "due_at"),
                       description=f"Acuerdo registrado: {agreement.title}")

    def perform_update(self, serializer):
        _require_manager(self.request)
        instance = serializer.instance
        before = _snapshot(instance, "status", "due_at", "estimated_budget", "actual_cost")
        extra = {}
        new_due = serializer.validated_data.get("due_at")
        if instance.status == Agreement.Status.OVERDUE and new_due and new_due > timezone.now():
            extra["status"] = Agreement.Status.IN_PROGRESS
        agreement = serializer.save(**extra)
        services.audit(self.request, agreement, "AGREEMENT_UPDATED", before=before,
                       after=_snapshot(agreement, "status", "due_at", "estimated_budget", "actual_cost"),
                       description="Plazo reprogramado" if extra else "Acuerdo actualizado")

    def _transition(self, request, allowed_from, to_status, action_code, description, **updates):
        _require_manager(request)
        tenant = TenantContext.get_current_tenant_id()
        with transaction.atomic():
            try:
                agreement = Agreement.objects.select_for_update().get(
                    pk=self.kwargs["pk"], assembly__condominium_id=tenant
                )
            except Agreement.DoesNotExist:
                raise Http404 from None
            if agreement.status not in allowed_from:
                raise ValidationError(
                    f"No se puede pasar de «{agreement.get_status_display()}» a «{dict(Agreement.Status.choices)[to_status]}»."
                )
            before = _snapshot(agreement, "status", "actual_cost")
            agreement.status = to_status
            for name, value in updates.items():
                setattr(agreement, name, value)
            agreement.save()
        services.audit(request, agreement, action_code, before=before,
                       after=_snapshot(agreement, "status", "actual_cost"), description=description)
        agreement = self.get_queryset().get(pk=agreement.pk)
        return Response(AgreementSerializer(agreement, context=self.get_serializer_context()).data)

    @extend_schema(tags=AGREEMENT_TAG, summary="Iniciar la ejecución del acuerdo",
                   request=AgreementStartSerializer, responses=AgreementSerializer)
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        _require_manager(request)
        payload = AgreementStartSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        comment = payload.validated_data.get("comment", "")
        return self._transition(request, (Agreement.Status.PENDING,), Agreement.Status.IN_PROGRESS,
                                "AGREEMENT_STARTED", f"Ejecución iniciada. {comment}".strip())

    @extend_schema(tags=AGREEMENT_TAG, summary="Completar el acuerdo (opcionalmente con costo real)",
                   request=AgreementCompleteSerializer, responses=AgreementSerializer)
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        _require_manager(request)
        payload = AgreementCompleteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        updates = {"completed_at": timezone.now()}
        if payload.validated_data.get("actual_cost") is not None:
            updates["actual_cost"] = payload.validated_data["actual_cost"]
        comment = payload.validated_data.get("comment", "")
        return self._transition(
            request,
            (Agreement.Status.PENDING, Agreement.Status.IN_PROGRESS, Agreement.Status.OVERDUE),
            Agreement.Status.COMPLETED, "AGREEMENT_COMPLETED", f"Acuerdo completado. {comment}".strip(), **updates,
        )

    @extend_schema(tags=AGREEMENT_TAG, summary="Cancelar el acuerdo",
                   request=AgreementCancelSerializer, responses=AgreementSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        _require_manager(request)
        payload = AgreementCancelSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return self._transition(
            request,
            (Agreement.Status.PENDING, Agreement.Status.IN_PROGRESS, Agreement.Status.OVERDUE),
            Agreement.Status.CANCELLED, "AGREEMENT_CANCELLED",
            f"Acuerdo cancelado. {payload.validated_data['reason']}",
        )

    @extend_schema(tags=AGREEMENT_TAG, summary="Miembros del condominio elegibles como responsables",
                   responses={200: ResponsibleOptionSerializer(many=True)})
    @action(detail=False, methods=["get"])
    def responsibles(self, request):
        members = TenantMembership.objects.filter(
            condominium_id=TenantContext.get_current_tenant_id(), is_active=True, user__is_active=True,
        ).select_related("user__person", "role").order_by("user__person__first_name", "user__email")
        data = [
            {"id": m.user_id, "name": _user_label(m.user), "role": m.role.name if m.role else ""}
            for m in members
        ]
        return Response(ResponsibleOptionSerializer(data, many=True).data)

    @extend_schema(tags=AGREEMENT_TAG, summary="Historial de seguimiento del acuerdo",
                   responses=AgreementHistorySerializer(many=True))
    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        agreement = self.get_object()
        events = AuditEvent.objects.filter(
            condominium_id=TenantContext.get_current_tenant_id(),
            resource_type="Agreement", resource_id=str(agreement.pk),
        ).select_related("actor_user__person").order_by("occurred_at", "id")
        data = [
            {
                "id": event.pk,
                "action_code": event.action_code,
                "description": event.description,
                "actor_name": _user_label(event.actor_user),
                "occurred_at": event.occurred_at,
                "before_status": (event.before_data or {}).get("status"),
                "after_status": (event.after_data or {}).get("status"),
            }
            for event in events
        ]
        return Response(AgreementHistorySerializer(data, many=True).data)

    @extend_schema(
        tags=AGREEMENT_TAG, summary="Listar o subir evidencias del acuerdo",
        request=AgreementAttachmentUploadSerializer, responses=AgreementAttachmentSerializer(many=True),
    )
    @action(detail=True, methods=["get", "post"], url_path="attachments",
            parser_classes=[MultiPartParser, FormParser, JSONParser])
    def attachments(self, request, pk=None):
        agreement = self.get_object()
        if request.method == "GET":
            qs = agreement.attachments.select_related("uploaded_by_user__person").order_by("-created_at", "-id")
            return Response(AgreementAttachmentSerializer(qs, many=True, context=self.get_serializer_context()).data)

        _require_manager(request)
        if agreement.status == Agreement.Status.CANCELLED:
            raise ValidationError("No se pueden adjuntar evidencias a un acuerdo cancelado.")
        payload = AgreementAttachmentUploadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        if agreement.attachments.count() >= services.MAX_ATTACHMENTS_PER_AGREEMENT:
            raise ValidationError(
                {"file": f"Máximo {services.MAX_ATTACHMENTS_PER_AGREEMENT} evidencias por acuerdo."}
            )
        upload = payload.validated_data["file"]
        name = services.validate_upload(upload)
        tenant = TenantContext.get_current_tenant_id()
        stored = services.store_attachment(agreement, tenant, upload, name)
        try:
            attachment = AgreementAttachment.objects.create(
                agreement=agreement, uploaded_by_user=request.user, file_path=stored,
                description=payload.validated_data.get("description", "").strip(),
            )
        except Exception:
            services.delete_stored_file(stored)
            raise
        services.audit(request, agreement, "AGREEMENT_ATTACHMENT_ADDED",
                       description=f"Evidencia adjuntada: {name}")
        return Response(
            AgreementAttachmentSerializer(attachment, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    def _attachment(self, agreement, attachment_id):
        attachment = agreement.attachments.filter(pk=attachment_id).first()
        prefix = services.storage_prefix(TenantContext.get_current_tenant_id(), agreement.pk)
        path = attachment.file_path if attachment else ""
        if not attachment or not path.startswith(prefix) or ".." in PurePosixPath(path).parts:
            raise Http404
        return attachment

    @extend_schema(tags=AGREEMENT_TAG, summary="Descargar una evidencia", responses={200: bytes})
    @action(detail=True, methods=["get"], url_path=r"attachments/(?P<attachment_id>[0-9]+)/download")
    def download_attachment(self, request, pk=None, attachment_id=None):
        agreement = self.get_object()
        attachment = self._attachment(agreement, attachment_id)
        if not default_storage.exists(attachment.file_path):
            raise Http404
        name = PurePosixPath(attachment.file_path).name.split("-", 1)[-1]
        return FileResponse(default_storage.open(attachment.file_path, "rb"), as_attachment=True, filename=name)

    @extend_schema(tags=AGREEMENT_TAG, summary="Eliminar una evidencia", responses={204: None})
    @action(detail=True, methods=["delete"], url_path=r"attachments/(?P<attachment_id>[0-9]+)")
    def delete_attachment(self, request, pk=None, attachment_id=None):
        _require_manager(request)
        agreement = self.get_object()
        attachment = self._attachment(agreement, attachment_id)
        path, name = attachment.file_path, PurePosixPath(attachment.file_path).name.split("-", 1)[-1]
        attachment.delete()
        services.delete_stored_file(path)
        services.audit(request, agreement, "AGREEMENT_ATTACHMENT_REMOVED", description=f"Evidencia eliminada: {name}")
        return Response(status=status.HTTP_204_NO_CONTENT)
