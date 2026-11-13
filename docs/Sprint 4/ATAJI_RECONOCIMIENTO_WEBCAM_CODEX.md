# TAJI — Módulo de reconocimiento inteligente por webcam

## Instrucciones para Codex

Implementa **dentro del proyecto TAJI existente** un módulo de demostración universitaria de reconocimiento visual con **Angular en el frontend y Django en el backend**.

Este documento define **lo que debe funcionar y cómo debe integrarse**, pero **no impone código, nombres de archivos, librerías de visión artificial ni una arquitectura paralela**. Antes de programar, inspecciona el repositorio y decide los detalles técnicos de acuerdo con las dependencias, patrones, componentes, APIs y convenciones reales de TAJI. No sustituyas Django ni Angular. No construyas otra aplicación desde cero.

## 1. Alcance real del proyecto

- **Una sola webcam** conectada a la computadora del usuario que abre TAJI en su navegador.
- La cámara **solo se activa al entrar al módulo y pulsar «Iniciar cámara»**, después de otorgar permiso; se desactiva al pulsar «Detener», cambiar de pantalla, cerrar el módulo o destruir el componente.
- La funcionalidad existe **únicamente para pruebas y demostración de universidad**. No es un sistema de vigilancia continua, no usa cámaras IP, RTSP, NVR, redes de cámaras ni procesamiento 24/7.
- El backend puede ejecutarse en un **VPS modesto, sin GPU**. No debe recibir ni procesar un flujo de video permanente.
- La prioridad es **una demo funcional, ligera y razonablemente precisa**; no una plataforma industrial.
- Respeta las funciones ya existentes de TAJI (condominios, residentes, usuarios, accesos, vehículos, permisos o registros, en la medida en que existan).

## 2. Objetivos funcionales

### A. Reconocimiento de objetos

Detecta sobre la imagen en vivo, como mínimo:

- Persona.
- Automóvil.
- Motocicleta.
- Perro.
- Gato.

Cuando el modelo lo soporte de forma fiable, puede incluir camión y autobús sin ampliar innecesariamente el alcance. Para cada detección muestra:

- Recuadro de ubicación sobre el video.
- Clase detectada en español.
- Confianza de la predicción.
- Estado actualizado mientras el objeto siga visible.

No confundas «detectar una persona» con «identificar quién es». **No implementes reconocimiento facial ni identificación biométrica.** Tampoco inventes raza del perro, marca/modelo del automóvil u otros atributos que no tengan un modelo verificable.

### B. Lectura de placas

Cuando se detecte un vehículo en una región útil de la imagen:

1. Localiza la zona de la placa mediante un método apropiado; no ejecutes OCR a ciegas sobre todo el fotograma.
2. Usa una imagen o recorte suficientemente nítido, preferiblemente extraído del fotograma original de mayor resolución.
3. Intenta reconocer los caracteres de la placa.
4. Normaliza caracteres y espacios **sin alterar arbitrariamente el resultado**.
5. Confirma la lectura cuando sea posible mediante varias observaciones y evita registrar lecturas inestables o con baja confianza como definitivas.
6. Muestra los estados: `leyendo`, `placa detectada`, `lectura incierta`, `sin placa legible` y `error`, según corresponda.
7. Consulta la información **únicamente en la base de datos autorizada de TAJI**.

No supongas que toda placa tiene un formato fijo. Si hay validación de formato, que sea configurable y compatible con las placas utilizadas en la demo. Un automóvil visto de lado, a distancia o sin placa visible puede no ser legible: informa esa limitación sin inventar valores.

### C. Información asociada a un vehículo

Si la placa leída coincide con un registro real de vehículos/residentes de TAJI, muestra únicamente los campos que ya estén disponibles y que el usuario autenticado pueda consultar, por ejemplo:

- Placa registrada.
- Vehículo y datos registrados, si existen.
- Residente vinculado, si existe y está autorizado mostrarlo.
- Unidad o vivienda vinculada, si existe.
- Estado de autorización de acceso, si el proyecto ya lo maneja.

Si no hay coincidencia, muestra **«Vehículo no registrado»**. Si no hay módulo de vehículos/residentes, implementa la integración mínima coherente con el proyecto **solo si es necesaria** y sin duplicar entidades; explica qué quedó disponible para la demo. **No consultes bases gubernamentales ni afirmes conocer al propietario legal por ver la matrícula.**

### D. Detección de perros y otros eventos

- Al detectar un perro, muestra un evento visual del tipo «Perro detectado».
- Permite registrar eventos significativos: `persona detectada`, `vehículo detectado`, `placa leída`, `vehículo registrado/no registrado`, `perro detectado`, `gato detectado`.
- Evita registrar un evento nuevo en cada fotograma para el mismo objeto; utiliza seguimiento sencillo, enfriamiento temporal o deduplicación.
- Las alertas son **informativas dentro de la web**. No envíes notificaciones masivas ni actives dispositivos externos.

## 3. Arquitectura y restricciones de rendimiento

**Preferencia por procesamiento local en el navegador:** la inferencia para clases generales debe ejecutarse en el frontend si es compatible con el proyecto y el navegador. Utiliza aceleración disponible y una alternativa razonable cuando no haya soporte. No hagas que el VPS procese continuamente todos los fotogramas.

Para lectura de placas, decide entre OCR local o procesamiento **puntual** en Django según la viabilidad y precisión. Si Django recibe imágenes, que sean **capturas o recortes ocasionales**, únicamente cuando se detecta un vehículo con posibilidades reales de leer la placa; nunca video continuo por defecto.

Pautas de optimización:

- Mostrar la webcam fluidamente **no obliga a analizar todos los fotogramas**.
- Comenzar con una frecuencia objetivo de **2–5 inferencias por segundo** y hacerla adaptable al rendimiento real del equipo.
- Analizar una versión redimensionada de la imagen para detección y conservar resolución suficiente para recortar la placa.
- Evitar instanciar el modelo, la cámara o las conexiones varias veces.
- No lanzar nuevas inferencias si la anterior sigue ejecutándose; gestionar correctamente la cola o descartar fotogramas.
- Activar OCR **solo cuando sea pertinente**, con límites de frecuencia por vehículo y cancelación de solicitudes obsoletas.
- Liberar pistas de cámara, memoria de procesamiento, temporizadores, tareas y suscripciones al detener el módulo.
- Evitar guardar video completo, capturas masivas, duplicados o peticiones por fotograma.
- Evaluar tamaño de descarga, compatibilidad, precisión y **licencia** antes de elegir modelos o dependencias.

**No fuerces ninguna librería concreta**: selecciona herramientas mantenidas, compatibles con Angular/Django y con el despliegue existente. Si eliges detección local y OCR remoto, documenta por qué. No hace falta microservicio de IA separado, salvo que el repositorio ya tenga uno y reutilizarlo sea claramente más simple.

## 4. Integración con TAJI

Primero revisa:

1. Estructura de Angular: rutas, módulos, componentes, servicios, estado, estilos y controles de acceso.
2. Estructura de Django: aplicaciones, modelos, autenticación, permisos, APIs, configuración y migraciones.
3. Entidades existentes sobre residentes, condominios, unidades, vehículos, visitas y accesos.
4. Dependencias existentes reutilizables y forma actual de conectar frontend y backend.
5. Convenciones de pruebas, documentación y despliegue.

Después integra un apartado visible en la navegación adecuada, por ejemplo **«Reconocimiento por cámara»**, respetando el diseño visual y los patrones de TAJI. Si existen roles/condominios separados, los registros y consultas deben respetar ese ámbito; no se deben revelar datos de otro condominio.

**No reestructures el proyecto, no renombres indiscriminadamente componentes ni alteres módulos ajenos.** Crea solo los elementos y migraciones necesarios. Reutiliza los servicios/API existentes. Cualquier cambio transversal debe estar justificado.

## 5. Experiencia de usuario (Angular)

La pantalla debe incluir:

- Panel de video de webcam con recuadros de detección superpuestos, correctamente alineados aunque cambie el tamaño del contenedor.
- Botón **«Iniciar cámara»** y **«Detener cámara»**.
- Indicador claro del estado: `apagada`, `solicitando permiso`, `cargando IA`, `reconociendo`, `sin cámara`, `error`.
- Contador y lista de objetos visibles, con sus etiquetas y confianza.
- Sección **«Última placa leída»**, con resultado y nivel de certeza o advertencia.
- Sección **«Datos del vehículo»**, alimentada por TAJI cuando haya coincidencia.
- Lista breve de eventos recientes, con clase, hora y resultado.
- Mensajes claros si el navegador no soporta el reconocimiento, no se otorgó permiso, no existe webcam o la placa no es legible.

No pongas datos ficticios como si fueran predicciones reales. Si usas datos de demostración, identifícalos explícitamente. La interfaz debe ser utilizable desde una computadora corriente y coherente con el diseño de TAJI.

El botón «Iniciar» debe provocar una acción real. No actives la webcam al abrir cualquier otra página del sistema.

## 6. Backend Django y persistencia

El backend debe servir para:

- Resolver consultas de vehículos y residentes a partir de una placa reconocida, con autenticación y autorización.
- Recibir eventos relevantes, solo cuando sea necesario para la demo.
- Realizar OCR puntual de una captura **solo si la arquitectura elegida lo necesita**.
- Proporcionar los datos al frontend usando la estructura y los contratos de API que ya siga TAJI.

Persistencia mínima, si aporta valor y no existe una entidad equivalente: fecha/hora, tipo de evento, resultado, placa si se obtuvo, estado de coincidencia y referencia de condominio/usuario cuando corresponda. El almacenamiento de imágenes debe ser **opcional, explícito y limitado**; por defecto, no guardar vídeo ni imágenes innecesarias.

Requisitos de seguridad:

- Verificación de sesión/token y permisos en el backend, no solo en Angular.
- Validación de tipos y tamaños de imágenes si se habilita envío de capturas.
- Límites de frecuencia de OCR y operaciones costosas.
- Tratamiento consistente de errores sin filtrar datos personales ni detalles internos.
- Respetar la política de autenticación, CORS/CSRF y configuración existente del proyecto.
- No exponer datos de residentes en un endpoint público.
- Acceso a la cámara mediante los permisos del navegador; utilizar contexto seguro (HTTPS o localhost).

## 7. Casos de prueba obligatorios

1. **Inicio manual:** entrar al módulo no enciende automáticamente la cámara; al pulsar «Iniciar» se solicita permiso.
2. **Detención real:** al pulsar «Detener» se apaga la webcam y termina el procesamiento.
3. **Cambio de ruta:** al salir del módulo se liberan los recursos de cámara.
4. **Objetos:** una persona, automóvil, motocicleta, perro y gato son reconocidos en condiciones adecuadas y muestran recuadros coherentes.
5. **Placa legible:** al mostrar una placa suficientemente clara se intenta la lectura y aparece el resultado validado.
6. **Placa ilegible:** no se inventan números ni se asume una coincidencia.
7. **Placa registrada:** se recuperan los datos vinculados a esa placa desde TAJI, si el registro existe.
8. **Placa no registrada:** se indica que no existe coincidencia sin mostrar información inventada.
9. **Eventos:** un perro que permanece visible no genera cientos de registros duplicados.
10. **Permisos:** si el usuario deniega la cámara, la interfaz muestra cómo recuperarse del error.
11. **Sin webcam o sin aceleración:** se informa la limitación o se usa un mecanismo alternativo razonable sin bloquear todo TAJI.
12. **VPS:** con la pantalla cerrada, la carga asociada a reconocimiento debe ser nula o despreciable; durante la prueba no debe existir subida continua de video.
13. **Autorización:** un usuario sin permisos no puede consultar vehículos de otros ámbitos del sistema.
14. **Regresión:** las funcionalidades y pruebas existentes de TAJI siguen funcionando.

Si no dispones de hardware o datos para verificar una condición física, crea pruebas automatizadas para la lógica comprobable y **declara explícitamente qué requiere validación manual**; no afirmes haber probado detección real sin haberlo hecho.

## 8. Criterios de finalización

La tarea está completa cuando:

- Desde TAJI se puede abrir el módulo de cámara sin crear otra aplicación.
- La webcam se inicia y se detiene desde la interfaz.
- Se ven detecciones de clases generales y sus recuadros.
- Se intenta la lectura de placas **de verdad**, no con valores simulados encubiertos.
- Las placas reconocidas se contrastan con los registros disponibles del sistema.
- Los animales detectados aparecen como eventos sin duplicaciones excesivas.
- El VPS no realiza inferencia continua ni requiere GPU para operar el backend.
- Los errores comunes están tratados y no se afecta la funcionalidad existente.
- Las pruebas ejecutables pasan, y las limitaciones de precisión están documentadas.

## 9. Forma de trabajo exigida a Codex

1. **Audita primero el repositorio.** No supongas nombres de carpetas, modelos, rutas o dependencias.
2. **Expón un plan corto basado en lo que realmente encuentres**, señalando qué se reutiliza, qué se añade y dónde se ejecutará cada parte del reconocimiento.
3. **Implementa efectivamente la solución** siguiendo las convenciones del repositorio; evita respuestas que se limiten a describir cómo lo harías.
4. Elige modelos y librerías por compatibilidad, tamaño, rendimiento, licencia y precisión. **No introduzcas paquetes por moda ni dependencias innecesarias.**
5. Verifica las interfaces frontend/backend, migraciones necesarias, manejo de permisos, cancelación y liberación de recursos.
6. Añade o actualiza pruebas relevantes y ejecuta las que sea posible ejecutar en el entorno.
7. Documenta pasos concretos de instalación/configuración y cómo iniciar una demo desde el navegador.
8. Al terminar, informa: **archivos modificados**, **cómo probarlo**, **resultados de pruebas**, **dependencias añadidas** y **limitaciones o validaciones pendientes**.

## 10. Exclusiones explícitas

**No implementes:** 20 cámaras, CCTV industrial, cámaras IP, RTSP, procesamiento 24/7, NVR, grabación permanente, reconocimiento facial, biometría, portones físicos, dispositivos IoT, facturación, compra de hardware, un nuevo frontend, un backend alternativo, un VPS con GPU obligatorio, o un sistema de microservicios ajeno a la arquitectura del proyecto.

**No hagas sobreingeniería.** El objetivo es una **demostración universitaria convincente con una sola webcam**, usando **Django + Angular** y aprovechando la estructura real de **TAJI**.
