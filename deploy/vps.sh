#!/usr/bin/env bash
# Ubuntu 24.04 / Debian 12+. Run with sudo; no passwords in command arguments.
set -Eeuo pipefail
umask 027
ROOT=/opt/taji
REPO=https://github.com/Gerstep360/Taji-Backend.git
ENV_FILE=/etc/taji/backend.env
MODE=${1:-help}
fail() { echo "ERROR: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail "Ejecutar con sudo."
[[ $MODE == install || $MODE == update ]] || {
  echo 'Uso: sudo bash deploy/vps.sh install api.ejemplo.com correo@ejemplo.com https://web.ejemplo.com'
  echo '     sudo taji-deploy update'
  exit 2
}
exec 9>/var/lock/taji-deploy.lock
flock -n 9 || fail 'Hay otro despliegue ejecutándose.'
if [[ $MODE == install ]]; then
  DOMAIN=${2:?Falta dominio}; EMAIL=${3:?Falta email TLS}; FRONTEND=${4:?Falta origen HTTPS del frontend}
  [[ $DOMAIN =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ && $DOMAIN == *.* ]] || fail 'Dominio inválido.'
  [[ $EMAIL =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$ ]] || fail 'Email inválido.'
  [[ $FRONTEND =~ ^https://[A-Za-z0-9.-]+(:[0-9]+)?$ ]] || fail 'Origen frontend inválido (sin ruta ni barra final).'
  . /etc/os-release
  [[ $ID == ubuntu || $ID == debian ]] || fail 'Este instalador requiere Ubuntu o Debian.'
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y python3 python3-venv python3-dev build-essential libpq-dev postgresql postgresql-contrib nginx git curl openssl ca-certificates certbot
  id taji &>/dev/null || useradd --system --home-dir /var/lib/taji --create-home --shell /usr/sbin/nologin taji
  install -d -m 0755 "$ROOT" "$ROOT/releases" /var/www/taji-acme
  install -d -m 0750 -o root -g taji /etc/taji
  install -d -m 0700 /var/backups/taji
  install -d -m 0750 -o taji -g taji /var/lib/taji/media /var/cache/taji
  systemctl enable --now postgresql nginx
  if [[ ! -f $ENV_FILE ]]; then
    # Refuse to silently adopt a preexisting database or reset an existing role password.
    [[ $(runuser -u postgres -- psql -Atqc "SELECT count(*) FROM pg_roles WHERE rolname='taji'") == 0 ]] || fail 'El rol taji ya existe: configurar /etc/taji/backend.env manualmente.'
    [[ $(runuser -u postgres -- psql -Atqc "SELECT count(*) FROM pg_database WHERE datname='taji'") == 0 ]] || fail 'La base taji ya existe: configurar /etc/taji/backend.env manualmente.'
    DB_PASSWORD=$(openssl rand -hex 32)
    SECRET=$(openssl rand -hex 48)
    runuser -u postgres -- psql -v ON_ERROR_STOP=1 <<SQL
CREATE ROLE taji LOGIN PASSWORD '$DB_PASSWORD';
CREATE DATABASE taji OWNER taji;
SQL
    cat >"$ENV_FILE" <<ENV
DJANGO_SETTINGS_MODULE=config.settings_production
DEBUG=False
DJANGO_SECRET_KEY=$SECRET
DATABASE_URL=postgresql://taji:$DB_PASSWORD@127.0.0.1:5432/taji
ALLOWED_HOSTS=$DOMAIN
FRONTEND_URLS=$FRONTEND
PASSWORD_RESET_URL=$FRONTEND/restablecer-contrasena
COOKIE_SECURE=True
MEDIA_ROOT=/var/lib/taji/media
CACHE_DIR=/var/cache/taji
ENV
    chown root:taji "$ENV_FILE"; chmod 0640 "$ENV_FILE"
    unset DB_PASSWORD SECRET
  fi
  if [[ ! -d $ROOT/repository.git ]]; then
    git clone --bare "$REPO" "$ROOT/repository.git"
  fi
  # ACME-only virtual host until TLS is available. Do not overwrite existing TLS config.
  if [[ ! -f /etc/nginx/sites-available/taji ]]; then
    cat >/etc/nginx/sites-available/taji <<NGINX
server {
    listen 80;
    server_name $DOMAIN;
    location /.well-known/acme-challenge/ { root /var/www/taji-acme; }
    location / { return 503; }
}
NGINX
    ln -s /etc/nginx/sites-available/taji /etc/nginx/sites-enabled/taji
    nginx -t; systemctl reload nginx
  fi
  certbot certonly --webroot -w /var/www/taji-acme -d "$DOMAIN" -m "$EMAIL" --agree-tos --non-interactive --keep-until-expiring
  install -d /etc/letsencrypt/renewal-hooks/deploy
  printf '#!/bin/sh\nnginx -t && systemctl reload nginx\n' >/etc/letsencrypt/renewal-hooks/deploy/taji-nginx
  chmod 0755 /etc/letsencrypt/renewal-hooks/deploy/taji-nginx
  cat >/etc/nginx/sites-available/taji <<NGINX
server {
    listen 80;
    server_name $DOMAIN;
    location /.well-known/acme-challenge/ { root /var/www/taji-acme; }
    location / { return 301 https://$DOMAIN\$request_uri; }
}
server {
    listen 443 ssl;
    server_name $DOMAIN;
    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 10m;
    location /static/ { alias /opt/taji/current/staticfiles/; }
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
NGINX
  cat >/etc/systemd/system/taji.service <<'SERVICE'
[Unit]
Description=Taji Django API
After=network.target postgresql.service
Requires=postgresql.service
[Service]
User=taji
Group=taji
WorkingDirectory=/opt/taji/current
EnvironmentFile=/etc/taji/backend.env
ExecStart=/opt/taji/current/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 60 --access-logfile - --error-logfile -
Restart=on-failure
RestartSec=5
UMask=0027
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/taji /var/cache/taji
[Install]
WantedBy=multi-user.target
SERVICE
  if [[ $(readlink -f "${BASH_SOURCE[0]}") != /usr/local/sbin/taji-deploy ]]; then
    install -m 0755 "${BASH_SOURCE[0]}" /usr/local/sbin/taji-deploy
  fi
  systemctl daemon-reload
fi
[[ -f $ENV_FILE && -d $ROOT/repository.git ]] || fail 'Ejecutar install primero.'
# Fixed local database is intentionally used for peer-authenticated backups.
# Refuse a changed DB target rather than backing up the wrong database.
[[ $(sed -n 's/^DATABASE_URL=//p' "$ENV_FILE") =~ ^postgresql://taji:[a-f0-9]+@127\.0\.0\.1:5432/taji$ ]] || fail 'Conexión personalizada: adaptar respaldo antes de continuar.'
git --git-dir="$ROOT/repository.git" fetch origin refs/heads/main:refs/remotes/origin/main
SHA=$(git --git-dir="$ROOT/repository.git" rev-parse refs/remotes/origin/main)
OLD_SHA=$(cat "$ROOT/current/.release-sha" 2>/dev/null || true)
if [[ $SHA == "$OLD_SHA" && $MODE == update ]]; then
  echo "Sin cambios: $SHA"; exit 0
fi
if [[ -n $OLD_SHA ]]; then
  git --git-dir="$ROOT/repository.git" merge-base --is-ancestor "$OLD_SHA" "$SHA" || fail 'main fue reescrito; revisar antes de desplegar.'
fi
RELEASE=$(mktemp -d "$ROOT/releases/$(date -u +%Y%m%dT%H%M%SZ)-${SHA:0:12}-XXXXXX")
chmod 0755 "$RELEASE"
git --git-dir="$ROOT/repository.git" archive "$SHA" | tar -x -C "$RELEASE"
printf '%s\n' "$SHA" >"$RELEASE/.release-sha"
chown -R taji:taji "$RELEASE"
ln -s "$ENV_FILE" "$RELEASE/.env"
runuser -u taji -- python3 -m venv "$RELEASE/.venv"
runuser -u taji -- "$RELEASE/.venv/bin/pip" install -r "$RELEASE/requirements.txt"
manage() { (cd "$RELEASE" && runuser -u taji -- "$RELEASE/.venv/bin/python" manage.py "$@" --settings=config.settings_production); }
manage check --deploy --fail-level WARNING
manage makemigrations --check --dry-run
manage migrate --plan
manage collectstatic --noinput
# Nginx needs read access only to static output; uploaded private documents are not public.
chmod -R a+rX "$RELEASE/staticfiles"
BACKUP="/var/backups/taji/$(date -u +%Y%m%dT%H%M%SZ)-${SHA:0:12}.dump"
# From this point failures keep the service stopped: never run old code against a partly migrated DB.
STOPPED=0
on_error() {
  if [[ $STOPPED == 1 ]]; then
    systemctl stop taji || true
    echo "Despliegue detenido; respaldo: $BACKUP. Revisar logs y recuperar manualmente según deploy/README.md." >&2
  fi
}
trap on_error EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
systemctl stop taji
STOPPED=1
# Stop application writes before taking the rollback snapshot.
runuser -u postgres -- pg_dump -Fc taji >"$BACKUP"
[[ -s $BACKUP ]] || fail 'Respaldo vacío.'
runuser -u postgres -- pg_restore --list <"$BACKUP" >/dev/null
cp "$ENV_FILE" "${BACKUP%.dump}.env"
tar -czf "${BACKUP%.dump}.media.tar.gz" -C /var/lib/taji media
echo "Respaldo: $BACKUP"
manage migrate --noinput
if [[ -z $OLD_SHA ]]; then manage seed_rbac; fi
NEXT_LINK="$ROOT/.current-${SHA}-$$"
ln -s "$RELEASE" "$NEXT_LINK"
mv -Tf "$NEXT_LINK" "$ROOT/current"
nginx -t
systemctl enable taji
systemctl restart taji
systemctl reload nginx
DOMAIN=$(sed -n 's/^ALLOWED_HOSTS=//p' "$ENV_FILE")
healthy=0
for attempt in {1..20}; do
  if curl --fail --silent --show-error --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/api/v1/health/"; then healthy=1; break; fi
  sleep 1
done
[[ $healthy == 1 ]] || fail 'Falló comprobación HTTPS del servicio.'
bash -n "$RELEASE/deploy/vps.sh"
install -m 0755 "$RELEASE/deploy/vps.sh" /usr/local/sbin/taji-deploy
STOPPED=0
trap - EXIT INT TERM
echo "Desplegado $SHA. API: https://$DOMAIN/api/v1/docs/"
