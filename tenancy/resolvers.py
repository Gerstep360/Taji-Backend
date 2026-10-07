"""Tenant Resolution y validación de pertenencia (Sección 3 y 4 de multitenant_saas_optimizado.md)."""

from typing import Optional, Tuple
from django.http import HttpRequest
from condominiums.models import Condominium
from tenancy.models import TenantMembership


class TenantAccessDeniedError(Exception):
    """Lanzada cuando un actor intenta acceder a un tenant al cual no pertenece."""
    pass


class TenantResolver:
    """
    Responsable de resolver de forma confiable el tenant en cada request HTTP.
    Verifica que la identidad autenticada realmente pertenezca al tenant solicitado.
    """

    @classmethod
    def resolve(
        cls, request: HttpRequest
    ) -> Tuple[Optional[Condominium], Optional[TenantMembership], bool]:
        """
        Retorna (tenant, membership, is_global).
        """
        user = getattr(request, "_force_auth_user", None) or getattr(request, "user", None)
        if not (user and user.is_authenticated):
            try:
                from accounts.authentication import CookieJWTAuthentication
                auth_result = CookieJWTAuthentication().authenticate(request)
                if auth_result:
                    user, _ = auth_result
                    request.user = user
            except Exception:
                pass
        is_authenticated = bool(user and user.is_authenticated)

        # 1. Leer identificador solicitado (Header, Query Param o Sesión)
        explicit_header_or_param = (
            request.META.get("HTTP_X_TENANT_ID")
            or request.META.get("HTTP_X_CONDOMINIUM_ID")
            or request.GET.get("tenant_id")
            or request.GET.get("condominium_id")
        )
        session_identifier = (
            request.session.get("active_tenant_id") if hasattr(request, "session") else None
        )
        requested_identifier = explicit_header_or_param or session_identifier

        # 2. Usuario autenticado (incluye superusuarios con membresías de condominio)
        if is_authenticated:
            active_memberships = TenantMembership.objects.filter(
                user=user, is_active=True
            ).select_related("condominium", "role")

            # A. El usuario solicitó explícitamente un tenant vía header o query param
            if explicit_header_or_param:
                target_tenant = cls._find_tenant(explicit_header_or_param)
                if not target_tenant:
                    raise TenantAccessDeniedError("El condominio/tenant solicitado no existe o no está activo.")

                membership = active_memberships.filter(condominium=target_tenant).first()
                if membership:
                    return target_tenant, membership, False

                # Superusuario con privilegios de plataforma cambiando explícitamente de tenant
                if user.is_superuser:
                    return target_tenant, None, False

                raise TenantAccessDeniedError(
                    "Acceso denegado: no posees membresía activa en este condominio/tenant."
                )

            # B. Hay un identificador en sesión (cookie de sesión del navegador)
            if session_identifier:
                target_tenant = cls._find_tenant(session_identifier)
                if target_tenant:
                    membership = active_memberships.filter(condominium=target_tenant).first()
                    if membership:
                        return target_tenant, membership, False
                    # Superusuario sin membresías de condominio que navega por sesión
                    if user.is_superuser and not active_memberships.exists():
                        return target_tenant, None, False
                # Si el usuario no pertenece a ese tenant de la sesión (cookie residual o ajena),
                # no se debe conmutar a ese tenant; se continúa para resolver su membresía auténtica.

            # C. Resolver por membresía predeterminada del usuario
            default_membership = active_memberships.filter(is_default=True).first() or active_memberships.first()
            if default_membership:
                if hasattr(request, "session"):
                    request.session["active_tenant_id"] = default_membership.condominium.id
                return default_membership.condominium, default_membership, False

            # D. Superusuario sin ninguna membresía de condominio opera en modo global de plataforma
            if user.is_superuser:
                return None, None, True

            # E. Usuario regular sin membresías
            return None, None, True

        # 4. Fallback retrocompatible para peticiones no autenticadas o usuarios de prueba sin membresía explícita
        if requested_identifier:
            tenant = cls._find_tenant(requested_identifier)
            if tenant:
                return tenant, None, False

        default_condo = Condominium.objects.filter(is_active=True).first()
        return default_condo, None, False

    @staticmethod
    def _find_tenant(identifier: str | int) -> Optional[Condominium]:
        """Busca el condominio/tenant por ID numérico o por slug."""
        if not identifier:
            return None
        val = str(identifier).strip()
        if val.isdigit():
            return Condominium.objects.filter(id=int(val), is_active=True).first()
        return Condominium.objects.filter(slug=val, is_active=True).first()
