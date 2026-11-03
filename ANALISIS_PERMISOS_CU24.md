# ANÁLISIS DE PERMISOS CU24 - Identificar Activo mediante QR
**Análisis del 2026-11-02**

---

## 1. Historia DE USUARIO OFICIAL (T120)
- **Título:** Identificar y consultar activo mediante código QR
- **Actor:** "Personal autorizado del condominio"
- **Alcance:** Permite escanear un QR generado por CU23 para obtener datos del activo y su historial

---

## 2. LÓGICA DE PERMISOS EN EL BACKEND

### Función: `can_view()` (cu23_gestionar_activos/permissions.py:31-37)
```python
def can_view(user):
    if not user or not user.is_authenticated:
        return False
    if can_manage(user):
        return True
    codes = _role_permission_codes(user)
    return codes is None or bool(codes & VIEW_ONLY_PERMISSIONS)
```

**Requiere CUALQUIERA de:**
- `manage_assets` (MANAGEMENT_PERMISSIONS)
- `view_general_status` (VIEW_ONLY_PERMISSIONS)
- `maintain_assets` (VIEW_ONLY_PERMISSIONS)
- O ser **SUPERUSER**

### Endpoint: `POST /api/v1/assets/scan/` (CU24)
- **Permission Classes:**
  - `IsAuthenticated`
  - `HasAssetsTenant` (membresía activa)
  - `CanScanAssets` → llama a `can_view(request.user)`

---

## 3. MATRIZ DE PERMISOS POR ROL

| Rol | Permisos | ¿Puede usar CU24? | Razón |
|-----|----------|-------------------|-------|
| **administrador** | Todos (34) | ✅ **SÍ** | Tiene `manage_assets` |
| **mantenimiento** | view_assigned_work_orders, update_work_order_status, attach_work_evidence, **maintain_assets** | ✅ **SÍ** | Tiene `maintain_assets` |
| **directiva** | view_reports, view_expenses, track_assembly_decisions, view_important_incidents, **view_general_status** | ✅ **SÍ** | Tiene `view_general_status` |
| **seguridad** | validate_visits, register_entry_exit, capture_security_evidence, manage_shift_handover | ❌ **NO** | Sin permisos requeridos |
| **limpieza** | view_assigned_cleaning_tasks, report_detected_issues, complete_cleaning_tasks | ❌ **NO** | Sin permisos requeridos |
| **residente** | register_visits, report_incidents, reserve_areas, view_announcements, view_own_data, track_own_requests | ❌ **NO** | Sin permisos requeridos |
| **proveedor-externo** | access_assigned_external_orders, attach_work_evidence, update_work_order_status | ❌ **NO** | Sin permisos requeridos |
| **superadmin (Admin Sistema)** | Todos | ✅ **SÍ** | Bypass por `is_superuser=True` |

---

## 4. ENDPOINTS RELACIONADOS CON CU24

### GET `/api/v1/assets/1/`
- **Permiso:** `can_view()` (via CU23)
- **Estado:** ✅ Funciona

### GET `/api/v1/assets/1/qr/`
- **Permiso:** `can_view()` (via CU23)
- **Estado:** ✅ Funciona
- **Devuelve:** Payload QR (`TAJI-ASSET.<uuid_hex>`) + SVG base64

### POST `/api/v1/assets/scan/` (CU24)
- **Permiso:** `can_view()` (via CU24 CanScanAssets)
- **Validaciones:**
  - Formato payload: `TAJI-ASSET.<hex_uuid>`
  - UUID válido
  - Asset pertenece al condominio autorizado (X-Tenant-ID)
- **Devuelve:** Detalles del asset

### GET `/api/v1/assets/1/history/`
- **Permiso:** `can_view()` (via CU23)
- **Dependencias:** 
  - WorkOrder.condominium_id (requiere migración maintenance/0002 ✅ APLICADA)
  - MaintenancePlan
  - Incident
- **Estado:** ✅ Funciona

---

## 5. ACCESO EN FLUTTER

### Menú del Drawer (taji_drawer.dart:274-291)
- **Paquete 4: "Activos y Mantenimiento"**
  - Muestra: "Órdenes de Trabajo (CU25)" - solo si `canAccessMaintenance == true`
  - **CU24 NO está en el menú flotante**

### Acceso Directo a CU24
- Ruta: `/escanear-qr-activos` (AppRoute.assetQrScanner.path)
- **Sin protección específica en el router** (cualquier usuario autenticado)
- **Validación real:** Ocurre en el backend al hacer POST /assets/scan/

### Propiedades de Permiso en TajiUser (Flutter)
- `canAccessMaintenance` → Controla el acceso al menú de CU25
- **No hay `canAccessAssets`** para CU24

---

## 6. VALIDACIONES DE MULTITENANT

**En todos los endpoints:**
- Se valida el header `X-Tenant-ID`
- Se valida que el user tenga membresía activa en ese condominio
- `HasAssetsTenant` en CU24 valida que el condominio esté activo
- Solo se pueden acceder assets del condominio autorizado

---

## 7. RESPUESTA A PREGUNTAS ESPECÍFICAS

### 1. ¿Qué roles pueden acceder a "Escanear Activos" en Flutter?
**Ninguno en el menú**, pero acceso directo vía ruta si:
- Se conoce la URL `/escanear-qr-activos`
- El backend lo permite con POST /assets/scan/ (ve tabla 3)

### 2. ¿Qué roles pueden ejecutar POST /api/v1/assets/scan/?
**administrador**, **mantenimiento**, **directiva** y **superadmin**

### 3. ¿Qué roles pueden consultar GET /api/v1/assets/{id}/history/?
**administrador**, **mantenimiento**, **directiva** y **superadmin**

### 4. ¿Personal de mantenimiento está autorizado de principio a fin?
✅ **SÍ** - Tiene `maintain_assets` que satisface `can_view()`

### 5. ¿Seguridad tiene acceso?
❌ **NO** - No tiene ninguno de los permisos requeridos (`manage_assets`, `view_general_status`, `maintain_assets`)

### 6. ¿Administrador de condominio puede consultar QR?
✅ **SÍ** - Es `administrador`, tiene `manage_assets`

### 7. ¿Qué usuarios deben ser rechazados?
- **seguridad**: Portería solo (validate_visits, register_entry_exit)
- **limpieza**: Tareas de limpieza solo
- **residente**: Invitaciones y solicitudes propias solo
- **proveedor-externo**: Órdenes asignadas solo

### 8. ¿Se aplican restricciones entre condominios?
✅ **SÍ**
- `HasAssetsTenant`: Valida condominio activo
- `tenant_assets(tenant_id)`: Filtra por tenant
- POST /assets/scan/: Rechaza QR de otro condominio

---

## 8. HALLAZGOS

### Diseño Actual (Consistente)
1. **CU24 no está en el menú móvil** → coherente con "personal autorizado específico"
2. **Backend valida permisos** → es_superuser O (manage_assets | view_general_status | maintain_assets)
3. **Restricción multitenant** → correctamente implementada
4. **Flujo esperado:**
   - Administrador crea asset en CU23 → genera QR
   - Personal autorizado (mantenimiento, directiva, admin) accede a CU24 vía ruta directa
   - POST /assets/scan/ valida en backend
   - Historial cargado desde BD multitenant

### Coherencia con T120
- ✅ "Personal autorizado" = administrador + mantenimiento + directiva
- ✅ Seguridad excluido (es portería, no mantenimiento)
- ✅ Residents excluidos (solo datos propios)

---

## 9. CONCLUSIÓN

**No hay errores en el RBAC de CU24.** El diseño es deliberado:
- Permisos están correctamente asignados
- Validaciones multitenant en su lugar
- El permiso `maintain_assets` autoriza el flujo completo
- Seguridad/portería está excluido por diseño (no es su rol)

**Recomendación:** CU24 debería ser visible en el menú móvil para roles autorizados (mantenimiento, directiva, admin), no solo accesible vía ruta directa.
