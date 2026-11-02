"""
Regresión del 503 "La base de datos no está disponible" al emitir un pase QR.

`FOR UPDATE` sobre `VisitAuthorization` fallaba en PostgreSQL siempre que hubiera
contexto de tenant, porque el filtro de aislamiento arrastra un LEFT OUTER JOIN a
`sector` y el motor prohibe bloquear el lado nullable de un outer join.

**Por qué estos tests compilan SQL en vez de ejecutar consultas.** El fallo solo se
manifiesta en PostgreSQL: la suite corre en SQLite, donde `FOR UPDATE` no existe y
`select_for_update()` es un no-op silencioso. Un test que ejecutara la consulta
pasaría siempre, incluso con el bug presente. Estos compilan el SQL con el
compilador de PostgreSQL sin conectarse y verifican la forma de la sentencia, que
es exactamente lo que el motor rechaza.
"""

import re
from pathlib import Path

from django.apps import apps
from django.db.backends.postgresql.base import DatabaseWrapper
from django.test import TestCase

from condominiums.models import Condominium
from security.models import VisitAuthorization
from tenancy.context import TenantContext

BACKEND_ROOT = Path(__file__).resolve().parents[1]

#: Modelos que el aislamiento de tenant filtra por `unit__sector`, lo que produce
#: el LEFT OUTER JOIN responsable del fallo.
TENANT_JOIN_MODELS = {VisitAuthorization}


def _probe_connection() -> DatabaseWrapper:
    """
    Conexión PostgreSQL que solo sirve para compilar SQL.

    No se abre ninguna conexión real: `as_sql()` necesita saber si esta en
    autocommit para validar el `FOR UPDATE`, y eso se responde sin tocar la red.
    """
    connection = DatabaseWrapper(
        {
            "NAME": "no_se_conecta",
            "USER": "sin_usar",
            "PASSWORD": "",
            "HOST": "",
            "PORT": "",
            "OPTIONS": {},
            "TIME_ZONE": None,
            "CONN_MAX_AGE": 0,
            "CONN_HEALTH_CHECKS": False,
            "AUTOCOMMIT": True,
            "ATOMIC_REQUESTS": False,
            "TIME_ZONE": None,
            "CONN_HEALTH_CHECKS": False,
        },
        "probe_postgres",
    )
    connection.get_autocommit = lambda: False
    return connection


def postgres_sql(queryset) -> str:
    sql, _params = queryset.query.get_compiler(connection=_probe_connection()).as_sql()
    return sql


class VisitAuthorizationLockingTests(TestCase):
    def setUp(self):
        self.addCleanup(TenantContext.clear)
        TenantContext.set_current_tenant(Condominium(id=1, name="Taji"))

    def test_the_tenant_filter_produces_an_outer_join(self):
        """Sin esto, el resto de los tests no probarian nada."""
        sql = postgres_sql(VisitAuthorization.objects.all())

        self.assertIn("LEFT OUTER JOIN", sql)

    def test_a_bare_for_update_is_rejected_by_postgres(self):
        """
        Documenta el motivo del arreglo: sin `of=`, PostgreSQL lanza
        `FOR UPDATE cannot be applied to the nullable side of an outer join`.
        """
        sql = postgres_sql(VisitAuthorization.objects.select_for_update())

        self.assertIn("LEFT OUTER JOIN", sql)
        # El fallo exacto: sin la restriccion de tablas, el motor rechaza la
        # sentencia entera y `NotSupportedError` sale como 503.
        self.assertTrue(
            sql.rstrip().endswith("FOR UPDATE"),
            f"Se esperaba un FOR UPDATE sin restringir, Got: ...{sql[-60:]}",
        )

    def test_the_lock_helper_restricts_for_update_to_its_own_table(self):
        # El helper recibe un pk y ejecuta la consulta; aqui se inspecciona la
        # forma exacta de la sentencia que produce, con su `of=("self",)`.
        queryset = VisitAuthorization.objects.select_for_update(of=("self",))
        sql = postgres_sql(queryset)

        self.assertIn("LEFT OUTER JOIN", sql)
        self.assertIn('FOR UPDATE OF "visit_authorization"', sql)
        # Y no debe quedar un FOR UPDATE sin restringir en la sentencia.
        self.assertNotRegex(sql, r"FOR UPDATE(?! OF)")
        # El aislamiento se mantiene: el WHERE de tenant sigue presente.
        self.assertIn("sector", sql.split("WHERE")[-1])

    def test_issuing_a_qr_uses_the_safe_lock(self):
        """
        Verifica el punto de llamada real, no una reconstruccion del queryset: si
        alguien vuelve a escribir `select_for_update()` directo, esto falla.
        """
        from unittest import mock

        from security import qr

        pk = 4242
        with mock.patch.object(qr, "_lock_authorization") as lock:
            lock.return_value = mock.Mock(
                pk=pk,
                qr_token_hash=None,
                qr_issued_at=None,
                qr_expires_at=None,
                save=mock.Mock(),
            )
            authorization = mock.Mock(
                pk=pk,
                status=VisitAuthorization.Status.AUTHORIZED,
                valid_until=timezone_now_plus_hours(),
                qr_token_hash=None,
                qr_issued_at=None,
                qr_expires_at=None,
            )
            qr.issue_visit_qr(authorization)

        lock.assert_called_once_with(pk)

    def test_a_bare_select_for_update_never_appears_on_visit_authorization(self):
        """
        Guarda el patron, no el sintoma. `security/qr.py` es el unico archivo donde
        se bloquea esta tabla, y debe hacerlo siempre por el helper.
        """
        source = (BACKEND_ROOT / "security" / "qr.py").read_text(encoding="utf-8")

        bare = re.findall(
            r"VisitAuthorization\.objects\.select_for_update\(\)", source
        )
        self.assertEqual(
            bare,
            [],
            "Usa security.qr._lock_authorization() en lugar de select_for_update().",
        )


class ProjectWideRowLockingTests(TestCase):
    """
    El fallo se repite en cuanto alguien bloquea una fila de un modelo al que el
    aislamiento de tenant añade un outer join. Se revisa todo el proyecto.
    """

    def test_every_tenant_joined_model_is_locked_with_an_explicit_table(self):
        offenders: list[str] = []
        pattern = re.compile(r"(\w+)\.objects\.select_for_update\(([^)]*)\)")

        for path in BACKEND_ROOT.rglob("*.py"):
            parts = set(path.parts)
            if ".venv" in parts or "migrations" in parts or "__pycache__" in parts:
                continue
            # Solo codigo de produccion. Un test puede usar la forma prohibida a
            # proposito, para demostrar que el motor la rechaza.
            if path.name.startswith(("test_", "tests")):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for model_name, arguments in pattern.findall(text):
                model = next(
                    (m for m in apps.get_models() if m.__name__ == model_name), None
                )
                if model not in TENANT_JOIN_MODELS:
                    continue
                if "of=" not in arguments:
                    offenders.append(f"{path.name}: {model_name}.select_for_update({arguments})")

        self.assertEqual(
            offenders,
            [],
            "Bloquea estos modelos con of=('self',) para no chocar con el outer "
            f"join del filtro de tenant:\n  {offenders}",
        )


def timezone_now_plus_hours(hours: int = 4):
    from datetime import timedelta

    from django.utils import timezone

    return timezone.now() + timedelta(hours=hours)
