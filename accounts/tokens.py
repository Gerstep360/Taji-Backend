"""
Generador de tokens de un solo uso para activación de cuenta y restablecimiento
de contraseña.

Por qué no se usa `default_token_generator` de Django
------------------------------------------------------

El generador por hashea `pk + password + last_login + timestamp + email`.
Incluir `last_login` sirve para invalidar el enlace en cuanto el usuario inicia
sesión, pero aquí rompe el flujo de alta:

1. La administración registra a un residente y le manda **contraseña temporal
   y enlace de activación** en el mismo correo.
2. El residente prueba primero la contraseña temporal e inicia sesión.
3. Eso actualiza `last_login`.
4. Al pulsar el enlace de activación, el token deja de validar y la pantalla
   responde "El enlace no es válido o ya expiró".

El síntoma parecería intermitente porque depende solo del orden en que cada
persona intentara las dos vías de entrada.

Qué se conserva
---------------

Se mantiene `user.password` dentro del hash, que es lo que de verdad importa:
al usar el enlace se llama a `set_password`, la sal cambia aunque se elija la
misma contraseña, y el token queda invalidado de inmediato. El enlace sigue
siendo de un solo uso.

También se heredan sin tocar la expiración (`PASSWORD_RESET_TIMEOUT`), la
comparación en tiempo constante y la rotación de `SECRET_KEY` vía
`SECRET_KEY_FALLBACKS`.

La única diferencia con el comportamiento estándar es que un inicio de sesión
no invalida el enlace. Es un intercambio deliberado: sin `last_login`, el
enlace sobrevive a un ingreso legítimo y sigue muriendo por lo único que
importa, que es el cambio de contraseña.
"""

from django.contrib.auth.tokens import PasswordResetTokenGenerator


class TajiTokenGenerator(PasswordResetTokenGenerator):
    """
    Identico al de Django salvo que omite `last_login` del hash.

    Se hereda todo lo demas (formato del token, expiracion, comparacion en
    tiempo constante, rotacion de secreto); solo se redefine el valor que se
    hashea, que es donde estaba el problema.
    """

    def _make_hash_value(self, user, timestamp):
        email = getattr(user, user.get_email_field_name(), "") or ""
        # Sin `user.last_login`: iniciar sesion no debe invalidar el enlace.
        # `user.password` sigue presente y es lo que invalida el token al uso.
        return f"{user.pk}{user.password}{timestamp}{email}"


#: Generador unico compartido por el alta de cuenta y el restablecimiento.
token_generator = TajiTokenGenerator()

__all__ = ["TajiTokenGenerator", "token_generator"]
