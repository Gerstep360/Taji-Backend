from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication


class CookieJWTAuthentication(JWTAuthentication):
    """Acepta Bearer para móvil y cookies HttpOnly para la aplicación web."""

    def authenticate(self, request):
        header = self.get_header(request)
        raw_token = self.get_raw_token(header) if header else None
        if raw_token is None:
            raw_token = request.COOKIES.get(settings.AUTH_COOKIE_ACCESS)
        if raw_token is None:
            return None
        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token
