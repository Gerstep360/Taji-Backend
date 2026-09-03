PERMISSIONS = {
    "manage_residents": "Gestionar residentes",
    "manage_units": "Gestionar unidades",
    "manage_staff": "Gestionar personal",
    "manage_incidents": "Gestionar incidencias",
    "manage_maintenance": "Gestionar mantenimientos",
    "manage_visits": "Gestionar visitas",
    "manage_reservations": "Gestionar reservas",
    "manage_announcements": "Gestionar comunicados",
    "view_reports": "Consultar reportes",
    "manage_settings": "Gestionar configuración general",
    "view_expenses": "Revisar gastos",
    "track_assembly_decisions": "Dar seguimiento a decisiones de asamblea",
    "view_important_incidents": "Consultar incidencias importantes",
    "view_general_status": "Consultar el estado general",
    "register_visits": "Registrar visitas",
    "report_incidents": "Reportar incidencias",
    "reserve_areas": "Reservar áreas comunes",
    "view_announcements": "Consultar comunicados",
    "view_own_data": "Consultar datos propios",
    "track_own_requests": "Dar seguimiento a solicitudes propias",
    "validate_visits": "Validar visitas",
    "register_entry_exit": "Registrar entradas y salidas",
    "capture_security_evidence": "Capturar evidencia de seguridad",
    "manage_shift_handover": "Registrar entrega de turno",
    "view_assigned_work_orders": "Ver trabajos asignados",
    "update_work_order_status": "Actualizar estado de trabajos",
    "attach_work_evidence": "Adjuntar evidencias de trabajo",
    "maintain_assets": "Registrar mantenimiento de activos",
    "view_assigned_cleaning_tasks": "Ver tareas de limpieza asignadas",
    "report_detected_issues": "Reportar problemas detectados",
    "complete_cleaning_tasks": "Completar tareas de limpieza",
    "access_assigned_external_orders": "Acceder a órdenes externas asignadas",
    "manage_roles": "Gestionar roles y permisos",
}

ROLE_DEFINITIONS = {
    "administrador": {
        "name": "Administrador",
        "description": "Administrador del condominio con control general del sistema.",
        "permissions": list(PERMISSIONS),
    },
    "directiva": {
        "name": "Directiva",
        "description": "Presidente, tesorero, secretario y vocales.",
        "permissions": [
            "view_reports", "view_expenses", "track_assembly_decisions",
            "view_important_incidents", "view_general_status",
        ],
    },
    "residente": {
        "name": "Copropietario / Residente",
        "description": "Propietario o inquilino de una unidad.",
        "permissions": [
            "register_visits", "report_incidents", "reserve_areas",
            "view_announcements", "view_own_data", "track_own_requests",
        ],
        "is_public": True,
    },
    "seguridad": {
        "name": "Seguridad / Guardia",
        "description": "Personal de portería y seguridad.",
        "permissions": [
            "validate_visits", "register_entry_exit",
            "capture_security_evidence", "manage_shift_handover",
        ],
    },
    "mantenimiento": {
        "name": "Mantenimiento",
        "description": "Técnico o encargado interno de mantenimiento.",
        "permissions": [
            "view_assigned_work_orders", "update_work_order_status",
            "attach_work_evidence", "maintain_assets",
        ],
    },
    "limpieza": {
        "name": "Limpieza",
        "description": "Personal interno de limpieza.",
        "permissions": [
            "view_assigned_cleaning_tasks", "report_detected_issues",
            "complete_cleaning_tasks",
        ],
    },
    "proveedor-externo": {
        "name": "Proveedor externo",
        "description": "Proveedor con acceso limitado a órdenes asignadas.",
        "permissions": [
            "access_assigned_external_orders", "attach_work_evidence",
            "update_work_order_status",
        ],
    },
}


# --- CU4 business rule constants ---

# Permisos exclusivos del Administrador; no pueden cederse a otros roles (RN1)
ADMIN_ONLY_PERMISSIONS: frozenset[str] = frozenset({"manage_roles"})

# Permisos exclusivos de portería/seguridad (RN2)
SECURITY_EXCLUSIVE_PERMISSIONS: frozenset[str] = frozenset({
    "validate_visits", "register_entry_exit",
    "capture_security_evidence", "manage_shift_handover",
})

# Permisos exclusivos de empleado operativo (RN2)
EMPLOYEE_EXCLUSIVE_PERMISSIONS: frozenset[str] = frozenset({
    "view_assigned_work_orders", "update_work_order_status",
    "attach_work_evidence", "maintain_assets",
    "view_assigned_cleaning_tasks", "report_detected_issues",
    "complete_cleaning_tasks", "access_assigned_external_orders",
})

# Permisos que cada rol NO puede recibir jamás
FORBIDDEN_PERMISSIONS_BY_ROLE: dict[str, frozenset[str]] = {
    # RN3: Solo Residente crea invitaciones; RN2: no mezclar con Empleado
    "seguridad": (
        frozenset({"register_visits", "manage_roles"})
        | EMPLOYEE_EXCLUSIVE_PERMISSIONS
    ),
    # RN4: Directiva es solo lectura — únicamente puede tener permisos view_*/track_*
    "directiva": frozenset({
        "manage_residents", "manage_units", "manage_staff", "manage_incidents",
        "manage_maintenance", "manage_visits", "manage_reservations",
        "manage_announcements", "manage_settings", "manage_roles",
        "register_visits", "validate_visits", "register_entry_exit",
        "capture_security_evidence", "manage_shift_handover",
        "update_work_order_status", "attach_work_evidence", "maintain_assets",
        "report_detected_issues", "complete_cleaning_tasks",
        "access_assigned_external_orders", "report_incidents", "reserve_areas",
    }),
    # RN2: Empleado operativo no puede tener permisos de portería
    "mantenimiento": frozenset({"register_visits", "manage_roles"}) | SECURITY_EXCLUSIVE_PERMISSIONS,
    "limpieza": frozenset({"register_visits", "manage_roles"}) | SECURITY_EXCLUSIVE_PERMISSIONS,
    "proveedor-externo": frozenset({"register_visits", "manage_roles"}) | SECURITY_EXCLUSIVE_PERMISSIONS,
    "residente": frozenset({"manage_roles"}) | SECURITY_EXCLUSIVE_PERMISSIONS,
}

# Permisos que cada rol DEBE conservar siempre (RN1)
MANDATORY_PERMISSIONS_BY_ROLE: dict[str, frozenset[str]] = {
    "administrador": frozenset({"manage_roles"}),
}


def sync_rbac(**_kwargs):
    from .models import Role, SystemPermission

    permission_objects = {}
    for code, name in PERMISSIONS.items():
        permission, _ = SystemPermission.objects.update_or_create(
            code=code,
            defaults={"name": name, "description": "Permiso preparado para módulos futuros."},
        )
        permission_objects[code] = permission

    for slug, definition in ROLE_DEFINITIONS.items():
        role, _ = Role.objects.update_or_create(
            slug=slug,
            defaults={
                "name": definition["name"],
                "description": definition["description"],
                "is_public": definition.get("is_public", False),
                "is_active": True,
            },
        )
        role.permissions.set(permission_objects[code] for code in definition["permissions"])
