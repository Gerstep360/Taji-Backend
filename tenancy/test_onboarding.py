"""Verificación local del alta pública; no realiza cobros externos."""

from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient

from accounts.models import User
from condominiums.models import Condominium
from tenancy.models import SubscriptionPlan, TenantMembership, TenantSubscription, SaaSPayment


class OnboardingFlowTests(APITestCase):
    def setUp(self):
        self.plan = SubscriptionPlan.objects.create(code="test-local", name="Plan local", price_bob=100)

    def payload(self, suffix="a"):
        return {
            "condominium_name": f"Condominio prueba {suffix}", "admin_name": f"Administrador {suffix}",
            "admin_email": f"admin-{suffix}@example.test", "admin_document": f"ONBOARD-{suffix}",
            "admin_password": "Test-only-123!", "plan_code": self.plan.code, "payment_method": "TRIAL",
        }

    def test_trial_creates_condominium_admin_membership_and_authenticated_session(self):
        before = timezone.now()
        with patch("tenancy.stripe_service._stripe_request", side_effect=AssertionError("No debe cobrar")):
            response = self.client.post(reverse("saas-onboarding-register"), self.payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        user = User.objects.get(email="admin-a@example.test")
        condo = Condominium.objects.get(pk=response.data["condominium"]["id"])
        membership = TenantMembership.objects.get(user=user, condominium=condo)
        self.assertTrue(membership.is_active)
        self.assertIn(membership.role.slug, ("admin", "administrador"))
        self.assertFalse(user.is_superuser)
        subscription = TenantSubscription.objects.get(condominium=condo)
        self.assertEqual(subscription.status, "TRIAL")
        self.assertGreaterEqual(subscription.trial_ends_at, before + timedelta(days=14))
        self.assertFalse(SaaSPayment.objects.filter(condominium=condo).exists())
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')
        self.assertEqual(client.get(reverse("saas-subscription")).data["status"], "TRIAL")
        self.assertEqual(client.get(reverse("turnos-seguridad-list")).status_code, 200)

    def test_two_registered_administrators_cannot_switch_to_each_others_condominium(self):
        first = self.client.post(reverse("saas-onboarding-register"), self.payload("a"), format="json")
        second = APIClient().post(reverse("saas-onboarding-register"), self.payload("b"), format="json")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 201, second.data)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {first.data["access"]}')
        response = client.get(reverse("turnos-seguridad-list"), HTTP_X_TENANT_ID=str(second.data["condominium"]["id"]))
        self.assertEqual(response.status_code, 403)

    def test_current_stripe_onboarding_uses_simulated_payment_without_external_charge(self):
        payload = self.payload()
        payload["payment_method"] = "STRIPE"
        with patch("tenancy.stripe_service._stripe_request", side_effect=AssertionError("No debe cobrar")):
            response = self.client.post(reverse("saas-onboarding-register"), payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        payment = SaaSPayment.objects.get(condominium_id=response.data["condominium"]["id"])
        self.assertTrue(payment.metadata["sandbox"])
        self.assertEqual(payment.status, "APROBADO")
        self.assertEqual(response.data["subscription"]["status"], "ACTIVE")
