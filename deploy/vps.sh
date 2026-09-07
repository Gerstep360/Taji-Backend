#!/usr/bin/env bash
# Ubuntu 24.04 / Debian 12+. Full Production Zero-Downtime Deployment with Clean TUI for Taji Backend.
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
BRIGHT_YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BRIGHT_GREEN='\033[1;32m'
RED='\033[0;31m'
WHITE='\033[1;37m'
BRIGHT_WHITE='\033[1;37m'
GRAY='\033[0;90m'
RESET='\033[0m'

animated_banner() {
    clear
    echo -e "${BRIGHT_CYAN}+------------------------------------------------------------------------+${RESET}"
    echo -e "${BRIGHT_CYAN}|   ████████╗ █████╗  ██████╗ ██╗                                        |${RESET}"
    echo -e "${BRIGHT_CYAN}|   ╚══██╔══╝██╔══██╗   ██║   ██║   ${BRIGHT_WHITE}S I S T E M A                        ${BRIGHT_CYAN}|${RESET}"
    echo -e "${YELLOW}|      ██║   ███████║   ██║   ██║   ${BRIGHT_YELLOW}C O N D O M I N I O S                ${YELLOW}|${RESET}"
    echo -e "${MAGENTA}|      ██║   ██║  ██║██   ██║ ██║                                        |${RESET}"
    echo -e "${BRIGHT_MAGENTA}|      ██║   ██║  ██║╚█████╔╝ ██║   ${BRIGHT_GREEN}[*] DEPLOYMENT VPS ENGINE (DJANGO)   ${BRIGHT_MAGENTA}|${RESET}"
    echo -e "${BRIGHT_MAGENTA}|      ╚═╝   ╚═╝  ╚═╝ ╚════╝  ╚═╝                                        |${RESET}"
    echo -e "${BRIGHT_CYAN}+------------------------------------------------------------------------+${RESET}"
    echo -e "${GRAY}        =========================================================${RESET}\n"
    sleep 0.1
}

animated_progress_bar() {
    local pid=$1
    local msg=$2
    local step=0
    local width=30
    local spin=('|' '/' '-' '\')
    
    while kill -0 "$pid" 2>/dev/null; do
        local frame=${spin[$((step % 4))]}
        local filled_len=$(( (step % width) + 1 ))
        local fill=""
        local empty=""
        
        for ((i=0; i<filled_len; i++)); do fill="${fill}#"; done
        for ((i=filled_len; i<width; i++)); do empty="${empty}-"; done
        
        printf "\r ${BRIGHT_YELLOW}[%s]${RESET} ${CYAN}%-45s${RESET} ${BRIGHT_GREEN}[%s%s]${RESET}" "$frame" "$msg" "$fill" "$empty"
        step=$((step + 1))
        sleep 0.1
    done
    wait "$pid"
    local exit_code=$?
    
    local full_bar=""
    for ((i=0; i<width; i++)); do full_bar="${full_bar}#"; done
    
    if [ $exit_code -eq 0 ]; then
        printf "\r ${BRIGHT_GREEN}[OK] %-45s [%s] 100%% COMPLETADO${RESET}\n" "$msg" "$full_bar"
    else
        printf "\r ${RED}[ERROR] %-45s [FALLO EN EL PROCESO]${RESET}\n" "$msg"
        return $exit_code
    fi
}

release_lock() {
    exec 9>&- 2>/dev/null || true
    rm -f "$LOCK_FILE" 2>/dev/null || true
}

acquire_lock() {
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        echo -e "${YELLOW}[!] Se detecto un bloqueo anterior no liberado. Limpiando lock...${RESET}"
        exec 9>&- 2>/dev/null || true
        rm -f "$LOCK_FILE" 2>/dev/null || true
        exec 9>"$LOCK_FILE"
        flock -n 9 || fail 'No se pudo obtener el bloqueo de despliegue backend.'
    fi
}

fail() {
    echo -e "${RED}ERROR: $*${RESET}" >&2
    release_lock
    return 1 2>/dev/null || exit 1
}

[[ $EUID -eq 0 ]] || fail 'Este script debe ejecutarse con sudo.'

check_backend_health() {
    if curl --fail --silent --connect-timeout 3 "http://127.0.0.1:8000/api/v1/health/" >/dev/null 2>&1; then
        return 0
    fi
    if curl --fail --silent --connect-timeout 3 "http://127.0.0.1/taji/api/v1/health/" >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

do_update_git() {
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        (git pull origin main >/dev/null 2>&1) &
        animated_progress_bar $! "Actualizando repositorio local Git (git pull origin main)" || true
    fi
}

show_backend_logs() {
    clear
    echo -e "${BRIGHT_CYAN}+------------------------------------------------------------------------+${RESET}"
    echo -e "${BRIGHT_CYAN}|        MONITOR DE LOGS EN TIEMPO REAL - BACKEND DJANGO / GUNICORN      |${RESET}"
    echo -e "${BRIGHT_CYAN}+------------------------------------------------------------------------+${RESET}"
    echo -e "${BRIGHT_YELLOW} Presiona [CTRL + C] para detener los logs y volver al menu principal.${RESET}\n"

    echo -e "${BRIGHT_WHITE}=== CONFIGURACION ACTIVA EN /etc/taji/backend.env ===${RESET}"
    if [[ -f /etc/taji/backend.env ]]; then
        cat /etc/taji/backend.env
    fi
    echo ""

    trap 'echo -e "\n${BRIGHT_GREEN}[OK] Monitor finalizado. Regresando al menu principal...${RESET}"; return 0' INT

    echo -e "${BRIGHT_GREEN}--- Transmitiendo logs de taji.service (Gunicorn / Django API) en tiempo real ---${RESET}\n"
    journalctl -u taji -n 15 -f || true
}

do_create_superuser() {
    [[ -d $ROOT/current ]] || fail "No existe /opt/taji/current. Ejecuta la opcion [1] primero."
    clear
    echo -e "${BRIGHT_CYAN}+------------------------------------------------------------------------+${RESET}"
    echo -e "${BRIGHT_CYAN}|        CREACION / ACTUALIZACION RAPIDA DE SUPERUSUARIO (ADMIN)         |${RESET}"
    echo -e "${BRIGHT_CYAN}+------------------------------------------------------------------------+${RESET}\n"

    read -p " Correo del Administrador [admin@gmail.com]: " ADMIN_EMAIL
    ADMIN_EMAIL=${ADMIN_EMAIL:-"admin@gmail.com"}

    read -p " Contrasena [Admin12345!]: " ADMIN_PASS
    ADMIN_PASS=${ADMIN_PASS:-"Admin12345!"}

    read -p " Nombre [Admin]: " ADMIN_NAME
    ADMIN_NAME=${ADMIN_NAME:-"Admin"}

    read -p " Apellido [Sistema]: " ADMIN_LAST
    ADMIN_LAST=${ADMIN_LAST:-"Sistema"}

    echo -e "\n${YELLOW}Procesando creacion/actualizacion de superusuario...${RESET}"

    (cd "$ROOT/current" && runuser -u taji -- "$ROOT/current/.venv/bin/python" manage.py shell --settings=config.settings_production <<PYTHON
import sys
from accounts.models import User, Person, Role

email = "${ADMIN_EMAIL}".strip().lower()
password = "${ADMIN_PASS}"
first_name = "${ADMIN_NAME}".strip()
last_name = "${ADMIN_LAST}".strip()

admin_role = Role.objects.filter(slug="administrador", is_active=True).first()

user = User.objects.filter(email=email).first()
if user:
    user.is_superuser = True
    user.is_staff = True
    user.is_approved = True
    user.is_active = True
    if admin_role:
        user.role = admin_role
    user.set_password(password)
    if user.person:
        user.person.first_name = first_name
        user.person.last_name = last_name
        user.person.save()
    else:
        person = Person.objects.create(first_name=first_name, last_name=last_name, contact_email=email)
        user.person = person
    user.save()
    print(f"\n >>> [OK] Usuario existente '{email}' actualizado a Superusuario (Admin).")
else:
    person = Person.objects.create(first_name=first_name, last_name=last_name, contact_email=email)
    user = User.objects.create_superuser(
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
        person=person,
        role=admin_role,
        is_approved=True,
        is_active=True
    )
    print(f"\n >>> [OK] Superusuario '{email}' creado exitosamente.")
PYTHON
)
    echo -e "\n${BRIGHT_GREEN}[OK] Operacion de superusuario finalizada con exito.${RESET}"
}

do_list_users() {
    [[ -d $ROOT/current ]] || fail "No existe /opt/taji/current. Ejecuta la opcion [1] primero."
    clear
    echo -e "${BRIGHT_CYAN}+------------------------------------------------------------------------+${RESET}"
    echo -e "${BRIGHT_CYAN}|                  LISTADO DE CUENTAS DE USUARIOS REGISTRADOS            |${RESET}"
    echo -e "${BRIGHT_CYAN}+------------------------------------------------------------------------+${RESET}\n"

    (cd "$ROOT/current" && runuser -u taji -- "$ROOT/current/.venv/bin/python" manage.py shell --settings=config.settings_production <<'PYTHON'
from accounts.models import User

users = User.objects.select_related('person', 'role').all().order_by('-date_joined')
if not users.exists():
    print(" No hay usuarios registrados en el sistema.")
else:
    print(f" {'ID':<4} | {'EMAIL':<32} | {'NOMBRE COMPLETO':<24} | {'ROL':<15} | {'ADMIN?':<6} | {'APROBADO?':<9}")
    print("-" * 105)
    for u in users:
        role_name = u.role.name if u.role else ("Superuser" if u.is_superuser else "Sin Rol")
        is_admin = "SI" if u.is_superuser else "NO"
        is_appr = "SI" if u.is_approved else "NO"
        name = u.full_name or "N/A"
        print(f" {u.id:<4} | {u.email:<32} | {name:<24} | {role_name:<15} | {is_admin:<6} | {is_appr:<9}")
PYTHON
)
}

do_change_password() {
    [[ -d $ROOT/current ]] || fail "No existe /opt/taji/current. Ejecuta la opcion [1] primero."
    clear
    echo -e "${BRIGHT_CYAN}+------------------------------------------------------------------------+${RESET}"
    echo -e "${BRIGHT_CYAN}|                 CAMBIO RAPIDO DE CONTRASEÑA DE USUARIO                 |${RESET}"
    echo -e "${BRIGHT_CYAN}+------------------------------------------------------------------------+${RESET}\n"

    local TARGET_EMAIL="${1:-}"
    local NEW_PASS="${2:-}"

    if [[ -z "$TARGET_EMAIL" ]]; then
        read -p " Correo del usuario a cambiar contraseña [admin@gmail.com]: " TARGET_EMAIL
        TARGET_EMAIL=${TARGET_EMAIL:-"admin@gmail.com"}
    fi

    if [[ -z "$NEW_PASS" ]]; then
        read -p " Nueva contraseña [Admin12345!]: " NEW_PASS
        NEW_PASS=${NEW_PASS:-"Admin12345!"}
    fi

    echo -e "\n${YELLOW}Procesando cambio de contraseña para: ${BRIGHT_WHITE}${TARGET_EMAIL}${RESET}..."

    (cd "$ROOT/current" && runuser -u taji -- "$ROOT/current/.venv/bin/python" manage.py shell --settings=config.settings_production <<PYTHON
import sys
from accounts.models import User, LoginAttempt

email = "${TARGET_EMAIL}".strip().lower()
password = "${NEW_PASS}"

user = User.objects.filter(email=email).first()
if not user:
    user = User.objects.filter(email__iexact=email).first()

if user:
    user.set_password(password)
    user.is_active = True
    user.is_approved = True
    user.save()

    try:
        deleted_count, _ = LoginAttempt.objects.filter(user=user, was_successful=False).delete()
        unlock_msg = f" y se limpiaron {deleted_count} intentos fallidos acumulados" if deleted_count > 0 else ""
    except Exception:
        unlock_msg = ""

    print(f"\n >>> [OK] Contraseña cambiada exitosamente para '{user.email}'{unlock_msg}.")
    print(f" >>> [OK] Nueva contraseña configurada: {password}")
    print(f" >>> [OK] Estado de la cuenta: Activo=SI, Aprobado=SI")
else:
    print(f"\n >>> [ERROR] No se encontro ningun usuario con el correo '{email}'.")
    print("\n --- Usuarios disponibles en el sistema ---")
    users = User.objects.all().order_by('email')
    if users.exists():
        for u in users:
            print(f"  * {u.email} ({u.full_name or 'Sin nombre'})")
    else:
        print("  (No hay usuarios registrados. Usa la opcion [4] para crear el primero).")
PYTHON
)
    echo -e "\n${BRIGHT_GREEN}[OK] Operacion finalizada con exito.${RESET}"
}

do_deploy_backend() {
    do_update_git

    [[ -f $ENV_FILE && -d $ROOT/repository.git ]] || fail 'Ejecutar opcion [1] install primero.'

    # Proceso de Despliegue / Actualizacion Zero-Downtime
    (git --git-dir="$ROOT/repository.git" fetch origin refs/heads/main:refs/remotes/origin/main >/dev/null 2>&1) &
    SHA=$(git --git-dir="$ROOT/repository.git" rev-parse refs/remotes/origin/main)

    RELEASE=$(mktemp -d "$ROOT/releases/$(date -u +%Y%m%dT%H%M%SZ)-${SHA:0:12}-XXXXXX")
    chmod 0755 "$RELEASE"
    git --git-dir="$ROOT/repository.git" archive "$SHA" | tar -x -C "$RELEASE"
    printf '%s\n' "$SHA" >"$RELEASE/.release-sha"
    ln -sf "$ENV_FILE" "$RELEASE/.env"
    chown -R taji:taji "$RELEASE"

    (runuser -u taji -- python3 -m venv "$RELEASE/.venv" && \
     runuser -u taji -- "$RELEASE/.venv/bin/pip" install --upgrade pip --quiet >/dev/null 2>&1 && \
     runuser -u taji -- "$RELEASE/.venv/bin/pip" install -r "$RELEASE/requirements.txt" gunicorn --quiet >/dev/null 2>&1) &
    animated_progress_bar $! "Creando entorno virtual Python e instalando Django y Gunicorn"

    chmod -R a+rX "$RELEASE"
    chmod +x "$RELEASE/.venv/bin/"* 2>/dev/null || true

    manage() { (cd "$RELEASE" && runuser -u taji -- "$RELEASE/.venv/bin/python" manage.py "$@" --settings=config.settings_production); }

    (manage makemigrations --check --dry-run || true) >/dev/null 2>&1
    manage migrate --noinput
    (manage collectstatic --noinput) >/dev/null 2>&1
    chmod -R a+rX "$RELEASE/staticfiles"

    NEXT_LINK="$ROOT/.current-${SHA}-$$"
    ln -s "$RELEASE" "$NEXT_LINK"
    mv -Tf "$NEXT_LINK" "$ROOT/current"

    echo -e "${YELLOW}Reiniciando servicios systemd (postgresql, taji, nginx)...${RESET}"
    systemctl daemon-reload
    systemctl enable taji >/dev/null 2>&1
    systemctl restart taji
    sleep 2
    nginx -t >/dev/null 2>&1 && systemctl restart nginx

    # Verificación de salud automática tras el despliegue
    echo -e "${YELLOW}Verificando arranque del servicio Django Gunicorn...${RESET}"
    healthy=0
    for i in {1..10}; do
        if check_backend_health; then
            healthy=1
            break
        fi
        sleep 1
    done

    if [[ $healthy -eq 1 ]]; then
        echo -e "\n${BRIGHT_GREEN}+------------------------------------------------------------------------+${RESET}"
        echo -e "${BRIGHT_GREEN}|   DESPLIEGUE DEL BACKEND COMPLETADO EXITOSAMENTE CON ZERO-DOWNTIME!    |${RESET}"
        echo -e "${BRIGHT_GREEN}+------------------------------------------------------------------------+${RESET}"
        echo -e " Backend API: ${BRIGHT_CYAN}http://$DOMAIN/api/v1/${RESET}"
        echo -e " Commit SHA:  ${BRIGHT_MAGENTA}$SHA${RESET}\n"
    else
        echo -e "${RED}[ERROR] El servidor Django no respondio despues del reinicio.${RESET}"
        echo -e "${YELLOW}--- Logs recientes del servicio taji.service ---${RESET}"
        journalctl -u taji -n 25 --no-pager || true
        fail "Fallo el arranque del servicio Backend Gunicorn."
    fi
}

run_action() {
    local MODE=$1

    if [[ $MODE == "superuser" || $MODE == "createsuperuser" ]]; then
        do_create_superuser
        return 0
    fi

    if [[ $MODE == "users" || $MODE == "listusers" ]]; then
        do_list_users
        return 0
    fi

    if [[ $MODE == "password" || $MODE == "changepassword" || $MODE == "passwd" ]]; then
        do_change_password "${2:-}" "${3:-}"
        return 0
    fi

    if [[ $MODE == "logs" ]]; then
        show_backend_logs
        return 0
    fi

    if [[ $MODE == "gitpull" ]]; then
        do_update_git
        echo -e "${BRIGHT_GREEN}[OK] Repositorio Git actualizado correctamente.${RESET}"
        return 0
    fi

    if [[ $MODE == "restart" ]]; then
        [[ -f $ENV_FILE ]] || fail "No existe /etc/taji/backend.env. Ejecuta la opcion [1] primero."
        [[ -x /opt/taji/current/.venv/bin/gunicorn ]] || fail "El ejecutable Gunicorn no existe en /opt/taji/current. Ejecuta la opcion [1] primero."
        do_update_git
        echo -e "${YELLOW}Reiniciando servicios PostgreSQL, Gunicorn (taji) y Nginx...${RESET}"
        systemctl daemon-reload
        systemctl restart postgresql taji nginx
        echo -e "${BRIGHT_GREEN}[OK] Servicios reiniciados correctamente.${RESET}"
        MODE="health"
    fi

    if [[ $MODE == "health" ]]; then
        [[ -f $ENV_FILE ]] || fail "No existe /etc/taji/backend.env. Ejecuta la opcion [1] primero."
        if [[ ! -x /opt/taji/current/.venv/bin/gunicorn ]]; then
            fail "No se encontro /opt/taji/current/.venv/bin/gunicorn. Ejecuta la opcion [1] primero."
        fi
        
        echo -e "${YELLOW}Comprobando estado de salud del Backend API...${RESET}"
        
        if ! systemctl is-active --quiet taji; then
            echo -e "${YELLOW}[!] El servicio taji.service no estaba activo. Iniciando servicio...${RESET}"
            systemctl restart taji || true
            sleep 2
        fi

        healthy=0
        for i in {1..10}; do
            if check_backend_health; then
                healthy=1
                break
            fi
            sleep 1
        done

        if [[ $healthy -eq 1 ]]; then
            echo -e "${BRIGHT_GREEN}[OK] Backend API responde correctamente (HTTP 200 OK)${RESET}"
            return 0
        else
            echo -e "${RED}[ERROR] El servidor Django en 127.0.0.1:8000 no esta respondiendo.${RESET}"
            echo -e "${YELLOW}--- Ultimos logs del servicio taji.service ---${RESET}"
            journalctl -u taji -n 20 --no-pager || true
            fail "El servicio Backend no respondio a la prueba de salud."
        fi
    fi

    if [[ $MODE == "backup" ]]; then
        [[ -f $ENV_FILE ]] || fail "No existe /etc/taji/backend.env."
        BACKUP_FILE="/var/backups/taji/manual-$(date -u +%Y%m%dT%H%M%SZ).dump"
        (runuser -u postgres -- pg_dump -Fc taji >"$BACKUP_FILE") &
        animated_progress_bar $! "Generando respaldo PostgreSQL ($BACKUP_FILE)"
        echo -e "${BRIGHT_GREEN}[OK] Respaldo creado exitosamente: $BACKUP_FILE${RESET}"
        return 0
    fi

    if [[ $MODE == "install" && -z "${2:-}" ]]; then
        animated_banner
        DETECTED_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
        [[ -z "$DETECTED_IP" ]] && DETECTED_IP="127.0.0.1"

        echo -e " ${GRAY}+----------------------------------------------------------------+${RESET}"
        echo -e " ${GRAY}|${RESET} Detector de Red: IP Publica / Servidor = ${BRIGHT_CYAN}$DETECTED_IP${RESET}"
        echo -e " ${GRAY}+----------------------------------------------------------------+${RESET}\n"
        
        read -p " Dominio o IP del Servidor [$DETECTED_IP]: " DOMAIN
        DOMAIN=${DOMAIN:-$DETECTED_IP}

        read -p " Correo para administracion [admin@$DOMAIN]: " EMAIL
        EMAIL=${EMAIL:-"admin@$DOMAIN"}

        read -p " URL Origen Frontend Web [http://$DOMAIN/taji]: " FRONTEND
        FRONTEND=${FRONTEND:-"http://$DOMAIN/taji"}
    elif [[ $MODE == "install" ]]; then
        DOMAIN=${2:?Falta dominio}
        EMAIL=${3:?Falta email}
        FRONTEND=${4:?Falta origen frontend}
    fi

    acquire_lock

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
            FRONTEND_ORIGIN=$(echo "$FRONTEND" | sed -E 's|(https?://[^/]+).*|\1|')
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
FRONTEND_URLS=$FRONTEND_ORIGIN,http://localhost:4200,http://127.0.0.1:4200
PASSWORD_RESET_URL=$FRONTEND/restablecer-contrasena
COOKIE_SECURE=False
MEDIA_ROOT=/var/lib/taji/media
CACHE_DIR=/var/cache/taji
ENV
            chown root:taji "$ENV_FILE"; chmod 0640 "$ENV_FILE"
            unset DB_PASSWORD SECRET FRONTEND_ORIGIN
        fi

        if [[ ! -d $ROOT/repository.git ]]; then
            (git clone --bare "$REPO" "$ROOT/repository.git" >/dev/null 2>&1) &
            animated_progress_bar $! "Clonando repositorio bare Git Backend"
        fi

        rm -f /etc/nginx/sites-enabled/default

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

        if [[ -f /etc/nginx/sites-available/taji-web ]]; then
            ln -sf /etc/nginx/sites-available/taji-web /etc/nginx/sites-enabled/taji-web
            rm -f /etc/nginx/sites-enabled/taji-backend
        else
            ln -sf /etc/nginx/sites-available/taji-backend /etc/nginx/sites-enabled/taji-backend
        fi
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

    do_deploy_backend
    release_lock
}

if [[ $# -gt 0 ]]; then
    run_action "$@"
    exit 0
fi

while true; do
    animated_banner
    echo -e "${BRIGHT_YELLOW}+------------------------------------------------------------------------+${RESET}"
    echo -e "${BRIGHT_YELLOW}|                      MENU INTERACTIVO DE OPERACIONES                   |${RESET}"
    echo -e "${BRIGHT_YELLOW}+------------------------------------------------------------------------+${RESET}"
    echo -e "|  ${BRIGHT_CYAN}[1] ${RESET} ${WHITE}[+] Instalacion Completa Inicial (PostgreSQL + Django + Nginx)${RESET}   |"
    echo -e "|  ${BRIGHT_CYAN}[2] ${RESET} ${WHITE}[*] Actualizar Version (git pull + Migration + Zero-Downtime)${RESET}   |"
    echo -e "|  ${BRIGHT_CYAN}[3] ${RESET} ${WHITE}[#] Sincronizar Cambios de Git (git pull origin main)${RESET}           |"
    echo -e "|  ${BRIGHT_CYAN}[4] ${RESET} ${WHITE}[@] Crear / Actualizar Superusuario (Admin)${RESET}                      |"
    echo -e "|  ${BRIGHT_CYAN}[5] ${RESET} ${WHITE}[=] Listar Cuentas de Usuarios Registrados${RESET}                       |"
    echo -e "|  ${BRIGHT_CYAN}[6] ${RESET} ${WHITE}[*] Cambiar Contraseña de Usuario${RESET}                                |"
    echo -e "|  ${BRIGHT_CYAN}[7] ${RESET} ${WHITE}[$] Respaldo de Base de Datos PostgreSQL (.dump)${RESET}                  |"
    echo -e "|  ${BRIGHT_CYAN}[8] ${RESET} ${WHITE}[?] Verificar Estado de Salud API (Health Check)${RESET}                  |"
    echo -e "|  ${BRIGHT_CYAN}[9] ${RESET} ${WHITE}[!] Reiniciar Servicio Gunicorn / Nginx Backend${RESET}                 |"
    echo -e "|  ${BRIGHT_CYAN}[10]${RESET} ${WHITE}[~] Ver Logs en Tiempo Real (CTRL+C para salir)${RESET}                 |"
    echo -e "|  ${BRIGHT_CYAN}[11]${RESET} ${WHITE}[x] Salir${RESET}                                                        |"
    echo -e "${BRIGHT_YELLOW}+------------------------------------------------------------------------+${RESET}\n"
    
    read -p " Selecciona una opcion [1-11]: " CHOICE
    case "$CHOICE" in
        1) run_action "install" || true ;;
        2) run_action "update" || true ;;
        3) run_action "gitpull" || true ;;
        4) run_action "superuser" || true ;;
        5) run_action "users" || true ;;
        6) run_action "password" || true ;;
        7) run_action "backup" || true ;;
        8) run_action "health" || true ;;
        9) run_action "restart" || true ;;
        10) run_action "logs" || true ;;
        11) echo -e "${YELLOW}Operacion finalizada.${RESET}"; exit 0 ;;
        *) echo -e "${RED}Opcion invalida.${RESET}" ;;
    esac

    echo -e "\n${GRAY}------------------------------------------------------------------------${RESET}"
    read -p " Presiona [ENTER] para regresar al menu principal... " _
done
