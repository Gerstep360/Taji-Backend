"""Conserva clientes anteriores sin duplicar documentación OpenAPI."""
from drf_spectacular.utils import extend_schema, extend_schema_view
from django.urls import path

from .urls import urlpatterns as current


def legacy(pattern):
    original = pattern.callback.cls
    view = type(f'Legacy{original.__name__}', (original,), {})
    annotations = {method: extend_schema(exclude=True) for method in ('get', 'post') if hasattr(view, method)}
    return path(str(pattern.pattern), extend_schema_view(**annotations)(view).as_view())


urlpatterns = [legacy(pattern) for pattern in current]
