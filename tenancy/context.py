"""Tenant Context — Sección 2 y 32 de multitenant_saas_optimizado.md."""

from contextlib import contextmanager
import contextvars
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from condominiums.models import Condominium
    from tenancy.models import TenantMembership

_current_tenant: contextvars.ContextVar[Optional["Condominium"]] = contextvars.ContextVar(
    "current_tenant", default=None
)
_current_membership: contextvars.ContextVar[Optional["TenantMembership"]] = contextvars.ContextVar(
    "current_membership", default=None
)
_is_global_mode: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "is_global_mode", default=False
)


class TenantContext:
    """
    Abstracción central del Tenant Context.
    Mantiene el tenant activo, la membresía y el rol durante el ciclo de vida
    del request HTTP o de una tarea asíncrona.
    """

    @classmethod
    def get_current_tenant(cls) -> Optional["Condominium"]:
        """Retorna el objeto Condominium (Tenant) actualmente activo."""
        return _current_tenant.get()

    @classmethod
    def get_current_tenant_id(cls) -> Optional[int]:
        """Retorna el ID entero del tenant activo o None si no hay uno fijado."""
        tenant = _current_tenant.get()
        return tenant.id if tenant else None

    @classmethod
    def get_current_membership(cls) -> Optional["TenantMembership"]:
        """Retorna la membresía del usuario actual en el tenant activo."""
        return _current_membership.get()

    @classmethod
    def is_global(cls) -> bool:
        """
        True cuando la operación actual se ejecuta como plataforma global / superusuario
        sin aplicar filtros restrictivos de aislamiento de tenant.
        """
        return _is_global_mode.get()

    @classmethod
    def set_current_tenant(
        cls,
        tenant: Optional["Condominium"],
        membership: Optional["TenantMembership"] = None,
    ):
        """Establece el tenant activo y opcionalmente la membresía del usuario."""
        _current_tenant.set(tenant)
        _current_membership.set(membership)
        _is_global_mode.set(False)

    @classmethod
    def set_global(cls, value: bool = True):
        """Activa o desactiva el modo de administración global de plataforma."""
        _is_global_mode.set(value)
        if value:
            _current_tenant.set(None)
            _current_membership.set(None)

    @classmethod
    def clear(cls):
        """Limpia el contexto al finalizar la operación."""
        _current_tenant.set(None)
        _current_membership.set(None)
        _is_global_mode.set(False)

    @classmethod
    @contextmanager
    def as_global(cls):
        """
        Context manager para ejecutar operaciones de plataforma global
        (ej. migraciones, reportes consolidados o superusuario global).
        """
        old_tenant = _current_tenant.get()
        old_membership = _current_membership.get()
        old_global = _is_global_mode.get()
        cls.set_global(True)
        try:
            yield
        finally:
            _current_tenant.set(old_tenant)
            _current_membership.set(old_membership)
            _is_global_mode.set(old_global)

    @classmethod
    @contextmanager
    def for_tenant(
        cls,
        tenant: "Condominium",
        membership: Optional["TenantMembership"] = None,
    ):
        """
        Context manager para ejecutar una tarea en el contexto de un tenant específico.
        """
        old_tenant = _current_tenant.get()
        old_membership = _current_membership.get()
        old_global = _is_global_mode.get()
        cls.set_current_tenant(tenant, membership)
        try:
            yield tenant
        finally:
            _current_tenant.set(old_tenant)
            _current_membership.set(old_membership)
            _is_global_mode.set(old_global)
