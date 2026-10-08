# Despliegue de Taji en un VPS

El instalador está preparado para Ubuntu 24.04 o Debian 12 y posteriores, con
systemd. Instala Python, venv, PostgreSQL, Nginx, Gunicorn, Certbot y dependencias.
Usa `main` de https://github.com/Gerstep360/Taji-Backend.git.

## Primera instalación

1. Apunta el registro DNS A del dominio de la API al VPS. Si publicas AAAA, IPv6
   también debe llegar al servidor. Permite TCP 80 y 443 en el firewall del
   proveedor y del sistema; conserva el acceso SSH. PostgreSQL y Gunicorn no
   necesitan puertos públicos. No se modifica automáticamente el firewall.
2. Ejecuta en el VPS, reemplazando los tres valores de ejemplo:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/Gerstep360/Taji-Backend.git
cd Taji-Backend
sudo bash deploy/vps.sh install api.ejemplo.com correo@ejemplo.com https://web.ejemplo.com
```

El último argumento es el origen HTTPS del frontend, sin ruta ni barra final.
El correo se utiliza para el certificado de Let's Encrypt. Debes aceptar sus
condiciones de servicio para usar esa emisión automatizada (`--agree-tos`).
El dominio debe estar accesible desde Internet para validar el certificado.

La instalación crea un usuario de sistema `taji`, una base `taji` y su rol SQL.
Genera contraseñas y una clave Django aleatorias en `/etc/taji/backend.env`,
legible solamente por root y el grupo del servicio. Si la base o el rol ya
existen sin ese archivo de configuración, se detiene para no sobrescribirlos.
La configuración actual del respaldo admite la base local que crea el
instalador; una base remota o credenciales personalizadas requieren adaptar
la comprobación y el respaldo antes de continuar.

Los roles/permisos se inicializan una sola vez.

### Administración de cuentas y contraseñas

Desde el menú interactivo (`sudo bash deploy/vps.sh`) o directamente desde la consola:

- **Cambiar contraseña de cualquier usuario (Opción [6]):**
  ```bash
  sudo bash deploy/vps.sh password
  # O especificando correo y contraseña directamente:
  sudo bash deploy/vps.sh password admin@gmail.com Admin12345!
  ```
  *Actualiza la contraseña, asegura que la cuenta esté activa/aprobada y desbloquea intentos fallidos acumulados.*

- **Crear / Actualizar Superusuario (Admin) (Opción [4]):**
  ```bash
  sudo bash deploy/vps.sh superuser
  ```

- **Listar cuentas de usuarios registrados (Opción [5]):**
  ```bash
  sudo bash deploy/vps.sh users
  ```

Swagger queda en `https://api.ejemplo.com/api/v1/docs/`. Comprueba el servicio:

```bash
sudo systemctl status taji nginx postgresql --no-pager
sudo journalctl -u taji -n 100 --no-pager
curl --fail https://api.ejemplo.com/api/v1/health/
```

## Actualizar después de subir cambios

```bash
sudo taji-deploy update
```

Si `main` no cambió y la API está sana, termina sin reinstalar ni reiniciar.
Si un intento previo falló, reintenta incluso cuando el commit coincide.
Si hay commits nuevos:

1. Prepara otra versión en `/opt/taji/releases/`, con su propio venv.
2. Instala dependencias, comprueba producción, modelos/migraciones y estáticos.
3. Detiene la API y respalda PostgreSQL, configuración y archivos subidos.
4. Aplica migraciones, cambia `/opt/taji/current` a la nueva versión, reinicia
   Gunicorn y recarga Nginx. No restablece los permisos personalizados.
5. Verifica la API por HTTPS y actualiza el comando `taji-deploy` desde la versión
   publicada. Conserva versiones anteriores y respaldos.

La actualización es manual; no se instala un cron que publique cambios sin
supervisión. Lo único automático es el **respaldo** diario, que no despliega
código (ver «Respaldos»). Hay un bloqueo para impedir despliegues simultáneos y
se rechaza una reescritura de `main`. Los cambios de dependencias usan un venv
nuevo; los de esquema pasan por migraciones. Para cambios en la configuración de
Nginx, systemd o paquetes del sistema, vuelve a ejecutar `install` desde el
script actualizado con el mismo dominio, correo y origen. Esto conserva la base y
los secretos existentes. No cambies de dominio mediante una reinstalación:
ajusta también `ALLOWED_HOSTS` y los orígenes en la configuración.

## Configuración que depende del servicio real

### Correo (SMTP) — obligatorio para las invitaciones

Las invitaciones de acceso de residentes y el restablecimiento de contraseña se
envían por SMTP. **Sin configurar esto nada sale**: el instalador deja
`EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend`, que acepta el
mensaje y lo escribe en el log de Gunicorn, así que Django nunca reporta un
error aunque la invitación no se haya enviado.

La API ya no esconde ese caso: el alta de un residente devuelve
`invitation.email_sent=false` con un detalle explicativo, y *Reenviar
invitación* responde `502` en lugar de un `200` falso.

Configúralo desde el menú del instalador:

```
sudo ./deploy/vps.sh
# Opción [12] Configurar Envío de Correo SMTP
```

La opción pide servidor, puerto, usuario, contraseña y remitente; escribe las
variables en `/etc/taji/backend.env` conservando el resto del archivo, reinicia
Gunicorn y envía un correo de prueba para confirmar que llegó.

Equivalente manual (equipo ya instalado):

```bash
sudo nano /etc/taji/backend.env   # o sudoedit
```

```ini
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=taji.app@gmail.com
EMAIL_HOST_PASSWORD=abcd efgh ijkl mnop
DEFAULT_FROM_EMAIL=Taji <taji.app@gmail.com>
```

```bash
sudo systemctl restart taji
sudo journalctl -u taji -n 50 --no-pager
```

En Gmail la contraseña debe ser una **contraseña de aplicación**
(https://myaccount.google.com/apppasswords), no la contraseña de la cuenta. Sin
verificación en dos pasos activada, Google no emite contraseñas de aplicación.

Las claves de aplicación de Google contienen espacios. `django-environ` conserva
el valor tal cual y `smtplib` lo acepta, pero si tu servidor da problemas de
autenticación, quita los espacios de `EMAIL_HOST_PASSWORD`.

### Otras variables

- Si frontend y API pertenecen a sitios diferentes, revisa la política de
  cookies del navegador y configura `COOKIE_SAMESITE=None` cuando corresponda.
  Los orígenes autorizados son explícitos en `FRONTEND_URLS`.
- Los archivos de `/var/lib/taji/media` son persistentes y se respaldan, pero
  no se exponen públicamente mediante Nginx. Los CU futuros deben decidir qué
  descargas son públicas y cuáles requieren autenticación.
- HTTPS, cookies seguras y HSTS están activos. Las comprobaciones W005 y W021
  se excluyen de forma deliberada: el instalador no administra los subdominios
  descendientes ni inscribe el dominio en la lista preload del navegador.
- Certbot instala la renovación programada del certificado; el hook recarga
  Nginx después de renovar. Verifica con `sudo certbot renew --dry-run`.

## Respaldos

Taji usa **una sola base de datos PostgreSQL compartida** entre todos los
condominios: el aislamiento entre tenants es a nivel de ORM
(`TenantAwareManager` filtra por `condominium_id`), no una base por condominio.
Por eso un único `pg_dump` de `taji` **incluye todos los tenants** y no hace
falta `pg_dumpall` (que solo añadiría los roles globales de PostgreSQL).

Los respaldos quedan en `/var/backups/taji/` (configurable con `BACKUP_DIR` en
`/etc/taji/backend.env`) en formato `custom`, que ya viene comprimido.

Cada respaldo se **verifica antes de darse por bueno**: el volcado se escribe en
un `.dump.partial` y solo se renombra a `.dump` tras pasar `pg_restore --list`.
Un respaldo fallido nunca se presenta como utilizable.

### Manuales

Desde el menú del instalador:

```
sudo ./deploy/vps.sh
# Opción [7]  Respaldo manual (verificado)
# Opción [13] Respaldos: listar / verificar / restaurar
```

O directamente:

```bash
sudo bash deploy/vps.sh backup
```

### Automáticos

El menú ofrece la **opción [14]**, que instala un `systemd timer`
(`taji-backup.timer`) con ejecución diaria a la hora que elijas. Se eligió un
timer y no un cron porque es el mismo mecanismo que ya usa el instalador para
`taji.service`, no depende del paquete `cron` y lleva `Persistent=true`, que
ejecuta el respaldo pendiente si el servidor estaba apagado a la hora.

```bash
systemctl list-timers taji-backup.timer
systemctl start taji-backup.service   # ejecutar uno ahora
journalctl -u taji-backup.service -n 30 --no-pager
sudo bash deploy/vps.sh backup-schedule off   # desactivar
```

La automatización cubre solo los **respaldos**, no los despliegues: publicar
cambios sigue siendo una operación manual y supervisada.

### Antes de cada migración

`taji-deploy update` genera y verifica un respaldo `premigrate-*.dump` antes de
aplicar `migrate`. Es el único paso del despliegue capaz de destruir datos de
forma irreversible. **Si el respaldo falla, el despliegue se detiene** en vez de
seguir adelante a ciegas.

### Retención

Por defecto se conservan los respaldos de los últimos **14 días** y siempre las
**10 copias más recientes** (el piso manda: si el servidor lleva mucho sin
generar copias, nunca se queda sin respaldo reciente). Los `.dump.partial` en
curso nunca se listan.

```bash
python deploy/backup_database.py create --keep-days 30 --keep-count 20
```

### Verificar y restaurar

```bash
sudo python deploy/backup_database.py list
sudo python deploy/backup_database.py verify /var/backups/taji/taji-20261008T033000123456Z.dump
sudo python deploy/backup_database.py restore /var/backups/taji/taji-....dump \
  --target-db taji_restaurado
```

La restauración **se niega a sobrescribir la base en uso**: exige un
`--target-db` distinto y crea esa base si no existe. Poner la aplicación en
servicio es un paso manual posterior:

1. Compara la base restaurada con el commit correspondiente.
2. Ajusta `DATABASE_URL` en `/etc/taji/backend.env` a la base restaurada.
3. `sudo systemctl restart taji`.

## Fallos y recuperación

El archivo `.release-sha` de cada versión identifica el commit. Los respaldos
incluyen datos y secretos: consérvalos fuera del repositorio y cópialos
periódicamente a almacenamiento privado.

Si falla la preparación, la versión activa continúa funcionando. Una vez
detenido el servicio, cualquier fallo (incluyendo la comprobación HTTPS) lo
deja detenido para evitar ejecutar código con un esquema parcialmente migrado.
Lee `journalctl -u taji` y la salida del despliegue. Una migración correctiva
puede publicarse y aplicarse con `sudo taji-deploy update`.

No basta con volver a apuntar el código antiguo si cambió el esquema: una
migración puede haber destruido datos. Restaura sobre una base nueva con
`backup_database.py restore` y comprueba esa base antes de ponerla en servicio.

## Respaldo y migración local en Windows

La conexión sale de `Backend/.env`. No publiques ese archivo ni los respaldos.

```powershell
# Sin subcomando equivale a `create`.
.venv/Scripts/python.exe deploy/backup_database.py create --pg-bin 'C:\Program Files\PostgreSQL\18\bin'
.venv/Scripts/python.exe deploy/backup_database.py list
.venv/Scripts/python.exe manage.py migrate --plan
.venv/Scripts/python.exe manage.py migrate
```

En local los respaldos van a `Backend/backups/` salvo que se indique
`--output-dir`. Fuera de PostgreSQL, el mismo comando sirve para verificar o
restaurar:

Para verificar la aplicación usa PostgreSQL: la suite heredada contiene una
prueba que exige ese motor. Django crea y elimina una base de pruebas separada.

```powershell
.venv/Scripts/python.exe manage.py test --noinput
```

## Verificación del despliegue

El workflow `Backend checks` comprueba la suite con PostgreSQL, los ajustes de
producción y ShellCheck. El job del VPS ejecuta una instalación real en Ubuntu,
Nginx, Gunicorn y PostgreSQL; sustituye únicamente la emisión pública de Let's
Encrypt por un certificado local de prueba. Comprueba instalación, actualización,
ausencia de reinicio sin cambios, recuperación de un fallo de salud del mismo
commit y parada segura ante una migración fallida.
Esa prueba no valida tu DNS, firewall, certificado público ni credenciales SMTP.

Referencias: [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)
y [Gunicorn deployment](https://gunicorn.org/deploy/).
