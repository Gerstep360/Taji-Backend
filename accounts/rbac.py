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
