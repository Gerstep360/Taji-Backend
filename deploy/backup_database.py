"""Back up the configured PostgreSQL database without credentials in argv/output."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def main():
    from django.conf import settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", type=Path, help="PostgreSQL bin directory")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "backups")
    args = parser.parse_args()
    database = settings.DATABASES["default"]
    if database["ENGINE"] != "django.db.backends.postgresql":
        parser.error("This command requires PostgreSQL.")
    suffix = ".exe" if os.name == "nt" else ""

    def executable(name):
        candidate = str(args.pg_bin / (name + suffix)) if args.pg_bin else shutil.which(name)
        if not candidate or not Path(candidate).is_file():
            parser.error(f"{name} not found. Set --pg-bin.")
        return candidate

    pg_dump, pg_restore = executable("pg_dump"), executable("pg_restore")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = output / f"taji-{stamp}.dump"
    environment = os.environ.copy()
    environment.update({
        "PGHOST": database.get("HOST") or "localhost",
        "PGPORT": str(database.get("PORT") or 5432),
        "PGUSER": database["USER"],
        "PGPASSWORD": database.get("PASSWORD") or "",
        "PGDATABASE": database["NAME"],
    })
    with destination.open("xb") as stream:
        subprocess.run([pg_dump, "--no-password", "--format=custom"],
                       env=environment, stdout=stream, check=True)
    subprocess.run([pg_restore, "--list", str(destination)],
                   stdout=subprocess.DEVNULL, check=True)
    if destination.stat().st_size == 0:
        raise RuntimeError("Empty backup.")
    print(f"Backup verified: {destination}")


if __name__ == "__main__":
    main()
