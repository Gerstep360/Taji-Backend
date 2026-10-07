"""Serializadores para la API de SaaS Multi-Tenant."""

from rest_framework import serializers
from condominiums.models import Condominium
from tenancy.models import TenantMembership


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Condominium
        fields = (
            "id",
            "name",
            "slug",
            "legal_name",
            "address",
            "phone",
            "email",
            "timezone",
            "is_active",
            "status",
            "max_units",
            "max_residents",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class TenantMembershipSerializer(serializers.ModelSerializer):
    condominium = TenantSerializer(read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)
    role_slug = serializers.CharField(source="role.slug", read_only=True)

    class Meta:
        model = TenantMembership
        fields = (
            "id",
            "condominium",
            "role_name",
            "role_slug",
            "is_default",
            "is_active",
            "created_at",
        )
        read_only_fields = ("id", "created_at")


class TenantProvisionRequestSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    slug = serializers.SlugField(max_length=80, required=False, allow_blank=True)
    legal_name = serializers.CharField(max_length=180, required=False, allow_blank=True)
    address = serializers.CharField(max_length=250, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=25, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    admin_email = serializers.EmailField(required=False, allow_null=True)
    max_units = serializers.IntegerField(default=500, min_value=1)
    max_residents = serializers.IntegerField(default=1500, min_value=1)


class TenantSwitchRequestSerializer(serializers.Serializer):
    tenant_id = serializers.CharField(
        help_text="ID numérico o slug del condominio/tenant al que se desea cambiar."
    )


class TenantContextResponseSerializer(serializers.Serializer):
    active_tenant = TenantSerializer(allow_null=True)
    membership = TenantMembershipSerializer(allow_null=True)
    is_global = serializers.BooleanField()


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        from tenancy.models import SubscriptionPlan
        model = SubscriptionPlan
        fields = (
            "id",
            "code",
            "name",
            "tagline",
            "description",
            "price_bob",
            "price_usd",
            "billing_period",
            "max_units",
            "max_residents",
            "features",
            "is_popular",
            "is_active",
            "order",
        )


class TenantSubscriptionDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    plan = SubscriptionPlanSerializer(read_only=True)
    status = serializers.CharField(read_only=True)
    status_label = serializers.CharField(read_only=True)
    is_valid = serializers.BooleanField(read_only=True)
    current_period_start = serializers.DateTimeField(read_only=True)
    current_period_end = serializers.DateTimeField(read_only=True)
    trial_ends_at = serializers.DateTimeField(read_only=True)
    days_left = serializers.IntegerField(read_only=True)
    max_units = serializers.IntegerField(read_only=True)
    used_units = serializers.IntegerField(read_only=True)
    max_residents = serializers.IntegerField(read_only=True)
    used_residents = serializers.IntegerField(read_only=True)


class SaaSPaymentSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name", read_only=True)

    class Meta:
        from tenancy.models import SaaSPayment
        model = SaaSPayment
        fields = (
            "id",
            "condominium_id",
            "plan_id",
            "plan_name",
            "amount",
            "currency",
            "provider",
            "status",
            "payment_intent_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class CreatePaymentIntentRequestSerializer(serializers.Serializer):
    plan_id = serializers.IntegerField(min_value=1)
    condominium_id = serializers.IntegerField(required=False, allow_null=True)


class ConfirmSandboxPaymentRequestSerializer(serializers.Serializer):
    payment_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    plan_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    condominium_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class UpdateCondominiumProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Condominium
        fields = (
            "name",
            "legal_name",
            "address",
            "phone",
            "email",
            "timezone",
            "rules_summary",
        )


class SaaSCondominiumRegisterSerializer(serializers.Serializer):
    """
    Registro y aprovisionamiento profesional para Administradores de nuevos Condominios.
    Crea el Condominio, la cuenta de Administrador (aprobada y activa) y su Suscripción SaaS.
    """
    condominium_name = serializers.CharField(max_length=150)
    condominium_code = serializers.CharField(max_length=80, required=False, allow_blank=True)
    address = serializers.CharField(max_length=250, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    estimated_units = serializers.IntegerField(required=False, default=20)
    admin_name = serializers.CharField(max_length=120)
    admin_document = serializers.CharField(max_length=40, required=False, allow_blank=True)
    admin_email = serializers.EmailField()
    admin_phone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    admin_password = serializers.CharField(min_length=8, write_only=True)
    plan_code = serializers.CharField(max_length=50, default="profesional")
    payment_method = serializers.ChoiceField(choices=["TRIAL", "STRIPE"], default="TRIAL")
    payment_id = serializers.IntegerField(required=False, allow_null=True)
