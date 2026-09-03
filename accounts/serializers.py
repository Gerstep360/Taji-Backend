from django.contrib.auth import password_validation
from django.db import IntegrityError, transaction
from rest_framework import serializers

from .exceptions import RegistrationUnavailable
from .models import Person, Role, User


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
        fields = ("id", "email", "is_superuser", "first_name", "last_name", "full_name", "phone", "role", "date_joined")
        read_only_fields = fields


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

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "phone", "password", "password_confirm")

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
        password_validation.validate_password(attrs["password"], candidate)
        return attrs

    def create(self, validated_data):
        data = dict(validated_data)
        data.pop("password_confirm")
        password = data.pop("password")
        first_name = data.pop("first_name")
        last_name = data.pop("last_name")
        phone = data.pop("phone", "")
        resident_role = Role.objects.filter(
            slug="residente", is_active=True, is_public=True
        ).first()
        if resident_role is None:
            raise RegistrationUnavailable()

        try:
            with transaction.atomic():
                person = Person.objects.create(
                    first_name=first_name,
                    last_name=last_name,
                    phone=phone,
                    contact_email=data["email"],
                )
                return User.objects.create_user(
                    password=password,
                    role=resident_role,
                    person=person,
                    **data,
                )
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