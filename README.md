```text
 ╔══════════════════════════════════════════════════════════════════════════════╗
 ║                                                                              ║
 ║   ████████╗  █████╗  ██████╗ ██╗    ██████╗  █████╗  ██████╗ ██╗  ██╗        ║
 ║   ╚══██╔══╝ ██╔══██╗   ██╔══╝██║    ██╔══██╗██╔══██╗██╔════╝ ██║ ██╔╝        ║
 ║      ██║    ███████║   ██║   ██║    ██████╔╝███████║██║      █████═╝         ║
 ║      ██║    ██╔══██║██   ██║ ██║    ██╔══██╗██╔══██║██║      ██╔═██╗         ║
 ║      ██║    ██║  ██║╚█████╔╝ ██║    ██████╔╝██║  ██║╚██████╗ ██║  ██╗        ║
 ║      ╚═╝    ╚═╝  ╚═╝ ╚════╝  ╚═╝    ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝        ║
 ║                                                                              ║
 ║                     TAJI — backend para condominios                          ║
 ║                    Django 5 REST Framework / PostgreSQL                      ║
 ╚══════════════════════════════════════════════════════════════════════════════╝
```

# TAJI Backend API — Sistema de Gestión de Condominios

La organización actual por CU y los detalles de integración están en
[Paquetes y Sprint 1](docs/PAQUETES-Y-SPRINT1.md). Para instalar o actualizar el
backend en un VPS con PostgreSQL, Nginx y HTTPS, consulta
[Despliegue](deploy/README.md).

Plataforma backend desarrollada con **Django 5**, **Django REST Framework (DRF)** y **PostgreSQL**. Ofrece autenticación basada en **JWT (SimpleJWT)** con RBAC (Control de Acceso Basado en Roles), 7 roles, 33 permisos y un modelo de dominio organizado en cinco paquetes.

---

## Base REST y Swagger (T003 / T058)

- DRF usa JSON, autenticación JWT/cookie, permisos autenticados por defecto y throttling por operación.
- Los listados usan paginación por página (`page`, `page_size`, máximo 100).
- Todos los errores siguen `{"error":{"code","message","fields?"}}`.
- Swagger UI: `http://localhost:8000/api/v1/docs/`.
- OpenAPI: `http://localhost:8000/api/v1/openapi/`.
- El contrato completo está en `docs/API.md`.

El registro crea `Person` y `User` dentro de una transacción, normaliza el correo, valida nombres/teléfono/contraseña y controla conflictos concurrentes sin dejar datos huérfanos.

---

## Requisitos Previos

- **Python 3.10+** (recomendado Python 3.11 o 3.12)
- **PowerShell** (para entornos Windows, incluido en Windows 10/11)
- **PostgreSQL** (opcional para desarrollo local; se puede usar SQLite por defecto mediante `.env`)

---

## Instalación y Configuración del Entorno

Puedes preparar e instalar las dependencias del proyecto de dos formas: mediante el script automático de PowerShell o usando comandos CLI manuales.

### Opción 1: Mediante Script de PowerShell (Recomendado)

Abre una terminal PowerShell en el directorio `Backend` y ejecuta:

```powershell
.\instalar_requerimientos.ps1
```

Este script automatiza los siguientes pasos:
1. Detecta la instalación de Python en tu sistema (`python` o `py`).
2. Crea el entorno virtual en la carpeta `.venv` si no existe.
3. Actualiza `pip` a la versión más reciente.
4. Instala todas las dependencias listadas en [requirements.txt](file:///c:/Users/rojas/Documents/Proyectos/Sistemas%20de%20informacion%20II/Backend/requirements.txt).
5. Crea el archivo de variables de entorno `.env` a partir de [.env.example](file:///c:/Users/rojas/Documents/Proyectos/Sistemas%20de%20informacion%20II/Backend/.env.example) si no existía.

---

### Opción 2: Mediante Comandos Manuales (CLI)

Si prefieres realizar el proceso paso a paso por consola:

1. **Navegar a la carpeta Backend**:
   ```powershell
   cd Backend
   ```

2. **Crear el entorno virtual Python**:
   ```powershell
   python -m venv .venv
   ```

3. **Activar el entorno virtual**:
   - **PowerShell**:
     ```powershell
     .\.venv\Scripts\Activate.ps1
     ```
   - **Command Prompt (cmd.exe)**:
     ```cmd
     .venv\Scripts\activate.bat
     ```
   - **Git Bash / Linux / macOS**:
     ```bash
     source .venv/bin/activate
     ```

4. **Actualizar pip e instalar dependencias**:
   ```powershell
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

5. **Configurar el archivo de entorno (`.env`)**:
   ```powershell
   Copy-Item .env.example .env
   ```

---

## Cómo Ejecutar el Servidor Backend

### Opción 1: Mediante Scripts PowerShell (Recomendado para Red Local / MVP)

Para habilitar la comunicación entre el Backend, la Web Angular y la App Móvil Flutter en tu red local:

```powershell
.\iniciar.ps1
```

#### Parámetros opcionales del script `iniciar.ps1`:
- **`-MachineIp`**: Especifica manualmente una dirección IP local (por defecto se detecta automáticamente la interfaz LAN activa).
- **`-ApiPort`**: Define el puerto de escucha (por defecto `8000`).

**Ejemplos de uso:**
```powershell
# Usar una IP específica
.\iniciar.ps1 -MachineIp "192.168.100.50"

# Cambiar el puerto
.\iniciar.ps1 -ApiPort 8080
```

---

### Opción 2: Mediante Comandos Manuales (CLI)

1. **Activar el entorno virtual**:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

2. **Ejecutar migraciones de la base de datos**:
   ```powershell
   python manage.py migrate
   ```

3. **Crear un superusuario (Administrador)** (Opcional):
   ```powershell
   python manage.py createsuperuser
   ```

4. **Iniciar el servidor de desarrollo**:
   - Escuchar solo en `localhost`:
     ```powershell
     python manage.py runserver
     ```
   - Escuchar en todas las interfaces de red (`0.0.0.0` para acceso desde celulares u otros equipos de la red):
     ```powershell
     python manage.py runserver 0.0.0.0:8000
     ```

---

## Scripts PowerShell Incluidos

El proyecto Backend incluye tres scripts automatizados en PowerShell para facilitar el flujo de trabajo:

| Script | Descripción | Parámetros Principales |
| --- | --- | --- |
| [instalar_requerimientos.ps1](file:///c:/Users/rojas/Documents/Proyectos/Sistemas%20de%20informacion%20II/Backend/instalar_requerimientos.ps1) | Detecta Python, crea el `.venv`, instala dependencias de `requirements.txt` y prepara el `.env`. | Ninguno |
| [iniciar.ps1](file:///c:/Users/rojas/Documents/Proyectos/Sistemas%20de%20informacion%20II/Backend/iniciar.ps1) | Detecta la IP IPv4 activa en la LAN, configura las variables `ALLOWED_HOSTS`, `FRONTEND_URLS`, `PASSWORD_RESET_URL` e invoca `run-dev.ps1`. | `-MachineIp` (string), `-ApiPort` (int) |
| [run-dev.ps1](file:///c:/Users/rojas/Documents/Proyectos/Sistemas%20de%20informacion%20II/Backend/run-dev.ps1) | Verifica que exista `.venv`, ejecuta las migraciones (`manage.py migrate`) y levanta `manage.py runserver`. | `-Address` (default `"0.0.0.0:8000"`) |

---

## Estructura del Proyecto y Apps Django

El Backend está subdividido en las siguientes aplicaciones especializadas:

```text
Backend/
├── accounts/        # Autenticación, usuarios, roles, permisos y JWT
├── condominiums/    # Condominios, sectores, unidades, residentes y personal
├── auditlog/        # Bitácora inmutable de auditoría (append-only)
├── security/        # Control de visitas, accesos, turnos y reconocimiento facial
├── incidents/       # Incidencias, históricos y catalogación para IA
├── maintenance/     # Activos, proveedores, planes de mantenimiento y órdenes
├── community/       # Áreas comunes, reservas, asambleas y acuerdos
├── notifications/   # Comunicados, dispositivos y notificaciones push
├── config/          # Ajustes globales de Django (settings, urls, wsgi/asgi)
├── .env.example     # Plantilla de configuración de variables de entorno
├── iniciar.ps1      # Script de lanzamiento con autodetección de IP LAN
├── run-dev.ps1      # Script de ejecución de migraciones y servidor
├── instalar_requerimientos.ps1 # Script de instalación de entorno y dependencias
├── manage.py        # CLI de administración de Django
└── requirements.txt # Lista de dependencias del proyecto
```

---

## Endpoints Principales de la API

| Método | Ruta | Descripción |
| --- | --- | --- |
| `POST` | `/api/v1/auth/register/` | Registro de residente / copropietario |
| `POST` | `/api/v1/auth/login/` | Inicio de sesión (Retorna JWT / Cookies HttpOnly) |
| `POST` | `/api/v1/auth/refresh/` | Rotación de token de sesión |
| `POST` | `/api/v1/auth/logout/` | Revocación de sesión |
| `GET`  | `/api/v1/auth/me/` | Obtener perfil, rol y permisos del usuario actual |
| `POST` | `/api/v1/auth/forgot-password/` | Solicitud de restablecimiento de contraseña |
| `POST` | `/api/v1/auth/reset-password/` | Confirmación y guardado de nueva contraseña |
| `GET`  | `/api/v1/health/` | Verificación de salud del servicio |
| `GET`  | `/api/docs/` | Documentación interactiva Swagger / OpenAPI |

---

## Pruebas Unitarias y Verificación

Para ejecutar la suite de pruebas del backend con configuraciones aisladas de test:

```powershell
# Aplicar migraciones de prueba
.\.venv\Scripts\python.exe manage.py migrate --settings=config.settings_test

# Ejecutar tests
.\.venv\Scripts\python.exe manage.py test --settings=config.settings_test
```
