#!/usr/bin/env bash
# ==============================================================================
# TAJI SAAS - Script de Gestión de Tenancy, Condominios y Roles de Usuario
# ==============================================================================
# Permite listar condominios/tenants, cambiar de tenant a los usuarios,
# asignar administradores, cambiar roles y sincronizar membresías.
#
# Uso CLI:
#   ./config.sh list
#   ./config.sh set-tenant <email> <condo_id_o_slug> [role_slug]
#   ./config.sh set-role <email> <role_slug> [condo_id]
#   ./config.sh make-admin <email> [condo_id] [--superuser]
#   ./config.sh rename-condo <id> "<nombre>" [slug]
#   ./config.sh sync-default [condo_id]
#   ./config.sh (sin argumentos: Menú Interactivo)
# ==============================================================================

set -e

# Detectar ruta del proyecto y entorno virtual Python
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -f "/opt/taji/current/.venv/bin/python" ]]; then
    PYTHON="/opt/taji/current/.venv/bin/python"
    SETTINGS="--settings=config.settings_production"
elif [[ -f "$SCRIPT_DIR/.venv/bin/python" ]]; then
    PYTHON="$SCRIPT_DIR/.venv/bin/python"
    SETTINGS=""
elif [[ -f "$SCRIPT_DIR/.venv/Scripts/python.exe" ]]; then
    PYTHON="$SCRIPT_DIR/.venv/Scripts/python.exe"
    SETTINGS=""
else
    PYTHON="python3"
    SETTINGS=""
fi

run_manage() {
    if [[ -n "$SETTINGS" ]]; then
        "$PYTHON" manage.py manage_tenants "$@" "$SETTINGS"
    else
        "$PYTHON" manage.py manage_tenants "$@"
    fi
}

show_menu() {
    clear
    echo "=================================================================="
    echo "       TAJI SAAS - PANEL DE GESTION DE TENANTS Y USUARIOS"
    echo "=================================================================="
    echo " [1] Listar condominios, usuarios y membresías"
    echo " [2] Asignar / Cambiar usuario a un condominio (Tenant)"
    echo " [3] Cambiar rol de un usuario (administrador, seguridad, residente)"
    echo " [4] Promover usuario a Administrador de Condominio (+ Staff)"
    echo " [5] Renombrar un condominio (ej. 'Condominio Taji')"
    echo " [6] Vincular usuarios huérfanos al condominio principal (Sync)"
    echo " [0] Salir"
    echo "=================================================================="
    read -rp "Selecciona una opción [0-6]: " OPTION

    case "$OPTION" in
        1)
            echo ""
            run_manage list
            echo ""
            read -rp "Presiona [ENTER] para volver al menú..." _
            show_menu
            ;;
        2)
            echo ""
            read -rp "Correo del usuario: " USER_EMAIL
            read -rp "ID o Slug del Condominio de destino: " CONDO_ID
            read -rp "Rol en el condominio (Enter para mantener el actual): " USER_ROLE
            if [[ -n "$USER_ROLE" ]]; then
                run_manage set_tenant --email="$USER_EMAIL" --condo="$CONDO_ID" --role="$USER_ROLE"
            else
                run_manage set_tenant --email="$USER_EMAIL" --condo="$CONDO_ID"
            fi
            echo ""
            read -rp "Presiona [ENTER] para volver al menú..." _
            show_menu
            ;;
        3)
            echo ""
            read -rp "Correo del usuario: " USER_EMAIL
            echo "Roles comunes: administrador, seguridad, directiva, residente, limpieza, mantenimiento"
            read -rp "Nuevo rol (slug): " USER_ROLE
            read -rp "ID de Condominio específico (Enter para aplicar a todos): " CONDO_ID
            if [[ -n "$CONDO_ID" ]]; then
                run_manage set_role --email="$USER_EMAIL" --role="$USER_ROLE" --condo="$CONDO_ID"
            else
                run_manage set_role --email="$USER_EMAIL" --role="$USER_ROLE"
            fi
            echo ""
            read -rp "Presiona [ENTER] para volver al menú..." _
            show_menu
            ;;
        4)
            echo ""
            read -rp "Correo del usuario a promover: " USER_EMAIL
            read -rp "ID del Condominio (Enter para usar el actual): " CONDO_ID
            read -rp "¿Otorgar también permisos de Superusuario global? (s/N): " IS_SUPER
            SUPER_FLAG=""
            if [[ "$IS_SUPER" =~ ^[sSyY]$ ]]; then
                SUPER_FLAG="--superuser"
            fi
            if [[ -n "$CONDO_ID" ]]; then
                run_manage make_admin --email="$USER_EMAIL" --condo="$CONDO_ID" $SUPER_FLAG
            else
                run_manage make_admin --email="$USER_EMAIL" $SUPER_FLAG
            fi
            echo ""
            read -rp "Presiona [ENTER] para volver al menú..." _
            show_menu
            ;;
        5)
            echo ""
            read -rp "ID del Condominio a renombrar: " CONDO_ID
            read -rp "Nuevo nombre (ej. 'Condominio Taji'): " CONDO_NAME
            read -rp "Nuevo slug (Enter para omitir): " CONDO_SLUG
            if [[ -n "$CONDO_SLUG" ]]; then
                run_manage rename_condo --id="$CONDO_ID" --name="$CONDO_NAME" --slug="$CONDO_SLUG"
            else
                run_manage rename_condo --id="$CONDO_ID" --name="$CONDO_NAME"
            fi
            echo ""
            read -rp "Presiona [ENTER] para volver al menú..." _
            show_menu
            ;;
        6)
            echo ""
            read -rp "ID o Slug del Condominio principal [Por defecto: 1]: " CONDO_ID
            CONDO_ID="${CONDO_ID:-1}"
            run_manage sync_default --condo="$CONDO_ID"
            echo ""
            read -rp "Presiona [ENTER] para volver al menú..." _
            show_menu
            ;;
        0)
            echo "Hasta luego."
            exit 0
            ;;
        *)
            echo "Opción inválida."
            sleep 1
            show_menu
            ;;
    esac
}

# Modo de línea de comandos (CLI) o Interactivo
CMD="${1:-}"

case "$CMD" in
    ""|"menu"|"interactive")
        show_menu
        ;;
    "list")
        run_manage list
        ;;
    "set-tenant")
        EMAIL="${2:-}"
        CONDO="${3:-}"
        ROLE="${4:-}"
        [[ -n "$EMAIL" && -n "$CONDO" ]] || { echo "Uso: ./config.sh set-tenant <email> <condo_id> [role_slug]"; exit 1; }
        if [[ -n "$ROLE" ]]; then
            run_manage set_tenant --email="$EMAIL" --condo="$CONDO" --role="$ROLE"
        else
            run_manage set_tenant --email="$EMAIL" --condo="$CONDO"
        fi
        ;;
    "set-role")
        EMAIL="${2:-}"
        ROLE="${3:-}"
        CONDO="${4:-}"
        [[ -n "$EMAIL" && -n "$ROLE" ]] || { echo "Uso: ./config.sh set-role <email> <role_slug> [condo_id]"; exit 1; }
        if [[ -n "$CONDO" ]]; then
            run_manage set_role --email="$EMAIL" --role="$ROLE" --condo="$CONDO"
        else
            run_manage set_role --email="$EMAIL" --role="$ROLE"
        fi
        ;;
    "make-admin")
        EMAIL="${2:-}"
        CONDO="${3:-}"
        SUPER="${4:-}"
        [[ -n "$EMAIL" ]] || { echo "Uso: ./config.sh make-admin <email> [condo_id] [--superuser]"; exit 1; }
        EXTRA_ARGS=()
        if [[ "$CONDO" == "--superuser" ]]; then
            EXTRA_ARGS+=("--superuser")
        elif [[ -n "$CONDO" ]]; then
            EXTRA_ARGS+=("--condo=$CONDO")
            if [[ "$SUPER" == "--superuser" ]]; then
                EXTRA_ARGS+=("--superuser")
            fi
        fi
        run_manage make_admin --email="$EMAIL" "${EXTRA_ARGS[@]}"
        ;;
    "rename-condo")
        ID="${2:-}"
        NAME="${3:-}"
        SLUG="${4:-}"
        [[ -n "$ID" && -n "$NAME" ]] || { echo "Uso: ./config.sh rename-condo <id> \"<nombre>\" [slug]"; exit 1; }
        if [[ -n "$SLUG" ]]; then
            run_manage rename_condo --id="$ID" --name="$NAME" --slug="$SLUG"
        else
            run_manage rename_condo --id="$ID" --name="$NAME"
        fi
        ;;
    "sync-default")
        CONDO="${2:-1}"
        run_manage sync_default --condo="$CONDO"
        ;;
    *)
        echo "Comando desconocido '$CMD'."
        echo "Uso: ./config.sh [list | set-tenant | set-role | make-admin | rename-condo | sync-default]"
        exit 1
        ;;
esac
