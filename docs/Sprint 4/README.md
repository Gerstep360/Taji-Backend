# Sprint 4 — CU32 Reconocimiento por cámara

Especificación: [ATAJI_RECONOCIMIENTO_WEBCAM_CODEX.md](../../ATAJI_RECONOCIMIENTO_WEBCAM_CODEX.md). Identificadores CU32 y T146–T149 propuestos para este incremento. Entrega local: no se desplegó al VPS ni se modificó Móvil.

## Ficha del caso de uso

| Campo | Descripción |
| --- | --- |
| Actor | Operador autenticado con condominio activo y permiso `validate_visits` |
| Disparador | Pulsa **Iniciar cámara** en **Seguridad y Accesos → Reconocimiento por cámara** |
| Precondiciones | HTTPS o localhost, navegador compatible, una webcam autorizada |
| Flujo principal | Solicitar cámara, cargar COCO-SSD, detectar objetos en el navegador, mostrar cajas y confianza. Opcionalmente habilitar OCR, centrar placa, confirmar dos lecturas y consultar el catálogo del condominio. |
| Alternativas | Permiso denegado, cámara ausente u ocupada, error de modelo, lectura incierta, placa no legible, proveedor no disponible o vehículo no registrado. |
| Postcondición | Al detener, ocultar pestaña, cambiar de condominio o salir se liberan las pistas y se descartan respuestas obsoletas. Los eventos de sesión se borran. |
| Exclusiones | Sin identificación facial, biometría, grabación, vigilancia permanente, consulta gubernamental, alertas masivas ni autorización de ingreso. |

## Cómo probar

1. En **Backend**, ejecutar `python manage.py migrate` sobre la base de demo y arrancar Django con el flujo habitual de Taji.
2. En Django Admin, un superusuario puede añadir un **Demo vehicle** con placa y descripción de prueba en el condominio correcto. No hace falta vincular una persona ni modificar residentes.
3. En **Frontend**, instalar el lockfile (`npm ci`) e iniciar la web (`npm start`) con el API habitual. Usar localhost o HTTPS.
4. Iniciar sesión con un rol que tenga `validate_visits`, abrir el módulo, pulsar **Iniciar cámara** y otorgar permiso. Mostrar material autorizado de las cinco clases.
5. Para OCR, configurar las credenciales y un modelo con visión NVIDIA en el entorno del Backend. Habilitar la casilla y alinear una placa sintética o autorizada dentro de la guía. Mantener el vehículo visible para dos observaciones. Confirmar visualmente el resultado.
6. Pulsar **Detener cámara** o cambiar de pantalla. Confirmar que desaparezca el indicador de cámara activa del navegador.

### Contrato y persistencia

| Método y ruta | Entrada y salida | Límites |
| --- | --- | --- |
| POST `/api/v1/security/cu32/plate/read/` | Multipart `image`, JPEG. Devuelve `{"plate": null}` o texto candidato. | 350 KB; 100–640 px de ancho, 32–360 px de alto; 6/min por usuario en la caché DRF. |
| POST `/api/v1/security/cu32/plate/lookup/` | JSON `plate`. Devuelve `registered` y `vehicle` con placa y descripción, o nulo. | 12/min por usuario; coincidencia exacta normalizada solo en el condominio activo. |

Ambas rutas requieren autenticación y permiso, no aceptan un condominio del cuerpo y devuelven `Cache-Control: no-store`. El OCR re-encodea el recorte sin metadatos. No se guardan imágenes ni video. `security.0007_cu32_demo_vehicle` añade solo el catálogo mínimo, con clave única condominio/placa. Los eventos permanecen en memoria, sin auditoría ni historial persistente.

### Rendimiento y límites

- COCO-SSD Lite MobileNet V2 se carga al iniciar; WebGL con alternativa CPU durante la carga. El primer uso requiere descargar los pesos desde Google Storage. Las imágenes de detección no salen del navegador. Referencias: [documentación de COCO-SSD](https://github.com/tensorflow/tfjs-models/tree/master/coco-ssd), [código Apache-2.0](https://github.com/tensorflow/tfjs-models/blob/master/coco-ssd/src/index.ts).
- Una inferencia a la vez, entrada de hasta 480 px de ancho y objetivo de ~3 inferencias/s si el equipo lo permite. El tamaño/ritmo reales dependen del navegador y el hardware.
- La guía manual identifica la región de placa. Solo se recorta si exactamente un vehículo de tamaño suficiente la cubre. Hasta tres recortes por presencia en la guía, separados por al menos 11 segundos. Activar OCR implica enviar esos recortes al proveedor NVIDIA mediante Django, no a un registro externo.
- Dos lecturas iguales no garantizan precisión: requieren revisión visual. Una placa de lado, borrosa o demasiado pequeña puede no ser legible. No se fuerzan equivalencias O/0 ni un formato nacional.
- Al cerrar, no se programan nuevas lecturas. Una petición ya recibida por el servidor puede terminar dentro de su timeout aunque el navegador la cancele.
- El modelo del navegador y el OCR son independientes. No hay inferencia de video en Django ni requisito de GPU en el VPS.

## Diagramas

| Tipo | PlantUML editable | Imagen |
| --- | --- | --- |
| Clases | [Fuente](<Diagrama de clases/CU32_Clases.puml>) | [PNG](<Diagrama de clases/CU32_Clases.png>) |
| Secuencia | [Fuente](<Diagrama de secuencia/CU32_Secuencia.puml>) | [PNG](<Diagrama de secuencia/CU32_Secuencia.png>) |
| Navegación | [Fuente](<Diagrama de Navegación/CU32_Navegacion.puml>) | [PNG](<Diagrama de Navegación/CU32_Navegacion.png>) |
| Tiempo | [Fuente](<Diagrama de Tiempo/CU32_Tiempo.puml>) | [PNG](<Diagrama de Tiempo/CU32_Tiempo.png>) |

## Tablas del Sprint

| ID | Tarea | Plataforma | Horas estimadas / PHU |
| --- | --- | --- | ---: |
| T146 | Gestionar el ciclo de la webcam | Web | 5 |
| T147 | Detectar objetos en el navegador | Web / IA | 6 |
| T148 | Leer recortes y validar el consenso de placa | Backend / IA | 6 |
| T149 | Consultar vehículos del condominio activo | Backend / QA | 4 |
| | **Total propuesto** | | **21** |

- [Historias por tarea](<historias de usuario/Historias_CU32.xlsx>), [plan de pruebas](<pruebas/Plan de pruebas (criterios de aceptación)/Plan_CU32.xlsx>) (28 casos) y [reporte consolidado por CU](<pruebas/reporte de pruebas/Reporte_CU32.xlsx>).
- [Planificación del Sprint 4](<otros/Planificacion_CU32.xlsx>) y [Daily Scrum planificado](<otros/Daily_Scrum_CU32.xlsx>). No son actas de reuniones ya realizadas.

## Verificación

| Comprobación | Resultado |
| --- | --- |
| Django y migraciones en SQLite aislada | [702 aprobadas y 6 omitidas](<pruebas/evidencias/backend.log>); 7 pruebas específicas de CU32 |
| Angular | [130 aprobadas](<pruebas/evidencias/web-unit.log>); build correcto con advertencias de dependencias y del presupuesto previo de estilos |
| Edge, fuente sintética y API controlada | [5 recorridos aprobados](<pruebas/evidencias/web-e2e.log>), incluido COCO-SSD real sobre una fuente sintética vacía; capturas [1440 px](<pruebas/evidencias/CU32-escritorio.png>) y [390 px](<pruebas/evidencias/CU32-390px.png>) |
| Pendiente | Validar clases/precisión con webcam y placas autorizadas; probar OCR real y medir recursos en el despliegue objetivo. |

### Archivos de implementación

- **Backend:** `security/models.py`, `security/plate.py`, `security/admin.py`, migración `security.0007`, `config/urls.py` y `paquetes/paquete2_seguridad_accesos/cu32_webcam/`.
- **Frontend:** `app.routes.ts`, navegación de `main-layout.component.ts`, `paquetes/paquete2_seguridad_accesos/cu32_webcam/`, `e2e/cu32.spec.ts`, manifest y lockfile de npm. Dependencias nuevas: COCO-SSD 2.2.3, TensorFlow.js Core, Converter, CPU y WebGL 4.22.0.
