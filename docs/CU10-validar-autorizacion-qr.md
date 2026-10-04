# CU10: Validar Autorización de Visitante mediante QR

## 1. Identificación

| Atributo | Valor |
|---|---|
| **Código** | CU10 |
| **Nombre** | Validar autorización de visitante mediante QR |
| **Tareas asociadas** | T022 (Backend · Implementar validación de QR y reglas de autorización de visita) |
| **Versión** | 1.0 |
| **Estado** | Implementado |
| **Módulo** | Seguridad, Accesos y Auditoría (Paquete 2) |

---

## 2. Requisitos

### Requisito Funcional (RF)
> **RF-10 · Validación de autorización de visitante.** El sistema debe permitir al personal de seguridad escanear el QR de una visita y verificar su validez, vigencia, estado, visitante y unidad autorizante antes de permitir el ingreso.

### Requisito No Funcional (RNF)
> **Trazabilidad:** Toda validación debe quedar registrada para poder auditar los ingresos y los rechazos en portería.
> **Objetivo Asociado:** Evitar accesos no registrados y disputas sobre quién ingresó, cuándo y con qué autorización.

---

## 3. Descripción

El personal de seguridad escanea el QR presentado por el visitante y el sistema devuelve un veredicto inmediato con la validez del código, la vigencia de la visita, el estado de la autorización y la identidad del visitante junto con la unidad que lo autoriza. Cuando el ingreso es aprobado se registra un `AccessEvent` de entrada y la autorización pasa a `ACTIVE`; cuando es rechazado se registra el intento denegado con su motivo.

La validación se recalcula **siempre en el servidor**: el reloj del lector no influye en el resultado y ninguna condición se resuelve solo por lo que el código afirme.

---

## 4. Actores

| Actor | Tipo | Rol en el CU |
|---|---|---|
| **Personal de Seguridad** | Principal | Escanea el QR en portería y decide el ingreso según el veredicto. |
| **Administrador** | Supervisor | Puede validar y auditar los escaneos. |
| **Sistema RBAC** | Soporte | Exige `validate_visits`. |
| **Base de Datos** | Soporte | Persiste `AccessEvent` y la transición de estado. |

---

## 5. Precondiciones

1. El usuario tiene una sesión activa y el permiso `validate_visits` (o `manage_visits`).
2. Si el usuario tiene ficha en `Staff`, esta está en estado `ACTIVE`.
3. El visitante presenta el QR emitido por CU09 sin que haya sido rotado.

---

## 6. Postcondiciones

1. Se devuelve el veredicto (`valid`) con el motivo (`reason`) y el detalle de la visita.
2. Si el ingreso fue aprobado: se crea `AccessEvent` (`ENTRY` / `QR` / `APPROVED`) y la autorización pasa a `ACTIVE`.
3. Si fue rechazado sobre una autorización existente: se crea `AccessEvent` (`DENIED` / `QR` / `REJECTED`) con el motivo.
4. Si la ventana de la visita ya Conclusionó, la autorización queda persistida como `EXPIRED`.
5. Todo rechazo genera además un `AuditEvent` `VISIT_QR_VALIDATION_REJECTED`.

---

## 7. Flujo Principal (Ingreso Autorizado)

1. El guardia abre la pantalla de escaneo en portería.
2. El cliente envía `POST /api/v1/visit-qr/validate/` con `{"token": "<texto escaneado>"}`.
3. El backend normaliza el texto (admite payload `TAJI1.<uuid>.<token>`, token suelto, deep link `taji://visit/validate?code=...` y espacios añadidos por el lector).
4. Resuelve la autorización por UUID público y compara el hash del token en **tiempo constante**.
5. Aplica las reglas de autorización en orden: estado terminal → fin de ventana → QR emitido → expiración del QR → inicio de ventana → estado permitido.
6. Registra el `AccessEvent` de entrada y activa la autorización.
7. Responde `200 OK` con `valid: true` y el detalle del visitante, la unidad y el residente autorizante.

---

## 8. Flujo Secundario (Ingreso Denegado)

1. El mismo escaneo devuelve `200 OK` con `valid: false` y el `reason` del rechazo.
2. Se registra el `AccessEvent` de tipo `DENIED` y el `AuditEvent` de auditoría.
3. La interfaz muestra el motivo traducido al guardia.

> Un rechazo es un **resultado de negocio**, no un fallo de la API: por eso responde `200` y no `4xx`. Solo `400` se reserva para una petición mal formada.

---

## 9. Reglas de Negocio

| Código | Descripción |
|---|---|
| **RN1** | **Verificación en el servidor:** la validez se recalcula en cada escaneo a partir de la base de datos; el contenido del QR no es una afirmación de confianza. |
| **RN2** | **Comparación en tiempo constante:** el hash se contrasta con `secrets.compare_digest` para no filtrar información por tiempos de respuesta. |
| **RN3** | **Estados terminales:** `CANCELLED`, `FINISHED` y `EXPIRED` impiden el ingreso (RF-09). |
| **RN4** | **Ventana de la visita:** se rechaza si la visita aún no empieza (`VISIT_NOT_YET_VALID`) o si ya Conclusionó (`VISIT_WINDOW_ENDED`). |
| **RN5** | **Vigencia del QR:** se rechaza un QR expirado aunque la visita siga vigente (`QR_EXPIRED`). |
| **RN6** | **Rotación:** un QR reemplazado se distingue de uno desconocido (`QR_ROTATED` frente a `NOT_FOUND`), para que el guardia sepa pedir un código nuevo. |
| **RN7** | **Personal activo:** un guardia con ficha `SUSPENDED` o `INACTIVE` no puede validar ingresos. |
| **RN8** | **Trazabilidad:** todo escaneo resuelto a una autorización real queda registrado, favorable o no. |
| **RN9** | **Robustez ante abuso:** un token inexistente **no** genera `AccessEvent`, para que nadie pueda inundar la base de datos escaneando cadenas inválidas. |
| **RN10** | **Reingreso:** volver a escanear un QR ya `ACTIVE` se aprueba y registra un nuevo evento; no se rechaza por idempotencia. |

---

## 10. Motivos de rechazo

| `reason` | Significado para el guardia |
|---|---|
| `NOT_FOUND` | El QR no corresponde a ninguna autorización. |
| `QR_ROTATED` | El código fue reemplazado; solicitar el nuevo. |
| `QR_NOT_ISSUED` | La autorización aún no tiene QR emitido. |
| `QR_EXPIRED` | El código venció; solicitar uno nuevo. |
| `VISIT_NOT_YET_VALID` | La visita aún no está vigente. |
| `VISIT_WINDOW_ENDED` | El periodo de validez ya Conclusionó. |
| `VISIT_CANCELLED` | La autorización fue cancelada. |
| `VISIT_FINISHED` | La visita ya fue finalizada. |
| `VISIT_EXPIRED` | La autorización está vencida. |
| `STATUS_NOT_ALLOWED` | El estado no admite ingreso. |

El catálogo está disponible en `GET /api/v1/visit-qr/validate/reasons/` para que la app no codifique textos.

---

## 11. Contrato de la API REST

| Método | Endpoint | Permiso | Descripción |
|---|---|---|---|
| `POST` | `/api/v1/visit-qr/validate/` | `validate_visits` / `manage_visits` | Valida el QR escaneado. |
| `GET` | `/api/v1/visit-qr/validate/reasons/` | `validate_visits` / `manage_visits` | Catálogo de motivos de rechazo. |

*(Los mismos endpoints existen bajo el prefijo `/api/v1/paquete2/visit-qr/`.)*

### Entrada

```json
{
  "token": "TAJI1.6f2a...c1d2",
  "notes": "Visitante sin autorización",
  "device_id": "tablet-portania-1"
}
```

| Campo | Obligatorio | Descripción |
|---|---|---|
| `token` | Sí | Texto escaneado. También se aceptan las claves `code`, `qr`, `payload` y `value`. |
| `notes` | No | Observación del guardia (máx. 300 caracteres). |
| `device_id` | No | Identificador del lector, para auditoría. |

### Respuesta

```json
{
  "valid": true,
  "reason": "VALID",
  "message": "Autorización de visita vigente. Ingreso permitido.",
  "checked_at": "2026-10-03T16:30:00Z",
  "authorization": {
    "id": 12,
    "status": "ACTIVE",
    "status_display": "Activa",
    "purpose": "Almuerzo familiar",
    "visitor": { "id": 8, "full_name": "Mario Gómez", "document_number": "7766554" },
    "resident": { "id": 3, "full_name": "Carlos Mendoza" },
    "unit_detail": { "id": 5, "code": "A-101", "sector_name": "Torre A" },
    "valid_from": "2026-10-03T15:00:00Z",
    "valid_until": "2026-10-03T21:00:00Z"
  },
  "access_event": {
    "id": 44,
    "event_type": "ENTRY",
    "validation_method": "QR",
    "validation_result": "APPROVED",
    "occurred_at": "2026-10-03T16:30:00Z"
  }
}
```

---

## 12. Códigos de respuesta

| Código | Significado |
|---|---|
| `200` | Escaneo procesado. `valid` indica si se autoriza el ingreso. |
| `400` | Falta el token o llegó vacío. |
| `401` | Sesión no iniciada. |
| `403` | Sin `validate_visits`, o ficha de personal no activa. |
| `405` | Método no admitido en este endpoint. |