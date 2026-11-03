# CU22: procesamiento real con Nemotron Nano Omni

## Causa del bloqueo local

El 1 de noviembre de 2026 la API estaba atendiendo peticiones, pero no había un
trabajador IA activo. Se encontró un trabajo `QUEUED` con unos 24 minutos de
antigüedad. Esperar desde Angular o cambiar el modelo no podía procesar esa cola.

`runserver` ahora inicia un único hilo trabajador de desarrollo desde
`IncidentsConfig.ready`, únicamente con DEBUG, el comando runserver y el proceso
real del autoreloader (o `--noreload`). No se inicia en tests, migrate o gunicorn.
El panel no levanta otro proceso competidor. En producción se mantiene el servicio
separado `taji-incident-ai.service`.

La migración `0010_ai_worker_heartbeat` permite que la API detecte al trabajador.
Publica un latido cada 15 segundos y se considera desconectado si supera 90
segundos. La respuesta GET de análisis incluye `processor.available`, `last_seen`
y un mensaje sin información del host ni credenciales. Angular distingue una
cola sin procesador de una petición real al proveedor, y permite actualizar el
estado sin encolar solicitudes duplicadas.

## Configuración e imágenes

La configuración efectiva de esta máquina está en `Backend/.env`, excluido de Git.
Modelo: `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`.
La credencial nunca se entrega a Angular/Flutter ni se guarda en argumentos o logs.
Una clave publicada en una conversación debe rotarse.

Se usa `/v1/chat/completions`, respuesta JSON, `stream=false`, temperatura cero y
`chat_template_kwargs.enable_thinking=false`. El límite por defecto es de 1600
tokens y 30 segundos, configurable y acotado. No se copian los presupuestos de
65536 tokens/16384 de razonamiento del ejemplo, porque añadirían espera innecesaria
al formulario. No se descargan ni se ejecutan pesos del modelo en la máquina.

Las fotos se guardan antes de encolar, por lo que el snapshot incluye sus IDs.
El trabajador abre únicamente el storage del backend: nunca obtiene URLs escritas
por el reportante. Convierte JPEG/PNG/WebP a JPEG, reduce el lado a 1280 px por
defecto, elimina EXIF y envía como base64 privado por HTTPS. Límite por defecto:
dos fotos por análisis, tres como máximo configurable; máximo 20 megapíxeles por
archivo para acotar memoria. Base64 y píxeles no se copian al snapshot de BD.

La respuesta conserva qué fotos se enviaron y por qué se omitió alguna. PDF no
se envía como imagen. Las observaciones visuales identifican la foto mediante
`source=image` y `attachment_id`, y se presentan como propuestas por verificar.
Un ID de foto no enviada invalida la propuesta. Las entidades textuales siguen
requiriendo citas literales del reporte; las imágenes no permiten identificar
personas ni inferir identidades o rasgos sensibles.

Las reglas de seguridad también revisan los peligros visuales y no permiten
reducir su prioridad silenciosamente. La clasificación oficial solo cambia al
guardar una revisión autorizada; se conserva la predicción original.

## Qué se verificó, y qué no demuestra

`evaluation_cases.json` contiene cinco escenarios etiquetados de regresión.
`tests_live.py`, activado explícitamente mediante `TAJI_NVIDIA_LIVE_TEST=1`, envía
esos escenarios a NVIDIA real y valida categoría y prioridad después de aplicar
las reglas del backend. También prueba POST con foto, almacenamiento del análisis,
consulta del residente y revisión autorizada.

Resultados observados con Omni:

| Caso | Categoría | Prioridad validada | Tiempo de análisis |
| --- | --- | --- | --- |
| Incendio con niños a salvo | FIRE | HIGH | 3.233 s |
| Incendio negado y limpieza | CLEANING | LOW | 1.842 s |
| Agua en tablero eléctrico | ELECTRICITY | HIGH | 2.750 s |
| Niños atrapados en ascensor | PERSON_SAFETY | CRITICAL | 2.312 s |
| Foto y texto subidos por la API | Análisis almacenado | Revisión pendiente | 1.891 s |
| Registro, análisis y revisión | Análisis conservado | Revisión autorizada 200 | 2.546 s |

Además se verificó el servidor local realmente ejecutándose en el puerto 8000,
sin invocar el procesador desde la prueba: encolado 16 ms, trabajador 2.234 s,
flujo completo 3.250 s y consulta autenticada HTTP 200 con latido activo.
El fixture sintético se eliminó al terminar. Evidencia: `CU22.omni-local.json`.

Son muestras funcionales y de regresión, no una garantía de precisión ni de
disponibilidad de NVIDIA. La calidad real necesita un conjunto representativo
de reportes e imágenes del condominio revisados por personas. Cualquier fallo
del proveedor o respuesta no verificable conserva el reporte y habilita revisión
manual, sin inventar una respuesta exitosa.

## Violencia explícita, incluso descrita como juego

La migración `0011_critical_violence_rules` agrega reglas de disparos, lesiones por
armas, amenazas de muerte y sangrado grave en el catálogo `RiskRule`. No dependen
de que NVIDIA interprete un meme. Una amenaza explícita impone prioridad mínima
CRITICAL y puntuación 100; negar el hecho o describir un simulacro no activa la
regla. Una lesión violenta pasada sigue requiriendo atención y revisión.

El reporte local `INC-1-000002` se volvió a analizar con Omni: SUCCEEDED,
CRITICAL, 100/100, 2500 ms, versión `cu22-4-threats`. NVIDIA sugirió HIGH y el
servidor elevó a CRITICAL. La propuesta anterior queda conservada; no se sustituye
la clasificación oficial sin revisión autorizada. Es una verificación puntual,
no una garantía general de exactitud.

Las pruebas simulan además que NVIDIA devuelve LOW y que falla por timeout:
el peligro explícito permanece CRITICAL. Un fallo conserva su estado FAILED y
la interfaz identifica la alerta como regla local, no como análisis exitoso.
Reducir el mínimo exige permiso de revisión, confirmación de excepción y motivo
de al menos 20 caracteres. Las reglas no sustituyen la atención de emergencias.

## Fotos visibles, sin hacer públicos los archivos

El detalle incluye `attachments[].preview_url` para imágenes. El endpoint GET
`/api/v1/paquete3/incidents/{codigo}/attachments/{id}/preview/` exige la misma
autenticación y acceso al condominio/incidencia que su detalle. Solo permite
JPEG, PNG y WebP del directorio propio del reporte, hasta 20 MP; responde inline,
`nosniff` y `private, no-store`. Rechaza SVG, rutas ajenas y archivos inexistentes.
No pone tokens en URLs. Se mantiene la descarga original como acción secundaria.

La galería Angular se reutiliza en seguimiento y clasificación: miniaturas con
carga diferida, ampliación, anterior/siguiente, Escape y retorno del foco; los
documentos conservan su enlace de descarga. Las capturas de pruebas usan un
bitmap diagnóstico, no fotografías de residentes.

Fuentes oficiales: [API de Nano Omni](https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-nano-omni-30b-a3b-reasoning),
[modelo, imágenes y control del razonamiento](https://build.nvidia.com/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning/modelcard).
