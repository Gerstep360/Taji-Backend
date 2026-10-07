from rest_framework.routers import DefaultRouter
from paquetes.paquete2_seguridad_accesos.cu17_verificacion_facial.views import (
    BiometricReferenceViewSet,
    FaceVerificationViewSet,
)

router = DefaultRouter()
router.register(r"biometrics", BiometricReferenceViewSet, basename="biometrics")
router.register(r"face-verification", FaceVerificationViewSet, basename="face-verification")

urlpatterns = router.urls
