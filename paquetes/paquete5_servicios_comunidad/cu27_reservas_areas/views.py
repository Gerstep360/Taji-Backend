"""API del CU27: ``/api/v1/paquete5/cu27/``.

- ``areas/``                         áreas reservables del condominio (lectura).
- ``areas/{id}/availability/?date=``  horarios libres/ocupados de un día (T121).
- ``reservations/``                  listar y solicitar reservas (T122).
- ``reservations/{id}/approve|reject|cancel|complete/``  ciclo de vida (T049).
- ``reservations/calendar/?date_from&date_to``  agenda administrativa (T096).
- ``reservations/summary/``          contadores para la administración.
- ``residents/``                     residentes para reservar a nombre de otro.
"""
from datetime import date, timedelta

from django.db.models import Prefetch, Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from community.models import CommonArea, CommonAreaBlock, CommonAreaSchedule, Reservation
from condominiums.models import Resident, ResidentUnit

from . import services
from .permissions import (
    CanManageReservations,
    CanUseReservations,
    ReservationsTenantMember,
    can_manage,
    can_reserve,
    current_resident,
    current_tenant_id,
)
from .serializers import (
    AreaSerializer,
    BlockCalendarSerializer,
    ReasonSerializer,
    ReservationCreateSerializer,
    ReservationSerializer,
    ResidentOptionSerializer,
)

MAX_CALENDAR_DAYS = 62
BASE_PERMISSIONS = [IsAuthenticated, ReservationsTenantMember, CanUseReservations]


def parse_date(value, field):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValidationError({field: "Usa el formato de fecha AAAA-MM-DD."}) from None


def current_unit_links():
    return Prefetch(
        "resident__unit_links",
        queryset=ResidentUnit.objects.filter(end_date__isnull=True).select_related("unit"),
        to_attr="current_unit_links",
    )


class AreaViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AreaSerializer
    permission_classes = BASE_PERMISSIONS

    def get_queryset(self):
        tenant_id = current_tenant_id()
        if getattr(self, "swagger_fake_view", False) or not tenant_id:
            return CommonArea.objects.none()
        return (
            CommonArea.objects.filter(condominium_id=tenant_id)
            .exclude(status=CommonArea.Status.INACTIVE)
            .select_related("sector")
            .prefetch_related(
                Prefetch("schedules", queryset=CommonAreaSchedule.objects.order_by("weekday", "opens_at")),
                Prefetch("blocks", queryset=CommonAreaBlock.objects.filter(blocked_until__gt=timezone.now())),
            )
            .order_by("name")
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        search = (request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(description__icontains=search))
        if request.query_params.get("bookable") in ("1", "true"):
            queryset = queryset.filter(status=CommonArea.Status.AVAILABLE)
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page if page is not None else queryset, many=True)
        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)

    @action(detail=True, methods=["get"])
    def availability(self, request, pk=None):
        area = self.get_object()
        raw = request.query_params.get("date")
        day = parse_date(raw, "date") if raw else timezone.localdate()
        services.sync_expired(current_tenant_id())
        data = services.compute_availability(
            area,
            day,
            viewer_person_id=getattr(request.user, "person_id", None),
            manager=can_manage(request.user),
        )
        return Response(data)


class ReservationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = BASE_PERMISSIONS

    def get_serializer_class(self):
        return ReservationSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["manager"] = can_manage(self.request.user) if self.request.user.is_authenticated else False
        return context

    def base_queryset(self):
        tenant_id = current_tenant_id()
        if getattr(self, "swagger_fake_view", False) or not tenant_id:
            return Reservation.objects.none()
        qs = Reservation.objects.filter(common_area__condominium_id=tenant_id).select_related(
            "common_area", "resident__person", "approved_by_user__person",
            "cancelled_by_user__person", "created_by_user__person",
        ).prefetch_related(current_unit_links())
        if not can_manage(self.request.user):
            qs = qs.filter(resident__person_id=self.request.user.person_id)
        return qs

    def get_queryset(self):
        qs = self.base_queryset()
        params = self.request.query_params
        statuses = [s for s in (params.get("status") or "").upper().split(",") if s]
        if statuses:
            valid = set(Reservation.Status.values)
            if not set(statuses) <= valid:
                raise ValidationError({"status": "Estado no válido."})
            qs = qs.filter(status__in=statuses)
        if params.get("common_area"):
            area = params["common_area"]
            if not str(area).isdigit():
                raise ValidationError({"common_area": "Área no válida."})
            qs = qs.filter(common_area_id=int(area))
        if params.get("mine") in ("1", "true"):
            qs = qs.filter(resident__person_id=self.request.user.person_id)
        if params.get("date_from"):
            start, _ = services.local_day_bounds(parse_date(params["date_from"], "date_from"))
            qs = qs.filter(end_at__gt=start)
        if params.get("date_to"):
            _, end = services.local_day_bounds(parse_date(params["date_to"], "date_to"))
            qs = qs.filter(start_at__lt=end)
        when = params.get("when")
        now = timezone.now()
        if when == "upcoming":
            qs = qs.filter(end_at__gt=now)
        elif when == "past":
            qs = qs.filter(end_at__lte=now)
        search = (params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(purpose__icontains=search)
                | Q(common_area__name__icontains=search)
                | Q(resident__person__first_name__icontains=search)
                | Q(resident__person__last_name__icontains=search)
            )
        ordering = params.get("ordering") or ("start_at" if when == "upcoming" else "-start_at")
        if ordering not in ("start_at", "-start_at", "created_at", "-created_at"):
            ordering = "-start_at"
        return qs.order_by(ordering, "pk")

    def list(self, request, *args, **kwargs):
        services.sync_expired(current_tenant_id())
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        services.sync_expired(current_tenant_id())
        return super().retrieve(request, *args, **kwargs)

    def _respond(self, reservation, code=status.HTTP_200_OK):
        fresh = self.base_queryset().get(pk=reservation.pk)
        return Response(self.get_serializer(fresh).data, status=code)

    def create(self, request, *args, **kwargs):
        user = request.user
        manager = can_manage(user)
        if not (manager or can_reserve(user)):
            return Response({"detail": "No tienes permiso para reservar áreas."}, status=status.HTTP_403_FORBIDDEN)
        serializer = ReservationCreateSerializer(data=request.data, tenant_id=current_tenant_id())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        resident = data.get("resident")
        own = current_resident(user)
        if resident is None:
            resident = own
            if resident is None:
                raise ValidationError({"resident": "No tienes un perfil de residente activo en este condominio."
                                       if not manager else "Selecciona el residente de la reserva."})
        elif not manager and (own is None or resident.pk != own.pk):
            return Response({"detail": "Solo puedes reservar a tu nombre."}, status=status.HTTP_403_FORBIDDEN)
        reservation = services.create_reservation(
            area=data["common_area"],
            resident=resident,
            start=data["start_at"],
            end=data["end_at"],
            purpose=data.get("purpose", ""),
            actor=user,
            manager=manager,
            request=request,
        )
        return self._respond(reservation, status.HTTP_201_CREATED)

    def _reason(self, request):
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data.get("reason", "")

    @action(detail=True, methods=["post"], permission_classes=BASE_PERMISSIONS + [CanManageReservations])
    def approve(self, request, pk=None):
        reservation = services.approve_reservation(self.get_object(), actor=request.user, request=request)
        return self._respond(reservation)

    @action(detail=True, methods=["post"], permission_classes=BASE_PERMISSIONS + [CanManageReservations])
    def reject(self, request, pk=None):
        reservation = services.reject_reservation(
            self.get_object(), actor=request.user, reason=self._reason(request), request=request
        )
        return self._respond(reservation)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        reservation = services.cancel_reservation(
            self.get_object(),
            actor=request.user,
            reason=self._reason(request),
            manager=can_manage(request.user),
            request=request,
        )
        return self._respond(reservation)

    @action(detail=True, methods=["post"], permission_classes=BASE_PERMISSIONS + [CanManageReservations])
    def complete(self, request, pk=None):
        reservation = services.complete_reservation(self.get_object(), actor=request.user, request=request)
        return self._respond(reservation)

    @action(detail=False, methods=["get"], permission_classes=BASE_PERMISSIONS + [CanManageReservations])
    def calendar(self, request):
        params = request.query_params
        today = timezone.localdate()
        day_from = parse_date(params["date_from"], "date_from") if params.get("date_from") else today
        day_to = parse_date(params["date_to"], "date_to") if params.get("date_to") else day_from + timedelta(days=6)
        if day_to < day_from:
            raise ValidationError({"date_to": "La fecha final debe ser igual o posterior a la inicial."})
        if (day_to - day_from).days + 1 > MAX_CALENDAR_DAYS:
            raise ValidationError({"date_to": f"El rango máximo es de {MAX_CALENDAR_DAYS} días."})
        services.sync_expired(current_tenant_id())
        start, _ = services.local_day_bounds(day_from)
        _, end = services.local_day_bounds(day_to)
        reservations = self.base_queryset().filter(start_at__lt=end, end_at__gt=start)
        blocks = CommonAreaBlock.objects.filter(
            common_area__condominium_id=current_tenant_id(), blocked_from__lt=end, blocked_until__gt=start
        ).select_related("common_area")
        area = params.get("common_area")
        if area:
            if not str(area).isdigit():
                raise ValidationError({"common_area": "Área no válida."})
            reservations = reservations.filter(common_area_id=int(area))
            blocks = blocks.filter(common_area_id=int(area))
        statuses = [s for s in (params.get("status") or "").upper().split(",") if s in Reservation.Status.values]
        if statuses:
            reservations = reservations.filter(status__in=statuses)
        return Response({
            "date_from": day_from.isoformat(),
            "date_to": day_to.isoformat(),
            "reservations": self.get_serializer(reservations.order_by("start_at", "pk"), many=True).data,
            "blocks": BlockCalendarSerializer(blocks.order_by("blocked_from"), many=True).data,
        })

    @action(detail=False, methods=["get"], permission_classes=BASE_PERMISSIONS + [CanManageReservations])
    def summary(self, request):
        services.sync_expired(current_tenant_id())
        qs = self.base_queryset()
        now = timezone.now()
        day_start, day_end = services.local_day_bounds(timezone.localdate())
        week_end = day_start + timedelta(days=7)
        active = qs.filter(status__in=services.ACTIVE_STATUSES)
        return Response({
            "pending": qs.filter(status=Reservation.Status.PENDING).count(),
            "today": active.filter(start_at__lt=day_end, end_at__gt=day_start).count(),
            "in_progress": qs.filter(status=Reservation.Status.APPROVED, start_at__lte=now, end_at__gt=now).count(),
            "next_7_days": active.filter(start_at__gte=now, start_at__lt=week_end).count(),
        })


class ResidentOptionsViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = ResidentOptionSerializer
    permission_classes = BASE_PERMISSIONS + [CanManageReservations]
    pagination_class = None

    def get_queryset(self):
        tenant_id = current_tenant_id()
        if getattr(self, "swagger_fake_view", False) or not tenant_id:
            return Resident.objects.none()
        qs = (
            Resident.objects.all_tenants()
            .filter(condominium_id=tenant_id, status=Resident.Status.ACTIVE)
            .select_related("person")
            .prefetch_related(
                Prefetch(
                    "unit_links",
                    queryset=ResidentUnit.objects.filter(end_date__isnull=True).select_related("unit"),
                    to_attr="current_unit_links",
                )
            )
        )
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(person__first_name__icontains=search)
                | Q(person__last_name__icontains=search)
                | Q(unit_links__unit__code__icontains=search, unit_links__end_date__isnull=True)
            ).distinct()
        return qs.order_by("person__first_name", "person__last_name")[:30]
