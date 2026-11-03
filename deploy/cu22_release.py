"""Publica el árbol probado en una release nueva; recibe una conexión SSH autenticada.

No contiene credenciales. La clave NVIDIA se transmite por SFTP a backend.env,
nunca por argumentos de shell. El llamador suministra el cliente SSH existente.
"""
import hashlib
import io
import json
import shlex
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from config.nvidia import configuration


def deploy(client, backend_root, frontend_dist, report_path):
    backend_root = Path(backend_root).resolve()
    frontend_dist = Path(frontend_dist).resolve()
    config = configuration(backend_root)
    if not config['API_KEY']:
        raise RuntimeError('Falta configurar NVIDIA_API_KEY.')
    release_id = 'cu22-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    release = '/opt/taji/releases/' + release_id
    web_release = '/opt/taji-web/releases/' + release_id

    def run(command):
        _, stdout, stderr = client.exec_command(command, timeout=300)
        output = stdout.read().decode('utf-8', errors='replace')
        error = stderr.read().decode('utf-8', errors='replace')
        code = stdout.channel.recv_exit_status()
        # La salida operacional no debe incluir la clave ni siquiera si un comando falla.
        output = output.replace(config['API_KEY'], '[redacted]')
        error = error.replace(config['API_KEY'], '[redacted]')
        if code:
            raise RuntimeError(f'Falló un paso del despliegue ({code}): {error[-1800:]} {output[-800:]}')
        return output

    old = run('readlink -f /opt/taji/current').strip()
    old_web = run('readlink -f /opt/taji-web/current').strip()
    if not old.startswith('/opt/taji/releases/') or not old_web.startswith('/opt/taji-web/releases/'):
        raise RuntimeError('Las releases actuales no están en las rutas esperadas.')
    q = shlex.quote
    sftp = client.open_sftp()
    env_path = '/etc/taji/backend.env'
    old_env = sftp.open(env_path, 'rb').read()
    metadata = sftp.stat(env_path)
    backed_up = env_path + '.' + release_id + '.bak'
    with sftp.open(backed_up, 'wb') as file:
        file.write(old_env)
    sftp.chmod(backed_up, 0o640)
    sftp.chown(backed_up, metadata.st_uid, metadata.st_gid)
    overrides = {
        'NVIDIA_API_KEY': config['API_KEY'], 'NVIDIA_MODEL': config['MODEL'],
        'NVIDIA_BASE_URL': config['BASE_URL'], 'NVIDIA_ENABLED': 'True',
        'NVIDIA_AUTO_ANALYZE': 'True', 'NVIDIA_TIMEOUT_SECONDS': str(config['TIMEOUT_SECONDS']),
        'NVIDIA_MAX_TOKENS': str(config['MAX_TOKENS']),
    }
    env_lines = [line for line in old_env.decode().splitlines() if line.partition('=')[0].strip() not in overrides]
    for key, value in overrides.items():
        if '\n' in value or '\r' in value:
            raise RuntimeError('La configuración NVIDIA no puede contener saltos de línea.')
        env_lines.append(key + '=' + value)
    next_env = env_path + '.' + release_id + '.next'
    with sftp.open(next_env, 'wb') as file:
        file.write(('\n'.join(env_lines) + '\n').encode())
    sftp.chmod(next_env, 0o640)
    sftp.chown(next_env, metadata.st_uid, metadata.st_gid)
    published = False
    try:
        # Copia verificada de la BD ANTES de cualquier migración.
        backup = run(f'cd {q(old)} && runuser -u taji -- .venv/bin/python deploy/backup_database.py --settings config.settings_production create --prefix cu22')
        print('Respaldo de PostgreSQL completado.')
        with tempfile.TemporaryDirectory(prefix='taji-cu22-') as temp:
            archive = Path(temp) / 'backend.tar.gz'
            files = subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=backend_root).decode().split('\0')
            manifest = {}
            with tarfile.open(archive, 'w:gz') as tar:
                for name in sorted(set(files)):
                    if not name:
                        continue
                    path = backend_root / name
                    if not path.is_file() or path.is_symlink() or path.name.startswith('.env') and path.name != '.env.example':
                        continue
                    content = path.read_bytes()
                    if config['API_KEY'].encode() in content:
                        raise RuntimeError(f'Credencial detectada en el archivo {name}; no se publicó.')
                    if path.suffix == '.py' and not name.startswith('docs/'):
                        manifest[name] = hashlib.sha256(content).hexdigest()
                    tar.add(path, arcname=name, recursive=False)
            remote_archive = '/tmp/' + release_id + '-backend.tar.gz'
            sftp.put(str(archive), remote_archive)
            run(f'mkdir {q(release)} && tar -xzf {q(remote_archive)} -C {q(release)} && rm -f {q(remote_archive)}')
            # Usa las dependencias verificadas del servidor, con venv independiente.
            run(f'cp -a {q(old + "/.venv")} {q(release + "/.venv")}')
            relocate = (
                "from pathlib import Path; root=Path(" + repr(release + '/.venv/bin') + "); "
                "old=" + repr((old + '/.venv').encode()) + "; new=" + repr((release + '/.venv').encode()) + "; "
                "[(p.write_bytes(p.read_bytes().replace(old,new))) for p in root.iterdir() if p.is_file() and not p.is_symlink() and p.read_bytes().startswith(b'#!')]"
            )
            run('python3 -c ' + q(relocate))
            run(f'ln -s /etc/taji/backend.env {q(release + "/.env")} && ln -s /opt/taji/shared/ai_models {q(release + "/ai_models")}')
            try:
                sftp.stat(old + '/downloads')
            except FileNotFoundError:
                pass
            else:
                run(f'ln -s {q(old + "/downloads")} {q(release + "/downloads")}')
            run(f'chown -Rh taji:taji {q(release)}')
            sftp.posix_rename(next_env, env_path)
            manage = f'cd {q(release)} && runuser -u taji -- .venv/bin/python manage.py '
            run(manage + 'check --settings config.settings_production')
            run(manage + 'migrate --noinput --settings config.settings_production')
            run(manage + 'collectstatic --noinput --settings config.settings_production')
            print('Release backend y migraciones verificadas.')
            archive_web = Path(temp) / 'web.tar.gz'
            with tarfile.open(archive_web, 'w:gz') as tar:
                for path in frontend_dist.rglob('*'):
                    if path.is_file() and path.suffix not in ('.apk','.map'):
                        tar.add(path, arcname=path.relative_to(frontend_dist).as_posix())
            remote_web = '/tmp/' + release_id + '-web.tar.gz'
            sftp.put(str(archive_web), remote_web)
            run(f'mkdir -p {q(web_release + "/dist/taji-web/browser")} && tar -xzf {q(remote_web)} -C {q(web_release + "/dist/taji-web/browser")} && rm -f {q(remote_web)}')
            with sftp.open(release + '/.cu22-manifest.json', 'w') as file:
                file.write(json.dumps(manifest, sort_keys=True))
            run(f'cp {q(release + "/deploy/taji-incident-ai.service")} /etc/systemd/system/taji-incident-ai.service')
            run(f'ln -s {q(release)} /opt/taji/.current-cu22-next && mv -Tf /opt/taji/.current-cu22-next /opt/taji/current')
            run(f'ln -s {q(web_release)} /opt/taji-web/.current-cu22-next && mv -Tf /opt/taji-web/.current-cu22-next /opt/taji-web/current')
            published = True
            run('systemctl daemon-reload && systemctl restart taji && systemctl enable --now taji-incident-ai && systemctl reload nginx')
            run('curl --retry 10 --retry-delay 1 --retry-connrefused -fsS http://127.0.0.1:8000/api/v1/health/')
            probe = run(manage + 'probe_incident_ai --samples 3 --settings config.settings_production')
            if json.loads(probe)['successful'] != 3:
                raise RuntimeError('La verificación real de NVIDIA no completó las tres muestras.')
            report = {'release':release,'web_release':web_release,'previous_release':old,
                      'nvidia':json.loads(probe), 'worker':run('systemctl is-active taji-incident-ai').strip(),
                      'worker_memory':run('systemctl show taji-incident-ai -p MemoryCurrent -p MemoryPeak --no-pager').strip()}
            Path(report_path).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False,indent=2))
            return report
    except Exception:
        # Migraciones aditivas: la release anterior puede funcionar con las columnas nuevas.
        with sftp.open(next_env, 'wb') as file:
            file.write(old_env)
        sftp.chmod(next_env,0o640)
        sftp.chown(next_env,metadata.st_uid,metadata.st_gid)
        sftp.posix_rename(next_env,env_path)
        if published:
            run('systemctl disable --now taji-incident-ai || true')
            run(f'ln -s {q(old)} /opt/taji/.rollback-cu22 && mv -Tf /opt/taji/.rollback-cu22 /opt/taji/current')
            run(f'ln -s {q(old_web)} /opt/taji-web/.rollback-cu22 && mv -Tf /opt/taji-web/.rollback-cu22 /opt/taji-web/current')
            run('systemctl restart taji && systemctl reload nginx')
        raise
    finally:
        sftp.close()
