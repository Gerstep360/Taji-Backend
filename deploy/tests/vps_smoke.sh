#!/usr/bin/env bash
# Only for a disposable Ubuntu CI runner: installs real services and changes system trust.
set -Eeuo pipefail
[[ $EUID == 0 && ${GITHUB_ACTIONS:-} == true ]] || {
  echo 'Ejecutar solamente con sudo en un runner desechable de GitHub Actions.' >&2
  exit 2
}
SOURCE=${1:?Falta checkout de GitHub Actions}
[[ ! -e /opt/taji && ! -e /etc/taji ]] || {
  echo 'El runner ya contiene una instalación; no se modificará.' >&2
  exit 2
}
WORK=$(mktemp -d /tmp/taji-deploy-ci-XXXXXX)
git -c safe.directory="$SOURCE" clone --no-hardlinks "$SOURCE" "$WORK/source"
git -C "$WORK/source" checkout -B main
git -C "$WORK/source" config user.name 'Taji deployment CI'
git -C "$WORK/source" config user.email 'ci@example.invalid'
mkdir -p /opt/taji "$WORK/bin"
git clone --bare "$WORK/source" /opt/taji/repository.git

# Replace only the public ACME issuance. Nginx, TLS validation, Django, pip,
# PostgreSQL, migrations, systemd and curl all execute for real.
cat >"$WORK/bin/certbot" <<'CERTBOT'
#!/usr/bin/env bash
set -euo pipefail
mkdir -p /etc/letsencrypt/live/api.taji.test
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -subj /CN=api.taji.test -addext subjectAltName=DNS:api.taji.test \
  -keyout /etc/letsencrypt/live/api.taji.test/privkey.pem \
  -out /etc/letsencrypt/live/api.taji.test/fullchain.pem
cp /etc/letsencrypt/live/api.taji.test/fullchain.pem /usr/local/share/ca-certificates/taji-ci.crt
update-ca-certificates
CERTBOT
chmod 0755 "$WORK/bin/certbot"
export PATH="$WORK/bin:$PATH"
bash "$WORK/source/deploy/vps.sh" install api.taji.test ci@example.invalid https://web.taji.test
systemctl is-active --quiet taji
curl --fail --silent --resolve api.taji.test:443:127.0.0.1 https://api.taji.test/api/v1/health/
FIRST=$(cat /opt/taji/current/.release-sha)
INVOCATION=$(systemctl show taji --property=InvocationID --value)
taji-deploy update
[[ $(cat /opt/taji/current/.release-sha) == "$FIRST" ]]
[[ $(systemctl show taji --property=InvocationID --value) == "$INVOCATION" ]]

printf 'CI update\n' >"$WORK/source/deploy-ci-marker.txt"
git -C "$WORK/source" add deploy-ci-marker.txt
git -C "$WORK/source" commit -m 'Exercise deployment update'
taji-deploy update
SECOND=$(cat /opt/taji/current/.release-sha)
[[ $SECOND != "$FIRST" ]]
[[ $(systemctl show taji --property=InvocationID --value) != "$INVOCATION" ]]
systemctl is-active --quiet taji

# A failed HTTPS verification after switching current must stop the service,
# and retrying the same SHA must actually recover instead of returning a no-op.
cat >"$WORK/bin/curl" <<'CURL'
#!/usr/bin/env bash
if [[ ${TAJI_CI_HTTP_FAILURE:-} == 1 ]]; then exit 22; fi
exec /usr/bin/curl "$@"
CURL
chmod 0755 "$WORK/bin/curl"
printf 'CI health recovery\n' >>"$WORK/source/deploy-ci-marker.txt"
git -C "$WORK/source" add deploy-ci-marker.txt
git -C "$WORK/source" commit -m 'Exercise HTTPS failure and same-commit recovery'
set +e
TAJI_CI_HTTP_FAILURE=1 taji-deploy update
HTTP_FAILED_STATUS=$?
set -e
[[ $HTTP_FAILED_STATUS != 0 ]]
if systemctl is-active --quiet taji; then
  echo 'ERROR: la API continuó activa después de fallar HTTPS.' >&2
  exit 1
fi
RECOVERY_SHA=$(cat /opt/taji/current/.release-sha)
taji-deploy update
[[ $(cat /opt/taji/current/.release-sha) == "$RECOVERY_SHA" ]]
systemctl is-active --quiet taji

cat >"$WORK/source/condominiums/migrations/0006_ci_intentional_failure.py" <<'MIGRATION'
from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [("condominiums", "0005_sync_condominium_sequence")]
    operations = [migrations.RunSQL("SELECT taji_ci_intentional_failure()")]
MIGRATION
git -C "$WORK/source" add condominiums/migrations/0006_ci_intentional_failure.py
git -C "$WORK/source" commit -m 'Exercise failed migration recovery boundary'
# Separate process is intentional: Bash errexit must remain enabled inside the installer.
set +e
taji-deploy update
FAILED_STATUS=$?
set -e
[[ $FAILED_STATUS != 0 ]]
if systemctl is-active --quiet taji; then
  echo 'ERROR: la API continuó activa después de una migración fallida.' >&2
  exit 1
fi
[[ $(cat /opt/taji/current/.release-sha) == "$RECOVERY_SHA" ]]
BACKUP_COUNT=$(find /var/backups/taji -maxdepth 1 -name '*.dump' | wc -l)
[[ $BACKUP_COUNT -ge 3 ]]
echo 'VPS smoke OK: instalación, HTTPS, actualización, no-op, recuperación y parada segura.'
