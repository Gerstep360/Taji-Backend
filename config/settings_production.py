"""Production settings for the Nginx + Gunicorn VPS deployment."""
from django.core.exceptions import ImproperlyConfigured
from .settings import *  # noqa: F403

DEBUG = False
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")
if len(SECRET_KEY) < 50 or SECRET_KEY.startswith("django-insecure-"):
    raise ImproperlyConfigured("Configure a random DJANGO_SECRET_KEY of at least 50 characters.")
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Production requires explicit ALLOWED_HOSTS.")
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = 60
IS_SECURE = env.bool("COOKIE_SECURE", default=False)
AUTH_COOKIE_SECURE = SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = IS_SECURE
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)
if IS_SECURE:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
# This installer controls one hostname, not its descendant domains or the browser
# preload list. Keep all other deployment checks enabled and fatal in vps.sh.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]
STATIC_ROOT = env("STATIC_ROOT", default=str(BASE_DIR / "staticfiles"))
MEDIA_ROOT = env("MEDIA_ROOT", default="/var/lib/taji/media")
MEDIA_URL = "/media/"
# Shared between Gunicorn workers: Django's login throttle otherwise uses per-worker memory.
CACHES = {"default": {
    "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
    "LOCATION": env("CACHE_DIR", default="/var/cache/taji"),
}}
