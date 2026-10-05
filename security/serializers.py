from django.utils import timezone
from rest_framework import serializers

from accounts.models import Person
from condominiums.models import Staff, Unit
from security.models import AccessEvent, VisitAuthorization


class PersonAccessSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = Person
        fields = (
            "id",
            "first_name",
            "last_name",
            "full_name",
            "document_type",
            "document_number",
            "contact_email",
            "phone",
        )

    def get_full_name(self, obj) -> str:
        return obj.full_name if obj else ""


class GuardStaffSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = Staff
        fields = (
            "id",
            "employee_code",
            "staff_type",
            "status",
            "full_name",
        )

    def get_full_name(self, obj) -> str:
        return obj.person.full_name if obj and obj.person else ""


class AccessUnitSerializer(serializers.ModelSerializer):
    sector_name = serializers.CharField(source="sector.name", read_only=True, allow_null=True)

    class Meta:
        model = Unit
        fields = ("id", "code", "unit_type", "sector_name")


class AccessEventSerializer(serializers.ModelSerializer):
    person_id = serializers.PrimaryKeyRelatedField(
        source="person",
        queryset=Person.objects.all(),
        required=False,
        allow_null=True,
    )
    guard_staff_id = serializers.PrimaryKeyRelatedField(
        source="guard_staff",
        queryset=Staff.objects.all(),
        required=False,
        allow_null=True,
    )
    authorization_id = serializers.PrimaryKeyRelatedField(
        source="authorization",
        queryset=VisitAuthorization.objects.all(),
        required=False,
        allow_null=True,
    )
    unit_id = serializers.PrimaryKeyRelatedField(
        source="unit",
        queryset=Unit.objects.filter(status=Unit.Status.ACTIVE),
        required=False,
    )
    person = PersonAccessSerializer(read_only=True)
    guard_staff = GuardStaffSerializer(read_only=True)
    unit = AccessUnitSerializer(read_only=True)
    event_type_display = serializers.CharField(source="get_event_type_display", read_only=True)
    validation_method_display = serializers.CharField(
        source="get_validation_method_display", read_only=True
    )
    validation_result_display = serializers.CharField(
        source="get_validation_result_display", read_only=True
    )
    occurred_at = serializers.DateTimeField(required=False)

    class Meta:
        model = AccessEvent
        fields = (
            "id",
            "person_id",
            "person",
            "guard_staff_id",
            "guard_staff",
            "authorization_id",
            "unit_id",
            "unit",
            "event_type",
            "event_type_display",
            "validation_method",
            "validation_method_display",
            "validation_result",
            "validation_result_display",
            "occurred_at",
            "notes",
            "visitor_name",
            "visitor_document_number",
        )

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        person = attrs.get("person")
        visitor_name = self.initial_data.get("visitor_name", "").strip()
        visitor_document_number = self.initial_data.get("visitor_document_number", "").strip()
        if bool(person) == bool(visitor_name or visitor_document_number):
            raise serializers.ValidationError(
                {"person_id": ["Selecciona una persona registrada o ingresa los datos del visitante nuevo."]}
            )
        if not person and (not visitor_name or not visitor_document_number):
            raise serializers.ValidationError(
                {
                    "visitor_name": ["Indica el nombre y el número de carnet del visitante nuevo."],
                    "visitor_document_number": ["Indica el nombre y el número de carnet del visitante nuevo."],
                }
            )
        if not person and Person.objects.filter(
            document_type=Person.DocumentType.CI,
            document_number=visitor_document_number,
            document_complement="",
        ).exists():
            raise serializers.ValidationError(
                {
                    "visitor_document_number": [
                        "Este carnet ya está registrado. Busca y selecciona a la persona existente."
                    ]
                }
            )
        if not attrs.get("unit"):
            raise serializers.ValidationError({"unit_id": ["Selecciona la casa o unidad de destino."]})
        attrs["visitor_name"] = visitor_name
        attrs["visitor_document_number"] = visitor_document_number

        guard = None
        if user and getattr(user, "person", None):
            try:
                guard = user.person.staff
            except Staff.DoesNotExist:
                pass
        is_security_user = bool(user and user.role and user.role.slug == "seguridad")
        if is_security_user and not guard:
            raise serializers.ValidationError(
                {"guard_staff_id": ["La cuenta de Seguridad debe estar vinculada a una ficha de Personal activa."]}
            )
        if is_security_user:
            attrs["guard_staff"] = guard
        elif guard:
            attrs["guard_staff"] = guard
        elif not attrs.get("guard_staff"):
            raise serializers.ValidationError(
                {"guard_staff_id": ["No se pudo asociar el guardia actual al evento."]}
            )

        event_type = attrs.get("event_type")
        if event_type == AccessEvent.Type.DENIED:
            attrs["validation_result"] = AccessEvent.Result.REJECTED
        elif attrs.get("validation_result") in (None, ""):
            attrs["validation_result"] = AccessEvent.Result.APPROVED

        if attrs.get("occurred_at") is None:
            attrs["occurred_at"] = timezone.now()
        return attrs
