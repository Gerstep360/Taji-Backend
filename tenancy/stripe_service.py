"""
Servicio de Integración con Stripe para Suscripciones SaaS (Condominios Taji).
Espejo arquitectónico y funcional de Primer examen (backend/app/services/stripe_payments.py).
Soporta:
1. Creación de PaymentIntent contra la API REST de Stripe con moneda BOB.
2. Modo Sandbox transparente para desarrollo y pruebas offline o sin keys de producción.
3. Validación criptográfica de webhooks mediante HMAC-SHA256 y control de deriva temporal.
4. Activación y extensión automática de cuotas del Condominio (unidades y residentes).
"""

from decimal import Decimal
import hashlib
import hmac
import json
import logging
import time
from uuid import uuid4
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

import httpx

from tenancy.models import SubscriptionPlan, TenantSubscription, SaaSPayment
from condominiums.models import Condominium

logger = logging.getLogger(__name__)


def minor_units(amount: Decimal) -> int:
    """Convierte el monto en moneda base (BOB) a centavos / unidades menores enteras."""
    value = Decimal(str(amount)) * 100
    if not value.is_finite() or value <= 0 or value != value.to_integral_value():
        raise ValidationError("El importe del plan de suscripción es inválido.")
    return int(value)


def verify_event(raw: bytes, signature: str | None, secret: str) -> dict:
    """
    Verifica la firma criptográfica HMAC-SHA256 y la frescura del timestamp
    del webhook de Stripe (idéntico a Primer examen).
    """
    if not secret or not secret.startswith("whsec_"):
        raise APIException("El webhook secret de Stripe no está configurado adecuadamente.")
    try:
        parts = [part.split("=", 1) for part in (signature or "").split(",") if "=" in part]
        timestamp = next(value for key, value in parts if key == "t")
        if abs(time.time() - int(timestamp)) > 300:
            raise ValueError("Timestamp del webhook expirado (desfase > 300s).")
        expected = hmac.new(secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, value) for key, value in parts if key == "v1"):
            raise ValueError("Firma v1 del webhook de Stripe inválida.")
        event = json.loads(raw)
        if not isinstance(event, dict) or not isinstance(event.get("data", {}).get("object"), dict):
            raise ValueError("Payload de evento JSON malformado.")
        return event
    except (ValueError, StopIteration, TypeError, AttributeError) as exc:
        logger.error("Error validando firma de Stripe: %s", exc)
        raise ValidationError("Firma o payload de evento de Stripe inválido.") from exc


def _stripe_request(method: str, path: str, *, data=None, key=None) -> dict:
    """Ejecuta una petición autenticada vía HTTP a la API REST de Stripe."""
    secret_key = (getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip()
    headers = {"Authorization": f"Bearer {secret_key}"}
    if key:
        headers["Idempotency-Key"] = key
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.request(
                method,
                f"https://api.stripe.com/v1/{path}",
                headers=headers,
                data=data,
            )
        if response.status_code >= 400:
            logger.warning("Stripe API error %s: %s", response.status_code, response.text)
            raise APIException("Stripe no pudo preparar el pago de suscripción.")
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Error de conexión con Stripe API: %s", exc)
        raise APIException("No se pudo contactar con la pasarela Stripe.") from exc


def create_subscription_intent(condominium: Condominium, plan: SubscriptionPlan, user) -> dict:
    """
    Crea un PaymentIntent para la suscripción de un condominio a un plan SaaS.
    Si las credenciales de Stripe fallan o no hay red, activa el modo Sandbox transparente.
    """
    amount = minor_units(plan.price_bob)
    idempotency_key = f"saas-condo-{condominium.id}-plan-{plan.id}-{int(time.time() // 3600)}"

    # Buscar pago existente pendiente o crear uno nuevo
    payment = SaaSPayment.objects.filter(
        condominium=condominium,
        plan=plan,
        status=SaaSPayment.Status.PENDIENTE,
    ).first()

    if not payment:
        payment = SaaSPayment.objects.create(
            condominium=condominium,
            plan=plan,
            user=user if getattr(user, "is_authenticated", False) else None,
            amount=plan.price_bob,
            currency=getattr(settings, "STRIPE_CURRENCY", "bob").lower(),
            provider="stripe",
            status=SaaSPayment.Status.PENDIENTE,
            idempotency_key=f"stripe-saas-{condominium.id}-{uuid4().hex[:12]}",
            metadata={
                "condominium_id": condominium.id,
                "condominium_name": condominium.name,
                "plan_id": plan.id,
                "plan_code": plan.code,
                "plan_name": plan.name,
            },
        )

    secret_key = (getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip()
    pub_key = (getattr(settings, "STRIPE_PUBLISHABLE_KEY", "") or "").strip()
    is_real_stripe_key = secret_key.startswith("sk_") or secret_key.startswith("rk_")

    if is_real_stripe_key:
        try:
            if payment.payment_intent_id and payment.payment_intent_id.startswith("pi_") and not payment.payment_intent_id.startswith("pi_sandbox_"):
                intent = _stripe_request("GET", f"payment_intents/{payment.payment_intent_id}")
            else:
                intent = _stripe_request(
                    "POST",
                    "payment_intents",
                    key=payment.idempotency_key,
                    data={
                        "amount": str(amount),
                        "currency": getattr(settings, "STRIPE_CURRENCY", "bob").lower(),
                        "payment_method_types[]": "card",
                        "description": f"Suscripción Taji SaaS - {plan.name} para {condominium.name}",
                        "metadata[condominium_id]": str(condominium.id),
                        "metadata[plan_id]": str(plan.id),
                        "metadata[payment_id]": str(payment.id),
                    },
                )
            if intent.get("id"):
                payment.payment_intent_id = intent["id"]
                payment.client_secret = intent.get("client_secret", "")
                payment.save(update_fields=["payment_intent_id", "client_secret", "updated_at"])
                return {
                    "payment_id": payment.id,
                    "provider": "stripe",
                    "payment_intent_id": intent["id"],
                    "client_secret": intent.get("client_secret"),
                    "publishable_key": pub_key,
                    "amount": amount,
                    "currency": getattr(settings, "STRIPE_CURRENCY", "bob").lower(),
                    "status": payment.status,
                    "sandbox": False,
                    "plan_name": plan.name,
                    "condominium_name": condominium.name,
                }
        except Exception as exc:
            logger.warning("No se pudo conectar a Stripe (%s). Habilitando modo sandbox.", exc)

    # Fallback transparente a sandbox de prueba para Stripe
    sandbox_id = f"pi_sandbox_{condominium.id}_{uuid4().hex[:10]}"
    client_secret = f"{sandbox_id}_secret_{uuid4().hex[:16]}"
    payment.payment_intent_id = sandbox_id
    payment.client_secret = client_secret
    payment.save(update_fields=["payment_intent_id", "client_secret", "updated_at"])

    return {
        "payment_id": payment.id,
        "provider": "stripe",
        "payment_intent_id": sandbox_id,
        "client_secret": client_secret,
        "publishable_key": pub_key or "pk_test_taji_sandbox",
        "amount": amount,
        "currency": getattr(settings, "STRIPE_CURRENCY", "bob").lower(),
        "status": payment.status,
        "sandbox": True,
        "plan_name": plan.name,
        "condominium_name": condominium.name,
    }


def confirm_subscription_payment(payment: SaaSPayment, new_status: str = "APROBADO") -> SaaSPayment:
    """
    Confirma un pago y actualiza / extiende la suscripción y cuotas del condominio.
    """
    payment.status = new_status
    payment.save(update_fields=["status", "updated_at"])

    if new_status == SaaSPayment.Status.APROBADO:
        now = timezone.now()
        condominium = payment.condominium
        plan = payment.plan

        duration_days = 365 if plan.billing_period == SubscriptionPlan.Period.ANNUAL else 30

        subscription, created = TenantSubscription.objects.get_or_create(
            condominium=condominium,
            defaults={
                "plan": plan,
                "status": TenantSubscription.Status.ACTIVE,
                "current_period_start": now,
                "current_period_end": now + timedelta(days=duration_days),
            },
        )

        if not created:
            subscription.plan = plan
            subscription.status = TenantSubscription.Status.ACTIVE
            if subscription.current_period_end and subscription.current_period_end > now:
                subscription.current_period_end = subscription.current_period_end + timedelta(days=duration_days)
            else:
                subscription.current_period_start = now
                subscription.current_period_end = now + timedelta(days=duration_days)
            subscription.save()

        # Actualizar cuotas del condominio de acuerdo al plan contratado
        condominium.max_units = plan.max_units
        condominium.max_residents = plan.max_residents
        condominium.save(update_fields=["max_units", "max_residents", "updated_at"])

    return payment


def confirm_sandbox_payment(
    payment_id: int | None = None,
    user=None,
    plan_id: int | None = None,
    condo_id: int | None = None,
) -> SaaSPayment:
    """Confirma de inmediato un pago en modo sandbox para pruebas ágiles."""
    payment = None
    if payment_id:
        payment = SaaSPayment.objects.select_related("condominium", "plan").filter(id=payment_id).first()

    if not payment and condo_id:
        condo = Condominium.objects.filter(id=condo_id, is_active=True).first()
        plan = SubscriptionPlan.objects.filter(id=plan_id, is_active=True).first() if plan_id else None
        if not plan:
            plan = SubscriptionPlan.objects.filter(is_active=True).order_by("order").first()
        if condo and plan:
            payment = SaaSPayment.objects.create(
                condominium=condo,
                plan=plan,
                user=user if getattr(user, "is_authenticated", False) else None,
                amount=plan.price_bob,
                currency=getattr(settings, "STRIPE_CURRENCY", "bob").lower(),
                provider="stripe",
                status=SaaSPayment.Status.APROBADO,
                payment_intent_id=f"pi_sandbox_{condo.id}_{uuid4().hex[:10]}",
                idempotency_key=f"stripe-sandbox-direct-{condo.id}-{uuid4().hex[:8]}",
                metadata={"sandbox": True, "direct_confirm": True},
            )
            return confirm_subscription_payment(payment, SaaSPayment.Status.APROBADO)

    if not payment:
        raise NotFound("Registro de pago o condominio no encontrado.")

    if payment.status == SaaSPayment.Status.APROBADO:
        return payment

    return confirm_subscription_payment(payment, SaaSPayment.Status.APROBADO)


def process_stripe_webhook_event(event: dict) -> SaaSPayment | None:
    """Procesa eventos de webhook entrantes desde Stripe."""
    event_type = event.get("type")
    if event_type not in {"payment_intent.succeeded", "payment_intent.canceled"}:
        return None

    intent = event.get("data", {}).get("object", {})
    intent_id = intent.get("id")
    if not intent_id:
        return None

    payment = SaaSPayment.objects.select_related("condominium", "plan").filter(
        provider="stripe",
        payment_intent_id=intent_id,
    ).first()

    if payment is None:
        logger.info("Webhook Stripe recibido para intent_id desconocido: %s", intent_id)
        return None

    metadata = intent.get("metadata") or {}
    expected_amount = minor_units(payment.amount)
    if (intent.get("amount") != expected_amount or
        intent.get("currency", "").lower() != payment.currency.lower() or
        metadata.get("payment_id") != str(payment.id)):
        raise ValidationError("El evento de Stripe no coincide con los registros del pago.")

    if event_type == "payment_intent.succeeded":
        if intent.get("status") != "succeeded" or intent.get("amount_received") != expected_amount:
            raise ValidationError("El importe de Stripe no ha sido completado íntegramente.")
        return confirm_subscription_payment(payment, SaaSPayment.Status.APROBADO)

    return confirm_subscription_payment(payment, SaaSPayment.Status.RECHAZADO)
