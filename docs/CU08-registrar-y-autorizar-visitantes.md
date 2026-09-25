# CU08: Registrar y Autorizar Visitantes

## 1. Identificación

| Atributo | Valor |
|---|---|
| **Código** | CU08 |
| **Nombre** | Registrar y autorizar visitantes |
| **Tareas asociadas** | T020 (Backend · Implementar API de visitantes y autorizaciones anticipadas asociadas a residente y unidad) |
| **Versión** | 1.0 |
| **Estado** | Implementado |
| **Módulo** | Seguridad, Accesos y Auditoría (Paquete 2) |

---

## 2. Requisitos

### Requisito Funcional (RF)
> *El sistema debe permitir al residente registrar y autorizar anticipadamente una visita indicando visitante, unidad, motivo y periodo de validez. La administración debe poder consultar y gestionar las autorizaciones registradas.*

### Requisito No Funcional (RNF)
> **Integridad:** Consistencia transaccional de datos.
> **Actores:** Todos los actores que registran o modifican información.
> **Objetivo Asociado:** Evitar estados incompletos o inconsistentes en procesos críticos mediante operaciones atómicas (`transaction.atomic()`).

---

## 3. Descripción

Permite a los residentes crear autorizaciones anticipadas de ingreso para sus visitantes hacia sus unidades habitacionales activas, especificando la información personal del visitante, el motivo de la visita y el rango de validez temporal. Asimismo, otorga a la Administración del condominio la capacidad de auditar, consultar de forma global con filtros y gestionar (editar o cancelar) todas las autorizaciones emitidas en el condominio.

---

## 4. Actores

| Actor | Tipo | Rol en el CU |
|---|---|---|
| **Residente** | Principal | Registra visitas anticipadas a sus unidades asociadas, consulta sus autorizaciones y cancela visitas pendientes. |
| **Administrador** | Secundario / Supervisor | Consulta el listado general de visitas, filtra por unidad, residente o estado, y puede gestionar o cancelar autorizaciones. |
| **Sistema RBAC** | Soporte | Valida los permisos funcionales `register_visits` y `manage_visits`. |
| **Base de Datos** | Soporte | Persiste atómicamente `Person`, `VisitAuthorization` y eventos en `AuditEvent`. |

---

## 5. Precondiciones

1. El usuario tiene una sesión activa (JWT válido vía cookie o cabecera `Authorization: Bearer <token>`).
2. El usuario cuenta con el permiso `register_visits` (Residente o Administrador) o `manage_visits` (Administrador).
3. Si el actor es un Residente, debe contar con un perfil `Resident` activo y tener al menos una asociación activa en `ResidentUnit`.

---

## 6. Postcondiciones

1. La visita queda registrada en `VisitAuthorization` con estado `AUTHORIZED`.
2. Se genera un identificador único seguro `qr_uuid` y una expiración `qr_expires_at` sincronizada con el periodo de validez.
3. Se crea o reutiliza la identidad en `Person` respetando la regla de unicidad por tipo y número de documento, sin duplicar registros.
4. Se registra un evento inmutable en `AuditEvent` (`VISIT_AUTHORIZATION_CREATED`, `VISIT_AUTHORIZATION_UPDATED` o `VISIT_AUTHORIZATION_CANCELLED`).

---

## 7. Flujo Principal (Registro por Residente)

1. El Residente accede a la sección de autorizaciones de visita en la aplicación móvil o web.
2. El sistema solicita y muestra las unidades habitacionales activas asociadas al residente.
3. El Residente selecciona la unidad de destino, introduce los datos del visitante (nombres, apellidos, documento, teléfono opcional), motivo y rango de fechas (`valid_from` y `valid_until`).
4. El cliente envía `POST /api/v1/visit-authorizations/` (o `/api/v1/paquete2/visit-authorizations/`).
5. El backend valida:
   - Permiso `register_visits`.
   - Que la unidad pertenezca a las unidades activas del residente (`ResidentUnit`).
   - Que `valid_until > valid_from` y que no sea una fecha en el pasado.
6. Dentro de una transacción atómica:
   - Resuelve la persona visitante en `Person` (creando un nuevo registro o actualizando contacto si ya existía el documento).
   - Crea `VisitAuthorization` con estado `AUTHORIZED` y UUID de QR.
   - Registra el evento de auditoría en `AuditEvent`.
7. El sistema responde con código `201 Created` y los datos completos de la autorización creada.

---

## 8. Flujo Secundario (Consulta y Gestión por Administración)

1. El Administrador accede al panel de control de accesos y visitas.
2. El cliente solicita `GET /api/v1/visit-authorizations/`.
3. El backend verifica el permiso `manage_visits` y devuelve el listado paginado global, permitiendo aplicar filtros por `unit`, `resident`, `status`, `date_from`, `date_to` y `search`.
4. El Administrador puede consultar el detalle (`GET /{id}/`) o cancelar la autorización (`POST /{id}/cancel/`).

---

## 9. Reglas de Negocio

| Código | Descripción |
|---|---|
| **RN1** | **Asociación Residente-Unidad:** Un residente solo puede autorizar visitas a unidades habitacionales donde mantenga un vínculo activo (`ResidentUnit.end_date IS NULL`). |
| **RN2** | **Periodo de Validez Coherente:** La fecha de fin (`valid_until`) debe ser estrictamente posterior a la fecha de inicio (`valid_from`) y no puede registrarse con fechas pasadas. |
| **RN3** | **Fuente Única de Identidad:** Los visitantes se registran en `Person`. Si se proporciona un número de documento ya existente, el sistema reutiliza la entidad para evitar inconsistencias y redundancia de datos. |
| **RN4** | **Aislamiento de Información:** Los residentes solo tienen visibilidad y control sobre las visitas autorizadas por ellos mismos. Únicamente la administración posee visibilidad global. |
| **RN5** | **Integridad Transaccional:** La creación, actualización y cancelación se ejecutan en bloques transaccionales atómicos (`transaction.atomic()`). Ante cualquier fallo, se revierte la operación garantizando un estado consistente. |
| **RN6** | **Cancelación Segura:** Una autorización solo puede cancelarse si está en estado `AUTHORIZED` o `ACTIVE`. No se permite cancelar visitas ya finalizadas (`FINISHED`) o expiradas (`EXPIRED`). |

---

## 10. Contrato de la API REST

### Endpoints Expuestos

| Método | Endpoint | Permiso requerido | Descripción |
|---|---|---|---|
| `GET` | `/api/v1/visit-authorizations/` | `register_visits` / `manage_visits` | Listado paginado con filtros. |
| `POST` | `/api/v1/visit-authorizations/` | `register_visits` / `manage_visits` | Registrar y autorizar visitante. |
| `GET` | `/api/v1/visit-authorizations/{id}/` | `register_visits` / `manage_visits` | Detalle de la autorización. |
| `PATCH` | `/api/v1/visit-authorizations/{id}/` | `register_visits` / `manage_visits` | Actualizar motivo o vigencia. |
| `POST` | `/api/v1/visit-authorizations/{id}/cancel/` | `register_visits` / `manage_visits` | Cancelar autorización. |
| `GET` | `/api/v1/visit-authorizations/options/` | Autenticado | Catálogo de estados y tipos de documento. |

*(Los mismos endpoints se encuentran disponibles bajo el prefijo `/api/v1/paquete2/visit-authorizations/`)*.
