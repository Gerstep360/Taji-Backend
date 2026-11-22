# Integración Sprint 4 en Gerstep — CU26–CU37

Se aplicaron los aportes por funcionalidad, con `cherry-pick -x`, desde las
referencias de `origin/Gerstep`. No se fusionaron ramas completas.

| CU | Autor | Backend | Web | Móvil |
| --- | --- | --- | --- | --- |
| CU26 | Eunice (`18283`) | `d9da4fa` | `e14ee31` | `d7e957b` |
| CU27 | Daniel (`danixprox`) | `cb2d5c2` | `bbe79e2` | `628a639` |
| CU28 | Noelia (`707Noa`) | `e4e04a2`, `859e825` | `817b6ef`, `32116ed`, `476f115` | `cf3c0bc`, `919c02b` |
| CU29 | Rodrigo (`Viveros123`) | `c2a9d7a` | `e5a5d8b` | `3319e14` |
| CU30 | Cristel (`iscrisis`) | `88eed00` | `a073c6be` | No aplica |

Se preservó el trabajo de Gerstep para CU31 (voz y reportes), CU32 (webcam y
observaciones) y CU33–CU37 (Operaciones). No se volvieron a aplicar esos commits
ni el historial anterior de Noelia para CU18. CU27 ya estaba en el `main` del
Backend (PR #28), pero faltaba en Gerstep y se tomó solo el commit indicado.
Se omitieron `cc8df3c` (actualización Angular independiente) y `3894521` (URL de
emulador); no eran necesarios para la integración.

## Resoluciones

- CU26/CU27: se mantuvo la unicidad del nombre de un área **por condominio** y
  los campos de ciclo de vida de la reserva. Los dos nodos `community.0005_*` se
  conservaron y `0006_merge_cu26_cu27` los reconcilia sin duplicar operaciones.
  En PostgreSQL dos transacciones con reservas solapadas no pueden confirmar
  ambas: la segunda viola `ex_reservation_no_overlap`.
- CU28: el listado y el marcado de notificaciones de comunicados respetan el
  condominio activo; el cliente Flutter admite las respuestas sin `user_id`.
- Web: se conservaron calendario de áreas, administración de reservas,
  comunicados y su campana, asambleas y dashboard. Las rutas de voz, cámara,
  Operaciones y los endpoints de mantenimiento siguen separados.
- Móvil: las rutas nativas de comunidad conviven con autenticación, selección
  de condominio, incidentes, activos, mantenimiento, voz y PDF. La URL de
  producción y las opciones de entorno no se sustituyeron.

## Cómo reproducir la verificación

1. Backend: configura `DATABASE_URL` de una instancia **aislada** de PostgreSQL
   y ejecuta `check`, `makemigrations --check --dry-run`, `migrate --plan`,
   `migrate` y `test` con `manage.py`. La corrida de integración usó un hash rápido
   y correo en memoria solo en el proceso de pruebas.
2. Para E2E, inicia `python scripts/serve_cu24_test_api.py` desde Backend. Es una
   API HTTP real en `http://localhost:18766`, con datos ficticios, SQLite en
   memoria y Operaciones con un proveedor NVIDIA simulado.
3. Web: ejecuta `npm ci`, `npm run build` y `npm test -- --watch=false`. Define
   `CU24_LIVE_URL` y `TAJI_E2E_BACKEND` con la URL del servidor de pruebas y
   `TAJI_E2E_BROWSER_CHANNEL=msedge` para `npm run test:e2e` en Edge.
4. Móvil: ejecuta `flutter pub get`, `flutter analyze`, `flutter test` y
   `flutter build apk --debug --no-pub`. Con `CU24_LIVE_URL` definida, ejecuta
   `flutter test test/community_reports_live_test.dart test/assets_maintenance_live_test.dart`
   para probar el cliente Dart contra la misma API.

La cámara y el micrófono se verifican con entradas sintéticas o dobles. Las
pruebas no certifican el hardware de un teléfono, latencia/disponibilidad de
NVIDIA, recepción FCM en un dispositivo ni el entorno de producción.
