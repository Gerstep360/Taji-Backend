from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers
from accounts.models import Person, Role, User
from condominiums.models import Staff


STAFF_ROLE_BY_TYPE = {
    Staff.Type.SECURITY: "seguridad",
    Staff.Type.CLEANING: "limpieza",
    Staff.Type.MAINTENANCE: "mantenimiento",
    Staff.Type.ADMINISTRATION: "directiva",
    Staff.Type.OTHER: "proveedor-externo",
}


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
    has_user_account = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    create_user_account = serializers.BooleanField(write_only=True, required=False, default=False)
    account_password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        min_length=10,
        max_length=128,
        trim_whitespace=False,
    )

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
            "has_user_account",
            "user_email",
            "create_user_account",
            "account_password",
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

        if attrs.get("create_user_account"):
            email = person_data.get(
                "contact_email",
                self.instance.person.contact_email if self.instance else "",
            )
            if not email:
                errors["contact_email"] = ["Debes indicar un correo para crear la cuenta de acceso."]
            else:
                existing_user = User.objects.filter(email__iexact=email)
                if self.instance:
                    existing_user = existing_user.exclude(person_id=self.instance.person_id)
                if existing_user.exists():
                    errors["contact_email"] = ["Ya existe una cuenta de usuario con este correo."]

            if self.instance and self._person_has_user(self.instance.person):
                errors["create_user_account"] = ["Esta persona ya tiene una cuenta de acceso."]

            password = attrs.get("account_password") or ""
            if not password:
                errors["account_password"] = ["Debes definir una contraseña inicial."]
            else:
                try:
                    validate_password(password)
                except DjangoValidationError as exc:
                    errors["account_password"] = list(exc.messages)

            staff_type = attrs.get(
                "staff_type", self.instance.staff_type if self.instance else None
            )
            role_slug = STAFF_ROLE_BY_TYPE.get(staff_type)
            if not role_slug or not Role.objects.filter(slug=role_slug, is_active=True).exists():
                errors["staff_type"] = ["No existe un rol activo para el área seleccionada."]

        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        create_user_account = validated_data.pop("create_user_account", False)
        account_password = validated_data.pop("account_password", "")
        person_data = validated_data.pop("person")
        person = Person.objects.create(**person_data)
        staff = Staff.objects.create(person=person, **validated_data)
        staff.employee_code = self._generated_employee_code(staff.pk)
        staff.save(update_fields=("employee_code",))
        if create_user_account:
            self._create_user_account(staff, account_password)
        return staff

    @transaction.atomic
    def update(self, instance, validated_data):
        create_user_account = validated_data.pop("create_user_account", False)
        account_password = validated_data.pop("account_password", "")
        person_data = validated_data.pop("person", {})
        for field, value in person_data.items():
            setattr(instance.person, field, value)
        if person_data:
            instance.person.save(update_fields=(*person_data.keys(), "updated_at"))

        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if create_user_account:
            self._create_user_account(instance, account_password)
        return instance

    def get_has_user_account(self, obj) -> bool:
        return self._person_has_user(obj.person)

    def get_user_email(self, obj) -> str:
        if not self._person_has_user(obj.person):
            return ""
        return obj.person.user.email

    @staticmethod
    def _person_has_user(person) -> bool:
        return User.objects.filter(person=person).exists()

    @staticmethod
    def _create_user_account(staff, password) -> User:
        role_slug = STAFF_ROLE_BY_TYPE[staff.staff_type]
        role = Role.objects.get(slug=role_slug, is_active=True)
        return User.objects.create_user(
            email=staff.person.contact_email,
            password=password,
            role=role,
            person=staff.person,
            is_approved=True,
        )

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
