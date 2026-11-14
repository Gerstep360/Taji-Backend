# CU32 · Visión y memoria de incidencias

En **Incidencias e IA → Reconocimiento por cámara**, inicia la webcam y abre **Observaciones de cámara**. Selecciona su sector real, decide si quieres conservar evidencia y pulsa **Activar análisis visual**. Usa solo imágenes autorizadas; no se capta audio. La cámara, la detección COCO-SSD y la lectura de placas siguen funcionando por separado. No se modifica la app Flutter.

El historial permite buscar por texto, fecha, sector, relevancia, estado y antecedentes abiertos. Un revisor autorizado puede confirmar, corregir, descartar o proponer una incidencia sin alterar la predicción inicial ni crear una incidencia oficial. Django recupera antecedentes después de la inferencia mediante términos compartidos, cercanía y estado, sobre candidatos autorizados del condominio. No salen títulos, descripciones ni antecedentes hacia NVIDIA. Una similitud no prueba identidad ni causalidad.

## Inicio

1. Usa `.env.example` como referencia para `TAJI_VISION_*` en el `.env` privado del backend, o `/etc/taji/backend.env` en producción. Rota las credenciales si estaban en documentos compartidos. No deben estar en Git, Angular ni en el entorno virtual.
2. Aplica `python manage.py migrate`. `security.0008_cu32_visual_vision` es aditiva. El `runserver` local inicia el trabajador si la visión está habilitada, `DEBUG=True` y `TAJI_VISION_DEV_WORKER=True`. Para operarlo aparte, desactiva el trabajador de desarrollo y ejecuta `python manage.py run_visual_vision`.
3. En VPS, después de respaldo y migración, instala `deploy/taji-visual-vision.service`, recarga systemd y habilita la unidad. Verifica `systemctl is-active taji-visual-vision` y el indicador **Análisis visual** en el visor. Mantén HTTPS y el worker de CU22 sin cambios.

## Verificación NVIDIA

`python manage.py probe_visual_vision --live` envía una figura JPEG y un MP4 sintético, no imágenes del condominio. Se verificó `integrate.api.nvidia.com`:

| Modelo y formato | Resultado | Latencia | Tamaño del medio |
| --- | --- | ---: | ---: |
| `nvidia/cosmos3-nano-reasoner` · JPEG | HTTP 404 | 375 ms | 3.541 B |
| `nvidia/cosmos3-nano-reasoner` · MP4/H.264, 6 s, 4 FPS | HTTP 404 | 422 ms | 2.337 B |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` · JPEG | HTTP 200; identificó el color | 1.093 ms | 3.541 B |
| Omni · MP4/H.264 | HTTP 200; identificó el orden de colores | 1.156 ms | 2.337 B |
| Omni · mismo MP4 con el prompt de Taji | HTTP 200; pasó la validación JSON | 2.188 ms | 2.337 B |
| Omni · MP4 sintético de Edge, Django y PostgreSQL aislado | Resultado válido `skipped` por escena vacía; sesión cerrada | 1.312 ms | 1.649 B antes de normalizar |

El perfil local usa Omni con `TAJI_VISION_COSMOS_MODE=off`, `TAJI_VISION_FALLBACK_VERIFIED=True`, `TAJI_VISION_FALLBACK_VIDEO_VERIFIED=True` y `TAJI_VISION_ENABLED=True`. La latencia no incluye cola, cámara ni interfaz. Django valida el MP4 con ffprobe y normaliza el contenedor del navegador con ffmpeg, sin recodificar. Si falta alguno o el navegador no puede codificar MP4/H.264, se usa JPEG cuando está habilitado. El modo fijo no puede confirmar acciones ni secuencias. Las cuotas reales no se midieron. Para Cosmos, la guía de [NVIDIA Build](https://build.nvidia.com/nvidia/cosmos3-nano-reasoner/deploy) documenta un NIM dedicado; no se verificó ese despliegue ni se habilitó en el VPS.

La API principal es `/api/v1/paquete3/cu32/`. El prefijo anterior `/api/v1/security/cu32/` se conserva como alias autenticado. La URL web `/reconocimiento-camara` no cambia. Los modelos ya migrados conservan las tablas `security_*` para no mover datos ni romper instalaciones existentes.

## Límites

- Una revisión inicial. Luego un comparador de 24 × 16 píxeles, independiente de COCO-SSD, permite adelantar revisiones ante cambios sostenidos. Pausa mínima de 40 s; revisión general a 150 s con actividad leve o a 240 s si la imagen sigue estable. No cubre todos los sucesos. Si se habilita video, el navegador conserva 24 fotogramas en un búfer circular a ~4 FPS y codifica solo la ventana seleccionada. En modo fijo no hay búfer de video.
- Una ventana en curso por sesión; 3 envíos por 5 minutos por usuario, hasta 20 por sesión y cuotas adicionales por usuario, condominio y global. La sesión vence a los 20 min. Máximos: 200 KB JPEG o 900 KB MP4 sin audio. Cuotas y retención son configurables.
- El medio de cola se elimina al reclamar, cancelar o expirar. Por defecto no se guarda evidencia. Si el usuario opta por conservarla, queda solo en observaciones guardadas, con acceso autenticado y retención de 30 días por defecto. Al detener, ocultar o salir se detienen nuevas capturas; una petición ya iniciada en NVIDIA puede terminar sin publicar resultados de una sesión cerrada.
- El filtro de antecedentes abiertos comprueba hasta 500 observaciones candidatas recientes. No es un buscador semántico de cobertura ilimitada ni un sistema de respuesta automática.
