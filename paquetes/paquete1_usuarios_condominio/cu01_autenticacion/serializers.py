from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers

from accounts.exceptions import RegistrationUnavailable
from accounts.models import Person, Role, User


class RoleSerializer(serializers.ModelSerializer):
    permissions = serializers.SlugRelatedField(many=True, read_only=True, slug_field="code")

    class Meta:
        model = Role
        fields = ("slug", "name", "description", "permissions")


class UserSerializer(serializers.ModelSerializer):
    role = RoleSerializer(read_only=True)
    full_name = serializers.CharField(read_only=True)
    first_name = serializers.CharField(source="person.first_name", read_only=True)
    last_name = serializers.CharField(source="person.last_name", read_only=True)
    phone = serializers.CharField(source="person.phone", read_only=True)

    class Meta:
        model = User
        fields = ("id", "email", "is_superuser", "is_approved", "first_name", "last_name", "full_name", "phone", "role", "date_joined")
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.is_superuser and data.get("role") is None:
            admin_role = Role.objects.filter(slug="administrador", is_active=True).first()
            if admin_role:
                data["role"] = RoleSerializer(admin_role).data

        from tenancy.models import TenantMembership
        from tenancy.context import TenantContext
        active_tenant = TenantContext.get_current_tenant()
        if not active_tenant:
            membership = (
                TenantMembership.objects.filter(user=instance, is_active=True, is_default=True).select_related("condominium").first()
                or TenantMembership.objects.filter(user=instance, is_active=True).select_related("condominium").first()
            )
            if membership:
                active_tenant = membership.condominium

        if active_tenant:
            data["active_tenant"] = {
                "id": active_tenant.id,
                "name": active_tenant.name,
                "slug": getattr(active_tenant, "slug", "") or "",
                "address": getattr(active_tenant, "address", "") or "",
            }
        else:
            data["active_tenant"] = None
        return data


class RegisterSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(
        max_length=254,
        validators=[],
        error_messages={
            "blank": "Ingresa tu correo electrónico.",
            "invalid": "Ingresa un correo electrónico válido.",
        },
    )
    first_name = serializers.CharField(
        min_length=2, max_length=100, trim_whitespace=True
    )
    last_name = serializers.CharField(
        min_length=2, max_length=120, trim_whitespace=True
    )
    phone = serializers.RegexField(
        regex=r"^\+?[0-9 ()-]{7,25}$",
        required=False,
        allow_blank=True,
        error_messages={"invalid": "Ingresa un teléfono válido."},
    )
    password = serializers.CharField(
        write_only=True, min_length=10, max_length=128, trim_whitespace=False
    )
    password_confirm = serializers.CharField(
        write_only=True, min_length=10, max_length=128, trim_whitespace=False
    )

    condominium_id = serializers.IntegerField(required=False, allow_null=True)
    condominium_code = serializers.CharField(required=False, allow_blank=True, max_length=100)
    unit_label = serializers.CharField(required=False, allow_blank=True, max_length=100)

    class Meta:
        model = User
        fields = (
            "email",
            "first_name",
            "last_name",
            "phone",
            "password",
            "password_confirm",
            "condominium_id",
            "condominium_code",
            "unit_label",
        )

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "Este correo ya tiene una cuenta. Inicia sesión o recupera tu contraseña."
            )
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "Las contraseñas no coinciden."})
        candidate = User(
            email=attrs.get("email", ""),
        )
        candidate.person = Person(
            first_name=attrs.get("first_name", ""),
            last_name=attrs.get("last_name", ""),
        )
        try:
            password_validation.validate_password(attrs["password"], candidate)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"password": error.messages}) from error
        return attrs

    def create(self, validated_data):
        data = dict(validated_data)
        data.pop("password_confirm")
        password = data.pop("password")
        first_name = data.pop("first_name")
        last_name = data.pop("last_name")
        phone = data.pop("phone", "")
        condo_id = data.pop("condominium_id", None)
        condo_code = data.pop("condominium_code", None)
        unit_label = data.pop("unit_label", "")

        resident_role = Role.objects.filter(
            slug="residente", is_active=True, is_public=True
        ).first()
        if resident_role is None:
            raise RegistrationUnavailable()

        try:
            with transaction.atomic():
                # Si el Administrador ya registró a esta persona en CU05 (Person con el
                # mismo correo de contacto y sin cuenta todavía), se reutiliza esa Person
                # en vez de crear una identidad duplicada.
                person = Person.objects.filter(
                    contact_email__iexact=data["email"], user__isnull=True
                ).first()
                if person is not None:
                    person.first_name = first_name
                    person.last_name = last_name
                    person.phone = phone
                    person.save(update_fields=("first_name", "last_name", "phone", "updated_at"))
                else:
                    person = Person.objects.create(
                        first_name=first_name,
                        last_name=last_name,
                        phone=phone,
                        contact_email=data["email"],
                    )
                user = User.objects.create_user(
                    password=password,
                    role=resident_role,
                    person=person,
                    is_approved=False,
                    **data,
                )

                from condominiums.models import Condominium
                from tenancy.models import TenantMembership

                target_condo = None
                if condo_id:
                    target_condo = Condominium.objects.filter(id=condo_id, is_active=True).first()
                elif condo_code:
                    target_condo = Condominium.objects.filter(slug=condo_code.strip(), is_active=True).first()

                if target_condo:
                    TenantMembership.objects.create(
                        user=user,
                        condominium=target_condo,
                        role=resident_role,
                        is_default=True,
                        is_active=False,
                    )
                return user
        except IntegrityError as error:
            if User.objects.filter(email__iexact=data["email"]).exists():
                raise serializers.ValidationError(
                    {
                        "email": [
                            "Este correo ya tiene una cuenta. Inicia sesión o "
                            "recupera tu contraseña."
                        ]
                    }
                ) from error
            raise



class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    client = serializers.ChoiceField(choices=("web", "mobile"), default="web")


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField(required=False, allow_blank=False)
    client = serializers.ChoiceField(choices=("web", "mobile"), default="web")


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(required=False, allow_blank=False)


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ResetPasswordSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    password_confirm = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "Las contraseñas no coinciden."})
        return attrs