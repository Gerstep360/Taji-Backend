"""Serializadores para CU02: Gestionar usuarios, roles y permisos."""

from django.db import transaction
from rest_framework import serializers

from accounts.models import Person, Role, SystemPermission, User
from accounts.rbac import (
    ADMIN_ONLY_PERMISSIONS,
    FORBIDDEN_PERMISSIONS_BY_ROLE,
    MANDATORY_PERMISSIONS_BY_ROLE,
)


class SystemPermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemPermission
        fields = ("code", "name", "description", "module", "is_active")


class RoleDetailSerializer(serializers.ModelSerializer):
    permissions = SystemPermissionSerializer(many=True, read_only=True)

    class Meta:
        model = Role
        fields = ("slug", "name", "description", "is_active", "permissions")


class RolePermissionsUpdateSerializer(serializers.Serializer):
    """Valida y aplica la nueva configuración de permisos de un rol.

    Reglas de negocio críticas (RN1-RN4):
    - No se pueden asignar permisos inexistentes.
    - manage_roles solo puede tenerlo el Administrador.
    - El Administrador no puede perder manage_roles.
    - Seguridad no puede recibir register_visits ni permisos de empleado.
    - Directiva solo puede tener permisos de solo lectura.
    - Empleado operativo no puede recibir permisos de portería.
    """

    permissions = serializers.ListField(
        child=serializers.SlugField(max_length=100),
        allow_empty=True,
    )

    def validate_permissions(self, codes: list[str]) -> list[str]:
        existing_codes = set(
            SystemPermission.objects.filter(is_active=True).values_list("code", flat=True)
        )
        unknown = sorted(set(codes) - existing_codes)
        if unknown:
            raise serializers.ValidationError(
                f"Permisos no reconocidos o inactivos: {', '.join(unknown)}."
            )
        return codes

    def validate(self, attrs: dict) -> dict:
        role: Role = self.context["role"]
        requested: frozenset[str] = frozenset(attrs["permissions"])

        admin_only_violation = ADMIN_ONLY_PERMISSIONS & requested
        if admin_only_violation and role.slug != "administrador":
            raise serializers.ValidationError(
                {
                    "permissions": (
                        f"Los siguientes permisos son exclusivos del Administrador y no "
                        f"pueden asignarse al rol '{role.name}': "
                        f"{', '.join(sorted(admin_only_violation))}."
                    )
                }
            )

        if role.slug in MANDATORY_PERMISSIONS_BY_ROLE:
            mandatory = MANDATORY_PERMISSIONS_BY_ROLE[role.slug]
            missing = mandatory - requested
            if missing:
                raise serializers.ValidationError(
                    {
                        "permissions": (
                            f"El rol '{role.name}' debe conservar los siguientes permisos "
                            f"críticos: {', '.join(sorted(missing))}."
                        )
                    }
                )

        if role.slug in FORBIDDEN_PERMISSIONS_BY_ROLE:
            forbidden = FORBIDDEN_PERMISSIONS_BY_ROLE[role.slug]
            violation = forbidden & requested
            if violation:
                raise serializers.ValidationError(
                    {
                        "permissions": (
                            f"El rol '{role.name}' no puede recibir los siguientes permisos "
                            f"según las reglas del sistema: {', '.join(sorted(violation))}."
                        )
                    }
                )

        return attrs

    def save(self) -> Role:
        role: Role = self.context["role"]
        codes = self.validated_data["permissions"]
        permission_qs = SystemPermission.objects.filter(code__in=codes, is_active=True)
        role.permissions.set(permission_qs)
        return role


# ── Usuario interno ──────────────────────────────────────────────────────────

INTERNAL_ROLE_SLUGS = frozenset({
    "administrador",
    "directiva",
    "seguridad",
    "mantenimiento",
    "limpieza",
    "proveedor-externo",
})


class InternalUserCreateSerializer(serializers.Serializer):
    """Crea un usuario interno (no Residente) con rol asignado por el Administrador."""

    email = serializers.EmailField(max_length=254)
    first_name = serializers.CharField(min_length=2, max_length=100, trim_whitespace=True)
    last_name = serializers.CharField(min_length=2, max_length=120, trim_whitespace=True)
    role_slug = serializers.SlugField(max_length=80)
    password = serializers.CharField(
        write_only=True, min_length=10, max_length=128, trim_whitespace=False
    )

    def validate_email(self, value: str) -> str:
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Este correo ya está en uso.")
        return value

    def validate_role_slug(self, slug: str) -> str:
        if slug not in INTERNAL_ROLE_SLUGS:
            raise serializers.ValidationError(
                f"El rol '{slug}' no está permitido para usuarios internos. "
                f"Permitidos: {', '.join(sorted(INTERNAL_ROLE_SLUGS))}."
            )
        role = Role.objects.filter(slug=slug, is_active=True).first()
        if role is None:
            raise serializers.ValidationError(f"Rol '{slug}' no existe o está inactivo.")
        return slug

    @transaction.atomic
    def create(self, validated_data: dict) -> User:
        role = Role.objects.get(slug=validated_data["role_slug"])
        return User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=validated_data["first_name"],
            last_name=validated_data["last_name"],
            role=role,
            is_approved=True,
        )


# ── Residentes pendientes ────────────────────────────────────────────────────

class PendingResidentSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(source="person.first_name", read_only=True)
    last_name = serializers.CharField(source="person.last_name", read_only=True)
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "date_joined",
            "is_approved",
            "is_active",
        )
        read_only_fields = fields


class ResidentReviewSerializer(serializers.Serializer):
    """Aprobar o rechazar una solicitud de Residente pendiente."""

    ACTION_APPROVE = "approve"
    ACTION_REJECT = "reject"

    action = serializers.ChoiceField(choices=[ACTION_APPROVE, ACTION_REJECT])

    def validate(self, attrs: dict) -> dict:
        user: User = self.context["user"]
        if user.role is None or user.role.slug != "residente":
            raise serializers.ValidationError(
                {"action": "Solo se puede revisar usuarios con rol Residente."}
            )
        if attrs["action"] == self.ACTION_APPROVE and user.is_approved:
            raise serializers.ValidationError(
                {"action": "Este Residente ya está aprobado."}
            )
        return attrs

    @transaction.atomic
    def save(self) -> User:
        user: User = self.context["user"]
        action = self.validated_data["action"]
        if action == self.ACTION_APPROVE:
            user.is_approved = True
            user.is_active = True
            user.save(update_fields=["is_approved", "is_active", "updated_at"])
        else:
            user.is_approved = False
            user.is_active = False
            user.save(update_fields=["is_approved", "is_active", "updated_at"])
        return user
