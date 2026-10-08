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


class PlatformTenantSerializer(serializers.ModelSerializer):
    """
    Vista de solo lectura de un tenant para la consola global de la plataforma.

    A diferencia de `TenantSerializer`, aqui **todo** es de solo lectura: esta
    vista existe para que un administrador global pueda ver cuantos condominios
    hay, como estan y cuanta gente usan, no para gestionarlos. El alta y la
    edicion siguen pasando por `TenantViewSet` y el servicio de aprovisionamiento.

    Los contadores llegan como anotaciones de la vista, de modo que mostrar los
    N tenants no dispara N+1 consultas.
    """

    plan_name = serializers.SerializerMethodField()
    subscription_status = serializers.SerializerMethodField()
    subscription_status_display = serializers.SerializerMethodField()
    is_subscription_valid = serializers.SerializerMethodField()
    days_left = serializers.SerializerMethodField()

    # Contadores agregados en la vista. No son columnas de `Condominium`, asi
    # que se declaran a mano: un `ModelSerializer` no puede deducirlas.
    users_count = serializers.IntegerField(read_only=True, default=0)
    sectors_count = serializers.IntegerField(read_only=True, default=0)
    units_count = serializers.IntegerField(read_only=True, default=0)
    residents_count = serializers.IntegerField(read_only=True, default=0)
    staff_count = serializers.IntegerField(read_only=True, default=0)

    # Viene de la suscripcion asociada, no del condominio.
    current_period_end = serializers.SerializerMethodField()

    class Meta:
        model = Condominium
        fields = (
            "id",
            "name",
            "slug",
            "status",
            "is_active",
            "address",
            "phone",
            "email",
            "timezone",
            "created_at",
            # Poblados por anotaciones en la vista.
            "users_count",
            "sectors_count",
            "units_count",
            "residents_count",
            "staff_count",
            # Suscripcion (puede no existir).
            "plan_name",
            "subscription_status",
            "subscription_status_display",
            "is_subscription_valid",
            "days_left",
            "current_period_end",
        )
        read_only_fields = fields

    def _subscription(self, obj):
        # `select_related` deja la suscripcion en `None` si no existe, en lugar
        # de lanzar una excepcion por la relacion OneToOne ausente.
        return getattr(obj, "subscription", None)

    def get_plan_name(self, obj) -> str:
        subscription = self._subscription(obj)
        if not subscription or not subscription.plan:
            return ""
        return subscription.plan.name

    def get_subscription_status(self, obj) -> str:
        subscription = self._subscription(obj)
        return subscription.status if subscription else "NO_SUBSCRIPTION"

    def get_subscription_status_display(self, obj) -> str:
        subscription = self._subscription(obj)
        if not subscription:
            return "Sin suscripción"
        return subscription.get_status_display()

    def get_is_subscription_valid(self, obj) -> bool:
        subscription = self._subscription(obj)
        return bool(subscription and subscription.is_valid)

    def get_current_period_end(self, obj):
        subscription = self._subscription(obj)
        return subscription.current_period_end if subscription else None

    def get_days_left(self, obj):
        """
        Dias restantes del periodo o de la prueba.

        Devuelve `None` cuando no hay suscripcion, para que la interfaz pueda
        distinguir "sin plan" de "plan vencido hace 0 dias".
        """
        from django.utils import timezone

        subscription = self._subscription(obj)
        if not subscription:
            return None

        deadline = self._deadline(subscription)
        if not deadline:
            return None

        return max((deadline - timezone.now()).days, 0)

    @staticmethod
    def _deadline(subscription):
        """Fecha que manda: la prueba si esta en TRIAL, si no el periodo en curso."""
        if subscription.status == subscription.Status.TRIAL and subscription.trial_ends_at:
            return subscription.trial_ends_at
        return subscription.current_period_end


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
