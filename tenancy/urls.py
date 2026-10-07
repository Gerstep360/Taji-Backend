"""URLs para el módulo de SaaS Multi-Tenant."""

from django.urls import path
from rest_framework.routers import DefaultRouter
from tenancy.views import (
    ConfirmSandboxPaymentView,
    CreateSubscriptionIntentView,
    CurrentTenantView,
    MyTenantsView,
    PaymentConfigView,
    PaymentHistoryView,
    PublicCondominiumsListView,
    SaaSCondominiumRegisterView,
    StripeWebhookView,
    SubscriptionPlansView,
    SwitchTenantView,
    TenantSubscriptionView,
    TenantViewSet,
    UpdateCondominiumProfileView,
)

router = DefaultRouter()
router.register("tenants", TenantViewSet, basename="saas-tenant")

urlpatterns = [
    # Multi-Tenant Switch & Session
    path("my-tenants/", MyTenantsView.as_view(), name="saas-my-tenants"),
    path("switch-tenant/", SwitchTenantView.as_view(), name="saas-switch-tenant"),
    path("current-tenant/", CurrentTenantView.as_view(), name="saas-current-tenant"),
    path("my-condominium/", UpdateCondominiumProfileView.as_view(), name="saas-my-condominium"),

    # SaaS Subscription Plans & Stripe Payments (Espejo de Primer examen)
    path("plans/", SubscriptionPlansView.as_view(), name="saas-plans"),
    path("payment-config/", PaymentConfigView.as_view(), name="saas-payment-config"),
    path("subscription/", TenantSubscriptionView.as_view(), name="saas-subscription"),
    path("checkout/create-intent/", CreateSubscriptionIntentView.as_view(), name="saas-checkout-create-intent"),
    path("checkout/confirm-sandbox/", ConfirmSandboxPaymentView.as_view(), name="saas-checkout-confirm-sandbox"),
    path("checkout/webhook/", StripeWebhookView.as_view(), name="saas-checkout-webhook"),
    path("payments/", PaymentHistoryView.as_view(), name="saas-payments"),

    # SaaS Public Onboarding / Provisioning for Condominium Administrators
    path("onboarding/register/", SaaSCondominiumRegisterView.as_view(), name="saas-onboarding-register"),
    path("condominiums/public/", PublicCondominiumsListView.as_view(), name="saas-public-condominiums"),
] + router.urls
