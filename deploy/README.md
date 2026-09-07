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
supervisión. Hay un bloqueo para impedir despliegues simultáneos y se rechaza
una reescritura de `main`. Los cambios de dependencias usan un venv nuevo; los
de esquema pasan por migraciones. Para cambios en la configuración de Nginx,
systemd o paquetes del sistema, vuelve a ejecutar `install` desde el script
actualizado con el mismo dominio, correo y origen. Esto conserva la base y
los secretos existentes. No cambies de dominio mediante una reinstalación:
ajusta también `ALLOWED_HOSTS` y los orígenes en la configuración.

## Configuración que depende del servicio real

- Para enviar recuperación de contraseñas, configura SMTP en
  `/etc/taji/backend.env`: `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`,
  `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`,
  `EMAIL_HOST_PASSWORD` y `DEFAULT_FROM_EMAIL`. Sin SMTP los correos usan el
  backend de consola existente. Después ejecuta `sudo systemctl restart taji`.
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

## Fallos y recuperación

Los respaldos quedan en `/var/backups/taji/`: `.dump`, `.env` y `.media.tar.gz`.
El archivo `.release-sha` de cada versión identifica el commit. Los respaldos
incluyen datos y secretos: consérvalos fuera del repositorio, copia periódicamente
a almacenamiento privado y define tu retención; el script no los elimina.

Si falla la preparación, la versión activa continúa funcionando. Una vez
detenido el servicio, cualquier fallo (incluyendo la comprobación HTTPS) lo
deja detenido para evitar ejecutar código con un esquema parcialmente migrado.
Lee `journalctl -u taji` y la salida del despliegue. Una migración correctiva
puede publicarse y aplicarse con `sudo taji-deploy update`.

No basta con volver a apuntar el código antiguo si cambió el esquema. Para
restaurar un respaldo, detén la aplicación, conserva la base fallida para
diagnóstico y restaura el `.dump` en otra base vacía con `pg_restore`. Comprueba
esa base con el commit correspondiente, configura su conexión y restaura los
archivos subidos del mismo respaldo. Esto requiere adaptar la conexión del
script, que por defecto solo actualiza la base local `taji`.

## Respaldo y migración local en Windows

La conexión sale de `Backend/.env`. No publiques ese archivo ni los respaldos.

```powershell
.venv/Scripts/python.exe deploy/backup_database.py --pg-bin 'C:\Program Files\PostgreSQL\18\bin'
.venv/Scripts/python.exe manage.py migrate --plan
.venv/Scripts/python.exe manage.py migrate
```

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
