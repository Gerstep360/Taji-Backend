#!/usr/bin/env bash
# ==============================================================================
# TAJI SAAS - Panel TUI Interactivo de Gestión de Condominios, Tenants y Roles
# Estilo unificado y compatible con el ecosistema de despliegue VPS de Taji.
# ==============================================================================

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- Carga Automática de Variables de Entorno ---
for env_candidate in "/etc/taji/backend.env" "/opt/taji/current/.env" "$SCRIPT_DIR/.env" "$SCRIPT_DIR/../.env"; do
    if [[ -f "$env_candidate" ]]; then
        set -a
        # shellcheck source=/dev/null
        source "$env_candidate" 2>/dev/null || true
        set +a
        break
    fi
done

# Detección del módulo de settings
if [[ -f "/opt/taji/current/.venv/bin/python" ]] || [[ -f "/etc/taji/backend.env" ]]; then
    export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings_production}"
else
    export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings}"
fi

# Resolución del intérprete Python
if [[ -f "/opt/taji/current/.venv/bin/python" ]]; then
    PYTHON="/opt/taji/current/.venv/bin/python"
elif [[ -f "$SCRIPT_DIR/.venv/bin/python" ]]; then
    PYTHON="$SCRIPT_DIR/.venv/bin/python"
elif [[ -f "$SCRIPT_DIR/.venv/Scripts/python.exe" ]]; then
    PYTHON="$SCRIPT_DIR/.venv/Scripts/python.exe"
else
    PYTHON="python3"
fi

# --- Colores ANSI (idénticos a vps.sh) ---
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
    echo -e "${BRIGHT_CYAN}|   ╚══██╔══╝██╔══██╗   ██║   ██║   ${BRIGHT_WHITE}G E S T O R   S a a S                ${BRIGHT_CYAN}|${RESET}"
    echo -e "${YELLOW}|      ██║   ███████║   ██║   ██║   ${BRIGHT_YELLOW}T E N A N T S  &  R O L E S          ${YELLOW}|${RESET}"
    echo -e "${MAGENTA}|      ██║   ██║  ██║██   ██║ ██║                                        |${RESET}"
    echo -e "${BRIGHT_MAGENTA}|      ██║   ██║  ██║╚█████╔╝ ██║   ${BRIGHT_GREEN}[*] PANEL DE CONFIGURACION INTERACTIVO${BRIGHT_MAGENTA}|${RESET}"
    echo -e "${BRIGHT_MAGENTA}|      ╚═╝   ╚═╝  ╚═╝ ╚════╝  ╚═╝                                        |${RESET}"
    echo -e "${BRIGHT_CYAN}+------------------------------------------------------------------------+${RESET}"
    echo -e "${GRAY}        =========================================================${RESET}\n"
}

run_manage() {
    "$PYTHON" manage.py manage_tenants "$@"
}

op_list() {
    echo -e "\n${BRIGHT_CYAN}=== LISTA DE CONDOMINIOS (TENANTS) Y USUARIOS DEL SISTEMA ===${RESET}\n"
    run_manage list
}

op_set_tenant() {
    echo -e "\n${YELLOW}=== ASIGNAR O CAMBIAR DE CONDOMINIO (TENANT) A UN USUARIO ===${RESET}\n"
    read -rp "  Correo del usuario: " USER_EMAIL
    read -rp "  ID o Slug del Condominio de destino: " CONDO_ID
    read -rp "  Rol en el condominio (Enter para conservar rol actual): " USER_ROLE
    echo ""
    if [[ -n "$USER_ROLE" ]]; then
        run_manage set_tenant --email="$USER_EMAIL" --condo="$CONDO_ID" --role="$USER_ROLE"
    else
        run_manage set_tenant --email="$USER_EMAIL" --condo="$CONDO_ID"
    fi
}

op_set_role() {
    echo -e "\n${YELLOW}=== CAMBIAR ROL DE USUARIO ===${RESET}\n"
    read -rp "  Correo del usuario: " USER_EMAIL
    echo -e "  ${GRAY}Roles disponibles: administrador, seguridad, directiva, residente, limpieza, mantenimiento${RESET}"
    read -rp "  Nuevo rol (slug): " USER_ROLE
    read -rp "  ID de Condominio específico (Enter para aplicar al condominio predeterminado): " CONDO_ID
    echo ""
    if [[ -n "$CONDO_ID" ]]; then
        run_manage set_role --email="$USER_EMAIL" --role="$USER_ROLE" --condo="$CONDO_ID"
    else
        run_manage set_role --email="$USER_EMAIL" --role="$USER_ROLE"
    fi
}

op_make_admin() {
    echo -e "\n${YELLOW}=== PROMOVER USUARIO A ADMINISTRADOR DE CONDOMINIO ===${RESET}\n"
    read -rp "  Correo del usuario: " USER_EMAIL
    read -rp "  ID del Condominio (Enter para condominio principal): " CONDO_ID
    read -rp "  ¿Otorgar también permisos de Superusuario global? (s/N): " IS_SUPER
    echo ""
    SUPER_FLAG=""
    if [[ "$IS_SUPER" =~ ^[sSyY]$ ]]; then
        SUPER_FLAG="--superuser"
    fi
    if [[ -n "$CONDO_ID" ]]; then
        if [[ -n "$SUPER_FLAG" ]]; then
            run_manage make_admin --email="$USER_EMAIL" --condo="$CONDO_ID" --superuser
        else
            run_manage make_admin --email="$USER_EMAIL" --condo="$CONDO_ID"
        fi
    else
        if [[ -n "$SUPER_FLAG" ]]; then
            run_manage make_admin --email="$USER_EMAIL" --superuser
        else
            run_manage make_admin --email="$USER_EMAIL"
        fi
    fi
}

op_rename_condo() {
    echo -e "\n${YELLOW}=== RENOMBRAR CONDOMINIO (NOMBRE Y SLUG) ===${RESET}\n"
    read -rp "  ID del Condominio a modificar (ej. 1): " CONDO_ID
    read -rp "  Nuevo Nombre oficial (ej. 'Condominio Taji'): " CONDO_NAME
    read -rp "  Nuevo Slug URL (Enter para autogenerar): " CONDO_SLUG
    echo ""
    if [[ -n "$CONDO_SLUG" ]]; then
        run_manage rename_condo --id="$CONDO_ID" --name="$CONDO_NAME" --slug="$CONDO_SLUG"
    else
        run_manage rename_condo --id="$CONDO_ID" --name="$CONDO_NAME"
    fi
}

op_create_condo() {
    echo -e "\n${YELLOW}=== CREAR NUEVO CONDOMINIO (TENANT) ===${RESET}\n"
    read -rp "  Nombre del Condominio: " CONDO_NAME
    read -rp "  Slug URL (Enter para generar automáticamente): " CONDO_SLUG
    read -rp "  Dirección física (opcional): " CONDO_ADDR
    read -rp "  Capacidad máxima de unidades habitacionales (default: 100): " CONDO_UNITS
    CONDO_UNITS="${CONDO_UNITS:-100}"
    read -rp "  Capacidad máxima de residentes autorizados (default: 400): " CONDO_RESIDENTS
    CONDO_RESIDENTS="${CONDO_RESIDENTS:-400}"
    echo ""
    if [[ -n "$CONDO_SLUG" ]]; then
        run_manage create_condo --name="$CONDO_NAME" --slug="$CONDO_SLUG" --address="$CONDO_ADDR" --units="$CONDO_UNITS" --residents="$CONDO_RESIDENTS"
    else
        run_manage create_condo --name="$CONDO_NAME" --address="$CONDO_ADDR" --units="$CONDO_UNITS" --residents="$CONDO_RESIDENTS"
    fi
}

op_sync_default() {
    echo -e "\n${YELLOW}=== VINCULAR USUARIOS HUERFANOS A CONDOMINIO POR DEFECTO ===${RESET}\n"
    read -rp "  ID o Slug del Condominio de destino (Enter para [1] Condominio Taji): " CONDO_ID
    CONDO_ID="${CONDO_ID:-1}"
    echo ""
    run_manage sync_default --condo="$CONDO_ID"
}

op_stripe_status() {
    echo -e "\n${BRIGHT_CYAN}=== ESTADO DE CONFIGURACION STRIPE & SAAS SANDBOX ===${RESET}\n"
    PUB_KEY="${STRIPE_PUBLISHABLE_KEY:-}"
    SEC_KEY="${STRIPE_SECRET_KEY:-}"
    CURR="${STRIPE_CURRENCY:-BOB}"
    echo -e "  Proveedor de pagos : ${WHITE}Stripe${RESET}"
    echo -e "  Moneda por defecto : ${WHITE}${CURR}${RESET}"
    if [[ -n "$PUB_KEY" ]]; then
        echo -e "  Publishable Key    : ${BRIGHT_GREEN}${PUB_KEY:0:14}...${RESET}"
    else
        echo -e "  Publishable Key    : ${YELLOW}[No configurada - Modo Sandbox Activo]${RESET}"
    fi
    if [[ -n "$SEC_KEY" ]]; then
        echo -e "  Secret Key         : ${BRIGHT_GREEN}${SEC_KEY:0:10}**********${RESET}"
    else
        echo -e "  Secret Key         : ${YELLOW}[No configurada - Modo Sandbox Activo]${RESET}"
    fi
    echo -e "\n  ${BRIGHT_GREEN}[OK]${RESET} El modo Sandbox está totalmente activo para pruebas locales y en producción."
    echo -e "  Las suscripciones se aprueban de inmediato sin cargos bancarios reales."
}

op_restart_service() {
    echo -e "\n${YELLOW}=== REINICIANDO SERVICIO TAJI BACKEND ===${RESET}\n"
    if command -v systemctl >/dev/null 2>&1; then
        systemctl restart taji.service 2>/dev/null || echo -e "${RED}[!] No se pudo reiniciar con systemctl.${RESET}"
        sleep 1
        if systemctl is-active --quiet taji.service 2>/dev/null; then
            echo -e "  ${BRIGHT_GREEN}[OK] Servicio taji.service reiniciado y activo.${RESET}"
        fi
    else
        echo -e "  ${YELLOW}[i] Entorno de desarrollo local. No aplica systemctl.${RESET}"
    fi
}

# Si se pasaron argumentos por línea de comandos, ejecutarlos directamente
if [[ $# -gt 0 ]]; then
    run_manage "$@"
    exit 0
fi

# Bucle interactivo principal
while true; do
    animated_banner
    echo -e "${BRIGHT_YELLOW}+------------------------------------------------------------------------+${RESET}"
    echo -e "${BRIGHT_YELLOW}|             PANEL INTERACTIVO DE TENANTS Y CONDOMINIOS (SAAS)          |${RESET}"
    echo -e "${BRIGHT_YELLOW}+------------------------------------------------------------------------+${RESET}"
    echo -e "|  ${BRIGHT_CYAN}[1] ${RESET} ${WHITE}[=] Listar condominios, usuarios y membresias activas${RESET}           |"
    echo -e "|  ${BRIGHT_CYAN}[2] ${RESET} ${WHITE}[+] Asignar o cambiar de condominio a un usuario${RESET}                 |"
    echo -e "|  ${BRIGHT_CYAN}[3] ${RESET} ${WHITE}[*] Cambiar rol de usuario (administrador, seguridad, etc.)${RESET}    |"
    echo -e "|  ${BRIGHT_CYAN}[4] ${RESET} ${WHITE}[@] Promover usuario a Administrador / Superusuario${RESET}             |"
    echo -e "|  ${BRIGHT_CYAN}[5] ${RESET} ${WHITE}[~] Renombrar un condominio (ej. 'Condominio Taji')${RESET}              |"
    echo -e "|  ${BRIGHT_CYAN}[6] ${RESET} ${WHITE}[#] Crear un nuevo Condominio (Nuevo Tenant SaaS)${RESET}               |"
    echo -e "|  ${BRIGHT_CYAN}[7] ${RESET} ${WHITE}[>] Sincronizar usuarios huerfanos al Condominio principal${RESET}       |"
    echo -e "|  ${BRIGHT_CYAN}[8] ${RESET} ${WHITE}[$] Ver estado de pasarela Stripe / Modo Sandbox${RESET}                 |"
    echo -e "|  ${BRIGHT_CYAN}[9] ${RESET} ${WHITE}[!] Reiniciar servicio de Backend (taji.service)${RESET}                |"
    echo -e "|  ${BRIGHT_CYAN}[0] ${RESET} ${WHITE}[x] Salir${RESET}                                                        |"
    echo -e "${BRIGHT_YELLOW}+------------------------------------------------------------------------+${RESET}\n"

    read -rp " Selecciona una opcion [0-9]: " OPTION
    case "$OPTION" in
        1) op_list ;;
        2) op_set_tenant ;;
        3) op_set_role ;;
        4) op_make_admin ;;
        5) op_rename_condo ;;
        6) op_create_condo ;;
        7) op_sync_default ;;
        8) op_stripe_status ;;
        9) op_restart_service ;;
        0) echo -e "\n${YELLOW}Operacion finalizada.${RESET}\n"; exit 0 ;;
        *) echo -e "\n${RED}Opcion no valida.${RESET}" ;;
    esac

    echo -e "\n${GRAY}------------------------------------------------------------------------${RESET}"
    read -rp " Presiona [ENTER] para regresar al menu principal... " _
done
