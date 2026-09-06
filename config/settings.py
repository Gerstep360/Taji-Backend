from datetime import timedelta
from pathlib import Path

import environ


BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(DEBUG=(bool, True), COOKIE_SECURE=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="django-insecure-local-only-change-this-before-production")
DEBUG = env.bool("DEBUG", default=True)
_DEV_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0", "*"]
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=_DEV_HOSTS if DEBUG else [])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "accounts.apps.AccountsConfig",
    "condominiums.apps.CondominiumsConfig",
    "auditlog.apps.AuditlogConfig",
    "security.apps.SecurityConfig",
    "incidents.apps.IncidentsConfig",
    "maintenance.apps.MaintenanceConfig",
    "community.apps.CommunityConfig",
    "notifications.apps.NotificationsConfig",
    "paquetes.paquete1_usuarios_condominio.cu02_roles_permisos.apps.Cu02RolesPermisosConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]
WSGI_APPLICATION = "config.wsgi.application"

# Configuración predeterminada a PostgreSQL local 'taji'
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgresql://postgres:root@localhost:5432/taji",
    )
}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-bo"
TIME_ZONE = "America/La_Paz"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

FRONTEND_URLS = env.list(
    "FRONTEND_URLS",
    default=["http://localhost:4200", "http://127.0.0.1:4200"],
)
CORS_ALLOWED_ORIGINS = FRONTEND_URLS
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGIN_REGEXES = (
    [r"^http://(?:localhost|127\.0\.0\.1|(?:\d{1,3}\.){3}\d{1,3}):4200$"]
    if DEBUG
    else []
)
CSRF_TRUSTED_ORIGINS = FRONTEND_URLS

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["accounts.authentication.CookieJWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_PAGINATION_CLASS": "config.api.TajiPageNumberPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "config.api.taji_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "login": "10/min",
        "register": "5/hour",
        "password_reset": "5/hour",
        "token_refresh": "30/min",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "SIGNING_KEY": env("JWT_SIGNING_KEY", default=SECRET_KEY),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

AUTH_COOKIE_ACCESS = "taji_access"
AUTH_COOKIE_REFRESH = "taji_refresh"
AUTH_COOKIE_SECURE = env.bool("COOKIE_SECURE", default=not DEBUG)
AUTH_COOKIE_SAMESITE = env("COOKIE_SAMESITE", default="Lax")
AUTH_COOKIE_DOMAIN = env("COOKIE_DOMAIN", default=None)

EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Taji <no-reply@taji.app>")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
PASSWORD_RESET_URL = env("PASSWORD_RESET_URL", default="http://localhost:4200/restablecer-contrasena")

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = AUTH_COOKIE_SECURE
CSRF_COOKIE_SECURE = AUTH_COOKIE_SECURE
X_FRAME_OPTIONS = "DENY"

SPECTACULAR_SETTINGS = {
    "TITLE": "Taji API",
    "DESCRIPTION": (
        "API REST de Taji para autenticación, RBAC y los módulos del condominio. "
        "La aplicación móvil usa Bearer JWT y la web cookies HttpOnly."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "ENUM_NAME_OVERRIDES": {
        "ResidentStatusEnum": "condominiums.models.Resident.Status",
        "StaffStatusEnum": "condominiums.models.Staff.Status",
        "UnitStatusEnum": "condominiums.models.Unit.Status",
    },
    "TAGS": [
        {"name": "Autenticación", "description": "CU01: Registro y ciclo de sesión."},
        {"name": "Roles y Permisos", "description": "CU02: Gestión de roles, permisos RBAC y aprobación de residentes."},
        {"name": "Residentes", "description": "CU05: CRUD de residentes y copropietarios."},
        {"name": "Personal", "description": "CU07: CRUD y clasificación del personal del condominio."},
        {"name": "Sistema", "description": "Salud y metadatos del servicio."},
    ],
}


