# Sprint 4 — Libro de operaciones (CU33–CU37)

Independiente de CU26–CU30. Usa la autenticación, permisos y condominio activo de Taji. Sin cambios en CU22, CU32, Flutter ni Stripe.

| CU | Tarea | Funcionalidad | Plataforma | Prioridad |
| --- | --- | --- | --- | --- |
| CU33 | T150 | Gestionar garantías, cobertura, vencimiento y reclamos | Web / Backend | Alta |
| CU34 | T151 | Gestionar cotizaciones por código de solicitud | Web / Backend | Alta |
| CU35 | T152 | Registrar inspecciones con checklist visual | Web / Backend | Alta |
| CU36 | T153 | Comparar cotizaciones mediante IA | Web / Backend / IA | Media |
| CU37 | T154 | Proponer seguimiento de hallazgos mediante IA | Web / Backend / IA | Media |

## Demostración

1. Aplica `python manage.py migrate` y arranca Django y Angular. Entra con un condominio activo y permiso `manage_settings`.
2. En **Operaciones → Garantías**, registra un vencimiento, proveedor y cobertura. Cambia el estado a **En reclamo** y filtra.
3. En **Cotizaciones**, crea dos ofertas con el mismo código y moneda, pero distinto costo, plazo o garantía. Selecciónalas y pulsa **Solicitar análisis**. El comparador no autoriza compras.
4. En **Inspecciones**, marca un punto como **Requiere atención** y otro **Sin revisar**. Guarda, selecciona el registro y solicita seguimiento. No se crea ninguna orden de trabajo ni se modifica el registro.
5. Si NVIDIA falla, puedes seguir revisando los datos calculados por Taji y trabajar manualmente.

**Solo web:** el módulo es para el puesto administrativo: permite revisar varios registros y mantener a la vista el panel de edición o análisis. La web es adaptable; no se añadió un flujo a Flutter.

**Privacidad:** NVIDIA recibe cifras, moneda, plazos, garantía o estados del checklist. Nombres, referencias, lugares y notas quedan en Taji. Máximo cuatro intentos por minuto y condominio. Las sugerencias requieren revisión humana.

**API:** `/api/v1/operations/{warranties|quotes|inspections}/`; GET/POST de lista, GET/PUT/DELETE por ID, POST a `analyze/` solo en cotizaciones e inspecciones. Escrituras auditadas; el servidor determina el condominio.

- [Daily Scrum del 4 al 22 de noviembre](<Daily Scrum.md>).
- [Criterios y pruebas por CU](Pruebas.md).
- [Diagramas PlantUML por CU](diagramas/): clases, secuencia, comunicación, navegación y tiempo ilustrativo.

| CU | Clases | Secuencia | Comunicación | Navegación | Tiempo |
| --- | --- | --- | --- | --- | --- |
| CU33 | [PNG](diagramas/CU33_Clases.png) | [PNG](diagramas/CU33_Secuencia.png) | [PNG](diagramas/CU33_Comunicacion.png) | [PNG](diagramas/CU33_Navegacion.png) | [PNG](diagramas/CU33_Tiempo.png) |
| CU34 | [PNG](diagramas/CU34_Clases.png) | [PNG](diagramas/CU34_Secuencia.png) | [PNG](diagramas/CU34_Comunicacion.png) | [PNG](diagramas/CU34_Navegacion.png) | [PNG](diagramas/CU34_Tiempo.png) |
| CU35 | [PNG](diagramas/CU35_Clases.png) | [PNG](diagramas/CU35_Secuencia.png) | [PNG](diagramas/CU35_Comunicacion.png) | [PNG](diagramas/CU35_Navegacion.png) | [PNG](diagramas/CU35_Tiempo.png) |
| CU36 | [PNG](diagramas/CU36_Clases.png) | [PNG](diagramas/CU36_Secuencia.png) | [PNG](diagramas/CU36_Comunicacion.png) | [PNG](diagramas/CU36_Navegacion.png) | [PNG](diagramas/CU36_Tiempo.png) |
| CU37 | [PNG](diagramas/CU37_Clases.png) | [PNG](diagramas/CU37_Secuencia.png) | [PNG](diagramas/CU37_Comunicacion.png) | [PNG](diagramas/CU37_Navegacion.png) | [PNG](diagramas/CU37_Tiempo.png) |
