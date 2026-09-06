from django.conf import settings


def set_auth_cookies(response, access, refresh=None):
    common = {
        "httponly": True,
        "secure": settings.AUTH_COOKIE_SECURE,
        "samesite": settings.AUTH_COOKIE_SAMESITE,
        "domain": settings.AUTH_COOKIE_DOMAIN,
        "path": "/",
    }
    response.set_cookie(
        settings.AUTH_COOKIE_ACCESS,
        access,
        max_age=int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
        **common,
    )
    if refresh:
        response.set_cookie(
            settings.AUTH_COOKIE_REFRESH,
            refresh,
            max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
            **common,
        )
    return response


def clear_auth_cookies(response):
    common = {
        "samesite": settings.AUTH_COOKIE_SAMESITE,
        "domain": settings.AUTH_COOKIE_DOMAIN,
        "path": "/",
    }
    response.delete_cookie(settings.AUTH_COOKIE_ACCESS, **common)
    response.delete_cookie(settings.AUTH_COOKIE_REFRESH, **common)
    return response
