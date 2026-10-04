from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from accounts.models import Person, Role, User
from condominiums.models import Staff


class StaffSerializer(serializers.ModelSerializer):
    """Contrato plano de CU07; persiste Person, Staff y opcionalmente User en una sola transacción."""

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

    # Campos de Acceso al Sistema
    create_system_access = serializers.BooleanField(required=False, default=False, write_only=True)
    access_email = serializers.CharField(required=False, allow_blank=True)
    access_role = serializers.CharField(required=False, allow_blank=True, write_only=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    password_confirm = serializers.CharField(write_only=True, required=False, allow_blank=True)
    toggle_access = serializers.BooleanField(required=False, allow_null=True, write_only=True)

    has_system_access = serializers.SerializerMethodField()
    user_id = serializers.SerializerMethodField()
    user_is_active = serializers.SerializerMethodField()
    role_slug = serializers.SerializerMethodField()
    role_name = serializers.SerializerMethodField()

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
            "create_system_access",
            "access_email",
            "access_role",
            "password",
            "password_confirm",
            "toggle_access",
            "has_system_access",
            "user_id",
            "user_is_active",
            "role_slug",
            "role_name",
        )
        extra_kwargs = {
            "hire_date": {"allow_null": True, "required": False},
            "end_date": {"allow_null": True, "required": False},
            "notes": {"allow_blank": True, "required": False},
        }

    def get_has_system_access(self, obj):
        return hasattr(obj.person, "user") and obj.person.user is not None

    def get_user_id(self, obj):
        if hasattr(obj.person, "user") and obj.person.user is not None:
            return obj.person.user.id
        return None

    def get_user_is_active(self, obj):
        if hasattr(obj.person, "user") and obj.person.user is not None:
            return obj.person.user.is_active
        return None

    def get_role_slug(self, obj):
        if hasattr(obj.person, "user") and obj.person.user and obj.person.user.role:
            return obj.person.user.role.slug
        return None

    def get_role_name(self, obj):
        if hasattr(obj.person, "user") and obj.person.user and obj.person.user.role:
            return obj.person.user.role.name
        return None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if hasattr(instance.person, "user") and instance.person.user:
            data["access_email"] = instance.person.user.email
        else:
            data["access_email"] = instance.person.contact_email or ""
        return data

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

        # Validaciones de Acceso al Sistema
        create_system_access = attrs.get("create_system_access", False)
        access_email = (attrs.get("access_email") or "").strip().lower()
        contact_email = (person_data.get("contact_email") or "").strip().lower()
        password = attrs.get("password")
        password_confirm = attrs.get("password_confirm")

        has_user = (
            self.instance
            and hasattr(self.instance.person, "user")
            and self.instance.person.user is not None
        )

        if create_system_access or password or (self.instance and not has_user and create_system_access):
            email_to_use = access_email or contact_email
            if not email_to_use:
                errors["access_email"] = ["El correo es obligatorio para habilitar acceso al sistema."]

            if not has_user:
                if not password:
                    errors["password"] = ["La contraseña es obligatoria para crear acceso."]
                elif password != password_confirm:
                    errors["password_confirm"] = ["Las contraseñas no coinciden."]
                else:
                    try:
                        candidate_user = User(email=email_to_use)
                        password_validation.validate_password(password, candidate_user)
                    except DjangoValidationError as err:
                        errors["password"] = list(err.messages)

            if email_to_use:
                existing_user = User.objects.filter(email__iexact=email_to_use).first()
                if existing_user:
                    is_same_person = (
                        self.instance and existing_user.person_id == self.instance.person_id
                    )
                    if not is_same_person:
                        errors["access_email"] = [
                            "Este correo ya está registrado por otro usuario en el sistema."
                        ]

        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        create_system_access = validated_data.pop("create_system_access", False)
        access_email = validated_data.pop("access_email", None)
        access_role = validated_data.pop("access_role", None)
        password = validated_data.pop("password", None)
        password_confirm = validated_data.pop("password_confirm", None)
        toggle_access = validated_data.pop("toggle_access", None)

        person_data = validated_data.pop("person")
        if access_email and not person_data.get("contact_email"):
            person_data["contact_email"] = access_email.strip().lower()

        person = Person.objects.create(**person_data)
        staff = Staff.objects.create(person=person, **validated_data)
        staff.employee_code = self._generated_employee_code(staff.pk)
        staff.save(update_fields=("employee_code",))

        if create_system_access:
            email_to_use = (access_email or person.contact_email or "").strip().lower()
            role = self._resolve_role(staff.staff_type, access_role)
            user = User.objects.filter(email__iexact=email_to_use).first()
            if user:
                if user.person_id is None or user.person_id == person.id:
                    user.person = person
                    user.role = role
                    user.is_approved = True
                    user.is_active = True
                    if password:
                        user.set_password(password)
                    user.save()
            else:
                User.objects.create_user(
                    email=email_to_use,
                    password=password,
                    person=person,
                    role=role,
                    is_approved=True,
                    is_active=True,
                )

        return staff

    @transaction.atomic
    def update(self, instance, validated_data):
        create_system_access = validated_data.pop("create_system_access", False)
        access_email = validated_data.pop("access_email", None)
        access_role = validated_data.pop("access_role", None)
        password = validated_data.pop("password", None)
        password_confirm = validated_data.pop("password_confirm", None)
        toggle_access = validated_data.pop("toggle_access", None)

        person_data = validated_data.pop("person", {})
        if access_email:
            person_data["contact_email"] = access_email.strip().lower()

        for field, value in person_data.items():
            setattr(instance.person, field, value)
        if person_data:
            instance.person.save(update_fields=(*person_data.keys(), "updated_at"))

        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()

        user = getattr(instance.person, "user", None)
        email_to_use = (access_email or instance.person.contact_email or "").strip().lower()

        if create_system_access and not user:
            role = self._resolve_role(instance.staff_type, access_role)
            existing_user = User.objects.filter(email__iexact=email_to_use).first()
            if existing_user:
                if existing_user.person_id is None or existing_user.person_id == instance.person.id:
                    existing_user.person = instance.person
                    existing_user.role = role
                    existing_user.is_approved = True
                    existing_user.is_active = True
                    if password:
                        existing_user.set_password(password)
                    existing_user.save()
            else:
                User.objects.create_user(
                    email=email_to_use,
                    password=password,
                    person=instance.person,
                    role=role,
                    is_approved=True,
                    is_active=True,
                )
        elif user:
            updated_fields = []
            if access_email and user.email != access_email.strip().lower():
                user.email = access_email.strip().lower()
                updated_fields.append("email")
            if instance.staff_type == Staff.Type.SECURITY and user.role and user.role.slug != "seguridad":
                sec_role = Role.objects.filter(slug="seguridad", is_active=True).first()
                if sec_role:
                    user.role = sec_role
                    updated_fields.append("role")
            if toggle_access is not None and user.is_active != toggle_access:
                user.is_active = toggle_access
                updated_fields.append("is_active")
            if password:
                user.set_password(password)
                updated_fields.append("password")
            if updated_fields:
                user.save()

        return instance

    @staticmethod
    def _resolve_role(staff_type, access_role=None):
        if staff_type == Staff.Type.SECURITY or access_role == "seguridad":
            sec_role = Role.objects.filter(slug="seguridad", is_active=True).first()
            if sec_role:
                return sec_role
        if access_role:
            role = Role.objects.filter(slug=access_role, is_active=True).first()
            if role:
                return role
        # Default fallback
        return Role.objects.filter(slug="seguridad", is_active=True).first()

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

