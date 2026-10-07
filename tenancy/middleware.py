"""Middleware de Multi-Tenancy (Sección 2, 4 y 30 de multitenant_saas_optimizado.md)."""

from django.http import JsonResponse
from tenancy.context import TenantContext
from tenancy.resolvers import TenantResolver, TenantAccessDeniedError


class TenantMiddleware:
    """
    Establece y aísla el TenantContext para cada petición HTTP.
    Protege contra accesos cruzados no autorizados y limpia el contexto
    al finalizar la respuesta.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        TenantContext.clear()

        try:
            tenant, membership, is_global = TenantResolver.resolve(request)
        except TenantAccessDeniedError as exc:
            return JsonResponse(
                {
                    "error": {
                        "code": "tenant_access_denied",
                        "message": str(exc),
                    }
                },
                status=403,
            )

        if is_global:
            TenantContext.set_global(True)
            request.tenant = None
            request.tenant_id = None
            request.tenant_membership = None
            request.is_global_tenant = True
        elif tenant:
            TenantContext.set_current_tenant(tenant, membership)
            request.tenant = tenant
            request.tenant_id = tenant.id
            request.tenant_membership = membership
            request.is_global_tenant = False
        else:
            request.tenant = None
            request.tenant_id = None
            request.tenant_membership = None
            request.is_global_tenant = False

        try:
            response = self.get_response(request)
        finally:
            TenantContext.clear()

        return response
