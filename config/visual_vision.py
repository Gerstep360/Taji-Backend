"""Configuración separada de CU22. Las claves nunca llegan al navegador."""
from pathlib import Path

import environ


class PrivateEnvironment(environ.Env):
    ENVIRON = {}


def configuration(base_dir):
    PrivateEnvironment.ENVIRON = {}
    for path in (base_dir / '.env', Path('/etc/taji/backend.env')):
        if path.is_file():
            PrivateEnvironment.read_env(path, overwrite=True)
    env = PrivateEnvironment()

    def value(name, default, cast=str):
        import os

        key = f'TAJI_VISION_{name}'
        if key in os.environ:
            return env.parse_value(os.environ[key], cast)
        return env(key, default=default, cast=cast)

    def bounded(name, default, low, high):
        return min(high, max(low, value(name, default, int)))

    hosted = 'https://integrate.api.nvidia.com/v1'
    return {
        'ENABLED': value('ENABLED', False, bool),
        'DEV_WORKER': value('DEV_WORKER', True, bool),
        'DEV_WORKER': value('DEV_WORKER', True, bool),
        'COSMOS_URL': value('COSMOS_URL', hosted).rstrip('/'),
        'COSMOS_KEY': value('COSMOS_KEY', ''),
        'COSMOS_MODE': value('COSMOS_MODE', 'off'),  # off, image, video (después de verificar)
        'FALLBACK_KEY': value('FALLBACK_KEY', ''),
        'FALLBACK_VERIFIED': value('FALLBACK_VERIFIED', False, bool),
        'FALLBACK_VIDEO_VERIFIED': value('FALLBACK_VIDEO_VERIFIED', False, bool),
        'FALLBACK_VIDEO_VERIFIED': value('FALLBACK_VIDEO_VERIFIED', False, bool),
        'TIMEOUT': bounded('TIMEOUT', 25, 5, 45),
        'INTERVAL': bounded('INTERVAL', 40, 30, 120),
        'PERIODIC': bounded('PERIODIC', 150, 120, 240),
        'IDLE': bounded('IDLE', 240, 180, 360),
        'SESSION_PER_HOUR': bounded('SESSION_PER_HOUR', 20, 1, 30),
        'SESSION_BURST': bounded('SESSION_BURST', 3, 1, 5),
        'GLOBAL_PER_MIN': bounded('GLOBAL_PER_MIN', 8, 1, 30),
        'TENANT_PER_MIN': bounded('TENANT_PER_MIN', 4, 1, 15),
        'USER_PER_MIN': bounded('USER_PER_MIN', 3, 1, 8),
        'RETENTION_DAYS': bounded('RETENTION_DAYS', 30, 1, 90),
        'FFPROBE': value('FFPROBE', 'ffprobe'),
        'FFMPEG': value('FFMPEG', 'ffmpeg'),
        'FFMPEG': value('FFMPEG', 'ffmpeg'),
    }
