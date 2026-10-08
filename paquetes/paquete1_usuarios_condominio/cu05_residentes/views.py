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

        # El correo de invitación se envía fuera de la transacción del
        # serializador: un SMTP caído no debe revertir el alta del residente.
        # `create` lo adjunta a la respuesta para que la UI pueda avisar.
        self._invitation = None
        if resident.person.contact_email:
            self._invitation = self._provision_access(resident, tenant)

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        invitation = getattr(self, "_invitation", None)
        if invitation is not None:
            response.data["invitation"] = {
                "email_sent": invitation.sent,
                "email": invitation.email,
                "detail": invitation.detail,
                "temporary_password_issued": invitation.temporary_password is not None,
            }
        return response

    def _provision_access(self, resident, tenant):
        """
        Crea (o reutiliza) la cuenta del residente y le entrega sus credenciales.

        Se emiten dos cosas y son complementarias, no excluyentes:
        * una contraseña temporal, para que pueda entrar el mismo día, y
        * un enlace de activación, para que defina su propia clave.

        El enlace siempre se envía; la clave temporal depende del rol que puede
       ilinearlo. Nunca se devuelve la contraseña en la respuesta de la API.
        """
        from accounts.invitations import deliver_invitation, generate_temporary_password
        from accounts.models import Role, User
        from tenancy.models import TenantMembership

        email = resident.person.contact_email.strip().lower()
        res_role = Role.objects.filter(slug="residente").first()
        user = getattr(resident.person, "user", None) or User.objects.filter(email__iexact=email).first()

        temporary_password = None
        if not user:
            temporary_password = generate_temporary_password()
            user = User.objects.create_user(
                email=email,
                password=temporary_password,
                person=resident.person,
                role=res_role,
                is_active=True,
                is_approved=True,
                # Obliga a cambiar la clave temporal en el primer ingreso.
                must_change_password=True,
            )
        else:
            changed_fields = []
            if not user.person:
                user.person = resident.person
                changed_fields.append("person")
            # Una cuenta que aún no ha definido su propia clave (creada por un
            # flujo antiguo) también debe pasar por el cambio obligatorio.
            if not user.has_usable_password():
                temporary_password = generate_temporary_password()
                user.set_password(temporary_password)
                user.must_change_password = True
                changed_fields.extend(["password", "must_change_password"])
            if changed_fields:
                user.save(update_fields=[*changed_fields, "updated_at"])

        if tenant:
            TenantMembership.objects.get_or_create(
                user=user,
                condominium=tenant,
                defaults={"role": res_role, "is_active": True, "is_default": True},
            )

        return deliver_invitation(
            user=user,
            tenant_name=tenant.name if tenant else "tu comunidad",
            first_name=resident.person.first_name if resident.person else "",
            temporary_password=temporary_password,
        )

    @extend_schema(
        tags=["Residentes"],
        summary="Reenviar invitación por correo a residente",
        responses={status.HTTP_200_OK: dict},
    )
    @action(detail=True, methods=["post"], url_path="resend-invitation")
    def resend_invitation(self, request, pk=None):
        """
        Reenvía el acceso de un residente ya registrado.

        A diferencia del alta, aquí solo se manda el enlace de activación: la
        cuenta ya existe y no se reemplaza su contraseña por sorpresa. Si la
        cuenta nunca ha definido una clave (flujo anterior a este), se emite
        además una temporal, porque sin ella el enlace es la única vía de
        entrada y podría perderse en el correo.
        """
        resident = self.get_object()
        if not resident.person.contact_email:
            return Response(
                {
                    "detail": "El residente no cuenta con correo electrónico registrado.",
                    "error": {
                        "code": "validation_error",
                        "message": "El residente no cuenta con correo electrónico registrado.",
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        invitation = self._provision_access(resident, self._tenant())

        # El enlace se pudo construir pero el correo no salió: responder 200
        # haría creer al operador que el residente recibió la invitación.
        if not invitation.sent:
            return Response(
                {
                    "detail": invitation.detail,
                    "error": {"code": "email_delivery_failed", "message": invitation.detail},
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "detail": invitation.detail,
                "email_sent": True,
                "email": invitation.email,
                "temporary_password_issued": invitation.temporary_password is not None,
            }
        )

    def _tenant(self):
        from tenancy.context import TenantContext

        return getattr(self.request, "tenant", None) or TenantContext.get_current_tenant()

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
