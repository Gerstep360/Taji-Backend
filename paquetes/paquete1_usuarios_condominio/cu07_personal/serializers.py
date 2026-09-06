from django.db import transaction
from rest_framework import serializers
from accounts.models import Person
from condominiums.models import Staff


class StaffSerializer(serializers.ModelSerializer):
    """Contrato plano de CU07; persiste Person y Staff en una sola transacción."""

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
    employee_code = serializers.CharField(read_only=True)
    staff_type_display = serializers.CharField(source="get_staff_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Staff
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
            "employee_code",
            "staff_type",
            "staff_type_display",
            "hire_date",
            "end_date",
            "status",
            "status_display",
            "notes",
        )
        extra_kwargs = {
            "hire_date": {"allow_null": True, "required": False},
            "end_date": {"allow_null": True, "required": False},
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

        hire_date = attrs.get("hire_date", self.instance.hire_date if self.instance else None)
        end_date = attrs.get("end_date", self.instance.end_date if self.instance else None)
        staff_status = attrs.get(
            "status", self.instance.status if self.instance else Staff.Status.ACTIVE
        )
        if staff_status != Staff.Status.INACTIVE and end_date:
            errors["end_date"] = [
                "El fin de trabajo solo se registra cuando el estado es Inactivo."
            ]
        if hire_date and end_date and end_date < hire_date:
            errors["end_date"] = ["El fin de trabajo no puede ser anterior al inicio."]
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        person_data = validated_data.pop("person")
        person = Person.objects.create(**person_data)
        staff = Staff.objects.create(person=person, **validated_data)
        staff.employee_code = self._generated_employee_code(staff.pk)
        staff.save(update_fields=("employee_code",))
        return staff

    @transaction.atomic
    def update(self, instance, validated_data):
        person_data = validated_data.pop("person", {})
        for field, value in person_data.items():
            setattr(instance.person, field, value)
        if person_data:
            instance.person.save(update_fields=(*person_data.keys(), "updated_at"))

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

    @staticmethod
    def _generated_employee_code(staff_id):
        """Genera un identificador estable sin depender del área ni de datos personales."""
        base = f"PER-{staff_id:05d}"
        candidate = base
        suffix = 1
        while Staff.objects.filter(employee_code=candidate).exclude(pk=staff_id).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate
