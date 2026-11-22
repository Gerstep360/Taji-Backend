# Integración selectiva de Backend en Gerstep

## Decisiones por PR

| PR / fuente | Decisión |
| --- | --- |
| [Cristel #31, CU24](https://github.com/Gerstep360/Taji-Backend/pull/31), `64fa3e2` | Importados solo los archivos `cu24_identificar_activo_qr`; no se fusionó el historial de su rama. |
| [Noelia #29, CU18](https://github.com/Gerstep360/Taji-Backend/pull/29), `f3843fa` | Ya es antecesor de Gerstep; se conservó la versión ampliada existente, sin reintroducirla. |
| [Eunice #30](https://github.com/Gerstep360/Taji-Backend/pull/30), `e4c10a3` | Se incorporó el alias `/health/`. El router CU18/CU19, filtros y asignaciones ya estaban cubiertos por Gerstep. No se importaron búsquedas globales sin aislamiento ni las migraciones que eliminan condominio/correlativo. |
| [Rodrigo #26, CU23](https://github.com/Gerstep360/Taji-Backend/pull/26) | Excluido por indicación del usuario; sin CRUD ni migraciones CU23. |
| [Daniel #28, CU25](https://github.com/Gerstep360/Taji-Backend/pull/28) | Excluido por indicación del usuario; sin CRUD ni migraciones CU25. |

No se aprobaron, cerraron ni fusionaron PRs en GitHub. `main` permanece intacto. Se creó `backup/Gerstep-before-cu24-integration-20261103` antes de integrar.

## Compatibilidad CU24

- `POST /api/v1/assets/scan/`: conserva el payload `TAJI-ASSET.<uuid_hex>` y los campos del contrato de Cristel.
- `GET /api/v1/assets/<id>/history/`: puente de lectura necesario para la Web CU24. Usa los modelos ya existentes; no habilita gestión de activos ni órdenes.
- Se eliminaron imports hacia los módulos CU23 excluidos, manteniendo controles equivalentes basados en membresía/rol activo y permisos existentes. `manage_maintenance` permite consultar desde la administración actual sin incorporar el nuevo catálogo CU23.
- El escaneo y el historial filtran por condominio y sector activo. El historial no incluye incidencias cruzadas ni órdenes con referencias a otro condominio; devuelve hasta 50 elementos por sección, sin datos de comentarios internos.
- Las respuestas no se almacenan en caché. El historial es de solo lectura. No se añadieron ni cambiaron migraciones.

## Corrección de sincronización RBAC detectada durante la revisión

La suite general tenía dos fallos: los permisos `analyze_incidents` y `review_incident_ai`, creados por `incidents.0008`, no estaban en el catálogo Python, y el fixture imponía PKs que colisionaban con los registros creados por migraciones.

Se alineó el catálogo con los 35 permisos existentes y se generó el fixture con claves naturales (`code` para permisos y `slug` para roles). Se verificó que cargarlo dos veces conserva IDs, referencias de usuarios y permisos personalizados. No se añadió `manage_assets` ni se importaron cambios RBAC del PR excluido de Rodrigo.

## Verificación

- Suite completa Django: **649 pruebas, OK, 6 omitidas por condiciones del entorno**.
- Suite Web completa: **124 pruebas aprobadas**.
- Navegador: **15 pruebas aprobadas**. Tres usan API Django real, autenticación real y base aislada en memoria: alta/comentarios de incidencias, QR e historial de activos, y denegación a residentes. El QR de cámara se genera y reproduce sintéticamente.
- `makemigrations --check --dry-run`: sin cambios detectados.
- Se conservaron los contratos y pruebas CU18/CU19/CU21/CU22 y CU31, incluyendo registro, evidencias privadas, seguimiento, IA y voz.

Repetir la prueba real, sin tocar la base de usuario:

```powershell
# En Backend; servidor limitado a loopback y base SQLite de pruebas en memoria.
.\.venv\Scripts\python.exe scripts/serve_cu24_test_api.py
# En otra terminal, desde Frontend (después de ng build):
$env:CU24_LIVE_URL='http://localhost:18766'
node node_modules/@playwright/test/cli.js test e2e/cu24-live.spec.ts
```

Detener el servidor de pruebas con Ctrl+C. El script no debe desplegarse como servidor de producción.

## Límites de la validación

Las pruebas no certifican PostgreSQL de producción, hardware de cámara ni disponibilidad real de SMTP, Stripe o NVIDIA. El runner usa SQLite aislado; siguen existiendo avisos previos de generación OpenAPI. Los log de fallos simulados de almacenamiento, QR y reconocimiento facial forman parte de pruebas negativas y no significan fallos de la suite.
