"""Modelos para la capa de SaaS Multi-Tenant (Sección 4 de multitenant_saas_optimizado.md)."""

from django.conf import settings
from django.db import models
from django.utils import timezone


class TenantMembership(models.Model):
    """
    Representa la pertenencia de un usuario a un condominio/tenant específico,
    con su rol y estado de vigencia dentro de ese tenant.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tenant_memberships",
    )
    condominium = models.ForeignKey(
        "condominiums.Condominium",
        on_delete=models.CASCADE,
        related_name="tenant_memberships",
    )
    role = models.ForeignKey(
        "accounts.Role",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tenant_memberships",
        help_text="Rol asignado al usuario dentro de este condominio/tenant.",
    )
    is_default = models.BooleanField(
        default=False,
        help_text="Tenant predeterminado para el usuario al iniciar sesión.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Indica si la membresía está activa y puede operar en el tenant.",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "tenant_membership"
        ordering = ("-is_default", "condominium__name")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "condominium"),
                name="uq_tenant_membership_user_condo",
            )
        ]

    def __str__(self):
        role_name = self.role.name if self.role else "Sin rol"
        return f"{self.user.email} -> {self.condominium.name} ({role_name})"

    def save(self, *args, **kwargs):
        # Si se establece como default, asegurar unicidad de is_default para este usuario
        if self.is_default and self.is_active:
            TenantMembership.objects.filter(
                user=self.user, is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class SubscriptionPlan(models.Model):
    """
    Planes de suscripción SaaS para condominios (Taji SaaS Platform).
    """

    class Period(models.TextChoices):
        MONTHLY = "MONTHLY", "Mensual"
        ANNUAL = "ANNUAL", "Anual"

    code = models.CharField(max_length=50, unique=True, help_text="Código único del plan (ej. 'basic', 'pro', 'enterprise')")
    name = models.CharField(max_length=100, help_text="Nombre visible del plan")
    tagline = models.CharField(max_length=200, blank=True, help_text="Subtítulo o descripción comercial corta")
    description = models.TextField(blank=True)
    price_bob = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Precio en Bolivianos (BOB)")
    price_usd = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Referencia en USD")
    billing_period = models.CharField(max_length=20, choices=Period.choices, default=Period.MONTHLY)
    max_units = models.PositiveIntegerField(default=50, help_text="Límite de unidades / departamentos")
    max_residents = models.PositiveIntegerField(default=150, help_text="Límite de residentes")
    features = models.JSONField(default=list, blank=True, help_text="Lista de características y módulos incluidos")
    is_popular = models.BooleanField(default=False, help_text="Destacar como más popular en landing")
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0, help_text="Orden de visualización")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "saas_subscription_plan"
        ordering = ("order", "price_bob")

    def __str__(self):
        return f"{self.name} ({self.price_bob} BOB / {self.get_billing_period_display()})"


class TenantSubscription(models.Model):
    """
    Estado de la suscripción SaaS activa para un condominio.
    """

    class Status(models.TextChoices):
        TRIAL = "TRIAL", "Período de Prueba"
        ACTIVE = "ACTIVE", "Activa"
        PAST_DUE = "PAST_DUE", "Pago Pendiente"
        CANCELED = "CANCELED", "Cancelada"
        EXPIRED = "EXPIRED", "Expirada"

    condominium = models.OneToOneField(
        "condominiums.Condominium",
        on_delete=models.CASCADE,
        related_name="subscription",
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.TRIAL,
    )
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    current_period_start = models.DateTimeField(default=timezone.now)
    current_period_end = models.DateTimeField(default=timezone.now)
    stripe_customer_id = models.CharField(max_length=120, blank=True, default="")
    stripe_subscription_id = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "saas_tenant_subscription"

    def __str__(self):
        return f"{self.condominium.name} -> {self.plan.name} [{self.get_status_display()}]"

    @property
    def is_valid(self) -> bool:
        now = timezone.now()
        if self.status == self.Status.ACTIVE:
            return self.current_period_end >= now
        if self.status == self.Status.TRIAL:
            return bool(self.trial_ends_at and self.trial_ends_at >= now)
        return False


class SaaSPayment(models.Model):
    """
    Registro histórico de transacciones de suscripción SaaS con pasarela Stripe.
    """

    class Status(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        APROBADO = "APROBADO", "Aprobado"
        RECHAZADO = "RECHAZADO", "Rechazado"

    condominium = models.ForeignKey(
        "condominiums.Condominium",
        on_delete=models.CASCADE,
        related_name="saas_payments",
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="saas_payments",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default="bob")
    provider = models.CharField(max_length=30, default="stripe")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDIENTE,
    )
    payment_intent_id = models.CharField(max_length=150, blank=True, default="")
    client_secret = models.CharField(max_length=255, blank=True, default="")
    idempotency_key = models.CharField(max_length=120, unique=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "saas_payment"
        ordering = ("-created_at",)

    def __str__(self):
        return f"Pago #{self.id} {self.condominium.name} ({self.amount} {self.currency.upper()}) - {self.status}"
