# Integración selectiva CU23/CU25 — Gerstep

Fecha: 2026-11-03. Autorización: revisar e integrar estos CU selectivamente, sin fusionar ramas completas.

## Procedencia y límites

| CU | Fuente revisada | Incorporación |
|---|---|---|
| CU23 | PR #26, Rodrigo/Viveros123, `a392ebd` | Solo `cu23_gestionar_activos`; permiso `manage_assets` integrado al catálogo y fixture natural existente. |
| CU25 | PR #28, Daniel/danixprox, `75630e8` | Solo `cu25_mantenimiento_ordenes`, modelos/admin/migración de mantenimiento. |
| CU24 | Integración previa en Gerstep | Se conserva escaneo. Historial único servido por CU23, sin la ruta puente duplicada. |
| CU18–CU22 y CU31 | Implementación existente de Gerstep | No se sustituyen módulos, contratos, configuración NVIDIA ni reportes/transcripción. |

No se incorporaron CI/despliegue, settings globales, cambios de credenciales ni implementaciones duplicadas de Noelia/Eunice. No se fusionaron/cerraron PR remotos. Respaldo local: `backup/Gerstep-before-cu18-cu25-completion-20261103`.

## Ajustes necesarios para integrarlos

- CRUD de activos, tipos, QR e historial bajo `/api/v1/assets/`; escaneo CU24 permanece en `/assets/scan/`.
- Órdenes, planes, proveedores y opciones bajo `/api/v1/maintenance/`.
- El queryset del sector de un activo se calcula por solicitud, no al importar los serializers. La prueba Web real detectó y verificó esta corrección.
- Relaciones de las órdenes resueltas dinámicamente; las incidencias se validan por su `condominium`, incluso cuando no tienen sector.
- Membresía del usuario y rol activos; trabajador sin identidad asignada obtiene una lista vacía, nunca todas las órdenes.
- Una orden antigua con referencias de distintos condominios queda fuera de las consultas. No se elimina ni se atribuye arbitrariamente.
- Historial de activos filtra incidencias y órdenes por condominio; máximo 50 registros por colección.
- Evidencias: extensión, tamaño y contenido real; imágenes verificadas con Pillow. Descarga autenticada con `nosniff`.
- `maintenance.0002` depende de la migración que introduce `Incident.condominium` y lo considera al recuperar pertenencia de órdenes antiguas.
- `maintenance.0003` recupera un proveedor antiguo solo si todas sus órdenes identifican un único condominio. Proveedores compartidos/ambiguos conservan `NULL` y requieren revisión administrativa; no se mezclan tenants.
- Fixture de permisos conserva claves naturales: no se importó el fixture numérico incompatible del PR.

## Verificación

Pruebas con `config.settings_test`: SQLite aislado en memoria; `makemigrations --check --dry-run` sin cambios pendientes. Suite completa: 677 pruebas, 6 omitidas por dependencias/entornos específicos; ninguna fallida.

Pruebas adicionales: permisos, sectores por solicitud, referencias cruzadas, trabajador sin ficha, incidente sin ubicación, imagen falsa y migración de proveedores compartidos. Web y Flutter consumieron Django real mediante `scripts/serve_cu24_test_api.py`, que crea y destruye exclusivamente una base de pruebas.

## Pendientes de entorno

El servicio `postgresql-x64-18` se encontró **detenido**. Los settings actuales pueden caer automáticamente a SQLite si PostgreSQL no escucha. No se aplicaron migraciones a la base real ni se verificó concurrencia específica de PostgreSQL. Aplicar y verificar `maintenance.0002/0003` en el PostgreSQL correcto antes de desplegar; respaldar primero.

No se llamó a NVIDIA para estas pruebas ni se modificaron claves. No se hizo despliegue ni push remoto.
