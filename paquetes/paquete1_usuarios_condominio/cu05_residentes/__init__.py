"""CU05: Gestionar residentes y copropietarios.

Módulo encargado del directorio de residentes y copropietarios del
condominio administrado por el Administrador:
- Registro, consulta, edición y activación/desactivación (baja lógica)
- Reutiliza Person como fuente única de datos personales
- No gestiona la asociación con unidades habitacionales (ver CU06)

La implementación real vive en `condominiums` (modelo Resident ya
existente); este paquete solo re-expone ese contrato bajo la nueva
convención de paquetes, igual que hace CU07 con el personal.
"""
