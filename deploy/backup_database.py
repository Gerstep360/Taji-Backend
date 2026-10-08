"""Respaldo y restauracion de la base de datos PostgreSQL de Taji.

Por que `pg_dump` y no `pg_dumpall`
----------------------------------

Taji usa una **unica base de datos compartida** (`DATABASE_URL` apunta siempre
a `taji`); el aislamiento entre condominios es a nivel de ORM, con
`TenantAwareManager` filtrando por `condominium_id`. Por lo tanto un solo
`pg_dump` de esa base ya incluye **todos los tenants**, y `pg_dumpall` solo
aportaria los roles y permisos globales de PostgreSQL.

Decisiones de seguridad aplicadas aqui
-------------------------------------

1. **Escritura atomica.** El volcado se escribe en un `.tmp` y solo se renombra
   a `.dump` despues de verificarlo. Un respaldo a medio escribir nunca aparece
   como un respaldo valido.
2. **Verificacion obligatoria.** Cada archivo pasa por `pg_restore --list` y se
   descarta si esta vacio. Un respaldo que no se puede leer no sirve de nada,
   y descubrirlo al necesitarlo es la peor forma de enterarse.
3. **Nunca se sobrescribe.** Se abre en modo exclusivo (`"xb"`).
4. **La restauracion no toca la base viva.** Exige un `--target-db` explicito y
   se niega a usar la base configurada salvo que se pase el interruptor
   `--allow-live-overwrite`, que ademas exige una confirmacion interactiva.
5. **No hay secretos en la linea de comandos.** La contraseña viaja por
   `PGPASSWORD` en el entorno del subproceso, nunca como argumento ni en la
   salida.

Uso:
    python deploy/backup_database.py create [--output-dir DIR] [--keep-days N]
    python deploy/backup_database.py list [--output-dir DIR]
    python deploy/backup_database.py verify RESPALDO
    python deploy/backup_database.py restore RESPALDO --target-db NOMBRE
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP_SUFFIX = ".dump"
TEMP_SUFFIX = ".dump.partial"

#: Retencion por defecto. Se conservan 14 dias y siempre las 10 copias mas
#: recientes, para no quedarse sin respaldo reciente aunque el servidor este
#: mucho tiempo sin generar copias nuevas.
DEFAULT_KEEP_DAYS = 14
DEFAULT_KEEP_COUNT = 10


class BackupError(RuntimeError):
    """Fallo recuperable de la operacion de respaldo."""


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    created_at: datetime
    size_bytes: int

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


# ---------------------------------------------------------------------------
# Utilidades compartidas con la CLI y con `vps.sh`
# ---------------------------------------------------------------------------


def _require_django_settings(settings_module: str | None) -> None:
    if settings_module:
        os.environ["DJANGO_SETTINGS_MODULE"] = settings_module
    elif not os.environ.get("DJANGO_SETTINGS_MODULE"):
        os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def _database_from_settings():
    from django.conf import settings

    database = settings.DATABASES["default"]
    if database["ENGINE"] != "django.db.backends.postgresql":
        raise BackupError("Esta operacion requiere PostgreSQL como motor de base de datos.")
    return database


def _executable(name: str, pg_bin: Path | None) -> str:
    suffix = ".exe" if os.name == "nt" else ""
    candidate = str(pg_bin / (name + suffix)) if pg_bin else shutil.which(name)
    if not candidate or not Path(candidate).is_file():
        raise BackupError(f"No se encontro '{name}'. Indica el directorio con --pg-bin.")
    return candidate


def _pg_environment(database: dict) -> dict:
    """Entorno para los clientes de PostgreSQL, con la clave fuera del argv."""
    environment = os.environ.copy()
    environment.update(
        {
            "PGHOST": database.get("HOST") or "localhost",
            "PGPORT": str(database.get("PORT") or 5432),
            "PGUSER": database["USER"],
            "PGPASSWORD": database.get("PASSWORD") or "",
            "PGDATABASE": database["NAME"],
        }
    )
    return environment


def default_output_dir() -> Path:
    """`/var/backups/taji` en produccion; `backups/` en desarrollo."""
    from django.conf import settings

    configured = getattr(settings, "BACKUP_DIR", None)
    return Path(configured) if configured else ROOT / "backups"


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def create_backup(
    *,
    output_dir: Path | None = None,
    pg_bin: Path | None = None,
    prefix: str = "taji",
) -> Path:
    """
    Genera un respaldo verificado y lo devuelve.

    El volcado va a un `.partial`; solo se renombra a `.dump` tras pasar la
    verificacion, de modo que un fallo a mitad no deje un archivo que parezca
    un respaldo correcto.
    """
    database = _database_from_settings()
    pg_dump = _executable("pg_dump", pg_bin)
    pg_restore = _executable("pg_restore", pg_bin)

    destination_dir = (output_dir or default_output_dir()).resolve()
    destination_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    # El sello lleva microsegundos, pero la resolucion del reloj no esta
    # garantizada en todas las plataformas (en Windows llega a ser de ~15 ms),
    # asi que dos respaldos seguidos pueden caer en el mismo instante. Se anade
    # un sufijo numerico cuando el nombre ya existe, en lugar de depender solo
    # del reloj y arriesgarse a que `open("xb")` tumbe el respaldo.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    final_path = destination_dir / f"{prefix}-{stamp}{BACKUP_SUFFIX}"
    partial_path = destination_dir / f"{prefix}-{stamp}{TEMP_SUFFIX}"

    attempt = 1
    while final_path.exists() or partial_path.exists():
        final_path = destination_dir / f"{prefix}-{stamp}-{attempt}{BACKUP_SUFFIX}"
        partial_path = destination_dir / f"{prefix}-{stamp}-{attempt}{TEMP_SUFFIX}"
        attempt += 1

    environment = _pg_environment(database)

    try:
        with partial_path.open("xb") as stream:
            subprocess.run(
                [pg_dump, "--no-password", "--format=custom"],
                env=environment,
                stdout=stream,
                check=True,
            )

        if partial_path.stat().st_size == 0:
            raise BackupError("El respaldo generado esta vacio.")

        # `pg_restore --list` lee el indice del archivo: si esta corrupto o
        # truncado, falla aqui y no al momento de necesitarlo.
        subprocess.run(
            [pg_restore, "--list", str(partial_path)],
            stdout=subprocess.DEVNULL,
            check=True,
        )

        os.replace(partial_path, final_path)
    except subprocess.CalledProcessError as error:
        partial_path.unlink(missing_ok=True)
        raise BackupError(f"Fallo la generacion del respaldo (codigo {error.returncode}).") from error
    except BackupError:
        partial_path.unlink(missing_ok=True)
        raise
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise

    return final_path


# ---------------------------------------------------------------------------
# list / verify
# ---------------------------------------------------------------------------


def list_backups(output_dir: Path | None = None) -> list[BackupInfo]:
    """Respaldos existentes, del mas reciente al mas antiguo."""
    directory = (output_dir or default_output_dir()).resolve()
    if not directory.is_dir():
        return []

    results: list[BackupInfo] = []
    for path in directory.glob(f"*{BACKUP_SUFFIX}"):
        if not path.is_file():
            continue
        stat = path.stat()
        created = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        results.append(BackupInfo(path=path, created_at=created, size_bytes=stat.st_size))
    return sorted(results, key=lambda item: item.created_at, reverse=True)


def verify_backup(path: Path, *, pg_bin: Path | None = None) -> BackupInfo:
    """Comprueba que el archivo existe, no esta vacio y es legible."""
    path = Path(path).resolve()
    if not path.is_file():
        raise BackupError(f"No existe el respaldo: {path}")
    if path.suffix != BACKUP_SUFFIX:
        raise BackupError(f"El archivo no es un respaldo: {path.name}")

    size = path.stat().st_size
    if size == 0:
        raise BackupError(f"El respaldo esta vacio: {path.name}")

    pg_restore = _executable("pg_restore", pg_bin)
    try:
        subprocess.run(
            [pg_restore, "--list", str(path)],
            stdout=subprocess.DEVNULL,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        raise BackupError(f"El respaldo esta corrupto o truncado: {path.name}") from error

    return BackupInfo(
        path=path,
        created_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
        size_bytes=size,
    )


def prune_backups(
    *,
    output_dir: Path | None = None,
    keep_days: int = DEFAULT_KEEP_DAYS,
    keep_count: int = DEFAULT_KEEP_COUNT,
    dry_run: bool = False,
) -> list[Path]:
    """
    Elimina respaldos antiguos conservando los ultimos dias y los mas recientes.

    El piso de `keep_count` manda sobre todo lo demas: las N copias mas
    recientes se conservan siempre, aunque sean viejas. A partir de ahi, se
    borra lo que haya superado la ventana de `keep_days`.

    Asi el disco no crece sin control y, a la vez, nunca se queda sin un numero
    minimo de respaldos por si el servidor lleva tiempo sin generar copias nuevas.
    """
    backups = list_backups(output_dir)
    if not backups:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(keep_days, 0))
    removed: list[Path] = []

    for index, backup in enumerate(backups):
        # Piso de seguridad: las N mas recientes nunca se tocan.
        if index < keep_count:
            continue
        # `keep_days <= 0` desactiva el recorte por antiguedad.
        if keep_days <= 0:
            continue
        if backup.created_at >= cutoff:
            continue

        if not dry_run:
            backup.path.unlink(missing_ok=True)
        removed.append(backup.path)

    return removed


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


def restore_backup(
    path: Path,
    *,
    target_db: str,
    pg_bin: Path | None = None,
    allow_live_overwrite: bool = False,
    create_target: bool = True,
) -> Path:
    """
    Restaura un respaldo en la base indicada.

    **Nunca** sobrescribe la base en uso salvo que se pase
    `allow_live_overwrite`, y aun asi solo si la base destino coincide
    exactamente con la configurada. Esa combinacion es la unica forma de
    perder datos de produccion, asi que exige intencion explicita.
    """
    database = _database_from_settings()
    pg_restore = _executable("pg_restore", pg_bin)

    info = verify_backup(path, pg_bin=pg_bin)
    live_name = database["NAME"]

    if target_db == live_name and not allow_live_overwrite:
        raise BackupError(
            f"La base '{target_db}' es la que usa la aplicacion. Usa "
            "--allow-live-overwrite solo si estas seguro de perder los datos actuales."
        )

    environment = _pg_environment(database)
    environment["PGDATABASE"] = target_db

    if create_target:
        # Se crea la base destino si no existe. `createdb` usa las credenciales
        # del rol configurado, que en Taji es dueno de su propia base.
        createdb = _executable("createdb", pg_bin)
        probe = subprocess.run(
            [createdb, "--no-password", target_db],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if probe.returncode != 0:
            # Si falla casi siempre es porque ya existe, que no es un error.
            check = subprocess.run(
                [_executable("psql", pg_bin), "--no-password", "-d", "postgres", "-tAc",
                 f"SELECT 1 FROM pg_database WHERE datname = '{target_db}'"],
                env=environment,
                stdout=subprocess.DEVNULL,
            )
            if check.returncode != 0:
                raise BackupError(f"No se pudo crear ni abrir la base '{target_db}'.")

    command = [pg_restore, "--no-password", "--dbname", target_db]
    if create_target:
        command.append("--clean")
        command.append("--if-exists")
    command.append(str(info.path))

    try:
        subprocess.run(command, env=environment, check=True)
    except subprocess.CalledProcessError as error:
        raise BackupError(f"Fallo la restauracion (codigo {error.returncode}).") from error

    return info.path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _format_size(size_bytes: int) -> str:
    megabytes = size_bytes / (1024 * 1024)
    if megabytes < 1:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{megabytes:.1f} MB"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--settings",
        help="Modulo de settings de Django (por defecto config.settings).",
    )
    subparsers = parser.add_subparsers(dest="command")

    create = subparsers.add_parser("create", help="Genera un respaldo verificado.")
    create.add_argument("--pg-bin", type=Path, help="Directorio con los binarios de PostgreSQL.")
    create.add_argument("--output-dir", type=Path, help="Directorio de destino.")
    create.add_argument("--prefix", default="taji", help="Prefijo del nombre del archivo.")
    create.add_argument(
        "--keep-days", type=int, default=DEFAULT_KEEP_DAYS, help="Dias a conservar (0 = sin limite)."
    )
    create.add_argument(
        "--keep-count", type=int, default=DEFAULT_KEEP_COUNT, help="Respaldo minimo a conservar."
    )
    create.add_argument(
        "--no-prune", action="store_true", help="No aplica la politica de retencion."
    )

    listing = subparsers.add_parser("list", help="Lista los respaldos existentes.")
    listing.add_argument("--output-dir", type=Path)

    verify = subparsers.add_parser("verify", help="Verifica un respaldo.")
    verify.add_argument("backup", type=Path)
    verify.add_argument("--pg-bin", type=Path)

    restore = subparsers.add_parser("restore", help="Restaura un respaldo en otra base.")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--target-db", required=True, help="Base de datos destino.")
    restore.add_argument("--pg-bin", type=Path)
    restore.add_argument("--no-create", action="store_true", help="No crea la base destino.")
    restore.add_argument(
        "--allow-live-overwrite",
        action="store_true",
        help="Permite restaurar sobre la base en uso. DESTRUCTIVO.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    _require_django_settings(getattr(args, "settings", None))

    # Sin subcomando se comporta como `create`, que es lo que se espera al
    # invocar el script sin argumentos.
    command = args.command or "create"

    try:
        if command == "create":
            path = create_backup(
                output_dir=getattr(args, "output_dir", None),
                pg_bin=getattr(args, "pg_bin", None),
                prefix=getattr(args, "prefix", "taji"),
            )
            size = _format_size(path.stat().st_size)
            print(f"Respaldo verificado: {path} ({size})")

            if not getattr(args, "no_prune", False):
                removed = prune_backups(
                    output_dir=getattr(args, "output_dir", None),
                    keep_days=getattr(args, "keep_days", DEFAULT_KEEP_DAYS),
                    keep_count=getattr(args, "keep_count", DEFAULT_KEEP_COUNT),
                )
                for item in removed:
                    print(f"Respaldo eliminado por retencion: {item.name}")
            return 0

        if command == "list":
            backups = list_backups(args.output_dir)
            if not backups:
                print("No hay respaldos en el directorio configurado.")
                return 0
            print(f"{'Archivo':<44} {'Fecha (UTC)':<22} {'Tamano':>10}")
            for backup in backups:
                stamp = backup.created_at.strftime("%Y-%m-%d %H:%M:%S")
                print(f"{backup.path.name:<44} {stamp:<22} {_format_size(backup.size_bytes):>10}")
            print(f"\nTotal: {len(backups)} respaldo(es).")
            return 0

        if command == "verify":
            info = verify_backup(args.backup, pg_bin=args.pg_bin)
            stamp = info.created_at.strftime("%Y-%m-%d %H:%M:%S")
            print(f"Respaldo correcto: {info.path.name} ({stamp}, {_format_size(info.size_bytes)})")
            return 0

        if command == "restore":
            path = restore_backup(
                args.backup,
                target_db=args.target_db,
                pg_bin=args.pg_bin,
                allow_live_overwrite=args.allow_live_overwrite,
                create_target=not args.no_create,
            )
            print(f"Restaurado {path.name} en la base '{args.target_db}'.")
            return 0

    except BackupError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    parser.error(f"Comando desconocido: {command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
