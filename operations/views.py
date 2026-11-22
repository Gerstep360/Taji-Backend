from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import Throttled, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from auditlog.services import record_audit_event
from condominiums.models import Condominium
from tenancy.context import TenantContext
from tenancy.permissions import IsTenantMember

from .ai import AdvisorUnavailable, advise, inputs
from .models import AnalysisAttempt, OperationsRecord
from .serializers import AnalysisInput, RecordSerializer, STATUSES


class OperationsAdmin(BasePermission):
    def has_permission(self, request, view):
        user, tenant = request.user, TenantContext.get_current_tenant()
        if not (tenant and tenant.is_active and user.is_authenticated and user.is_active and user.is_approved):
            return False
        if user.is_superuser:
            return True
        member = TenantContext.get_current_membership()
        return bool(member and member.user_id == user.pk and member.condominium_id == tenant.pk
                    and member.is_active and member.role and member.role.is_active
                    and member.role.permissions.filter(code="manage_settings", is_active=True).exists())


class RecordPagination(PageNumberPagination):
    page_size = 20


class Records(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
              mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = RecordSerializer
    permission_classes = [IsTenantMember, OperationsAdmin]
    pagination_class = RecordPagination

    def get_queryset(self):
        return OperationsRecord.objects.filter(condominium_id=TenantContext.get_current_tenant_id(),
                                               kind=self.kwargs["kind"]).order_by("-date", "-id")

    def list(self, request, *args, **kwargs):
        records = self.get_queryset()
        search = request.query_params.get("q", "").strip()[:100]
        state = request.query_params.get("status")
        if search:
            records = records.filter(Q(title__icontains=search) | Q(details__reference__icontains=search)
                                     | Q(details__request_code__icontains=search) | Q(details__location__icontains=search))
        if state:
            if state not in STATUSES[self.kwargs["kind"]]:
                raise ValidationError({"status": "Estado inválido."})
            records = records.filter(status=state)
        page = self.paginate_queryset(records)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def log(self, event, record):
        record_audit_event(action_code=f"operations.{event}", resource_type=record.kind,
                           resource_id=record.pk, description="Registro administrativo web", request=self.request)

    @transaction.atomic
    def perform_create(self, serializer):
        record = serializer.save(condominium_id=TenantContext.get_current_tenant_id(),
                                 created_by=self.request.user, kind=self.kwargs["kind"])
        self.log("create", record)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        record = self.get_object()
        serializer = self.get_serializer(record, data=request.data)
        serializer.is_valid(raise_exception=True)
        self.log("update", serializer.save())
        return Response(serializer.data)

    @transaction.atomic
    def perform_destroy(self, record):
        self.log("delete", record)
        record.delete()

    @action(detail=False, methods=["post"])
    def analyze(self, request, *args, **kwargs):
        kind = self.kwargs["kind"]
        if kind not in ("quotes", "inspections"):
            raise ValidationError("Este módulo no solicita análisis de IA.")
        serializer = AnalysisInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["ids"]
        records = self.get_queryset().in_bulk(ids)
        if len(records) != len(ids):
            raise ValidationError("Hay registros no disponibles para este análisis.")
        facts = inputs(kind, [records[pk] for pk in ids])
        self.reserve_attempt()
        try:
            suggestion = advise(kind, facts)
        except AdvisorUnavailable:
            return Response({"facts": facts, "ids": ids, "suggestion": None,
                             "message": "NVIDIA no respondió. Puedes seguir con la revisión manual."})
        return Response({"facts": facts, "ids": ids, "suggestion": suggestion})

    @transaction.atomic
    def reserve_attempt(self):
        tenant_id = TenantContext.get_current_tenant_id()
        Condominium.objects.select_for_update().only("id").get(pk=tenant_id)
        attempts = AnalysisAttempt.objects.filter(condominium_id=tenant_id)
        now = timezone.now()
        attempts.filter(created_at__lt=now - timedelta(days=1)).delete()
        if attempts.filter(created_at__gte=now - timedelta(minutes=1)).count() >= 4:
            raise Throttled(wait=60, detail="Espera antes de solicitar otro análisis.")
        attempts.create(condominium_id=tenant_id)
