from django.utils import timezone
from rest_framework import serializers

from accounts.models import Person
from condominiums.models import Staff
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

    def get_full_name(self, obj):
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

    def get_full_name(self, obj):
        return obj.person.full_name if obj and obj.person else ""


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
    person = PersonAccessSerializer(read_only=True)
    guard_staff = GuardStaffSerializer(read_only=True)
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
            "event_type",
            "event_type_display",
            "validation_method",
            "validation_method_display",
            "validation_result",
            "validation_result_display",
            "occurred_at",
            "notes",
        )

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        if not attrs.get("person"):
            raise serializers.ValidationError({"person_id": ["Debes indicar la persona vinculada al acceso."]})

        if not attrs.get("guard_staff"):
            guard = None
            if user and getattr(user, "person", None):
                guard = getattr(user.person, "staff", None)
            if guard:
                attrs["guard_staff"] = guard
            else:
                raise serializers.ValidationError({"guard_staff_id": ["No se pudo asociar el guardia actual al evento."]})

        event_type = attrs.get("event_type")
        validation_result = attrs.get("validation_result")
        if event_type == AccessEvent.Type.DENIED and validation_result in (None, ""):
            attrs["validation_result"] = AccessEvent.Result.REJECTED
        elif event_type in (AccessEvent.Type.ENTRY, AccessEvent.Type.EXIT) and validation_result in (None, ""):
            attrs["validation_result"] = AccessEvent.Result.APPROVED

        if attrs.get("occurred_at") is None:
            attrs["occurred_at"] = timezone.now()
        return attrs
