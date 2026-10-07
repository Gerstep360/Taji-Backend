from rest_framework import status, viewsets
from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from accounts.models import Person
from condominiums.models import Resident
from paquetes.paquete1_usuarios_condominio.cu05_residentes.permissions import CanManageResidents
from paquetes.paquete1_usuarios_condominio.cu05_residentes.serializers import ResidentSerializer
from rest_framework import filters, status, viewsets


@extend_schema_view(
    list=extend_schema(
        tags=["Residentes"],
        summary="Listar residentes y copropietarios",
        parameters=[
            OpenApiParameter("search", str, description="Nombre, documento, correo o teléfono."),
            OpenApiParameter("status", str, description="Estado del residente."),
            OpenApiParameter("ordering", str, description="Campo de orden; anteponer - para descendente."),
        ],
    ),
    retrieve=extend_schema(tags=["Residentes"], summary="Consultar residente"),
    create=extend_schema(tags=["Residentes"], summary="Registrar residente o copropietario"),
    update=extend_schema(tags=["Residentes"], summary="Reemplazar residente"),
    partial_update=extend_schema(tags=["Residentes"], summary="Editar residente"),
)
@method_decorator(never_cache, name="dispatch")
class ResidentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """T014: CRUD de residentes y copropietarios (CU05).

    Sin destroy: la baja se maneja mediante el estado lógico existente
    (Resident.status/deactivated_at), no se elimina físicamente el registro.
    """

    serializer_class = ResidentSerializer
    permission_classes = [IsAuthenticated, CanManageResidents]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = (
        "status",
        "registered_at",
        "person__first_name",
        "person__last_name",
    )
    ordering = ("person__last_name", "person__first_name")
    lookup_value_regex = "[0-9]+"

    def get_queryset(self):
        from tenancy.context import TenantContext
        tenant = getattr(self.request, "tenant", None) or TenantContext.get_current_tenant()
        queryset = Resident.objects.select_related("person")
        if tenant and not TenantContext.is_global():
            queryset = queryset.filter(
                Q(condominium=tenant)
                | Q(unit_links__unit__sector__condominium=tenant)
                | Q(person__user__tenant_memberships__condominium=tenant)
            ).distinct()

        resident_status = self.request.query_params.get("status", "").strip().upper()
        search = self.request.query_params.get("search", "").strip()

        if resident_status:
            queryset = queryset.filter(status=resident_status)
        if search:
            queryset = queryset.filter(
                Q(person__first_name__icontains=search)
                | Q(person__last_name__icontains=search)
                | Q(person__document_number__icontains=search)
                | Q(person__contact_email__icontains=search)
                | Q(person__phone__icontains=search)
            )
        return queryset

    def perform_create(self, serializer):
        from tenancy.context import TenantContext
        tenant = getattr(self.request, "tenant", None) or TenantContext.get_current_tenant()
        resident = serializer.save(condominium=tenant)
        if resident.person.contact_email:
            from accounts.models import Role, User
            from tenancy.models import TenantMembership

            email = resident.person.contact_email.strip().lower()
            res_role = Role.objects.filter(slug="residente").first()
            user = getattr(resident.person, "user", None) or User.objects.filter(email__iexact=email).first()

            is_new_user = False
            if not user:
                user = User.objects.create(
                    email=email,
                    person=resident.person,
                    role=res_role,
                    is_active=True,
                    is_approved=True,
                )
                user.set_unusable_password()
                user.save()
                is_new_user = True
            elif not user.person:
                user.person = resident.person
                user.save(update_fields=["person"])

            if tenant:
                TenantMembership.objects.get_or_create(
                    user=user,
                    condominium=tenant,
                    defaults={"role": res_role, "is_active": True, "is_default": True},
                )

            # Enviar correo para que el residente confirme sus datos y cree su contraseña de acceso
            self._send_activation_invitation(user, resident, tenant, is_new=is_new_user)

    def _send_activation_invitation(self, user, resident, tenant, is_new=True):
        from django.conf import settings
        from django.contrib.auth.tokens import default_token_generator
        from django.core.mail import send_mail
        from django.utils.encoding import force_bytes
        from django.utils.http import urlencode, urlsafe_base64_encode
        import logging

        try:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_base = getattr(settings, "PASSWORD_RESET_URL", "https://167.86.106.105/taji/restablecer-contrasena")
            activation_url = f"{reset_base}?{urlencode({'uid': uid, 'token': token, 'invite': '1'})}"

            tenant_name = tenant.name if tenant else "tu comunidad"
            first_name = resident.person.first_name if resident.person else "Residente"

            subject = f"Bienvenido a {tenant_name} - Activa tu cuenta en Taji"
            body = (
                f"Hola {first_name},\n\n"
                f"Has sido registrado como residente en el condominio {tenant_name}.\n\n"
                f"Para confirmar tus datos, crear tu contraseña personal e iniciar sesión en la plataforma Taji (Web y App Móvil), ingresa al siguiente enlace seguro:\n\n"
                f"{activation_url}\n\n"
                f"Tu correo registrado para inicio de sesión es: {user.email}\n\n"
                f"Si no reconoces este registro o tienes consultas, comunícate con la administración de {tenant_name}.\n\n"
                f"Atentamente,\n"
                f"Administración de {tenant_name} & Equipo Taji"
            )

            send_mail(
                subject=subject,
                message=body,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "Taji <no-reply@taji.app>"),
                recipient_list=[user.email],
                fail_silently=True,
            )
        except Exception as e:
            logging.getLogger("taji.residents").warning(
                f"No se pudo enviar correo de invitación a {user.email}: {e}"
            )

    @extend_schema(
        tags=["Residentes"],
        summary="Reenviar invitación por correo a residente",
        responses={status.HTTP_200_OK: dict},
    )
    @action(detail=True, methods=["post"], url_path="resend-invitation")
    def resend_invitation(self, request, pk=None):
        resident = self.get_object()
        if not resident.person.contact_email:
            return Response(
                {"detail": "El residente no cuenta con correo electrónico registrado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from tenancy.context import TenantContext
        tenant = getattr(self.request, "tenant", None) or TenantContext.get_current_tenant()
        from accounts.models import Role, User
        from tenancy.models import TenantMembership

        email = resident.person.contact_email.strip().lower()
        res_role = Role.objects.filter(slug="residente").first()
        user = getattr(resident.person, "user", None) or User.objects.filter(email__iexact=email).first()

        is_new = False
        if not user:
            user = User.objects.create(
                email=email,
                person=resident.person,
                role=res_role,
                is_active=True,
                is_approved=True,
            )
            user.set_unusable_password()
            user.save()
            is_new = True

        if tenant:
            TenantMembership.objects.get_or_create(
                user=user,
                condominium=tenant,
                defaults={"role": res_role, "is_active": True, "is_default": True},
            )

        self._send_activation_invitation(user, resident, tenant, is_new=is_new)
        return Response({
            "detail": f"Invitación de activación enviada exitosamente al correo {user.email}."
        })

    @extend_schema(
        tags=["Residentes"],
        summary="Consultar catálogos de residentes",
        responses={status.HTTP_200_OK: dict},
    )
    @action(detail=False, methods=["get"], url_path="options")
    def options_catalog(self, request):
        return Response(
            {
                "statuses": self._choices(Resident.Status.choices),
                "document_types": self._choices(Person.DocumentType.choices),
            }
        )

    @staticmethod
    def _choices(choices):
        return [{"value": value, "label": label} for value, label in choices]
