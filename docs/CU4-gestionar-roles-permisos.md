# CU4: Gestionar Roles y Permisos

## 1. Identificación

| Atributo | Valor |
|---|---|
| **Código** | CU4 |
| **Nombre** | Gestionar Roles y Permisos |
| **Versión** | 1.0 |
| **Estado** | Implementado |
| **Módulo** | Administración del sistema |

## 2. Descripción

Permite al Administrador del sistema consultar la configuración de roles y permisos del condominio, y modificar qué permisos tiene asignado cada rol, respetando las restricciones críticas que protegen la integridad del sistema RBAC.

## 3. Objetivo

Proporcionar una interfaz segura y controlada para que únicamente el Administrador pueda ajustar los permisos de cada rol del sistema, garantizando en todo momento que las reglas de negocio críticas no puedan vulnerarse desde el frontend, el backend ni la API directamente.

## 4. Actores

| Actor | Tipo | Rol en el CU |
|---|---|---|
| **Administrador** | Principal | Gestiona la configuración de roles y permisos |
| **Sistema RBAC** | Secundario | Valida permisos en cada operación |
| **Base de Datos** | Secundario | Persiste la configuración de roles |

## 5. Disparador

El Administrador accede a la sección "Roles y Permisos" desde el panel lateral de navegación, o navega directamente a `/roles-y-permisos`.

## 6. Precondiciones

- El Administrador tiene una sesión activa (JWT cookie válida).
- El usuario autenticado tiene el permiso `manage_roles` en su rol.
- El catálogo de roles y permisos está sincronizado con `rbac.py`.

## 7. Postcondiciones

- Los permisos del rol seleccionado quedan actualizados en la base de datos.
- Los cambios aplican de inmediato a todos los usuarios que tienen ese rol asignado.
- Las restricciones críticas del sistema se mantienen intactas.

## 8. Flujo Principal

1. El Administrador inicia sesión en el sistema.
2. El sistema muestra "Roles y Permisos" en la barra de navegación lateral (visible solo si el usuario tiene `manage_roles`).
3. El Administrador hace clic en "Roles y Permisos".
4. El frontend verifica `permissionGuard('manage_roles')`.
5. El frontend solicita `GET /api/v1/roles/`.
6. El backend verifica `CanManageRoles` → 200 OK con lista de roles activos.
7. El sistema muestra los roles disponibles en una lista lateral.
8. El Administrador selecciona un rol.
9. El frontend solicita `GET /api/v1/roles/{slug}/permissions/`.
10. El backend responde con el detalle del rol y sus permisos actuales.
11. El sistema muestra todos los permisos con checkboxes; los obligatorios y restringidos aparecen deshabilitados.
12. El Administrador activa o desactiva permisos permitidos.
13. El Administrador hace clic en "Guardar cambios".
14. El frontend envía `PATCH /api/v1/roles/{slug}/permissions/` con la lista de códigos seleccionados.
15. El backend valida:
    - Que los códigos existen y están activos.
    - Que no se eliminan permisos obligatorios del Administrador.
    - Que no se asignan permisos restringidos al rol.
    - Que `manage_roles` solo puede asignarse al Administrador.
16. El backend actualiza la relación `role_permission` en base de datos.
17. El sistema devuelve el rol actualizado (200 OK).
18. El frontend muestra "Permisos actualizados correctamente".

## 9. Flujos Alternativos

### A1. Usuario no Administrador intenta acceder al CU4

- **Frontend**: `permissionGuard('manage_roles')` redirige a `/acceso-denegado`.
- **API directa**: `CanManageRoles` devuelve 403 `{"error": {"code": "permission_denied"}}`.

### A2. Se intenta asignar un permiso inexistente

- El backend detecta el código desconocido en `validate_permissions()`.
- Responde 400 con el detalle de los códigos no encontrados.

### A3. Se intenta otorgar a Seguridad el permiso `register_visits`

- El backend detecta la violación en `FORBIDDEN_PERMISSIONS_BY_ROLE['seguridad']`.
- Responde 400 indicando que `register_visits` no puede asignarse al rol Seguridad.

### A4. Se intenta otorgar a Directiva un permiso de escritura

- El backend detecta la violación en `FORBIDDEN_PERMISSIONS_BY_ROLE['directiva']`.
- Responde 400 indicando los permisos que no pueden asignarse a Directiva.

### A5. Se intenta eliminar `manage_roles` del Administrador

- El backend detecta la violación en `MANDATORY_PERMISSIONS_BY_ROLE['administrador']`.
- Responde 400 indicando que el Administrador debe conservar `manage_roles`.

### A6. Error de conexión o servidor

- El frontend captura el error del observable.
- Muestra el mensaje de error sin perder el estado de la sesión ni los checkboxes del usuario.
- Ofrece un botón "Reintentar" en la sección afectada.

## 10. Reglas de Negocio

| Código | Descripción |
|---|---|
| **RN1** | Solo el Administrador puede acceder al CU4. El permiso `manage_roles` es exclusivo de ese rol. |
| **RN1b** | El Administrador no puede perder `manage_roles` (mínimo vital para administrar el sistema). |
| **RN2** | Seguridad y Empleado operativo son roles con permisos separados; no pueden compartir permisos de portería ni de mantenimiento. |
| **RN3** | Solo el Residente puede crear invitaciones de visitas (`register_visits`). Seguridad puede validar, pero no crear. |
| **RN4** | Directiva es de solo lectura: únicamente puede tener permisos `view_*` y `track_*` autorizados. |

## 11. Restricciones Técnicas

- La validación de reglas de negocio ocurre en el **backend** (`RolePermissionsUpdateSerializer`), no solo en el frontend.
- El frontend deshabilita checkboxes para permisos obligatorios y restringidos como ayuda visual, pero el backend rechaza la operación igualmente.
- No es posible saltarse la seguridad mediante Postman, curl, DevTools ni URL directa.

## 12. Requisitos Especiales

- La respuesta de error debe usar el formato estándar `{"error": {"code": "...", "fields": {...}}}`.
- Las operaciones sobre roles deben reflejarse inmediatamente para todos los usuarios con ese rol.
- No se requiere recarga de sesión para que los cambios surtan efecto en usuarios afectados (aplica en el próximo login o refresh de token).

## 13. Matriz de Roles y Permisos del CU4

| Operación | Administrador | Directiva | Residente | Seguridad | Mantenimiento | Limpieza |
|---|---|---|---|---|---|---|
| Listar roles | ✅ | ❌ 403 | ❌ 403 | ❌ 403 | ❌ 403 | ❌ 403 |
| Ver permisos de un rol | ✅ | ❌ 403 | ❌ 403 | ❌ 403 | ❌ 403 | ❌ 403 |
| Listar todos los permisos | ✅ | ❌ 403 | ❌ 403 | ❌ 403 | ❌ 403 | ❌ 403 |
| Actualizar permisos de un rol | ✅ (con restricciones) | ❌ 403 | ❌ 403 | ❌ 403 | ❌ 403 | ❌ 403 |

## 14. Endpoints

| Método | URL | Descripción | Auth |
|---|---|---|---|
| `GET` | `/api/v1/roles/` | Lista todos los roles activos | `manage_roles` |
| `GET` | `/api/v1/roles/permissions/` | Lista todos los permisos activos | `manage_roles` |
| `GET` | `/api/v1/roles/{slug}/permissions/` | Detalle de un rol con sus permisos | `manage_roles` |
| `PATCH` | `/api/v1/roles/{slug}/permissions/` | Actualiza los permisos de un rol | `manage_roles` |

## 15. Criterios de Aceptación

| # | Criterio | Estado |
|---|---|---|
| CA1 | Solo Administrador puede entrar al CU4 | ✅ |
| CA2 | Los roles existentes se muestran correctamente | ✅ |
| CA3 | Los permisos de un rol pueden consultarse | ✅ |
| CA4 | Administrador puede realizar modificaciones permitidas | ✅ |
| CA5 | Backend rechaza configuraciones prohibidas con 400 | ✅ |
| CA6 | Frontend refleja restricciones (checkboxes deshabilitados) | ✅ |
| CA7 | RBAC protege directamente los endpoints | ✅ |
| CA8 | Residente mantiene `register_visits`; Seguridad no puede tenerlo | ✅ |
| CA9 | Seguridad puede `validate_visits`; no puede `register_visits` | ✅ |
| CA10 | Directiva puede ver reportes; no puede gestionar staff | ✅ |
| CA11 | Administrador no puede perder `manage_roles` | ✅ |
| CA12 | Las pruebas correspondientes pasan (49/49) | ✅ |
| CA13 | No se rompen funcionalidades existentes | ✅ |

## 16. Archivos Implementados

### Backend (nuevos)
- `accounts/permissions.py` — clase `CanManageRoles`
- `accounts/roles_urls.py` — URL patterns del CU4

### Backend (modificados)
- `accounts/rbac.py` — permiso `manage_roles` + constantes de reglas de negocio
- `accounts/fixtures/initial_roles.json` — permiso pk=33 + administrador actualizado
- `accounts/serializers.py` — `SystemPermissionSerializer`, `RoleDetailSerializer`, `RolePermissionsUpdateSerializer`
- `accounts/views.py` — `RoleListView`, `AllPermissionsView`, `RolePermissionsView`
- `accounts/tests.py` — 24 tests nuevos en `RoleManagementApiTests`
- `config/urls.py` — montaje de `/api/v1/roles/`

### Frontend (nuevos)
- `src/app/features/roles/roles.models.ts`
- `src/app/features/roles/roles.api.ts`
- `src/app/features/roles/roles.page.ts`
- `src/app/features/roles/roles.page.scss`

### Frontend (modificados)
- `src/app/core/api/api-endpoints.ts` — endpoints de roles
- `src/app/app.routes.ts` — ruta `/roles-y-permisos`
- `src/app/shared/layout/main-layout.component.ts` — nav item + `canManageRoles` computed

### Diagramas
- `docs/CU4_diagrama_secuencia.puml`
- `docs/CU4_diagrama_comunicacion.puml`
