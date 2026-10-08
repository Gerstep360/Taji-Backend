from rest_framework.routers import SimpleRouter

from security.views import AccessEventViewSet

# Sin `app_name`. Este módulo se incluye dos veces, desde los prefijos
# `api/v1/paquete2/` y `api/v1/security/`, y ambos alias los necesitan porque el
# movil y la web llaman a rutas bajo cada prefijo. Declarar el namespace aqui lo
# registraba dos veces y Django lo reportaba como `urls.W005` ("URL namespace
# 'security' isn't unique"). En la practica no se revierte nada con ese
# namespace, asi que quitarlo mantiene las mismas rutas y elimina el aviso.

router = SimpleRouter()
router.register("access-events", AccessEventViewSet, basename="access-event")

urlpatterns = router.urls
