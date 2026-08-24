from rest_framework.exceptions import APIException


class RegistrationUnavailable(APIException):
    status_code = 503
    default_detail = (
        "El registro no está disponible temporalmente. "
        "Verifica la configuración de roles del sistema."
    )
    default_code = "registration_unavailable"
