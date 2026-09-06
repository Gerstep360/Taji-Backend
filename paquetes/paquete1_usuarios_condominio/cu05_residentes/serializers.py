from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from accounts.models import Person
from condominiums.models import Resident


class ResidentSerializer(serializers.ModelSerializer):
    """Contrato plano de CU05; persiste Person y Resident en una sola transacción."""

    person_id = serializers.IntegerField(source="person.id", read_only=True)
    first_name = serializers.CharField(source="person.first_name", max_length=100)
    last_name = serializers.CharField(source="person.last_name", max_length=120)
    full_name = serializers.CharField(source="person.full_name", read_only=True)
    document_type = serializers.ChoiceField(
        source="person.document_type",
        choices=Person.DocumentType.choices,
        default=Person.DocumentType.CI,
    )
    document_number = serializers.CharField(
        source="person.document_number",
        max_length=30,
        allow_blank=True,
        allow_null=True,
        required=False,
    )
    document_complement = serializers.CharField(
        source="person.document_complement",
        max_length=10,
        allow_blank=True,
        required=False,
    )
    phone = serializers.CharField(
        source="person.phone", max_length=25, allow_blank=True, required=False
    )
    contact_email = serializers.EmailField(
        source="person.contact_email", allow_blank=True, required=False
    )
    birth_date = serializers.DateField(
        source="person.birth_date", allow_null=True, required=False
    )
    profile_photo = serializers.CharField(
        source="person.profile_photo", max_length=500, allow_blank=True, required=False
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    registered_at = serializers.DateTimeField(read_only=True)
    deactivated_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Resident
        fields = (
            "id",
            "person_id",
            "first_name",
            "last_name",
            "full_name",
            "document_type",
            "document_number",
            "document_complement",
            "phone",
            "contact_email",
            "birth_date",
            "profile_photo",
            "status",
            "status_display",
            "notes",
            "registered_at",
            "deactivated_at",
        )
        extra_kwargs = {
            "notes": {"allow_blank": True, "required": False},
        }

    def validate(self, attrs):
        person_data = attrs.get("person", {})
        self._normalize_person(person_data)
        errors = {}

        document_number = person_data.get("document_number")
        if document_number:
            document_type = person_data.get(
                "document_type",
                self.instance.person.document_type if self.instance else Person.DocumentType.CI,
            )
            complement = person_data.get(
                "document_complement",
                self.instance.person.document_complement if self.instance else "",
            )
            duplicate_person = Person.objects.filter(
                document_type=document_type,
                document_number=document_number,
                document_complement=complement,
            )
            if self.instance:
                duplicate_person = duplicate_person.exclude(pk=self.instance.person_id)
            if duplicate_person.exists():
                errors["document_number"] = ["Ya existe una persona con este documento."]

        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        person_data = validated_data.pop("person")
        person = Person.objects.create(**person_data)
        status_value = validated_data.get("status", Resident.Status.ACTIVE)
        if status_value != Resident.Status.ACTIVE:
            validated_data["deactivated_at"] = timezone.now()
        return Resident.objects.create(person=person, **validated_data)

    @transaction.atomic
    def update(self, instance, validated_data):
        person_data = validated_data.pop("person", {})
        for field, value in person_data.items():
            setattr(instance.person, field, value)
        if person_data:
            instance.person.save(update_fields=(*person_data.keys(), "updated_at"))

        if "status" in validated_data:
            new_status = validated_data["status"]
            if new_status == Resident.Status.ACTIVE:
                validated_data["deactivated_at"] = None
            elif instance.status == Resident.Status.ACTIVE:
                validated_data["deactivated_at"] = timezone.now()

        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        return instance

    @staticmethod
    def _normalize_person(person_data):
        for field in (
            "first_name",
            "last_name",
            "document_number",
            "document_complement",
            "phone",
            "contact_email",
            "profile_photo",
        ):
            value = person_data.get(field)
            if isinstance(value, str):
                person_data[field] = value.strip()
        if person_data.get("document_number") == "":
            person_data["document_number"] = None
        if isinstance(person_data.get("contact_email"), str):
            person_data["contact_email"] = person_data["contact_email"].lower()
