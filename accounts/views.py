from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils.encoding import force_bytes
from django.utils import timezone
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, serializers, status
from rest_framework.response import Response
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from .cookies import clear_auth_cookies, set_auth_cookies
from .models import LoginAttempt, User
from .serializers import (
    ForgotPasswordSerializer,
    LoginSerializer,
    LogoutSerializer,
    RefreshSerializer,
    RegisterSerializer,
    ResetPasswordSerializer,
    UserSerializer,
)


GENERIC_LOGIN_ERROR = "Correo o contraseña incorrectos."
GENERIC_RESET_MESSAGE = (
    "Si existe una cuenta con ese correo, recibirás instrucciones para restablecer tu contraseña."
)
LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_MINUTES = 30


def token_pair_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


class RegisterView(generics.GenericAPIView):
    serializer_class = RegisterSerializer
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_scope = "register"

    @extend_schema(request=RegisterSerializer, responses={201: UserSerializer})
    @transaction.atomic
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {"message": "Tu cuenta fue creada. Ya puedes iniciar sesión.", "user": UserSerializer(user).data},
            status=status.HTTP_201_CREATED,
        )


class LoginView(generics.GenericAPIView):
    serializer_class = LoginSerializer
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_scope = "login"

    @extend_schema(request=LoginSerializer)
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()
        cutoff = timezone.now() - timezone.timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
        last_success = (
            LoginAttempt.objects.filter(email=email, was_successful=True)
            .order_by("-created_at")
            .first()
        )
        failures = LoginAttempt.objects.filter(
            email=email,
            was_successful=False,
            created_at__gte=cutoff,
        )
        if last_success:
            failures = failures.filter(created_at__gt=last_success.created_at)
        if failures.count() >= LOGIN_MAX_FAILURES:
            return Response(
                {"detail": "Has superado los 5 intentos. Espera 30 minutos antes de volver a intentar."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(LOGIN_LOCKOUT_MINUTES * 60)},
            )

        user = authenticate(
            request=request,
            email=email,
            password=serializer.validated_data["password"],
        )
        if user is None or not user.is_active:
            failures_count = failures.count() + 1
            known_user = User.objects.filter(email=email).first()
            LoginAttempt.objects.create(
                user=user if user and user.is_active else known_user,
                email=email,
                ip_address=request.META.get("REMOTE_ADDR"),
            )
            if failures_count >= LOGIN_MAX_FAILURES:
                return Response(
                    {"detail": "Has superado los 5 intentos. Espera 30 minutos antes de volver a intentar."},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                    headers={"Retry-After": str(LOGIN_LOCKOUT_MINUTES * 60)},
                )
            if known_user is None:
                detail = "Usuario no encontrado o no registrado. Regístrate para continuar."
            elif known_user.is_active:
                remaining = LOGIN_MAX_FAILURES - failures_count
                detail = f"Intento fallido. Te quedan {remaining} intentos."
            else:
                detail = "Usuario no encontrado o no registrado. Regístrate para continuar."
            return Response({"detail": detail}, status=status.HTTP_401_UNAUTHORIZED)

        LoginAttempt.objects.create(
            user=user,
            email=email,
            ip_address=request.META.get("REMOTE_ADDR"),
            was_successful=True,
        )
        tokens = token_pair_for_user(user)
        payload = {"message": "Sesión iniciada.", "user": UserSerializer(user).data}
        if serializer.validated_data["client"] == "mobile":
            payload["tokens"] = tokens
            return Response(payload)
        return set_auth_cookies(Response(payload), tokens["access"], tokens["refresh"])


class RefreshView(generics.GenericAPIView):
    serializer_class = RefreshSerializer
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_scope = "token_refresh"

    @extend_schema(request=RefreshSerializer)
    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        client = serializer.validated_data["client"]
        raw_refresh = serializer.validated_data.get("refresh") or request.COOKIES.get(
            settings.AUTH_COOKIE_REFRESH
        )
        if not raw_refresh:
            return Response({"detail": "La sesión no se puede renovar."}, status=status.HTTP_401_UNAUTHORIZED)

        refresh_serializer = TokenRefreshSerializer(data={"refresh": raw_refresh})
        try:
            refresh_serializer.is_valid(raise_exception=True)
        except Exception:
            return clear_auth_cookies(
                Response({"detail": "La sesión expiró. Inicia sesión nuevamente."}, status=status.HTTP_401_UNAUTHORIZED)
            )

        tokens = refresh_serializer.validated_data
        if client == "mobile":
            return Response({"tokens": tokens})
        return set_auth_cookies(Response({"message": "Sesión renovada."}), tokens["access"], tokens.get("refresh"))


class LogoutView(generics.GenericAPIView):
    serializer_class = LogoutSerializer
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        raw_refresh = request.data.get("refresh") or request.COOKIES.get(settings.AUTH_COOKIE_REFRESH)
        if raw_refresh:
            try:
                RefreshToken(raw_refresh).blacklist()
            except TokenError:
                pass
        return clear_auth_cookies(Response(status=status.HTTP_204_NO_CONTENT))


class MeView(generics.GenericAPIView):
    serializer_class = UserSerializer
    def get(self, request):
        return Response({"user": UserSerializer(request.user).data})


class ForgotPasswordView(generics.GenericAPIView):
    serializer_class = ForgotPasswordSerializer
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_scope = "password_reset"

    @extend_schema(request=ForgotPasswordSerializer)
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()
        user = User.objects.filter(email__iexact=email, is_active=True).first()

        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_url = f"{settings.PASSWORD_RESET_URL}?{urlencode({'uid': uid, 'token': token})}"
            send_mail(
                subject="Restablece tu contraseña de Taji",
                message=(
                    f"Hola {user.first_name},\n\n"
                    f"Usa este enlace para crear una nueva contraseña:\n{reset_url}\n\n"
                    "Si no solicitaste este cambio, ignora este mensaje."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )

        return Response({"message": GENERIC_RESET_MESSAGE})


class ResetPasswordView(generics.GenericAPIView):
    serializer_class = ResetPasswordSerializer
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_scope = "password_reset"

    @extend_schema(request=ResetPasswordSerializer)
    @transaction.atomic
    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            user_id = urlsafe_base64_decode(data["uid"]).decode()
            user = User.objects.get(pk=user_id, is_active=True)
        except (ValueError, TypeError, OverflowError, User.DoesNotExist):
            user = None

        if user is None or not default_token_generator.check_token(user, data["token"]):
            return Response(
                {"detail": "El enlace no es válido o ya expiró."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            password_validation.validate_password(data["password"], user)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"password": error.messages}) from error

        user.set_password(data["password"])
        user.save(update_fields=["password", "updated_at"])

        for outstanding in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=outstanding)

        return Response({"message": "Tu contraseña fue actualizada. Ya puedes iniciar sesión."})


