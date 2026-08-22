from django.contrib.auth import password_validation
from django.db import transaction
from rest_framework import serializers

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
        fields = ("id", "email", "first_name", "last_name", "full_name", "phone", "role", "date_joined")
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=120)
    phone = serializers.CharField(max_length=25, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    password_confirm = serializers.CharField(write_only=True, trim_whitespace=False)

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "phone", "password", "password_confirm")

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Ya existe una cuenta con este correo.")
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

    @transaction.atomic
    def create(self, validated_data):
        validated_data.pop("password_confirm")
        password = validated_data.pop("password")
        first_name = validated_data.pop("first_name")
        last_name = validated_data.pop("last_name")
        phone = validated_data.pop("phone", "")

        resident_role = Role.objects.get(slug="residente", is_active=True, is_public=True)
        person = Person.objects.create(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            contact_email=validated_data["email"],
        )
        return User.objects.create_user(
            password=password,
            role=resident_role,
            person=person,
            **validated_data,
        )


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