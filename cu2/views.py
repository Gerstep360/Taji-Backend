from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from accounts.api_serializers import ErrorResponseSerializer
from accounts.models import Role, SystemPermission, User
from accounts.serializers import UserSerializer
from cu2.permissions import CanManageRoles
from cu2.serializers import (
    InternalUserCreateSerializer,
    PendingResidentSerializer,
    ResidentReviewSerializer,
    RoleDetailSerializer,
    RolePermissionsUpdateSerializer,
    SystemPermissionSerializer,
)


class RoleListView(generics.ListAPIView):
    """Lista todos los roles activos del sistema. Solo Administrador. (CU2)"""

    permission_classes = [permissions.IsAuthenticated, CanManageRoles]
    serializer_class = RoleDetailSerializer
    queryset = Role.objects.filter(is_active=True).prefetch_related("permissions").order_by("name")
    pagination_class = None

    @extend_schema(
        tags=["Roles y Permisos"],
        summary="Listar roles del sistema",
        responses={
            200: RoleDetailSerializer(many=True),
            401: OpenApiResponse(ErrorResponseSerializer, description="No autenticado."),
            403: OpenApiResponse(ErrorResponseSerializer, description="Sin permisos de administrador."),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class AllPermissionsView(generics.GenericAPIView):
    """Lista todos los permisos activos del sistema. Solo Administrador. (CU2)"""

    permission_classes = [permissions.IsAuthenticated, CanManageRoles]

    @extend_schema(
        tags=["Roles y Permisos"],
        summary="Listar permisos disponibles",
        responses={
            200: SystemPermissionSerializer(many=True),
            401: OpenApiResponse(ErrorResponseSerializer, description="No autenticado."),
            403: OpenApiResponse(ErrorResponseSerializer, description="Sin permisos de administrador."),
        },
    )
    def get(self, request):
        qs = SystemPermission.objects.filter(is_active=True).order_by("module", "code")
        return Response(SystemPermissionSerializer(qs, many=True).data)


class RolePermissionsView(generics.GenericAPIView):
    """Consulta o actualiza los permisos de un rol específico. Solo Administrador. (CU2)"""

    permission_classes = [permissions.IsAuthenticated, CanManageRoles]

    def _get_role(self, slug: str) -> Role:
        try:
            return Role.objects.prefetch_related("permissions").get(slug=slug, is_active=True)
        except Role.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound(f"No existe un rol activo con slug '{slug}'.")

    @extend_schema(
        tags=["Roles y Permisos"],
        summary="Consultar permisos de un rol",
        responses={
            200: RoleDetailSerializer,
            401: OpenApiResponse(ErrorResponseSerializer, description="No autenticado."),
            403: OpenApiResponse(ErrorResponseSerializer, description="Sin permisos de administrador."),
            404: OpenApiResponse(ErrorResponseSerializer, description="Rol no encontrado."),
        },
    )
    def get(self, request, slug: str):
        role = self._get_role(slug)
        return Response(RoleDetailSerializer(role).data)

    @extend_schema(
        tags=["Roles y Permisos"],
        summary="Actualizar permisos de un rol",
        request=RolePermissionsUpdateSerializer,
        responses={
            200: RoleDetailSerializer,
            400: OpenApiResponse(ErrorResponseSerializer, description="Configuración inválida o regla crítica violada."),
            401: OpenApiResponse(ErrorResponseSerializer, description="No autenticado."),
            403: OpenApiResponse(ErrorResponseSerializer, description="Sin permisos de administrador."),
            404: OpenApiResponse(ErrorResponseSerializer, description="Rol no encontrado."),
        },
    )
    def patch(self, request, slug: str):
        role = self._get_role(slug)
        serializer = RolePermissionsUpdateSerializer(
            data=request.data, context={"role": role, "request": request}
        )
        serializer.is_valid(raise_exception=True)
        updated_role = serializer.save()
        updated_role.refresh_from_db()
        return Response(RoleDetailSerializer(updated_role).data)


# ── Usuarios internos ────────────────────────────────────────────────────────

class InternalUserCreateView(generics.GenericAPIView):
    """Crea un usuario interno con rol asignado. Solo Administrador. (CU2)"""

    permission_classes = [permissions.IsAuthenticated, CanManageRoles]
    serializer_class = InternalUserCreateSerializer

    @extend_schema(
        tags=["Roles y Permisos"],
        summary="Crear usuario interno",
        request=InternalUserCreateSerializer,
        responses={
            201: UserSerializer,
            400: OpenApiResponse(ErrorResponseSerializer, description="Datos inválidos."),
            401: OpenApiResponse(ErrorResponseSerializer, description="No autenticado."),
            403: OpenApiResponse(ErrorResponseSerializer, description="Sin permisos de administrador."),
        },
    )
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.create(serializer.validated_data)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


# ── Residentes pendientes ────────────────────────────────────────────────────

class PendingResidentsView(generics.ListAPIView):
    """Lista Residentes cuya solicitud está pendiente de aprobación. Solo Administrador. (CU2)"""

    permission_classes = [permissions.IsAuthenticated, CanManageRoles]
    serializer_class = PendingResidentSerializer
    pagination_class = None
    queryset = (
        User.objects
        .filter(role__slug="residente", is_approved=False, is_active=True)
        .select_related("person", "role")
        .order_by("date_joined")
    )

    @extend_schema(
        tags=["Roles y Permisos"],
        summary="Listar Residentes pendientes de aprobación",
        responses={
            200: PendingResidentSerializer(many=True),
            401: OpenApiResponse(ErrorResponseSerializer, description="No autenticado."),
            403: OpenApiResponse(ErrorResponseSerializer, description="Sin permisos de administrador."),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ResidentReviewView(generics.GenericAPIView):
    """Aprueba o rechaza la solicitud de un Residente pendiente. Solo Administrador. (CU2)"""

    permission_classes = [permissions.IsAuthenticated, CanManageRoles]
    serializer_class = ResidentReviewSerializer

    def _get_pending_user(self, pk: int) -> User:
        try:
            return User.objects.select_related("role").get(
                pk=pk, role__slug="residente", is_approved=False,
            )
        except User.DoesNotExist:
            raise NotFound(f"No existe un Residente pendiente con id '{pk}'.")

    @extend_schema(
        tags=["Roles y Permisos"],
        summary="Aprobar o rechazar Residente",
        request=ResidentReviewSerializer,
        responses={
            200: PendingResidentSerializer,
            400: OpenApiResponse(ErrorResponseSerializer, description="Acción inválida."),
            401: OpenApiResponse(ErrorResponseSerializer, description="No autenticado."),
            403: OpenApiResponse(ErrorResponseSerializer, description="Sin permisos de administrador."),
            404: OpenApiResponse(ErrorResponseSerializer, description="Residente pendiente no encontrado."),
        },
    )
    def patch(self, request, pk: int):
        user = self._get_pending_user(pk)
        serializer = self.get_serializer(data=request.data, context={"user": user, "request": request})
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(PendingResidentSerializer(updated).data)
