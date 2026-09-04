# CU05: Gestionar Residentes y Copropietarios

## 1. Identificación

| Atributo | Valor |
|---|---|
| **Código** | CU05 |
| **Nombre** | Gestionar Residentes y Copropietarios |
| **Tareas asociadas** | T014 (Backend · CRUD de residentes y copropietarios) · T082 (Frontend Web · gestión de residentes/copropietarios, sin asociación a unidades) |
| **Versión** | 1.0 |
| **Estado** | Implementado |
| **Módulo** | Administración del condominio |

## 2. Descripción

Permite al Administrador del condominio registrar, consultar, listar, editar y activar/desactivar a las personas que tienen la condición de residente o copropietario dentro del condominio, gestionando sus datos personales, documento de identidad, información de contacto y estado, sin asociarlas todavía a una unidad habitacional específica (esa asociación corresponde a CU06).

## 3. Objetivo

Proporcionar al Administrador una pantalla dentro de su panel para mantener actualizado el directorio de residentes y copropietarios del condominio, reutilizando `Person` como fuente única de datos personales y sin duplicar información ni tablas ya existentes en el sistema.

## 4. Actores

| Actor | Tipo | Rol en el CU |
|---|---|---|
| **Administrador** | Principal | Registra, consulta, edita y activa/desactiva residentes y copropietarios |
| **Sistema RBAC** | Secundario | Valida el permiso `manage_residents` en cada operación |
| **Base de Datos** | Secundario | Persiste `Person` y `Resident` |

## 5. Disparador

El Administrador accede a la sección "Residentes y copropietarios" desde el panel lateral de navegación, o navega directamente a `/residentes-y-copropietarios`.

## 6. Precondiciones

- El Administrador tiene una sesión activa (JWT cookie válida).
- El usuario autenticado tiene el permiso `manage_residents` en su rol (ya sembrado en `accounts/rbac.py` para el rol "administrador").

## 7. Postcondiciones

- El residente/copropietario queda registrado o actualizado en la base de datos (`Person` + `Resident`).
- El estado (`ACTIVE`/`INACTIVE`/`BLOCKED`) queda reflejado, junto con `deactivated_at` cuando corresponde.
- `Person` continúa siendo la única fuente de datos personales; no se crean duplicados.
- No se crea, modifica ni elimina ninguna unidad habitacional ni asociación residente-unidad (CU06 queda intacto).

## 8. Flujo Principal

1. El Administrador inicia sesión en el sistema.
2. El sistema muestra "Residentes y copropietarios" en la barra de navegación lateral (visible solo si el usuario tiene `manage_residents`).
3. El Administrador hace clic en "Residentes y copropietarios".
4. El frontend verifica `permissionGuard('manage_residents')`.
5. El frontend solicita `GET /api/v1/residents/`.
6. El backend verifica `CanManageResidents` → 200 OK con lista paginada de residentes.
7. El sistema muestra el directorio con nombre, documento, contacto, fecha de registro y estado.
8. El Administrador hace clic en "Nuevo residente" (o "Editar" sobre uno existente).
9. El Administrador completa el formulario (identidad, documento, contacto, estado, notas) y guarda.
10. El frontend envía `POST /api/v1/residents/` (registrar) o `PATCH /api/v1/residents/{id}/` (editar).
11. El backend valida los datos y, si son correctos, persiste `Person` y `Resident` en una única transacción.
12. El sistema devuelve el registro guardado (201 o 200) y el frontend confirma y refresca el directorio.

## 9. Flujos Alternativos

### A1. Usuario sin permiso `manage_residents` intenta acceder al CU05

- **Frontend**: `permissionGuard('manage_residents')` redirige a `/acceso-denegado`.
- **API directa**: `CanManageResidents` devuelve 403 `{"error": {"code": "permission_denied"}}`.

### A2. Documento de identidad duplicado

- El backend detecta que ya existe una `Person` con el mismo `document_type` + `document_number` + `document_complement`.
- Responde 400 `validation_error` con el error en el campo `document_number`.

### A3. Campos obligatorios faltantes (nombres, apellidos)

- El backend responde 400 `validation_error` con el detalle por campo.
- El frontend marca los campos y explica la corrección requerida.

### A4. Consultar, editar o cambiar estado de un residente inexistente

- El backend responde 404 `not_found`.

### A5. Activar / desactivar residente

- El Administrador pulsa "Desactivar" (con confirmación) o "Activar" sobre un residente.
- El frontend envía `PATCH /api/v1/residents/{id}/` con `{"status": "..."}`.
- El backend actualiza `status` y ajusta `deactivated_at` automáticamente (se fija al desactivar, se limpia al reactivar), **sin eliminar el registro**.

### A6. Error de conexión o servidor

- El frontend captura el error del observable y muestra el mensaje sin perder el estado del formulario ni la sesión.
- Ofrece un botón "Reintentar" en la sección afectada.

## 10. Reglas de Negocio

| Código | Descripción |
|---|---|
| **RN1** | Solo un usuario con el permiso `manage_residents` (por defecto, el rol Administrador) puede gestionar residentes y copropietarios. |
| **RN2** | `Person` es la fuente única de datos personales; CU05 no duplica nombre, documento, contacto ni fecha de nacimiento en otra tabla. |
| **RN3** | La baja de un residente es lógica (`status` + `deactivated_at`); no se elimina físicamente el registro (`DELETE` no está expuesto en el endpoint). |
| **RN4** | CU05 no gestiona la asociación de un residente con una unidad habitacional (bloque, torre, piso, unidad, propietario/inquilino/familiar/autorizado respecto a una unidad); esa relación es responsabilidad exclusiva de CU06 sobre `ResidentUnit`. |

## 11. Restricciones Técnicas

- La validación de datos y reglas ocurre en el **backend** (`ResidentSerializer`), no solo en el frontend.
- El backend protege los endpoints con `IsAuthenticated` + `CanManageResidents`; no basta con ocultar el enlace en el sidebar.
- El formulario del frontend no incluye ningún campo de sector, bloque, torre, piso o unidad (verificado con prueba automatizada).

## 12. Requisitos Especiales

- La respuesta de error usa el formato estándar de la API (`{"error": {"code": "...", "fields": {...}}}`), definido por T003.
- La paginación sigue el contrato estándar (`pagination` + `results`) usado por el resto de listados del sistema.

## 13. Matriz de Roles y Permisos del CU05

| Operación | Administrador | Directiva | Residente | Seguridad | Mantenimiento | Limpieza |
|---|---|---|---|---|---|---|
| Listar / consultar residentes | ✅ | ❌ 403 | ❌ 403 | ❌ 403 | ❌ 403 | ❌ 403 |
| Registrar residente | ✅ | ❌ 403 | ❌ 403 | ❌ 403 | ❌ 403 | ❌ 403 |
| Editar residente | ✅ | ❌ 403 | ❌ 403 | ❌ 403 | ❌ 403 | ❌ 403 |
| Activar / desactivar residente | ✅ | ❌ 403 | ❌ 403 | ❌ 403 | ❌ 403 | ❌ 403 |

## 14. Endpoints

| Método | URL | Descripción | Auth |
|---|---|---|---|
| `GET` | `/api/v1/residents/` | Lista residentes (búsqueda, filtro de estado, orden, paginación) | `manage_residents` |
| `GET` | `/api/v1/residents/{id}/` | Detalle de un residente | `manage_residents` |
| `POST` | `/api/v1/residents/` | Registra un residente/copropietario | `manage_residents` |
| `PATCH`/`PUT` | `/api/v1/residents/{id}/` | Edita datos o cambia el estado (activar/desactivar) | `manage_residents` |
| `GET` | `/api/v1/residents/options/` | Catálogos (estados, tipos de documento) | `manage_residents` |

## 15. Criterios de Aceptación

| # | Criterio | Estado |
|---|---|---|
| CA1 | Solo un usuario con `manage_residents` puede entrar al CU05 | ✅ |
| CA2 | El listado de residentes se muestra con búsqueda, filtro de estado y paginación | ✅ |
| CA3 | Se puede registrar un residente/copropietario nuevo | ✅ |
| CA4 | Se puede consultar el detalle de un residente | ✅ |
| CA5 | Se pueden editar los datos permitidos | ✅ |
| CA6 | Se puede activar/desactivar sin eliminar el registro | ✅ |
| CA7 | El backend rechaza documento duplicado con 400 | ✅ |
| CA8 | El backend rechaza campos obligatorios faltantes con 400 | ✅ |
| CA9 | El backend protege los endpoints con RBAC (403 sin permiso, 401 sin sesión) | ✅ |
| CA10 | No se implementó asociación a unidades ni ningún elemento de CU06 | ✅ |
| CA11 | `Person` sigue siendo la única fuente de datos personales (sin duplicados) | ✅ |
| CA12 | No se creó ninguna migración ni tabla adicional | ✅ |
| CA13 | Las pruebas correspondientes pasan (93/93 backend, 20/20 frontend) | ✅ |
| CA14 | No se rompieron funcionalidades existentes de otros CU | ✅ |

## 16. Archivos Implementados

### Backend (modificados)
- `condominiums/permissions.py` — clase `CanManageResidents`
- `condominiums/serializers.py` — `ResidentSerializer`
- `condominiums/views.py` — `ResidentViewSet`
- `condominiums/urls.py` — registro del router `residents`
- `condominiums/tests.py` — 16 tests nuevos en `ResidentApiTests`
- `config/settings.py` — tag OpenAPI "Residentes"

### Backend (reutilizados sin cambios)
- `condominiums/models.py` — `Resident` (ya existía, migrado en `0001_initial`)
- `accounts/models.py` — `Person`
- `accounts/rbac.py` — permiso `manage_residents` (ya sembrado y asignado al rol Administrador)

### Frontend (nuevos)
- `src/app/features/residents/resident.models.ts`
- `src/app/features/residents/resident.api.ts`
- `src/app/features/residents/resident.page.ts`
- `src/app/features/residents/resident.page.scss`
- `src/app/features/residents/resident-editor.component.ts`
- `src/app/features/residents/resident-editor.component.scss`

### Frontend (modificados)
- `src/app/core/api/api-endpoints.ts` — endpoints de residentes
- `src/app/app.routes.ts` — ruta `/residentes-y-copropietarios`
- `src/app/shared/layout/main-layout.component.ts` — nav item + `canManageResidents` computed

### Diagramas
- `docs/CU05_diagrama_secuencia.puml`
- `docs/CU05_diagrama_comunicacion.puml`
