# CU09: Generar y Consultar QR Temporal de Visita

## 1. Identificación

| Atributo | Valor |
|---|---|
| **Código** | CU09 |
| **Nombre** | Generar y consultar QR temporal de visita |
| **Tareas asociadas** | T021 (Backend · Implementar generación de QR temporal único con vigencia y expiración) |
| **Versión** | 1.0 |
| **Estado** | Implementado |
| **Módulo** | Seguridad, Accesos y Auditoría (Paquete 2) |

---

## 2. Requisitos

### Requisito Funcional (RF)
> **RF-09 · Generación de QR temporal para visitantes.** El sistema debe generar un código QR único para cada autorización de visita. El código debe tener vigencia limitada, fecha de expiración y quedar inutilizable cuando la autorización sea cancelada, finalizada o vencida.

### Requisito No Funcional (RNF)
> **Confidencialidad:** El contenido del QR es una credencial de acceso y no debe quedar en claro en la base de datos ni en los registros de auditoría.
> **Objetivo Asociado:** Impedir que una filtración de la base de datos o un volcado de logs permita clonar autorizaciones de ingreso.

---

## 3. Descripción

Permite al residente y a la administración emitir el código QR de una visita ya registrada en CU08. Cada emisión produce un token opaco aleatorio, calcula una vigencia acotada a la ventana de la visita y fija una fecha de expiración. El sistema entrega el contenido del QR y su imagen renderizada en SVG o PNG lista para mostrar o compartir, y permite consultar en cualquier momento si el código sigue vigente.

El token se persiste únicamente como hash SHA-256, por lo que el QR solo puede reconstruirse en el instante de la emisión. Rotar el código genera un token nuevo e invalida el anterior de inmediato.

---

## 4. Actores

| Actor | Tipo | Rol en el CU |
|---|---|---|
| **Residente** | Principal | Emite y consulta el QR de las visitas que él autorizó. |
| **Administrador** | Supervisor | Consulta el QR de cualquier visita del condominio. |
| **Sistema RBAC** | Soporte | Exige `register_visits` para emitir y `manage_visits` para consultar. |
| **Base de Datos** | Soporte | Persiste el hash del token y las marcas de vigencia. |

---

## 5. Precondiciones

1. El usuario tiene una sesión activa.
2. Existe una autorización de visita en estado `AUTHORIZED` (o `ACTIVE`) dentro de CU08.
3. Si el actor es un Residente, es el autorizante de esa autorización.

---

## 6. Postcondiciones

1. La autorización tiene `qr_token_hash` (SHA-256), `qr_issued_at` y `qr_expires_at`.
2. `qr_expires_at` nunca supera `valid_until` (garantizado por el constraint `chk_visit_qr_expiry`).
3. Se registra un `AuditEvent` con `VISIT_QR_ISSUED` o `VISIT_QR_ROTATED`.
4. El QR anterior, si existía, queda inutilizable tras una rotación.

---

## 7. Flujo Principal (Emisión del QR)

1. El Residente abre el detalle de una visita en la aplicación.
2. El cliente envía `POST /api/v1/visit-qr/{id}/generate/`.
3. El backend verifica el permiso `register_visits` y que la autorización le pertenezca.
4. Si ya existe un QR vigente y no se envía `force`, devuelve el mismo código con `200 OK` (**idempotente**), de modo que el QR que el visitante ya tiene no se invalida.
5. En caso contrario, dentro de `transaction.atomic()`:
   - Genera un token aleatorio de 192 bits con `secrets`.
   - Calcula `qr_expires_at = min(ahora + ttl, valid_until)`.
   - Guarda `SHA-256(token)`, `qr_issued_at` y `qr_expires_at`.
6. Registra el evento de auditoría.
7. Responde `201 Created` con el contenido del QR y su imagen en base64.

---

## 8. Flujo Secundario (Consulta y Rotación)

1. **Consulta:** `GET /api/v1/visit-qr/{id}/` informa `issued`, `active`, `qr_expires_at` y `expires_in_seconds` sin revelar el contenido del QR.
2. **Rotación:** `POST /api/v1/visit-qr/{id}/generate/` con `{"force": true}` emite un token nuevo y deja el anterior inutilizable. Responde `200 OK` con `rotated: true`.
3. **Formato de imagen:** el parámetro `image_format=svg|png` elige el formato (por defecto `svg`). No se usa `format` porque DRF lo reserva para la negociación de contenido.
4. **Mantenimiento:** `python manage.py expire_visit_qrs` marca como `EXPIRED` las autorizaciones cuya ventana Conclusionó, sin depender de que alguien lea el QR.

---

## 9. Reglas de Negocio

| Código | Descripción |
|---|---|
| **RN1** | **Unicidad:** cada emisión genera un token distinto; el hash se persiste en un campo `unique`. |
| **RN2** | **Secreto en la BD:** solo se almacena el SHA-256 del token. El token en claro nunca se persiste ni se audita. |
| **RN3** | **Vigencia acotada:** la vigencia efectiva es `min(ttl solicitado, VISIT_QR_TTL_MINUTES, minutos restantes de la visita)`, con mínimo `VISIT_QR_MIN_TTL_MINUTES` y máximo `VISIT_QR_MAX_TTL_MINUTES`. |
| **RN4** | **Invalidez por estado:** no se emite QR para autorizaciones `CANCELLED`, `FINISHED` o `EXPIRED`. |
| **RN5** | **Idempotencia:** reemitir sin `force` no invalida el QR vigente. |
| **RN6** | **Rotación segura:** rotar cambia el token, por lo que el código previo deja de autorizar el ingreso (RF-09). |
| **RN7** | **Aislamiento:** el Residente solo opera sobre sus propias autorizaciones; el QR de otro responde `404`, sin confirmar siquiera su existencia. |
| **RN8** | **Expiración efectiva:** aunque la autorización siga vigente, si `qr_expires_at` ya pasó el QR se marca inactivo. |
| **RN9** | **Integridad transaccional:** la emisión se ejecuta en `transaction.atomic()` con bloqueo de fila (`select_for_update`). |

---

## 10. Contrato de la API REST

| Método | Endpoint | Permiso | Descripción |
|---|---|---|---|
| `POST` | `/api/v1/visit-qr/{id}/generate/` | `register_visits` | Emite o rota el QR. Cuerpo opcional: `ttl_minutes`, `force`. |
| `GET` | `/api/v1/visit-qr/{id}/` | `register_visits` / `manage_visits` | Consulta el estado de vigencia del QR. |

*(Los mismos endpoints existen bajo el prefijo `/api/v1/paquete2/visit-qr/`.)*

### Parámetros de la emisión

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `ttl_minutes` | entero | `VISIT_QR_TTL_MINUTES` (240) | Vigencia solicitada del QR. |
| `force` | booleano | `false` | Rota un QR todavía vigente. |
| `image_format` | texto | `svg` | Formato de la imagen: `svg` o `png`. |

### Respuesta

```json
{
  "authorization": {
    "id": 12,
    "status": "AUTHORIZED",
    "status_display": "Autorizada",
    "purpose": "Almuerzo familiar",
    "visitor": { "id": 8, "full_name": "Mario Gómez", "document_number": "7766554" },
    "resident": { "id": 3, "full_name": "Carlos Mendoza" },
    "unit_detail": { "id": 5, "code": "A-101", "sector_name": "Torre A" },
    "valid_from": "2026-10-03T15:00:00Z",
    "valid_until": "2026-10-03T21:00:00Z",
    "qr_uuid": "6f2a...",
    "qr_issued_at": "2026-10-03T16:00:00Z",
    "qr_expires_at": "2026-10-03T20:00:00Z"
  },
  "issued": true,
  "active": true,
  "payload": "TAJI1.6f2a...c1d2",
  "expires_in_seconds": 14395,
  "image_format": "svg",
  "image_media_type": "image/svg+xml",
  "image_base64": "PHN2ZyB4bWxucz0i...",
  "rotated": false
}
```

> `payload` e `image_base64` solo se completan en la respuesta de emisión. La consulta devuelve `issued`, `active` y `expires_in_seconds`, pero nunca el contenido del QR.

---

## 11. Códigos de respuesta

| Código | Significado |
|---|---|
| `201` | QR emitido por primera vez. |
| `200` | QR ya vigente devuelto sin rotar, o QR rotado con `force`. |
| `400` | `ttl_minutes` fuera de límites, visita sin ventana útil o estado no permitido. |
| `403` | El usuario no tiene `register_visits` para emitir. |
| `404` | La autorización no existe o no pertenece al residente. |

---

## 12. Configuración

| Variable | Por defecto | Descripción |
|---|---|---|
| `VISIT_QR_TOKEN_BYTES` | `24` | Bytes de entropía del token (192 bits). |
| `VISIT_QR_TTL_MINUTES` | `240` | Vigencia por defecto del QR. |
| `VISIT_QR_MAX_TTL_MINUTES` | `1440` | Techo absoluto de la vigencia solicitada. |
| `VISIT_QR_MIN_TTL_MINUTES` | `5` | Vigencia mínima aceptable. |
| `VISIT_QR_ECC` | `medium` | Corrección de errores del símbolo QR. |
| `VISIT_QR_IMAGE_SCALE` | `6` | Escala de la imagen renderizada. |