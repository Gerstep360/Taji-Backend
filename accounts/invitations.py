"""
Credenciales de acceso y correo de invitación para cuentas creadas por la
administración (residentes, personal).

Este módulo concentra tres cosas que antes vivían dispersas en las vistas y que
deben comportarse igual para todo el mundo:

1. **Contraseña temporal**: las cuentas creadas por la administración (un
   residente registrado por la portería, un guardia dado de alta) no tienen una
   clave definitiva. Se les genera una clave temporal y se marca la cuenta con
   `must_change_password`, de modo que la API exige cambiarla antes de dejar
   usar el resto del sistema.
2. **Invitación por correo**: se envía un enlace de activación para que el
   interesado elija su propia contraseña, además de la clave temporal cuando
   existe. El enlace funciona aunque el correo se pierda.
3. **Diagnóstico del envío**: `deliver_invitation` no falla en silencio. Si el
   SMTP no está configurado (backend de consola) o el envío se rechaza, lo dice
   con un mensaje accionable en lugar de tragarse la excepción, que es
   exactamente lo que hacía que en el VPS pareciera que se enviaban
   invitaciones que nunca salían.

La contraseña temporal **nunca** se devuelve en la respuesta de la API ni se
registra en el log: solo se envía por correo.
"""

from __future__ import annotations

import logging
import secrets
import string
from dataclasses import dataclass
from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.tokens import token_generator

logger = logging.getLogger("taji.accounts.invitations")

# Se evita `0O1l` y los signos que se confunden al dictated o transcribir.
_TEMP_PASSWORD_LOWER = "abcdefghijkmnopqrstuvwxyz"
_TEMP_PASSWORD_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_TEMP_PASSWORD_DIGITS = "23456789"
_TEMP_PASSWORD_SYMBOLS = "!@#$%&*-_=+"
_TEMP_PASSWORD_ALPHABET = (
    _TEMP_PASSWORD_LOWER + _TEMP_PASSWORD_UPPER + _TEMP_PASSWORD_DIGITS + _TEMP_PASSWORD_SYMBOLS
)

# La clave debe superar `MinimumLengthValidator` (10) y `NumericPasswordValidator`.
TEMP_PASSWORD_LENGTH = 12


def generate_temporary_password(length: int = TEMP_PASSWORD_LENGTH) -> str:
    """
    Genera una contraseña temporal legible y con suficiente entropía.

    Garantiza al menos una minúscula, una mayúscula, un dígito y un símbolo para
    no fallar los validadores de Django, y usa `secrets` (no `random`) porque
    esta clave se comunica por correo.
    """
    length = max(length, 10)
    required = [
        secrets.choice(_TEMP_PASSWORD_LOWER),
        secrets.choice(_TEMP_PASSWORD_UPPER),
        secrets.choice(_TEMP_PASSWORD_DIGITS),
        secrets.choice(_TEMP_PASSWORD_SYMBOLS),
    ]
    remaining = [
        secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(length - len(required))
    ]
    chars = required + remaining
    # Barajar: `required` al principio haría la clave predecible.
    for index in range(len(chars) - 1, 0, -1):
        swap = secrets.randbelow(index + 1)
        chars[index], chars[swap] = chars[swap], chars[index]
    return "".join(chars)


def build_activation_url(user) -> str:
    """Enlace de un solo uso para que el interesado elija su contraseña."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = token_generator.make_token(user)
    base = getattr(settings, "PASSWORD_RESET_URL", "")
    return f"{base}?{urlencode({'uid': uid, 'token': token, 'invite': '1'})}"


@dataclass(frozen=True)
class InvitationResult:
    """Qué pasó con un envío de invitación, para poder avisar al operador."""

    sent: bool
    email: str
    detail: str
    temporary_password: str | None = None

    @property
    def ok(self) -> bool:
        return self.sent


def is_smtp_configured() -> bool:
    """
    Indica si el envío llega a una bandeja de entrada real.

    El único caso que se considera "no enviado" es el backend de consola:
    Django acepta el mensaje y lo escribe en el log, así que nada falla y nada
    sale. Eso es útil en desarrollo, pero en el VPS significa que la invitación
    nunca llega y hay que poder distinguirlo.

    `locmem`, el backend de las pruebas, sí cuenta como envío: existe y el
    destinatario recibiría el mensaje.
    """
    return "console" not in getattr(settings, "EMAIL_BACKEND", "")


def deliver_invitation(
    *,
    user,
    tenant_name: str,
    first_name: str = "",
    temporary_password: str | None = None,
) -> InvitationResult:
    """
    Envía la invitación de acceso y, si corresponde, la contraseña temporal.

    Nunca propaga la excepción de SMTP: la cuenta ya quedó creada y un correo
    rechazado no debe convertir un alta exitosa en un error 500. Lo que sí hace
    es devolver un `detail` explicativo para que la UI pueda avisar que la cuenta
    se creó pero el correo no pudo enviarse.
    """
    email = (user.email or "").strip()
    if not email:
        return InvitationResult(
            sent=False,
            email="",
            detail="La cuenta no tiene correo registrado, no se envió invitación.",
        )

    if not is_smtp_configured():
        logger.warning(
            "Invitación para %s no enviada: EMAIL_BACKEND es '%s' (los correos "
            "solo se escriben en el log). Configura el SMTP en el entorno.",
            email,
            getattr(settings, "EMAIL_BACKEND", ""),
        )
        return InvitationResult(
            sent=False,
            email=email,
            detail=(
                "El correo no pudo enviarse porque el SMTP no está configurado en el "
                "servidor. Reenvía la invitación cuando se habilite el envío."
            ),
        )

    activation_url = build_activation_url(user)
    subject = f"Bienvenido a {tenant_name} - Activa tu cuenta en Taji"

    temporary_block = ""
    if temporary_password:
        temporary_block = (
            "\n"
            "Contraseña temporal (úsala una sola vez):\n"
            f"    {temporary_password}\n"
            "\n"
            "Por seguridad, el sistema te pedirá cambiarla en tu primer ingreso. "
            "Si prefieres definirla tú mismo, ignora esta clave y usa el enlace de "
            "activación de arriba.\n"
        )

    body = (
        f"Hola {first_name or 'bienvenido'},\n\n"
        f"Has sido registrado como usuario en el condominio {tenant_name}.\n\n"
        "Para confirmar tus datos, crear tu contraseña personal e iniciar sesión en "
        "la plataforma Taji (Web y App Móvil), ingresa al siguiente enlace seguro:\n\n"
        f"{activation_url}\n"
        f"{temporary_block}\n"
        f"Tu correo registrado para inicio de sesión es: {email}\n\n"
        f"Si no reconoces este registro o tienes consultas, comunícate con la "
        f"administración de {tenant_name}.\n\n"
        "Atentamente,\n"
        f"Administración de {tenant_name} & Equipo Taji"
    )

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "Taji <no-reply@taji.app>"),
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001 - el envío nunca debe romper el alta
        logger.warning("No se pudo enviar la invitación a %s: %s", email, exc)
        return InvitationResult(
            sent=False,
            email=email,
            detail="La cuenta se creó, pero el correo no pudo enviarse. Reenvía la invitación.",
            temporary_password=temporary_password,
        )

    logger.info("Invitación de acceso enviada a %s", email)
    return InvitationResult(
        sent=True,
        email=email,
        detail=f"Invitación enviada correctamente a {email}.",
        temporary_password=temporary_password,
    )


__all__ = [
    "TEMP_PASSWORD_LENGTH",
    "InvitationResult",
    "build_activation_url",
    "deliver_invitation",
    "generate_temporary_password",
    "is_smtp_configured",
]
