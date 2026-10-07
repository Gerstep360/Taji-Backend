from django.db.models import Q
from rest_framework import generics, mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from accounts.models import Person
from condominiums.models import ResidentUnit, Unit
from security.models import AccessEvent
from security.serializers import AccessEventSerializer


class CanRegisterAccessEvents(BasePermission):
    message = "No tienes permiso para registrar accesos de portería."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return bool(user.is_superuser or user.has_system_permission("register_entry_exit"))


class AccessEventViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = AccessEvent.objects.select_related(
        "person", "guard_staff__person", "authorization", "unit__sector"
    )
    serializer_class = AccessEventSerializer
    permission_classes = [permissions.IsAuthenticated, CanRegisterAccessEvents]
    ordering = ("-occurred_at",)

    def get_queryset(self):
        queryset = self.queryset
        event_type = self.request.query_params.get("event_type", "").strip().upper()
        person_id = self.request.query_params.get("person_id", "").strip()
        guard_staff_id = self.request.query_params.get("guard_staff_id", "").strip()
        search = self.request.query_params.get("search", "").strip()

        if event_type:
            queryset = queryset.filter(event_type=event_type)
        if person_id:
            queryset = queryset.filter(person_id=person_id)
        if guard_staff_id:
            queryset = queryset.filter(guard_staff_id=guard_staff_id)
        if search:
            queryset = queryset.filter(
                Q(person__first_name__icontains=search)
                | Q(person__last_name__icontains=search)
                | Q(person__document_number__icontains=search)
                | Q(notes__icontains=search)
            )
        return queryset.order_by("-occurred_at")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        access_event = serializer.save()
        response = self.get_serializer(access_event, context={"request": request})
        return Response(response.data, status=status.HTTP_201_CREATED)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True, context={"request": request})
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True, context={"request": request})
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @action(detail=False, methods=["get"], url_path="people")
    def people(self, request):
        search = request.query_params.get("search", "").strip()
        if len(search) < 2:
            return Response({"results": []})
        people = Person.objects.filter(
            Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(document_number__icontains=search)
        ).order_by("last_name", "first_name")[:20]
        results = []
        for person in people:
            links = ResidentUnit.objects.filter(
                resident__person=person,
                end_date__isnull=True,
                unit__status=Unit.Status.ACTIVE,
            ).select_related("unit")
            results.append(
                {
                    "id": person.id,
                    "full_name": person.full_name,
                    "document_number": person.document_number,
                    "units": [{"id": link.unit_id, "code": link.unit.code} for link in links],
                }
            )
        return Response({"results": results})

    @action(detail=False, methods=["get"], url_path="units")
    def units(self, request):
        search = request.query_params.get("search", "").strip()
        if not search:
            return Response({"results": []})
        units = Unit.objects.filter(status=Unit.Status.ACTIVE).select_related("sector")
        units = units.filter(
            Q(code__icontains=search)
            | Q(sector__name__icontains=search)
            | Q(sector__code__icontains=search)
        ).order_by("code")[:20]
        return Response(
            {
                "results": [
                    {
                        "id": unit.id,
                        "code": unit.code,
                        "unit_type": unit.get_unit_type_display(),
                        "sector": unit.sector.name if unit.sector else "",
                    }
                    for unit in units
                ]
            }
        )
