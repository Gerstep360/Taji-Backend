# CU22: corrección de latencia NVIDIA

2026-11-03. Se mantiene `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` para texto e imágenes.

Diagnóstico: no había trabajos en cola ni proxy HTTP en el VPS; los dos análisis reportados agotaban unos 30 s. Cada inferencia abría y cerraba un cliente independiente. También se detectaron placeholders de entidades con texto vacío que invalidaban una respuesta por lo demás utilizable.

Cambios:

- Cliente HTTP reutilizado por proceso, conexiones keep-alive limitadas; reconexión si se atasca.
- Un solo reintento para timeout, conexión fallida o error 5xx, sin repetir autenticación, límites de cuota, rechazo de formato o salida truncada.
- Presupuesto compartido entre intentos; espera reducida por intento en texto. Las imágenes conservan un margen mayor. No hay reintentos ilimitados ni espera de 30 s por cada intento.
- JSON de entrada compacto, salida acotada, modo sin pensamiento y `top_k=1`/temperatura 0.2 según [NVIDIA](https://build.nvidia.com/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning/modelcard).
- Solo se omiten entidades cuyo texto está vacío; no se rellenan ni se inventan evidencias. El JSON literal original se conserva para auditoría. Categorías permitidas, citas literales, límites, negaciones y reglas críticas siguen validados.

Verificación local: suite completa de 682 pruebas, 6 omitidas; ninguna fallida. Casos adicionales de reconexión, cliente reutilizado, presupuesto agotado, ausencia de reintento ante 401 y conservación de respuesta original.

Última tanda sintética desde el VPS, antes de activar: 3/3 respuestas válidas en 2.092, 2.577 y 2.231 s. Estas medidas no son un SLA: el servicio compartido de NVIDIA puede sufrir nuevas demoras o caídas. No se ocultan esos fallos como análisis exitosos.

Los análisis históricos fallidos permanecen auditables. Reintentar desde su incidencia crea un nuevo análisis; no se borra la predicción anterior ni se modifica silenciosamente una corrección humana.
