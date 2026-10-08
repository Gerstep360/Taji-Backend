"""
Comprobaciones estaticas sobre `deploy/vps.sh`.

El despliegue real se prueba en `vps_smoke.sh` sobre Ubuntu con PostgreSQL, pero
ciertos fallos merecen un testigo mas rapido y mas explicito. Los dos que motivan
este archivo(compilar en la maquina del operador, no en el servidor) solo se
manifestan en el VPS y por eso pasaron inadvertidos:

1. `fail()` usaba `return 1`. Dentro de una funcion eso sale de `fail`, no de la
   funcion que la invoco, de modo que los guards `[[ ... ]] || fail "..."` no
   detenian nada: el despliegue anunciaba "Deteniendo el despliegue" y actuano
   igual, incluida la migracion.
2. El respaldo previo a migrar invocaba `deploy/backup_database.py` con ruta
   relativa desde el directorio de trabajo del menu (el clon de git del
   operador, propiedad de root). Bajo `runuser -u taji` eso es "Permission
   denied" y el respaldo no se creaba.

Son aserciones sobre el codigo fuente y no sobre la ejecucion: el objetivo es
que un cambio futuro que reintroduzca cualquiera de los dos formas falle aqui, en
segundos, en lugar de en el VPS.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

VPS_SH = Path(__file__).resolve().parents[1] / "vps.sh"


def _function_body(source: str, name: str) -> str:
    """Devuelve el cuerpo de una funcion bash, desde su llave hasta su cierre."""
    match = re.search(rf"^{re.escape(name)}\(\)\s*\{{", source, re.MULTILINE)
    if match is None:
        raise AssertionError(f"No se encontro la funcion {name}() en vps.sh")
    start = match.end() - 1
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"La funcion {name}() no cierra en vps.sh")


class FailAbortsTheScriptTests(SimpleTestCase):
    def setUp(self):
        self.source = VPS_SH.read_text(encoding="utf-8")

    def test_fail_ends_the_script_and_not_only_the_function(self):
        body = _function_body(self.source, "fail")

        self.assertIn("exit 1", body)
        # `return 1` es justamente lo que hacia que el despliegue continuara.
        self.assertNotRegex(body, r"^\s*return 1")

    def test_the_pre_migration_guard_really_stops_before_migrating(self):
        """`manage migrate` no puede ejecutarse despues del guard de respaldo."""
        marker = self.source.index('Respaldando PostgreSQL antes de migrar')
        migrate = self.source.index("manage migrate --noinput", marker)

        between = self.source[marker:migrate]
        self.assertIn("fail ", between)
        # El texto del aviso promete una parada; el codigo debe cumplirlo.
        self.assertIn("Deteniendo el despliegue", between)


class PreMigrationBackupTests(SimpleTestCase):
    def setUp(self):
        self.source = VPS_SH.read_text(encoding="utf-8")

    def test_first_install_can_backup_without_an_existing_current_release(self):
        body = _function_body(self.source, "run_backup_cli")
        self.assertIn("${TAJI_BACKUP_RELEASE:-$ROOT/current}", body)
        self.assertIn('cd "$backup_release"', body)
        self.assertIn('"$backup_release/.venv/bin/python"', body)
        self.assertIn('TAJI_BACKUP_RELEASE="$RELEASE" run_backup_cli create --prefix premigrate', self.source)

    def test_failed_backup_prints_diagnostics_and_aborts_before_migrations(self):
        marker = self.source.index('if ! animated_progress_bar "$backup_pid"')
        migrate = self.source.index("manage migrate --noinput", marker)
        block = self.source[marker:migrate]
        self.assertIn("cat /tmp/taji-premigrate-backup.log", block)
        self.assertIn('fail "No se pudo respaldar', block)
        self.assertIn('wait "$pid" || exit_code=$?', _function_body(self.source, "animated_progress_bar"))

    def test_the_pre_migration_backup_goes_through_run_backup_cli(self):
        """
        `run_backup_cli` es la unica via soportada: hace `cd` a /opt/taji/current
        y ejecuta como `taji`, que es lo que hace falta para leer el codigo del
        release y escribir en BACKUP_DIR.
        """
        marker = self.source.index('Respaldando PostgreSQL antes de migrar')
        backup_block = self.source[max(0, marker - 900) : marker]

        self.assertIn("run_backup_cli create --prefix premigrate", backup_block)
        # Invocar el script a mano es justamente lo que rompia. Se ignoran los
        # comentarios: el bloque documenta el motivo del error.
        executable = [
            line for line in backup_block.splitlines() if not line.lstrip().startswith("#")
        ]
        self.assertNotIn(
            "backup_database.py",
            "\n".join(executable),
            "El respaldo previo a migrar debe delegar en run_backup_cli.",
        )

    def test_only_a_dump_from_this_attempt_counts_as_a_backup(self):
        """
        Un `premigrate-*.dump` de un despliegue anterior no protege esta
        migracion. Sin el filtro por fecha, un respaldo fallido se daba por
        bueno y la migracion avanzaba sin copia.
        """
        marker = self.source.index('Respaldando PostgreSQL antes de migrar')
        after = self.source[marker : marker + 1200]

        self.assertIn("-newer", after)
        self.assertNotIn("ls -1t", after)
        # El marcador se crea antes de lanzar el respaldo: de lo contrario
        # `-newer` compararia contra un archivo posterior al dump.
        self.assertLess(
            self.source.index("mktemp /tmp/taji-premigrate-marker"),
            self.source.index("run_backup_cli create --prefix premigrate"),
        )

    def test_every_backup_invocation_runs_as_the_taji_user(self):
        """Ninguna llamada al CLI de respaldos puede ejecutarse como root."""
        for line_number, line in enumerate(self.source.splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            if "backup_database.py" not in line:
                continue
            self.assertNotIn(
                "runuser",
                line,
                f"vps.sh:{line_number} invoca el CLI de respaldos sin runuser: {line.strip()}",
            )


class InstallerOnlyVariablesTests(SimpleTestCase):
    """
    `DOMAIN`, `EMAIL` y `FRONTEND` los pregunta la instalacion (opcion [1]) y no
    existen en el resto del menu. El script corre con `set -u`, asi que leerlos
    desde otra opcion no produce un valor vacio: mata el proceso.
    """

    def setUp(self):
        self.source = VPS_SH.read_text(encoding="utf-8")

    def test_the_update_deploy_does_not_read_the_installer_domain(self):
        """Este fue un fallo real: el despliegue moria tras imprimir el exito."""
        body = _function_body(self.source, "do_deploy_backend")

        self.assertNotIn("$DOMAIN", body)
        self.assertNotIn("${DOMAIN", body)
        self.assertIn("resolve_domain", body)

    def test_the_domain_is_resolved_from_the_server_env_file(self):
        """No puede depender de una variable que solo existe al instalar."""
        resolver = _function_body(self.source, "resolve_domain")

        self.assertIn("ALLOWED_HOSTS", resolver)
        # `${first:-localhost}` evita que un env incompleto reintroduzca el fallo.
        self.assertIn(":-localhost", resolver)


class DatabaseConnectionTests(SimpleTestCase):
    def test_connection_health_checks_are_enabled_in_production(self):
        """
        Sin `CONN_HEALTH_CHECKS`, Gunicorn reutiliza conexiones que PostgreSQL ya
        cerro (por ejemplo tras el reinicio que hace el propio despliegue) y la
        peticion siguiente falla con un 503 "La base de datos no esta disponible".
        """
        production = (
            Path(__file__).resolve().parents[2] / "config" / "settings_production.py"
        ).read_text(encoding="utf-8")

        self.assertIn('DATABASES["default"]["CONN_HEALTH_CHECKS"] = True', production)

    def test_the_security_url_namespace_is_not_declared_twice(self):
        """
        `security/urls.py` se incluye bajo `api/v1/paquete2/` y `api/v1/security/`.
        Declarar `app_name` ahi registraba el namespace dos veces y Django lo
        reportaba como `urls.W005` en cada `manage.py migrate` del servidor.
        """
        from django.urls import get_resolver

        namespaces = [
            namespace
            for namespace in get_resolver().namespace_dict
            if namespace == "security"
        ]
        self.assertEqual(namespaces, [], "El namespace 'security' sigue duplicado.")

    def test_both_security_prefixes_still_resolve(self):
        """Quitar el namespace no puede cambiar las rutas que usan movil y web."""
        from django.urls import resolve

        for path in (
            "/api/v1/security/access-events/",
            "/api/v1/security/visit-qr/scans/",
            "/api/v1/security/cu12/visits/",
            "/api/v1/security/cu17/biometrics/",
            "/api/v1/security/turnos/actual/",
            "/api/v1/paquete2/access-events/",
            "/api/v1/visit-qr/1/generate/",
            "/api/v1/security/visit-qr/validate/",
        ):
            with self.subTest(path=path):
                self.assertIsNotNone(resolve(path).func)
