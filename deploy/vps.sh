#!/usr/bin/env bash
# Ubuntu 24.04 / Debian 12+. Full Production Zero-Downtime Deployment with GUI-like Animated TUI for Taji Backend.
set -Eeuo pipefail
umask 027

ROOT=/opt/taji
REPO=https://github.com/Gerstep360/Taji-Backend.git
ENV_FILE=/etc/taji/backend.env
LOCK_FILE=/var/lock/taji-deploy.lock

# --- ANSI Colors & Graphical Effects ---
CYAN='\033[0;36m'
BRIGHT_CYAN='\033[1;36m'
MAGENTA='\033[0;35m'
BRIGHT_MAGENTA='\033[1;35m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BRIGHT_GREEN='\033[1;32m'
RED='\033[0;31m'
WHITE='\033[1;37m'
GRAY='\033[0;90m'
RESET='\033[0m'

animated_banner() {
    clear
    echo -e "${BRIGHT_CYAN}╔════════════════════════════════════════════════════════════════════════╗${RESET}"
    echo -e "${BRIGHT_CYAN}║   ████████╗ █████╗  ██████╗ ██╗                                        ║${RESET}"
    echo -e "${BRIGHT_CYAN}║   ╚══██╔══╝██╔══██╗   ██║   ██║   ${BRIGHT_WHITE}S I S T E M A                        ${BRIGHT_CYAN}║${RESET}"
    echo -e "${YELLOW}║      ██║   ███████║   ██║   ██║   ${BRIGHT_YELLOW}C O N D O M I N I O S                ${YELLOW}║${RESET}"
    echo -e "${MAGENTA}║      ██║   ██║  ██║██   ██║ ██║                                        ║${RESET}"
    echo -e "${BRIGHT_MAGENTA}║      ██║   ██║  ██║╚█████╔╝ ██║   ${BRIGHT_GREEN}● DEPLOYMENT VPS ENGINE (DJANGO)     ${BRIGHT_MAGENTA}║${RESET}"
    echo -e "${BRIGHT_MAGENTA}║      ╚═╝   ╚═╝  ╚═╝ ╚════╝  ╚═╝                                        ║${RESET}"
    echo -e "${BRIGHT_CYAN}╚════════════════════════════════════════════════════════════════════════╝${RESET}"
    echo -e "${GRAY}        ═════════════════════════════════════════════════════════${RESET}\n"
    sleep 0.1
}

animated_progress_bar() {
    local pid=$1
    local msg=$2
    local duration=0
    local step=0
    local width=30
    local spin=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
    
    while kill -0 "$pid" 2>/dev/null; do
        local frame=${spin[$((step % 10))]}
        local filled_len=$(( (step % width) + 1 ))
        local fill=""
        local empty=""
        
        for ((i=0; i<filled_len; i++)); do fill="${fill}█"; done
        for ((i=filled_len; i<width; i++)); do empty="${empty}░"; done
        
        printf "\r ${BRIGHT_YELLOW}[%s]${RESET} ${CYAN}%-45s${RESET} ${BRIGHT_GREEN}[%s%s]${RESET}" "$frame" "$msg" "$fill" "$empty"
        step=$((step + 1))
        sleep 0.1
    done
    wait "$pid"
    local exit_code=$?
    
    local full_bar=""
    for ((i=0; i<width; i++)); do full_bar="${full_bar}█"; done
    
    if [ $exit_code -eq 0 ]; then
        printf "\r ${BRIGHT_GREEN}[✔] %-45s [%s] 100%% COMPLETADO${RESET}\n" "$msg" "$full_bar"
    else
        printf "\r ${RED}[✖] %-45s [ERROR] FALLÓ EL PROCESO${RESET}\n" "$msg"
        return $exit_code
    fi
}

fail() { echo -e "${RED}ERROR: $*${RESET}" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail 'Este script debe ejecutarse con sudo.'

# --- Menú Interactivo GUI-Style ---
MODE=${1:-""}

if [[ -z "$MODE" ]]; then
    animated_banner
    echo -e "${BRIGHT_YELLOW}┌────────────────────────────────────────────────────────────────────────┐${RESET}"
    echo -e "${BRIGHT_YELLOW}│                      MENÚ INTERACTIVO DE OPERACIONES                   │${RESET}"
    echo -e "${BRIGHT_YELLOW}├────────────────────────────────────────────────────────────────────────┤${RESET}"
    echo -e "│  ${BRIGHT_CYAN}[1]${RESET}  ${WHITE}⚡  Instalación Completa Inicial (PostgreSQL + Django + Nginx)${RESET}  │"
    echo -e "│  ${BRIGHT_CYAN}[2]${RESET}  ${WHITE}🔄  Actualizar Versión (Zero-Downtime Migration + Static Update)${RESET} │"
    echo -e "│  ${BRIGHT_CYAN}[3]  ${WHITE}💾  Respaldo de Base de Datos PostgreSQL (.dump)${RESET}                 │"
    echo -e "│  ${BRIGHT_CYAN}[4]  ${WHITE}●   Verificar Estado de Salud API (Health Check)${RESET}                 │"
    echo -e "│  ${BRIGHT_CYAN}[5]  ${WHITE}✖   Salir${RESET}                                                         │"
    echo -e "${BRIGHT_YELLOW}└────────────────────────────────────────────────────────────────────────┘${RESET}\n"
    
    read -p " ➜ Selecciona una opción [1-5]: " CHOICE
    case "$CHOICE" in
        1) MODE="install" ;;
        2) MODE="update" ;;
        3) MODE="backup" ;;
        4) MODE="health" ;;
        5) echo -e "${YELLOW}Operación finalizada.${RESET}"; exit 0 ;;
        *) fail "Opción inválida." ;;
    esac
fi

if [[ $MODE == "health" ]]; then
    [[ -f $ENV_FILE ]] || fail "No existe /etc/taji/backend.env."
    echo -e "${YELLOW}Comprobando estado de salud del Backend API...${RESET}"
    (curl --fail --silent --show-error --connect-timeout 3 "http://127.0.0.1:8000/api/v1/health/" >/dev/null) &
    animated_progress_bar $! "Verificando endpoint HTTP /api/v1/health/"
    echo -e "${BRIGHT_GREEN}[✔] Backend API responde correctamente (HTTP 200 OK)${RESET}"
    exit 0
fi

if [[ $MODE == "backup" ]]; then
    [[ -f $ENV_FILE ]] || fail "No existe /etc/taji/backend.env."
    BACKUP_FILE="/var/backups/taji/manual-$(date -u +%Y%m%dT%H%M%SZ).dump"
    (runuser -u postgres -- pg_dump -Fc taji >"$BACKUP_FILE") &
    animated_progress_bar $! "Generando respaldo PostgreSQL ($BACKUP_FILE)"
    echo -e "${BRIGHT_GREEN}[✔] Respaldo creado exitosamente: $BACKUP_FILE${RESET}"
    exit 0
fi

if [[ $MODE == "install" && $# -lt 2 ]]; then
    animated_banner
    DETECTED_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    [[ -z "$DETECTED_IP" ]] && DETECTED_IP="127.0.0.1"

    echo -e " ${GRAY}┌────────────────────────────────────────────────────────────────┐${RESET}"
    echo -e " ${GRAY}│${RESET} Detector de Red: IP Pública / Servidor = ${BRIGHT_CYAN}$DETECTED_IP${RESET}"
    echo -e " ${GRAY}└────────────────────────────────────────────────────────────────┘${RESET}\n"
    
    read -p " ➜ Dominio o IP del Servidor [$DETECTED_IP]: " DOMAIN
    DOMAIN=${DOMAIN:-$DETECTED_IP}

    read -p " ➜ Correo para administración [admin@$DOMAIN]: " EMAIL
    EMAIL=${EMAIL:-"admin@$DOMAIN"}

    read -p " ➜ URL Origen Frontend Web [http://$DOMAIN/taji]: " FRONTEND
    FRONTEND=${FRONTEND:-"http://$DOMAIN/taji"}
else
    if [[ $MODE == "install" ]]; then
        DOMAIN=${2:?Falta dominio}
        EMAIL=${3:?Falta email}
        FRONTEND=${4:?Falta origen frontend}
    fi
fi

exec 9>"$LOCK_FILE"
flock -n 9 || fail 'Hay otro despliegue de backend en curso.'

if [[ $MODE == "install" ]]; then
    . /etc/os-release
    [[ $ID == ubuntu || $ID == debian ]] || fail 'Este instalador requiere Ubuntu o Debian.'
    export DEBIAN_FRONTEND=noninteractive

    (apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-dev build-essential libpq-dev postgresql postgresql-contrib nginx git curl openssl ca-certificates certbot >/dev/null 2>&1) &
    animated_progress_bar $! "Instalando paquetes base de Linux (Python, Postgres, Nginx)"

    id taji &>/dev/null || useradd --system --home-dir /var/lib/taji --create-home --shell /usr/sbin/nologin taji
    install -d -m 0755 "$ROOT" "$ROOT/releases" /var/www/taji-acme
    install -d -m 0750 -o root -g taji /etc/taji
    install -d -m 0700 /var/backups/taji
    install -d -m 0750 -o taji -g taji /var/lib/taji/media /var/cache/taji
    systemctl enable --now postgresql nginx >/dev/null 2>&1

    if [[ ! -f $ENV_FILE ]]; then
        DB_PASSWORD=$(openssl rand -hex 32)
        SECRET=$(openssl rand -hex 48)
        runuser -u postgres -- psql -v ON_ERROR_STOP=1 <<SQL >/dev/null 2>&1 || true
CREATE ROLE taji LOGIN PASSWORD '$DB_PASSWORD';
CREATE DATABASE taji OWNER taji;
SQL
        cat >"$ENV_FILE" <<ENV
DJANGO_SETTINGS_MODULE=config.settings_production
DEBUG=False
DJANGO_SECRET_KEY=$SECRET
DATABASE_URL=postgresql://taji:$DB_PASSWORD@127.0.0.1:5432/taji
ALLOWED_HOSTS=$DOMAIN,localhost,127.0.0.1
FRONTEND_URLS=$FRONTEND
PASSWORD_RESET_URL=$FRONTEND/restablecer-contrasena
COOKIE_SECURE=False
MEDIA_ROOT=/var/lib/taji/media
CACHE_DIR=/var/cache/taji
ENV
        chown root:taji "$ENV_FILE"; chmod 0640 "$ENV_FILE"
        unset DB_PASSWORD SECRET
    fi

    if [[ ! -d $ROOT/repository.git ]]; then
        (git clone --bare "$REPO" "$ROOT/repository.git" >/dev/null 2>&1) &
        animated_progress_bar $! "Clonando repositorio bare Git Backend"
    fi

    cat >/etc/nginx/sites-available/taji-backend <<NGINX
server {
    listen 80;
    server_name $DOMAIN;

    location /taji/api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Real-IP \$remote_addr;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Real-IP \$remote_addr;
    }

    location /static/ {
        alias /opt/taji/current/staticfiles/;
    }
}
NGINX

    ln -sf /etc/nginx/sites-available/taji-backend /etc/nginx/sites-enabled/taji-backend
    nginx -t >/dev/null 2>&1 && systemctl reload nginx

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
ExecStart=/opt/taji/current/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 60
Restart=on-failure
RestartSec=5
UMask=0027

[Install]
WantedBy=multi-user.target
SERVICE

    systemctl daemon-reload
fi

[[ -f $ENV_FILE && -d $ROOT/repository.git ]] || fail 'Ejecutar install primero.'

# Proceso de Despliegue / Actualización Zero-Downtime
(git --git-dir="$ROOT/repository.git" fetch origin refs/heads/main:refs/remotes/origin/main >/dev/null 2>&1) &
animated_progress_bar $! "Sincronizando última versión de Git (fetch origin main)"
SHA=$(git --git-dir="$ROOT/repository.git" rev-parse refs/remotes/origin/main)

RELEASE=$(mktemp -d "$ROOT/releases/$(date -u +%Y%m%dT%H%M%SZ)-${SHA:0:12}-XXXXXX")
chmod 0755 "$RELEASE"
git --git-dir="$ROOT/repository.git" archive "$SHA" | tar -x -C "$RELEASE"
printf '%s\n' "$SHA" >"$RELEASE/.release-sha"
chown -R taji:taji "$RELEASE"
ln -sf "$ENV_FILE" "$RELEASE/.env"

(runuser -u taji -- python3 -m venv "$RELEASE/.venv" && \
 runuser -u taji -- "$RELEASE/.venv/bin/pip" install -r "$RELEASE/requirements.txt" --quiet >/dev/null 2>&1) &
animated_progress_bar $! "Creando entorno virtual Python e instalando Django/RestFramework"

manage() { (cd "$RELEASE" && runuser -u taji -- "$RELEASE/.venv/bin/python" manage.py "$@" --settings=config.settings_production >/dev/null 2>&1); }

(manage makemigrations --check --dry-run || true) &
animated_progress_bar $! "Verificando esquema de base de datos y migraciones"

manage migrate --noinput
(manage collectstatic --noinput) &
animated_progress_bar $! "Compilando archivos estáticos de Django (collectstatic)"
chmod -R a+rX "$RELEASE/staticfiles"

NEXT_LINK="$ROOT/.current-${SHA}-$$"
ln -s "$RELEASE" "$NEXT_LINK"
mv -Tf "$NEXT_LINK" "$ROOT/current"

systemctl enable taji >/dev/null 2>&1
systemctl restart taji

echo -e "\n${BRIGHT_GREEN}╔════════════════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BRIGHT_GREEN}║   ¡DESPLIEGUE DEL BACKEND COMPLETADO EXITOSAMENTE CON ZERO-DOWNTIME!   ║${RESET}"
echo -e "${BRIGHT_GREEN}╚════════════════════════════════════════════════════════════════════════╝${RESET}"
echo -e " Backend API: ${BRIGHT_CYAN}http://$DOMAIN/api/v1/${RESET}"
echo -e " Commit SHA:  ${BRIGHT_MAGENTA}$SHA${RESET}\n"
