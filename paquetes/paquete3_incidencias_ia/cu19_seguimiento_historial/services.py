"""Servicio de dominio para CU19: Consultar seguimiento e historial de incidencia.

Implementa la lógica del Controlador/ServicioIncidencia especificado en el diagrama UML
de CU19, integrando T034 (historial de estados), T037 (comentarios públicos/internos) y
T038 (fechas objetivo, cálculo y filtros de pendientes/vencidas).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from django.db import transaction
from django.db.models import Count, Q, QuerySet
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from accounts.models import User
from auditlog.services import record_audit_event
from condominiums.models import Resident, Staff
from incidents.models import (
    Incident,
    IncidentAssignment,
    IncidentAttachment,
    IncidentComment,
    IncidentStatusHistory,
    PriorityLevel,
)
from tenancy.context import TenantContext

from .permissions import (
    can_change_incident_status,
    can_modify_target_date,
    can_post_internal_comments,
    can_view_internal_comments,
    is_admin_user,
    is_directiva_user,
    is_resident_user,
    is_staff_user,
)


OPEN_STATUSES = (
    Incident.Status.REPORTED,
    Incident.Status.REVIEWED,
    Incident.Status.ASSIGNED,
    Incident.Status.IN_PROGRESS,
)

CLOSED_STATUSES = (
    Incident.Status.RESOLVED,
    Incident.Status.CLOSED,
    Incident.Status.CANCELLED,
)

VALID_TRANSITIONS = {
    Incident.Status.REPORTED: [Incident.Status.REVIEWED, Incident.Status.ASSIGNED, Incident.Status.IN_PROGRESS, Incident.Status.CANCELLED],
    Incident.Status.REVIEWED: [Incident.Status.ASSIGNED, Incident.Status.IN_PROGRESS, Incident.Status.CANCELLED],
    Incident.Status.ASSIGNED: [Incident.Status.IN_PROGRESS, Incident.Status.RESOLVED, Incident.Status.CANCELLED],
    Incident.Status.IN_PROGRESS: [Incident.Status.RESOLVED, Incident.Status.CLOSED, Incident.Status.CANCELLED],
    Incident.Status.RESOLVED: [Incident.Status.CLOSED, Incident.Status.IN_PROGRESS],
    Incident.Status.CLOSED: [Incident.Status.IN_PROGRESS],
    Incident.Status.CANCELLED: [Incident.Status.REPORTED],
}


class IncidentTrackingService:
    @staticmethod
    def has_platform_scope(user: User) -> bool:
        """Verdadero para administradores de plataforma (superusuario o staff).

        Los administradores de plataforma consultan el tablero completo de
        incidencias: su búsqueda global no debe quedar atada al condominio
        predeterminado de su membresía.
        """
        if not (user and user.is_authenticated):
            return False
        return bool(user.is_superuser or user.is_staff)

    @classmethod
    def get_user_condominium_id(cls, user: User) -> Optional[int]:
        tenant = TenantContext.get_current_tenant()
        if tenant:
            return tenant.pk

        person = getattr(user, "person", None)
        if person:
            resident = Resident.objects.filter(person=person, status=Resident.Status.ACTIVE).first()
            if resident and resident.condominium_id:
                return resident.condominium_id

            staff = Staff.objects.filter(person=person, status=Staff.Status.ACTIVE).first()
            if staff and staff.condominium_id:
                return staff.condominium_id

        membership = getattr(user, "tenant_memberships", None)
        if membership:
            active_m = membership.filter(is_default=True, is_active=True).first()
            if active_m and active_m.condominium_id:
                return active_m.condominium_id
        return None

    @classmethod
    def resolve_user_scope(cls, user: User, requested_scope: Optional[str] = None) -> str:
        req = (requested_scope or "").upper()
        if is_admin_user(user):
            if req in ("GLOBAL", "PROPIAS", "ASIGNADAS", "IMPORTANTES"):
                return req
            return "GLOBAL"
        if is_directiva_user(user):
            if req in ("GLOBAL", "IMPORTANTES"):
                return req
            return "IMPORTANTES"
        if is_staff_user(user):
            if req in ("PROPIAS", "ASIGNADAS"):
                return req
            return "ASIGNADAS"
        if is_resident_user(user):
            return "PROPIAS"
        return "PROPIAS"

    @classmethod
    def list_incidents(cls, user: User, filters: Dict[str, Any]) -> QuerySet[Incident]:
        queryset = Incident.objects.select_related(
            "reporter_user__person",
            "reporter_resident__person",
            "category",
            "priority",
            "current_assignee_staff__person",
            "sector",
            "unit",
        ).prefetch_related("status_history__changed_by_user__person").order_by("-created_at", "-id")

        if not cls.has_platform_scope(user):
            # El resto de actores queda acotado a su condominio.
            tenant_id = cls.get_user_condominium_id(user)
            if tenant_id:
                queryset = queryset.filter(condominium_id=tenant_id)
            elif not (user.is_superuser and TenantContext.is_global()):
                return queryset.none()

        # Control de alcance por rol
        scope = cls.resolve_user_scope(user, filters.get("scope"))
        person = getattr(user, "person", None)

        if scope == "PROPIAS":
            q_filter = Q(reporter_user=user)
            if person:
                q_filter |= Q(reporter_resident__person=person)
            queryset = queryset.filter(q_filter)
        elif scope == "ASIGNADAS" and person:
            staff_source = Staff.objects.all_tenants() if cls.has_platform_scope(user) else Staff.objects
            staff_obj = staff_source.filter(person=person, status=Staff.Status.ACTIVE).first()
            if staff_obj:
                queryset = queryset.filter(current_assignee_staff=staff_obj)
            else:
                queryset = queryset.none()
        elif scope == "IMPORTANTES":
            # Incidencias de alta prioridad o urgentes
            queryset = queryset.filter(Q(priority__code__in=("HIGH", "URGENT")) | Q(priority__rank__gte=3))

        # Filtros adicionales
        status_val = filters.get("status")
        if status_val:
            queryset = queryset.filter(status=status_val)

        priority_val = filters.get("priority")
        if priority_val:
            if priority_val.isdigit():
                queryset = queryset.filter(priority_id=int(priority_val))
            else:
                queryset = queryset.filter(priority__code=priority_val)

        category_val = filters.get("category")
        if category_val:
            if category_val.isdigit():
                queryset = queryset.filter(category_id=int(category_val))
            else:
                queryset = queryset.filter(category__code=category_val)

        is_pending_val = filters.get("is_pending")
        if is_pending_val is not None:
            if isinstance(is_pending_val, str):
                is_pending_bool = is_pending_val.lower() in ("true", "1", "yes")
            else:
                is_pending_bool = bool(is_pending_val)
            
            if is_pending_bool:
                queryset = queryset.filter(status__in=OPEN_STATUSES)
            else:
                queryset = queryset.exclude(status__in=OPEN_STATUSES)

        sla_status = filters.get("sla_status")
        now = timezone.now()
        if sla_status:
            sla_lower = sla_status.lower()
            if sla_lower == "overdue":
                queryset = queryset.filter(status__in=OPEN_STATUSES, due_at__isnull=False, due_at__lt=now)
            elif sla_lower in ("ontime", "on_time"):
                queryset = queryset.filter(status__in=OPEN_STATUSES).filter(Q(due_at__isnull=True) | Q(due_at__gte=now))
            elif sla_lower == "pending":
                queryset = queryset.filter(status__in=OPEN_STATUSES)
            elif sla_lower == "resolved":
                queryset = queryset.filter(status__in=CLOSED_STATUSES)

        if filters.get("is_overdue") is not None:
            overdue = Q(status__in=OPEN_STATUSES, due_at__lt=now)
            queryset = queryset.filter(overdue) if filters["is_overdue"] else queryset.exclude(overdue)
        for key, lookup in {
            "sector": "sector_id", "unit": "unit_id", "assignee": "current_assignee_staff_id",
            "due_from": "due_at__gte", "due_to": "due_at__lte",
            "created_from": "created_at__gte", "created_to": "created_at__lte",
        }.items():
            if key in filters:
                queryset = queryset.filter(**{lookup: filters[key]})

        search_q = filters.get("search")
        if search_q and str(search_q).strip():
            queryset = queryset.filter(cls.build_search_query(str(search_q).strip()))

        date_from = filters.get("date_from")
        if date_from:
            queryset = queryset.filter(created_at__gte=date_from)

        date_to = filters.get("date_to")
        if date_to:
            queryset = queryset.filter(created_at__lte=date_to)

        return queryset

    @staticmethod
    def build_search_query(term: str) -> Q:
        """Construye el filtro de búsqueda global de incidencias.

        Cada palabra escrita debe aparecer en el código público, el título o la
        descripción (AND entre palabras, OR entre campos). Además se acepta el
        código público completo y el correlativo numérico de la incidencia.
        """
        tokens = [part for part in term.split() if part]
        if not tokens:
            return Q(pk__in=[])

        query = Q()
        for token in tokens:
            query &= (
                Q(public_code__icontains=token)
                | Q(title__icontains=token)
                | Q(description__icontains=token)
            )

        exact = Q(public_code__iexact=term)
        if term.isdigit():
            exact |= Q(pk=int(term))
        return query | exact

    @classmethod
    def get_incident_detail(cls, identifier: Any, user: User) -> Incident:
        sid = str(identifier or "").strip()
        if not sid:
            raise NotFound("La incidencia solicitada no existe.")

        query = Q(public_code__iexact=sid)
        if sid.isdigit():
            query |= Q(pk=int(sid))

        incident = (
            Incident.objects.select_related(
                "reporter_user__person",
                "reporter_resident__person",
                "category",
                "priority",
                "current_assignee_staff__person",
                "sector",
                "unit",
            ).prefetch_related(
                "status_history__changed_by_user__person",
                "comments__author_user__person",
                "attachments__uploaded_by_user__person",
            ).filter(query).first()
        )
        if not incident:
            raise NotFound("La incidencia solicitada no existe.")

        if not cls.list_incidents(user, {}).filter(pk=incident.pk).exists():
            raise NotFound("La incidencia solicitada no está disponible en tu alcance.")
        return incident

    @classmethod
    def calculate_board_metrics(cls, queryset: QuerySet[Incident], user: User) -> Dict[str, Any]:
        total_count = queryset.count()
        open_qs = queryset.filter(status__in=OPEN_STATUSES)
        open_count = open_qs.count()

        now = timezone.now()
        overdue_count = open_qs.filter(due_at__isnull=False, due_at__lt=now).count()
        on_time_count = open_count - overdue_count
        resolved_count = queryset.filter(status__in=CLOSED_STATUSES).count()

        by_status = list(
            queryset.values("status").annotate(count=Count("id")).order_by("status")
        )
        by_priority = list(
            queryset.values("priority__name", "priority__code").annotate(count=Count("id")).order_by("priority__rank")
        )

        return {
            "total_count": total_count,
            "open_count": open_count,
            "pending_count": open_count,
            "overdue_count": overdue_count,
            "on_time_count": on_time_count,
            "resolved_count": resolved_count,
            "by_status": by_status,
            "by_priority": by_priority,
        }

    @classmethod
    def list_status_history(cls, incident: Incident) -> QuerySet[IncidentStatusHistory]:
        return incident.status_history.select_related("changed_by_user__person").order_by("changed_at")

    @classmethod
    @transaction.atomic
    def change_status(
        cls,
        incident: Incident,
        new_status: str,
        user: User,
        comment: str = "",
        request=None,
    ) -> tuple[Incident, IncidentStatusHistory]:
        incident = Incident.objects.select_for_update().get(pk=incident.pk)
        if new_status not in Incident.Status.values:
            raise ValidationError({"status": f"Estado inválido: {new_status}"})

        if new_status == incident.status:
            raise ValidationError({"status": "La incidencia ya se encuentra en este estado."})

        if not can_change_incident_status(user, incident, new_status):
            raise PermissionDenied("No tienes permiso para cambiar la incidencia a este estado.")

        if new_status not in VALID_TRANSITIONS.get(incident.status, ()):
            raise ValidationError({"status": "Esta transición no está permitida."})
        if new_status in (Incident.Status.ASSIGNED, Incident.Status.IN_PROGRESS) and not incident.current_assignee_staff_id:
            raise ValidationError({"status": "Primero asigna una persona responsable."})

        old_status = incident.status
        incident.status = new_status
        if new_status in OPEN_STATUSES:
            incident.resolved_at = None
            incident.closed_at = None

        if new_status in CLOSED_STATUSES:
            incident.assignments.filter(ended_at__isnull=True).update(ended_at=timezone.now())
        elif old_status in CLOSED_STATUSES and incident.current_assignee_staff_id:
            IncidentAssignment.objects.create(
                incident=incident, assigned_to_staff=incident.current_assignee_staff,
                assigned_by_user=user, reason="Reapertura de incidencia",
            )

        if new_status == Incident.Status.RESOLVED and not incident.resolved_at:
            incident.resolved_at = timezone.now()
        elif new_status == Incident.Status.CLOSED and not incident.closed_at:
            incident.closed_at = timezone.now()

        incident.save()

        history_entry = IncidentStatusHistory.objects.create(
            incident=incident,
            changed_by_user=user,
            from_status=old_status,
            to_status=new_status,
            comment=comment or f"Cambio de estado a {incident.get_status_display()}",
        )

        try:
            record_audit_event(
                actor_user=user,
                action_code="INCIDENT_STATUS_CHANGE",
                resource_type="Incident", resource_id=incident.pk,
                before_data={"status": old_status}, after_data={"status": new_status},
                description=f"Incidencia {incident.public_code} cambió de {old_status} a {new_status}",
                request=request,
            )
        except Exception:
            pass

        return incident, history_entry

    @classmethod
    def add_comment(
        cls,
        incident: Incident,
        user: User,
        body: str,
        visibility: str = "PUBLIC",
        request=None,
    ) -> IncidentComment:
        vis = visibility.upper()
        if vis == IncidentComment.Visibility.INTERNAL and not can_post_internal_comments(user):
            raise PermissionDenied("No tienes permiso para publicar comentarios internos.")

        comment = IncidentComment.objects.create(
            incident=incident,
            author_user=user,
            body=body,
            visibility=vis,
        )

        try:
            record_audit_event(
                actor_user=user,
                action_code="INCIDENT_COMMENT_ADD",
                resource_type="Incident", resource_id=incident.pk,
                description=f"Nuevo comentario ({vis}) en incidencia {incident.public_code}",
                request=request,
            )
        except Exception:
            pass

        return comment

    @classmethod
    def list_comments(
        cls,
        incident: Incident,
        user: User,
        visibility: Optional[str] = None,
    ) -> QuerySet[IncidentComment]:
        qs = incident.comments.select_related("author_user__person").order_by("created_at")

        if not can_view_internal_comments(user):
            if visibility and visibility.upper() == IncidentComment.Visibility.INTERNAL:
                raise PermissionDenied("Los comentarios internos solo están disponibles para el equipo autorizado.")
            qs = qs.filter(visibility=IncidentComment.Visibility.PUBLIC)

        if visibility:
            qs = qs.filter(visibility=visibility.upper())

        return qs

    @classmethod
    @transaction.atomic
    def set_target_date(
        cls,
        incident: Incident,
        user: User,
        due_at: Optional[datetime] = None,
        target_minutes: Optional[int] = None,
        request=None,
    ) -> Incident:
        if not can_modify_target_date(user):
            raise PermissionDenied("Solo los administradores pueden modificar la fecha objetivo.")

        if target_minutes is not None:
            base_time = incident.created_at or timezone.now()
            incident.due_at = base_time + timezone.timedelta(minutes=target_minutes)
        elif due_at is not None:
            incident.due_at = due_at

        incident.save()

        try:
            record_audit_event(
                actor_user=user,
                action_code="INCIDENT_SET_TARGET_DATE",
                resource_type="Incident", resource_id=incident.pk,
                description=f"Fecha objetivo actualizada para incidencia {incident.public_code}",
                request=request,
            )
        except Exception:
            pass

        return incident
