# Organización por paquetes e integración del Sprint 1

La integración conserva los modelos, tablas, migraciones históricas, clases y
reglas de los compañeros. Los cambios de ubicación se concentran en vistas,
serializadores y permisos. Los módulos anteriores importan las mismas clases
para conservar los imports que aparecen en los diagramas y pruebas.

| Paquete | Casos de uso | Carpeta | Apps de persistencia compartidas |
| --- | --- | --- | --- |
| Gestión de Usuarios y Condominio | CU01–CU07 | `paquetes/paquete1_usuarios_condominio` | `accounts`, `condominiums` |
| Seguridad, Accesos y Auditoría | CU08–CU17 | `paquetes/paquete2_seguridad_accesos` | `security`, `auditlog` |
| Incidencias e Inteligencia Artificial | CU18–CU22 | `paquetes/paquete3_incidencias_ia` | `incidents` |
| Activos y Mantenimiento | CU23–CU25 | `paquetes/paquete4_activos_mantenimiento` | `maintenance` |
| Servicios y Administración Comunitaria | CU26–CU30 | `paquetes/paquete5_servicios_comunidad` | `community`, `notifications` |

Las carpetas de los CU08–CU30 son reservas de estructura para los siguientes
sprints. Los modelos existentes de esos paquetes sí forman parte de la base;
no se eliminan por no tener todavía endpoints. No se declara implementada IA,
reconocimiento facial, QR ni los flujos futuros solo por existir una carpeta.

## Paquete 1

| CU | Carpeta | Rutas bajo `/api/v1/` |
| --- | --- | --- |
| CU01 Autenticación | `cu01_autenticacion` | `auth/` |
| CU02 Usuarios, roles y permisos | `cu02_roles_permisos` | `roles/` |
| CU03 Datos generales del condominio | `cu03_datos_condominio` | `condominiums/`, `condominiums/current/` |
| CU04 Sectores y unidades | `cu04_sectores_unidades` | `sectors/`, `units/` |
| CU05 Residentes y copropietarios | `cu05_residentes` | `residents/` |
| CU06 Asociar residentes a unidades | `cu06_asociar_residentes_unidades` | `resident-units/`, `resident-directory/` |
| CU07 Personal | `cu07_personal` | `staff/` |

Las mismas rutas están disponibles bajo `/api/v1/paquete1/`. El CRUD de
`residents/` conserva la implementación de Cristel. El directorio de solo lectura
de Daniel queda accesible en `resident-directory/`, sin sustituir el CRUD.
`Person` sigue siendo la fuente única de datos personales. Las identidades
Django `accounts` y `condominiums` no cambian y no se recrean tablas al mover
las implementaciones a paquetes.

## Integración

Se integraron #8 Eunice, #9 Cristel y #10 Daniel en ese orden. #11 Rodrigo ya
es ancestro de la rama de Daniel; GitHub reconoce ambos al publicar ese merge.
En los conflictos se conservaron las clases y pruebas de cada CU. En el punto
de aprobación de residentes, donde Cristel y Daniel añadieron la misma función,
se conservó la versión de Cristel que evita duplicar `Resident` para una `Person`.
Los documentos y diagramas originales permanecen disponibles.

La migración adicional `condominiums.0005_sync_condominium_sequence` sincroniza
el contador PostgreSQL después de la semilla con ID 1. Se reprodujo que una
instalación vacía podía fallar al crear el siguiente condominio con clave
duplicada. La corrección es posterior a las migraciones originales y no
elimina ni transforma registros.

## Relación con el Sprint 0 y Sprint 1

| Tareas | Evidencia en el backend |
| --- | --- |
| T001–T002 | Proyecto Django, ocho apps de dominio, PostgreSQL y migraciones históricas; configuración local, de pruebas y producción |
| T003 / T058 | Django REST Framework, paginación, manejo común de errores y OpenAPI/Swagger |
| T004–T007 | `Person`, usuario personalizado, roles/permisos, fixtures, comando `seed_rbac` y Django Admin |
| T008–T009 | Login, refresh, logout/blacklist, cookies/Bearer, intentos fallidos y bloqueo; implementación trasladada a CU01 |
| T010–T016 | CU02–CU07 integrados en el Paquete 1 |
| T076–T077 / T101 | Trabajo de frontend y móvil, fuera de este repositorio; no verificable desde este backend |
| T138–T144 | Arquitectura y ceremonias Scrum: su realización no puede inferirse del código |

La planificación proporcionada menciona React; el README heredado menciona
Angular. Esta integración no modifica ni acredita el framework del frontend.

## Hallazgos funcionales conservados para revisión del equipo

- CU03 usa solamente `IsAuthenticated`: cualquier usuario autenticado puede
  modificar datos del condominio. No se cambió esta regla por la instrucción de
  preservar la lógica del compañero. Debe revisarse antes de exponer la API a
  usuarios reales, conforme a los permisos administrativos de CU03.
- La respuesta 404 personalizada de `condominiums/current/` conserva el formato
  original `detail`, diferente del formato común `error` del backend.
- La reversión histórica de la migración semilla 0003 elimina el condominio ID 1;
  no debe usarse como procedimiento de recuperación de producción. El despliegue
  aplica migraciones hacia adelante y toma un respaldo primero.
- Correo SMTP, DNS y firewall son datos de operación que deben configurarse en
  el VPS. Pasar las pruebas no sustituye esa configuración.

Los detalles de instalación, actualización y recuperación están en
[`deploy/README.md`](../deploy/README.md).
