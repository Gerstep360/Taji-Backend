from django.db import transaction
from rest_framework import serializers

from accounts.models import Person

from .models import Condominium, Resident, ResidentUnit, Sector, Staff, Unit


class ResidentDirectorySerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="person.full_name", read_only=True)
    document_number = serializers.CharField(source="person.document_number", read_only=True)

    class Meta:
        model = Resident
        fields = ("id", "full_name", "document_number", "status", "registered_at")
        read_only_fields = fields


class ResidentUnitSerializer(serializers.ModelSerializer):
    resident_name = serializers.CharField(source="resident.person.full_name", read_only=True)
    unit_code = serializers.CharField(source="unit.code", read_only=True)
    relation_type_display = serializers.CharField(source="get_relation_type_display", read_only=True)

    class Meta:
        model = ResidentUnit
        fields = (
            "id", "resident", "resident_name", "unit", "unit_code", "relation_type",
            "relation_type_display", "is_primary", "start_date", "end_date", "created_at",
        )
        read_only_fields = ("resident_name", "unit_code", "relation_type_display", "created_at")

    def validate(self, attrs):
        instance = self.instance
        resident = attrs.get("resident", instance.resident if instance else None)
        unit = attrs.get("unit", instance.unit if instance else None)
        start_date = attrs.get("start_date", instance.start_date if instance else None)
        end_date = attrs.get("end_date", instance.end_date if instance else None)
        is_primary = attrs.get("is_primary", instance.is_primary if instance else False)
        if end_date and start_date and end_date < start_date:
            raise serializers.ValidationError({"end_date": "La fecha final no puede ser anterior a la fecha inicial."})
        active = ResidentUnit.objects.filter(resident=resident, unit=unit, end_date__isnull=True)
        if instance:
            active = active.exclude(pk=instance.pk)
        if end_date is None and active.exists():
            raise serializers.ValidationError("El residente ya tiene una asociación activa con esta unidad.")
        primary = ResidentUnit.objects.filter(resident=resident, is_primary=True, end_date__isnull=True)
        if instance:
            primary = primary.exclude(pk=instance.pk)
        if is_primary and end_date is None and primary.exists():
            raise serializers.ValidationError({"is_primary": "El residente ya tiene otra unidad principal activa."})
        return attrs


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
    
class SectorSerializer(serializers.ModelSerializer):
    """CU04: sectores/bloques/torres/pisos/zonas, con jerarquía padre-hijo."""

    parent_name = serializers.SerializerMethodField()

    def get_parent_name(self, obj) -> str | None:
        return obj.parent.name if obj.parent else None
    sector_type_display = serializers.CharField(source="get_sector_type_display", read_only=True)

    class Meta:
        model = Sector
        fields = (
            "id", "code", "name", "sector_type", "sector_type_display",
            "description", "parent", "parent_name", "is_active",
        )
        extra_kwargs = {
            "parent": {"required": False, "allow_null": True},
            "description": {"required": False, "allow_blank": True},
        }

    def validate_parent(self, value):
        if value and self.instance and value.pk == self.instance.pk:
            raise serializers.ValidationError("Un sector no puede ser su propio padre.")
        return value

    def create(self, validated_data):
        validated_data["condominium"] = Condominium.objects.first()
        return super().create(validated_data)


class UnitSerializer(serializers.ModelSerializer):
    """CU04: unidades habitacionales, vinculadas a un sector."""

    sector_name = serializers.SerializerMethodField()

    def get_sector_name(self, obj) -> str | None:
        return obj.sector.name if obj.sector else None
    unit_type_display = serializers.CharField(source="get_unit_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Unit
        fields = (
            "id", "code", "unit_type", "unit_type_display", "floor_label",
            "description", "status", "status_display", "sector", "sector_name",
        )
        extra_kwargs = {
            "sector": {"required": False, "allow_null": True},
            "floor_label": {"required": False, "allow_blank": True},
            "description": {"required": False, "allow_blank": True},
        }
