"""
Pruebas de la logica de respaldos que no necesita PostgreSQL.

Se cubren las tres garantias que hacen confiable un respaldo:

1. **Escritura atomica**: un volcado fallido nunca queda con nombre de `.dump`.
2. **Verificacion**: un archivo vacio o ilegible se rechaza.
3. **Retencion**: se conservan los ultimos dias y un minimo de copias, para que
   el disco no crezca sin control pero nunca quede sin respaldo reciente.

El volcado real (`pg_dump`) no se prueba aqui: requiere un servidor PostgreSQL y
lo cubre `deploy/tests/vps_smoke.sh` en CI.
"""

import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from deploy import backup_database as bd


class FakeDatabase(dict):
    """
    Configuración de base de datos suficiente para el entorno de pg.

    Es un `dict` porque en Django `settings.DATABASES["default"]` lo es, y el
    script usa tanto `database["NAME"]` como `database.get("HOST")`.
    """

    def __init__(self):
        super().__init__(
            ENGINE="django.db.backends.postgresql",
            NAME="taji",
            USER="taji",
            PASSWORD="secreto",
            HOST="127.0.0.1",
            PORT=5432,
        )


class BackupFileTests(SimpleTestCase):
    """Escritura atomica y verificacion."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.output = Path(self._tmp.name)

    def _fake_pg(self, dump_body: bytes = b"PGDMP\x00\x01datos", dump_fail: bool = False):
        """Sustituye `pg_dump` y `pg_restore` por dobles deterministas."""
        def fake_dump(argv, env=None, stdout=None, check=True):
            if dump_fail:
                raise bd.subprocess.CalledProcessError(1, argv)
            stdout.write(dump_body)
            return None

        def fake_restore(argv, stdout=None, check=True):
            # Simula que `pg_restore --list` puede leer el indice.
            path = Path(argv[-1])
            if not path.is_file():
                raise bd.subprocess.CalledProcessError(1, argv)
            return None

        patches = [
            mock.patch.object(bd, "_database_from_settings", return_value=FakeDatabase()),
            mock.patch.object(bd, "_executable", side_effect=lambda name, _bin: f"/usr/bin/{name}"),
            mock.patch.object(bd.subprocess, "run", side_effect=fake_dump),
        ]
        # El `pg_restore --list` usa el mismo `subprocess.run`, asi que se
        # enruta por nombre de comando.
        real_run = bd.subprocess.run

        def dispatcher(argv, *args, **kwargs):
            if argv and "pg_restore" in argv[0]:
                return fake_restore(argv, *args, **kwargs)
            return fake_dump(argv, *args, **kwargs)

        patches[2] = mock.patch.object(bd.subprocess, "run", side_effect=dispatcher)
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_create_writes_a_verified_dump(self):
        self._fake_pg()

        path = bd.create_backup(output_dir=self.output, prefix="taji")

        self.assertTrue(path.is_file())
        self.assertEqual(path.suffix, ".dump")
        self.assertTrue(path.name.startswith("taji-"))

    def test_a_failed_dump_leaves_no_file_that_looks_valid(self):
        """El `.partial` se borra: nunca hay un `.dump` incompleto."""
        self._fake_pg(dump_fail=True)

        with self.assertRaises(bd.BackupError):
            bd.create_backup(output_dir=self.output)

        self.assertEqual(list(self.output.glob("*.dump")), [])
        self.assertEqual(list(self.output.glob("*.partial")), [])

    def test_an_empty_dump_is_rejected(self):
        self._fake_pg(dump_body=b"")

        with self.assertRaises(bd.BackupError):
            bd.create_backup(output_dir=self.output)

        self.assertEqual(list(self.output.glob("*.dump")), [])

    def test_two_backups_do_not_collide(self):
        """El sello lleva microsegundos, asi que dos respaldosfollowed no se pisan."""
        self._fake_pg()
        first = bd.create_backup(output_dir=self.output)
        second = bd.create_backup(output_dir=self.output)
        self.assertNotEqual(first.name, second.name)

    def test_verify_rejects_a_missing_file(self):
        with self.assertRaises(bd.BackupError):
            bd.verify_backup(self.output / "no-existe.dump")

    def test_verify_rejects_an_empty_file(self):
        empty = self.output / "vacio.dump"
        empty.touch()
        self._fake_pg()

        with self.assertRaises(bd.BackupError):
            bd.verify_backup(empty)

    def test_verify_accepts_a_readable_file(self):
        good = self.output / "bueno.dump"
        good.write_bytes(b"PGDMP\x00\x01contenido")
        self._fake_pg()

        info = bd.verify_backup(good)

        self.assertEqual(info.path, good)
        self.assertGreater(info.size_bytes, 0)

    def test_verify_rejects_a_corrupted_file(self):
        corrupted = self.output / "roto.dump"
        corrupted.write_bytes(b"basura")

        def failing_restore(argv, *args, **kwargs):
            raise bd.subprocess.CalledProcessError(1, argv)

        with mock.patch.object(bd, "_executable", return_value="/usr/bin/pg_restore"), \
             mock.patch.object(bd.subprocess, "run", side_effect=failing_restore):
            with self.assertRaises(bd.BackupError) as ctx:
                bd.verify_backup(corrupted)

        self.assertIn("corrupto", str(ctx.exception))


class PgInvocationTests(SimpleTestCase):
    """
    Verifica la invocacion exacta de `pg_dump` y `pg_restore`.

    No hace falta un servidor PostgreSQL para esto, y es justo el punto: si el
    comando o las variables de conexion se alteran, el respaldo dejaria de
    funcionar en produccion sin que ninguna prueba de filesystem lo note.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.output = Path(self._tmp.name)
        self.calls: list[tuple] = []

    def _record(self):
        def runner(argv, env=None, stdout=None, check=True):
            self.calls.append((argv, env, stdout))
            # `stdout` es el archivo abierto para el volcado; en la verificacion
            # es `DEVNULL`, que es un entero y no admite `write`.
            if hasattr(stdout, "write"):
                stdout.write(b"PGDMP\x00\x01contenido")
            return None

        patches = [
            mock.patch.object(bd, "_database_from_settings", return_value=FakeDatabase()),
            # La ruta incluye el nombre para poder distinguir `pg_dump` de
            # `pg_restore` al inspeccionar argv.
            mock.patch.object(
                bd, "_executable", side_effect=lambda name, _bin: f"/usr/bin/{name}"
            ),
            mock.patch.object(bd.subprocess, "run", side_effect=runner),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_pg_dump_uses_custom_format_and_no_password_prompt(self):
        """
        `--format=custom` es lo que produce un .dump comprimido y que despues
        `pg_restore` puede leer. `--no-password` evita que el proceso se quede
        esperando una clave por consola si algo falla.
        """
        self._record()

        bd.create_backup(output_dir=self.output)

        dump_argv = self.calls[0][0]
        self.assertIn("pg_dump", dump_argv[0])
        self.assertIn("--format=custom", dump_argv)
        self.assertIn("--no-password", dump_argv)

    def test_connection_goes_through_the_environment_not_the_command_line(self):
        """La contraseña no debe aparecer en argv: queda visible en `ps`."""
        self._record()

        bd.create_backup(output_dir=self.output)

        _argv, env, _stdout = self.calls[0]
        self.assertEqual(env["PGHOST"], "127.0.0.1")
        self.assertEqual(env["PGPORT"], "5432")
        self.assertEqual(env["PGUSER"], "taji")
        self.assertEqual(env["PGPASSWORD"], "secreto")
        self.assertEqual(env["PGDATABASE"], "taji")

        for argv, _env, _stdout in self.calls:
            self.assertNotIn("secreto", " ".join(argv))

    def test_the_dump_is_verified_with_pg_restore_list_before_being_named(self):
        """
        El volcado se valida antes de renombrarse a `.dump`. Si `pg_restore
        --list` falla, el archivo parcial se borra y no queda nada que parezca
        un respaldo utilizable.
        """
        self._record()

        bd.create_backup(output_dir=self.output)

        restore_calls = [c for c in self.calls if "pg_restore" in c[0][0]]
        self.assertEqual(len(restore_calls), 1)
        self.assertIn("--list", restore_calls[0][0])
        # Verifica el temporal, no el nombre final.
        self.assertTrue(restore_calls[0][0][-1].endswith(".dump.partial"))

        # Tras la verificacion el temporal desaparece y queda un unico .dump.
        self.assertEqual(list(self.output.glob("*.partial")), [])
        final = list(self.output.glob("*.dump"))
        self.assertEqual(len(final), 1)
        self.assertTrue(final[0].name.startswith("taji-"))


class RetentionTests(SimpleTestCase):
    """Politica de conservacion de archivos."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.output = Path(self._tmp.name)

    def _make(self, name: str, age_days: int) -> Path:
        path = self.output / name
        path.write_bytes(b"PGDMP\x00\x01x")
        stamp = time.time() - age_days * 86400
        os.utime(path, (stamp, stamp))
        return path

    def test_list_returns_newest_first(self):
        self._make("viejo.dump", 10)
        self._make("nuevo.dump", 0)

        names = [item.path.name for item in bd.list_backups(self.output)]

        self.assertEqual(names, ["nuevo.dump", "viejo.dump"])

    def test_list_ignores_partial_files(self):
        """Un volcado en curso no debe aparecer como respaldo disponible."""
        self._make("listo.dump", 1)
        (self.output / "en-curso.dump.partial").write_bytes(b"PGDMP")

        names = [item.path.name for item in bd.list_backups(self.output)]

        self.assertEqual(names, ["listo.dump"])

    def test_prune_keeps_the_recent_copies(self):
        for index in range(5):
            self._make(f"copia{index}.dump", index)

        removed = bd.prune_backups(output_dir=self.output, keep_days=14, keep_count=5)

        self.assertEqual(removed, [])
        self.assertEqual(len(list(self.output.glob("*.dump"))), 5)

    def test_prune_removes_files_older_than_the_retention(self):
        self._make("reciente.dump", 1)
        self._make("antiguo.dump", 40)

        removed = bd.prune_backups(output_dir=self.output, keep_days=14, keep_count=1)

        self.assertEqual([item.name for item in removed], ["antiguo.dump"])
        self.assertTrue((self.output / "reciente.dump").exists())

    def test_prune_never_drops_below_keep_count(self):
        """Aunque todos sean viejos, siempre queda un piso de copias."""
        for index in range(8):
            self._make(f"viejo{index}.dump", 90)

        removed = bd.prune_backups(output_dir=self.output, keep_days=1, keep_count=3)

        remaining = len(list(self.output.glob("*.dump")))
        self.assertEqual(remaining, 3)
        self.assertEqual(len(removed), 5)

    def test_prune_dry_run_does_not_delete(self):
        self._make("antiguo.dump", 40)
        self._make("reciente.dump", 1)

        bd.prune_backups(output_dir=self.output, keep_days=14, keep_count=1, dry_run=True)

        self.assertEqual(len(list(self.output.glob("*.dump"))), 2)

    def test_prune_on_empty_directory_is_a_no_op(self):
        self.assertEqual(bd.prune_backups(output_dir=self.output), [])


class RestoreSafetyTests(SimpleTestCase):
    """
    La restauracion es la operacion mas peligrosa del script.

    Regla que se verifica aqui: **nunca** se sobrescribe la base en uso sin
    que se pida explicitamente.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.output = Path(self._tmp.name)
        self.backup = self.output / "bueno.dump"
        self.backup.write_bytes(b"PGDMP\x00\x01contenido")

    def test_refuses_to_overwrite_the_live_database(self):
        with mock.patch.object(bd, "_database_from_settings", return_value=FakeDatabase()), \
             mock.patch.object(bd, "_executable", return_value="/usr/bin/pg_restore"), \
             mock.patch.object(bd.subprocess, "run", return_value=None):
            with self.assertRaises(bd.BackupError) as ctx:
                bd.restore_backup(self.backup, target_db="taji")

        self.assertIn("allow-live-overwrite", str(ctx.exception))

    def test_restores_into_a_different_database(self):
        with mock.patch.object(bd, "_database_from_settings", return_value=FakeDatabase()), \
             mock.patch.object(bd, "_executable", return_value="/usr/bin/pg_restore"), \
             mock.patch.object(bd.subprocess, "run", return_value=None):
            path = bd.restore_backup(
                self.backup, target_db="taji_restaurado", create_target=False
            )

        self.assertEqual(path, self.backup)

    def test_refuses_a_corrupted_backup_before_restoring(self):
        corrupted = self.output / "roto.dump"
        corrupted.write_bytes(b"basura")

        with mock.patch.object(bd, "_database_from_settings", return_value=FakeDatabase()), \
             mock.patch.object(bd, "_executable", return_value="/usr/bin/pg_restore"), \
             mock.patch.object(bd.subprocess, "run", side_effect=bd.subprocess.CalledProcessError(1, [])):
            with self.assertRaises(bd.BackupError):
                bd.restore_backup(corrupted, target_db="otra", create_target=False)


class CliTests(SimpleTestCase):
    """Los subcomandos que expone la CLI."""

    def test_no_subcommand_behaves_like_create(self):
        """Invocar el script sin argumentos hacia un respaldo, como antes."""
        with mock.patch.object(bd, "create_backup") as create, \
             mock.patch.object(bd, "prune_backups", return_value=[]):
            create.return_value = Path(__file__).parent / "x.dump"
            with mock.patch.object(Path, "stat", return_value=mock.Mock(st_size=1024)):
                self.assertEqual(bd.main([]), 0)

        create.assert_called_once()

    def test_requires_postgres(self):
        with mock.patch.object(bd, "_database_from_settings",
                               side_effect=bd.BackupError("requiere PostgreSQL")):
            self.assertEqual(bd.main(["create"]), 1)
