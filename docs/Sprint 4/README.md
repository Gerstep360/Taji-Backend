# Sprint 4 — CU32 Reconocimiento por cámara

Especificación: [ATAJI_RECONOCIMIENTO_WEBCAM_CODEX.md](ATAJI_RECONOCIMIENTO_WEBCAM_CODEX.md). Identificadores CU32 y T146–T149 propuestos para este incremento. No se modificó Móvil.

## Ficha del caso de uso

| Campo | Descripción |
| --- | --- |
| Actor | Operador autenticado con condominio activo y permiso `validate_visits` |
| Disparador | Pulsa **Iniciar cámara** en **Incidencias e IA → Reconocimiento por cámara** |
| Precondiciones | HTTPS o localhost, navegador compatible, una webcam autorizada |
| Flujo principal | Detectar objetos en el navegador. Si el operador activa el análisis, comparar escenas, enviar una ventana autorizada a NVIDIA y mostrar observaciones y posibles antecedentes. El OCR de placas sigue siendo opcional e independiente. |
| Alternativas | Permiso denegado, cámara ausente u ocupada, error de modelo, lectura incierta, placa no legible, proveedor no disponible o vehículo no registrado. |
| Postcondición | Al detener, ocultar pestaña, cambiar de condominio o salir se liberan las pistas y se cancelan trabajos pendientes. Se conservan observaciones guardadas y revisiones según la política de retención. |
| Exclusiones | Sin identificación facial, biometría, grabación continua, vigilancia permanente, consulta gubernamental ni autorización de ingreso. |

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
| POST `/api/v1/paquete3/cu32/plate/read/` | Multipart `image`, JPEG. Devuelve `{"plate": null}` o texto candidato. | 350 KB; 100–640 px de ancho, 32–360 px de alto; 6/min por usuario en la caché DRF. |
| POST `/api/v1/paquete3/cu32/plate/lookup/` | JSON `plate`. Devuelve `registered` y `vehicle` con placa y descripción, o nulo. | 12/min por usuario; coincidencia exacta normalizada solo en el condominio activo. |
| `/api/v1/paquete3/cu32/vision/…` | Configuración, sesión, ventanas, historial, revisión y evidencia protegida. | Permisos de condominio, cuotas de envío, una ventana en vuelo por sesión. |

Las rutas requieren autenticación y permiso, no aceptan un condominio del cuerpo y devuelven `Cache-Control: no-store`. Los recortes del OCR no se guardan. La observación contextual es independiente y puede conservar evidencia opcional, con retención. Ver la [guía actual del incremento](../CU32_VISION_CONTEXTUAL.md) para activación, rutas, pruebas y limitaciones.

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
| Comunicación | [Fuente](<Diagrama de comunicación/CU32_Comunicacion.puml>) | [PNG](<Diagrama de comunicación/CU32_Comunicacion.png>) |
| Navegación | [Fuente](<Diagrama de Navegación/CU32_Navegacion.puml>) | [PNG](<Diagrama de Navegación/CU32_Navegacion.png>) |
| Tiempo | [Fuente](<Diagrama de Tiempo/CU32_Tiempo.puml>) | [PNG](<Diagrama de Tiempo/CU32_Tiempo.png>) |

## Tablas del Sprint

| ID | Tarea | Plataforma | Horas estimadas / PHU |
| --- | --- | --- | ---: |
| T146 | Gestionar webcam, consentimiento y sesión visual | Web | 5 |
| T147 | Detectar objetos y activar análisis contextual por cambios | Web / IA | 6 |
| T148 | Leer recortes y validar el consenso de placa | Backend / IA | 6 |
| T149 | Validar catálogo, antecedentes y revisión por condominio | Backend / QA | 4 |
| | **Total del plan original (sin reestimación)** | | **21** |

- [Historias por tarea](<historias de usuario/Historias_CU32.xlsx>), [plan de pruebas](<pruebas/Plan de pruebas (criterios de aceptación)/Plan_CU32.xlsx>) (28 casos) y [reporte consolidado por CU](<pruebas/reporte de pruebas/Reporte_CU32.xlsx>).
- [Planificación del Sprint 4](<otros/Planificacion_CU32.xlsx>) y [Daily Scrum planificado](<otros/Daily_Scrum_CU32.xlsx>). No son actas de reuniones ya realizadas.

## Verificación

| Comprobación | Resultado |
| --- | --- |
| Django y migraciones | Migración aditiva y suite CU32 verificadas en PostgreSQL 18 aislado. |
| Angular | 157 pruebas unitarias en la ampliación y compilación correcta después de mover el módulo; advertencias preexistentes de dependencias y estilos. |
| Edge, fuente sintética y API controlada | 7 recorridos aprobados, incluidos COCO-SSD real y captura MP4 desde el búfer sin audio. |
| NVIDIA real | Omni reconoció el orden de colores y aceptó un MP4 sintético de Edge normalizado por Django; la escena vacía se descartó en 1,312 s de inferencia. Cosmos respondió 404. |
| Pendiente | Webcam y placas físicas autorizadas, precisión operativa, migración de la base del despliegue y medición en VPS. |

### Archivos de implementación

- **Backend:** `paquetes/paquete3_incidencias_ia/cu32_webcam/`, `config/urls.py`, migraciones `security.0007` y `security.0008`.
- **Frontend:** `app.routes.ts`, navegación de `main-layout.component.ts`, `paquetes/paquete3_incidencias_ia/cu32_webcam/` y `e2e/cu32.spec.ts`. Se conserva COCO-SSD 2.2.3 y TensorFlow.js 4.22.0.
