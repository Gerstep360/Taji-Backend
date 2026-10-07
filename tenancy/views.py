"""Vistas y endpoints para la capa SaaS Multi-Tenant (Sección 21, 31, 35 de multitenant_saas_optimizado.md)."""

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from condominiums.models import Condominium
from tenancy.context import TenantContext
from tenancy.models import TenantMembership
from tenancy.permissions import IsPlatformAdmin, IsTenantAdmin, IsTenantMember
from tenancy.serializers import (
    TenantContextResponseSerializer,
    TenantMembershipSerializer,
    TenantProvisionRequestSerializer,
    TenantSerializer,
    TenantSwitchRequestSerializer,
)
from tenancy.services import TenantProvisioningService


@extend_schema_view(
    list=extend_schema(tags=["SaaS - Tenants"], summary="Listar tenants disponibles"),
    retrieve=extend_schema(tags=["SaaS - Tenants"], summary="Consultar datos de un tenant"),
    create=extend_schema(
        tags=["SaaS - Tenants"],
        summary="Aprovisionar un nuevo tenant (Platform Admin)",
        request=TenantProvisionRequestSerializer,
        responses={status.HTTP_201_CREATED: TenantSerializer},
    ),
    partial_update=extend_schema(tags=["SaaS - Tenants"], summary="Modificar configuración de un tenant"),
)
class TenantViewSet(viewsets.ModelViewSet):
    """
    CRUD y Aprovisionamiento rápido de tenants en arquitectura Pool.
    """

    serializer_class = TenantSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.is_staff:
            return Condominium.objects.all().order_by("name")
        # Usuarios regulares solo ven los condominios donde tienen membresía activa
        return Condominium.objects.filter(
            tenant_memberships__user=user,
            tenant_memberships__is_active=True,
        ).distinct().order_by("name")

    def create(self, request, *args, **kwargs):
        if not (request.user.is_superuser or request.user.is_staff):
            raise PermissionDenied("Solo administradores globales de la plataforma pueden aprovisionar nuevos tenants.")

        serializer = TenantProvisionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        condominium = TenantProvisioningService.provision_tenant(
            name=data["name"],
            slug=data.get("slug"),
            legal_name=data.get("legal_name", ""),
            address=data.get("address", ""),
            phone=data.get("phone", ""),
            email=data.get("email", ""),
            admin_email=data.get("admin_email"),
            max_units=data.get("max_units", 500),
            max_residents=data.get("max_residents", 1500),
            actor_user=request.user,
            request=request,
        )

        return Response(TenantSerializer(condominium).data, status=status.HTTP_201_CREATED)


class MyTenantsView(APIView):
    """
    Lista todos los condominios/tenants a los que pertenece el usuario autenticado.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["SaaS - Tenants"],
        summary="Consultar mis tenants y membresías",
        responses={status.HTTP_200_OK: TenantMembershipSerializer(many=True)},
    )
    def get(self, request):
        user = request.user
        memberships = (
            TenantMembership.objects.filter(user=user, is_active=True)
            .select_related("condominium", "role")
            .order_by("-is_default", "condominium__name")
        )
        return Response(TenantMembershipSerializer(memberships, many=True).data)


class SwitchTenantView(APIView):
    """
    Cambia el tenant activo para la sesión del usuario.
    Valida estrictamente que el usuario pertenezca al tenant solicitado.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["SaaS - Tenants"],
        summary="Cambiar tenant activo de la sesión",
        request=TenantSwitchRequestSerializer,
        responses={status.HTTP_200_OK: TenantContextResponseSerializer},
    )
    def post(self, request):
        serializer = TenantSwitchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw_id = serializer.validated_data["tenant_id"].strip()

        # Buscar el condominio
        if raw_id.isdigit():
            condo = Condominium.objects.filter(id=int(raw_id), is_active=True).first()
        else:
            condo = Condominium.objects.filter(slug=raw_id, is_active=True).first()

        if not condo:
            raise ValidationError({"tenant_id": ["El condominio/tenant especificado no existe o no está activo."]})

        # Validar membresía a menos que sea superusuario
        membership = None
        if not request.user.is_superuser:
            membership = TenantMembership.objects.filter(
                user=request.user,
                condominium=condo,
                is_active=True,
            ).select_related("condominium", "role").first()

            if not membership:
                raise PermissionDenied("No posees membresía activa para operar en este condominio/tenant.")

        # Guardar en sesión
        if hasattr(request, "session"):
            request.session["active_tenant_id"] = condo.id

        return Response(
            {
                "active_tenant": TenantSerializer(condo).data,
                "membership": TenantMembershipSerializer(membership).data if membership else None,
                "is_global": False,
            },
            status=status.HTTP_200_OK,
        )


class CurrentTenantView(APIView):
    """
    Devuelve los datos del tenant actualmente activo en el request.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["SaaS - Tenants"],
        summary="Obtener contexto del tenant actualmente activo",
        responses={status.HTTP_200_OK: TenantContextResponseSerializer},
    )
    def get(self, request):
        tenant = getattr(request, "tenant", None) or TenantContext.get_current_tenant()
        membership = getattr(request, "tenant_membership", None) or TenantContext.get_current_membership()
        is_global = getattr(request, "is_global_tenant", False) or TenantContext.is_global()

        return Response(
            {
                "active_tenant": TenantSerializer(tenant).data if tenant else None,
                "membership": TenantMembershipSerializer(membership).data if membership else None,
                "is_global": is_global,
            }
        )


# =====================================================================
# Endpoints de Planes SaaS, Suscripciones y Pagos Stripe
# (Espejo de Primer examen y multitenant_saas_optimizado.md)
# =====================================================================

from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny

from condominiums.models import ResidentUnit, Unit
from tenancy.models import SaaSPayment, SubscriptionPlan, TenantSubscription
from tenancy.serializers import (
    ConfirmSandboxPaymentRequestSerializer,
    CreatePaymentIntentRequestSerializer,
    SaaSPaymentSerializer,
    SubscriptionPlanSerializer,
    TenantSubscriptionDetailSerializer,
    UpdateCondominiumProfileSerializer,
)
from tenancy.stripe_service import (
    confirm_sandbox_payment,
    create_subscription_intent,
    process_stripe_webhook_event,
    verify_event,
)


class SubscriptionPlansView(APIView):
    """
    Lista todos los planes SaaS activos para la página de bienvenida y precios.
    Acceso público para visitantes interesados en adquirir el servicio.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["SaaS - Suscripciones"],
        summary="Listar planes de suscripción disponibles",
        responses={status.HTTP_200_OK: SubscriptionPlanSerializer(many=True)},
    )
    def get(self, request):
        plans = SubscriptionPlan.objects.filter(is_active=True).order_by("order", "price_bob")
        return Response(SubscriptionPlanSerializer(plans, many=True).data)


class PaymentConfigView(APIView):
    """
    Retorna la configuración pública de pagos (proveedor, publishable_key, moneda).
    Idéntico a /api/v1/stripe/config de Primer examen.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["SaaS - Suscripciones"],
        summary="Obtener configuración pública de pagos",
    )
    def get(self, request):
        return Response(
            {
                "provider": getattr(settings, "PAYMENT_PROVIDER", "stripe"),
                "publishable_key": (getattr(settings, "STRIPE_PUBLISHABLE_KEY", "") or "").strip(),
                "currency": getattr(settings, "STRIPE_CURRENCY", "bob").lower(),
            }
        )


class TenantSubscriptionView(APIView):
    """
    Consulta el estado detallado de suscripción y límites de cuota del condominio activo.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["SaaS - Suscripciones"],
        summary="Consultar suscripción y métricas de cuota del tenant",
        responses={status.HTTP_200_OK: TenantSubscriptionDetailSerializer},
    )
    def get(self, request):
        condo = getattr(request, "tenant", None) or TenantContext.get_current_tenant()
        if not condo:
            # Si es superusuario sin condominio seleccionado, buscar el primero
            if request.user.is_superuser:
                condo = Condominium.objects.filter(is_active=True).first()
            if not condo:
                raise ValidationError("No hay un condominio activo en la sesión actual.")

        subscription = TenantSubscription.objects.filter(condominium=condo).select_related("plan").first()

        # Si aún no tiene suscripción registrada, crear una en modo TRIAL con el plan inicial
        if not subscription:
            default_plan = SubscriptionPlan.objects.filter(is_active=True).order_by("order").first()
            if default_plan:
                now = timezone.now()
                subscription = TenantSubscription.objects.create(
                    condominium=condo,
                    plan=default_plan,
                    status=TenantSubscription.Status.TRIAL,
                    trial_ends_at=now + timedelta(days=14),
                    current_period_start=now,
                    current_period_end=now + timedelta(days=14),
                )

        used_units = Unit.objects.filter(sector__condominium=condo, status="ACTIVE").count()
        used_residents = (
            ResidentUnit.objects.filter(unit__sector__condominium=condo, resident__status="ACTIVE")
            .values("resident")
            .distinct()
            .count()
        )

        now = timezone.now()
        days_left = 0
        if subscription:
            target_date = subscription.trial_ends_at if subscription.status == TenantSubscription.Status.TRIAL else subscription.current_period_end
            if target_date and target_date > now:
                days_left = (target_date - now).days

        data = {
            "id": subscription.id if subscription else None,
            "plan": SubscriptionPlanSerializer(subscription.plan).data if subscription and subscription.plan else None,
            "status": subscription.status if subscription else "NO_SUBSCRIPTION",
            "status_label": subscription.get_status_display() if subscription else "Sin suscripción",
            "is_valid": subscription.is_valid if subscription else False,
            "current_period_start": subscription.current_period_start if subscription else None,
            "current_period_end": subscription.current_period_end if subscription else None,
            "trial_ends_at": subscription.trial_ends_at if subscription else None,
            "days_left": days_left,
            "max_units": condo.max_units,
            "used_units": used_units,
            "max_residents": condo.max_residents,
            "used_residents": used_residents,
        }
        return Response(data)


class CreateSubscriptionIntentView(APIView):
    """
    Crea un PaymentIntent con Stripe para la suscripción de un condominio.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["SaaS - Suscripciones"],
        summary="Crear PaymentIntent de Stripe para suscripción",
        request=CreatePaymentIntentRequestSerializer,
    )
    def post(self, request):
        serializer = CreatePaymentIntentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan_id = serializer.validated_data["plan_id"]
        condo_id = serializer.validated_data.get("condominium_id")

        if condo_id:
            condo = Condominium.objects.filter(id=condo_id, is_active=True).first()
        else:
            condo = getattr(request, "tenant", None) or TenantContext.get_current_tenant()

        if not condo:
            raise ValidationError("Condominio/tenant no identificado o inactivo.")

        plan = SubscriptionPlan.objects.filter(id=plan_id, is_active=True).first()
        if not plan:
            raise NotFound("El plan de suscripción seleccionado no existe o está inactivo.")

        intent_data = create_subscription_intent(condominium=condo, plan=plan, user=request.user)
        return Response(intent_data, status=status.HTTP_200_OK)


class ConfirmSandboxPaymentView(APIView):
    """
    Confirma un pago en entorno Sandbox de Stripe para pruebas ágiles.
    Idéntico a /stripe-sandbox-confirm de Primer examen.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["SaaS - Suscripciones"],
        summary="Confirmar pago Sandbox de Stripe",
        request=ConfirmSandboxPaymentRequestSerializer,
    )
    def post(self, request):
        serializer = ConfirmSandboxPaymentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment_id = serializer.validated_data["payment_id"]

        payment = confirm_sandbox_payment(payment_id=payment_id, user=request.user)
        return Response(SaaSPaymentSerializer(payment).data, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(APIView):
    """
    Recibe y procesa webhooks criptográficamente firmados por Stripe.
    Idéntico a /stripe-webhook de Primer examen.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["SaaS - Suscripciones"],
        summary="Webhook seguro de Stripe",
    )
    def post(self, request):
        signature = request.headers.get("stripe-signature")
        secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")
        raw_body = request.body

        event = verify_event(raw_body, signature, secret)
        payment = process_stripe_webhook_event(event)

        return Response({"received": True, "processed": payment is not None}, status=status.HTTP_200_OK)


class PaymentHistoryView(APIView):
    """
    Lista el historial de transacciones de suscripción para el condominio activo.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["SaaS - Suscripciones"],
        summary="Historial de pagos de suscripción del tenant",
        responses={status.HTTP_200_OK: SaaSPaymentSerializer(many=True)},
    )
    def get(self, request):
        condo = getattr(request, "tenant", None) or TenantContext.get_current_tenant()
        if not condo:
            return Response([])
        payments = SaaSPayment.objects.filter(condominium=condo).select_related("plan").order_by("-created_at")[:30]
        return Response(SaaSPaymentSerializer(payments, many=True).data)


class UpdateCondominiumProfileView(APIView):
    """
    Permite al Administrador del Condominio actualizar datos generales de su Tenant.
    """

    permission_classes = [IsAuthenticated, IsTenantAdmin]

    @extend_schema(
        tags=["SaaS - Tenants"],
        summary="Actualizar perfil del condominio activo",
        request=UpdateCondominiumProfileSerializer,
        responses={status.HTTP_200_OK: TenantSerializer},
    )
    def patch(self, request):
        condo = getattr(request, "tenant", None) or TenantContext.get_current_tenant()
        if not condo:
            raise ValidationError("No hay un condominio activo en la sesión.")

        serializer = UpdateCondominiumProfileSerializer(condo, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(TenantSerializer(condo).data)


class PublicCondominiumsListView(APIView):
    """
    Lista pública de condominios activos para selección de residentes durante el registro.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["SaaS - Tenants"],
        summary="Listar condominios activos disponibles para residentes",
    )
    def get(self, request):
        condos = Condominium.objects.filter(is_active=True).order_by("name")
        data = [
            {
                "id": c.id,
                "name": c.name,
                "slug": c.slug,
                "address": c.address or "",
                "phone": c.phone or "",
            }
            for c in condos
        ]
        return Response(data)


from django.db import transaction
from accounts.models import User, Person, Role
from accounts.cookies import set_auth_cookies
from accounts.serializers import UserSerializer
from paquetes.paquete1_usuarios_condominio.cu01_autenticacion.views import token_pair_for_user
from tenancy.serializers import SaaSCondominiumRegisterSerializer


class SaaSCondominiumRegisterView(APIView):
    """
    Onboarding público de un nuevo Condominio y Administrador.
    Permite registrar el condominio, crea al administrador activado de inmediato (is_approved=True)
    y aprovisiona su suscripción (Prueba gratuita de 14 días o Stripe).
    Inicia sesión automáticamente retornando tokens JWT y estableciendo cookies seguras.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["SaaS - Onboarding"],
        summary="Aprovisionar nuevo Condominio y cuenta de Administrador",
        request=SaaSCondominiumRegisterSerializer,
    )
    @transaction.atomic
    def post(self, request):
        serializer = SaaSCondominiumRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        admin_email = data["admin_email"].strip().lower()
        if User.objects.filter(email=admin_email).exists():
            raise ValidationError({"admin_email": ["Ya existe un usuario registrado con este correo electrónico."]})

        # Buscar plan seleccionado
        plan = SubscriptionPlan.objects.filter(code=data["plan_code"], is_active=True).first()
        if not plan:
            plan = SubscriptionPlan.objects.filter(is_active=True).order_by("order").first()
        if not plan:
            raise ValidationError({"plan_code": ["No hay planes de suscripción disponibles."]})

        # 1. Crear Persona
        full_name_parts = data["admin_name"].strip().split(" ", 1)
        first_name = full_name_parts[0]
        last_name = full_name_parts[1] if len(full_name_parts) > 1 else ""
        doc_num = data.get("admin_document") or data.get("admin_phone") or "CI-PENDIENTE"

        person = Person.objects.create(
            first_name=first_name,
            last_name=last_name,
            document_number=doc_num,
            phone=data.get("admin_phone", ""),
        )

        # 2. Rol Administrador
        admin_role = (
            Role.objects.filter(slug="administrador").first()
            or Role.objects.filter(slug="admin").first()
            or Role.objects.create(slug="administrador", name="Administrador")
        )

        # 3. Crear Usuario Administrador (Aprobado y Activo de fábrica)
        user = User.objects.create_user(
            email=admin_email,
            password=data["admin_password"],
            person=person,
            role=admin_role,
            is_approved=True,  # ¡Inmediatamente aprobado como fundador del condominio!
            is_active=True,
        )

        # 4. Aprovisionar Condominio (Tenant)
        condominium = TenantProvisioningService.provision_tenant(
            name=data["condominium_name"],
            slug=data.get("condominium_code") or None,
            address=data.get("address", ""),
            phone=data.get("phone", ""),
            email=admin_email,
            admin_user=user,
            max_units=plan.max_units,
            max_residents=plan.max_residents,
            actor_user=user,
            request=request,
        )

        # 5. Crear Suscripción
        now = timezone.now()
        payment_method = data.get("payment_method", "TRIAL")

        if payment_method == "STRIPE":
            payment_id = data.get("payment_id")
            if payment_id:
                payment = SaaSPayment.objects.filter(id=payment_id).first()
                if payment:
                    payment.condominium = condominium
                    payment.user = user
                    payment.status = SaaSPayment.Status.APROBADO
                    payment.save(update_fields=["condominium", "user", "status", "updated_at"])

            subscription = TenantSubscription.objects.create(
                condominium=condominium,
                plan=plan,
                status=TenantSubscription.Status.ACTIVE,
                current_period_start=now,
                current_period_end=now + timedelta(days=30),
            )
        else:
            # 14 días de prueba gratuita
            subscription = TenantSubscription.objects.create(
                condominium=condominium,
                plan=plan,
                status=TenantSubscription.Status.TRIAL,
                trial_ends_at=now + timedelta(days=14),
                current_period_start=now,
                current_period_end=now + timedelta(days=14),
            )

        # 6. Guardar tenant activo en sesión
        if hasattr(request, "session"):
            request.session["active_tenant_id"] = condominium.id

        # 7. Generar tokens JWT
        tokens = token_pair_for_user(user)

        response_data = {
            "message": "Condominio aprovisionado exitosamente. ¡Bienvenido a Taji!",
            "user": UserSerializer(user).data,
            "condominium": TenantSerializer(condominium).data,
            "subscription": {
                "id": subscription.id,
                "plan_name": plan.name,
                "status": subscription.status,
                "days_left": 14 if subscription.status == "TRIAL" else 30,
            },
            "access": tokens["access"],
            "refresh": tokens["refresh"],
        }
        response = Response(response_data, status=status.HTTP_201_CREATED)
        set_auth_cookies(response, access=tokens["access"], refresh=tokens["refresh"])
        return response
