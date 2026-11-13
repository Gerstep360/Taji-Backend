# Comunidad móvil y reportes PDF

## Contratos

Todos requieren JWT y condominio activo. Prefijo `/api/v1/`.

| Recurso | Ruta | Escritura |
|---|---|---|
| Datos del condominio actual | `community/condominium/` | PATCH, `manage_settings`; no crea ni elimina condominios |
| Áreas comunes | `community/areas/` | `manage_reservations` |
| Reservas | `community/reservations/` | `reserve_areas` para las propias; `manage_reservations` para gestión |
| Comunicados | `community/announcements/` | `manage_announcements` |
| Asambleas y acuerdos | `community/assemblies/`, `community/agreements/` | `manage_settings` |
| Bitácora móvil | `community/audit/` | Solo lectura, `manage_roles` o `view_audit_log` |

Las listas usan la paginación DRF del proyecto y `search`. Los lectores de comunicados ven únicamente publicaciones vigentes para su audiencia. Un residente solo puede consultar y cancelar sus propias reservas antes del inicio; la API asigna su perfil automáticamente. No puede autoaprobarse. Se validan horarios, bloqueos, estados y cruces; el bloqueo transaccional del área complementa la restricción de exclusión de PostgreSQL.

Las bajas de áreas/comunicados/asambleas/acuerdos son por estado, conservando historial. Las reservas se cancelan con PATCH. Los eventos nuevos incluyen condominio; el endpoint móvil excluye los eventos antiguos sin tenant identificable, sin alterar la bitácora append-only. El endpoint global legado de auditoría no fue sustituido.

## PDF

`GET cu31/catalog/` anuncia `pdf`. `POST cu31/export/` acepta el contrato existente con `format: "pdf"` y devuelve `application/pdf`, encabezados repetidos y paginación. Límite PDF: **1.000 filas**; aplicar filtros o usar CSV/Excel para conjuntos mayores. Se conserva el aislamiento del catálogo de reportes y se reconoce el permiso explícito `view_reports`.

Dependencia nueva: `reportlab==5.1.0`. No requiere navegador ni servicio externo. Los textos se escapan antes de renderizar. Las migraciones agregan FKs nullable: áreas antiguas con sector se asignan al tenant de ese sector; registros ambiguos no se atribuyen al primer condominio.

## Verificación

- Suite Django: `python manage.py test --settings=config.settings_test --noinput`.
- Integración Flutter/Django: iniciar `python scripts/serve_cu24_test_api.py` y ejecutar las pruebas móviles con `CU24_LIVE_URL=http://localhost:18766`. Usa exclusivamente SQLite efímero y datos sintéticos.
- En producción: respaldar PostgreSQL antes de migrar; instalar ReportLab en el entorno de la nueva versión, verificar MIME y firma `%PDF-`, permisos, listas de comunidad y estado del worker de NVIDIA. No ejecutar pruebas destructivas sobre datos de residentes.
