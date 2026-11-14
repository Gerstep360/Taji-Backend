"""Lee exclusivamente la configuración NVIDIA; nunca sustituye DATABASE_URL."""
import os
from pathlib import Path
import environ


class NvidiaEnvironment(environ.Env):
    ENVIRON = {}


def configuration(base_dir: Path):
    NvidiaEnvironment.ENVIRON = {}
    for path in (base_dir.parent / '.env', base_dir / '.env', Path('/etc/taji/backend.env')):
        if path.is_file():
            NvidiaEnvironment.read_env(path, overwrite=True)
    values = NvidiaEnvironment.ENVIRON
    allowed = ('NVIDIA_API_KEY', 'NVIDIA_MODEL', 'NVIDIA_BASE_URL', 'NVIDIA_ENABLED',
               'NVIDIA_TIMEOUT_SECONDS', 'NVIDIA_MAX_TOKENS', 'NVIDIA_AUTO_ANALYZE',
               'NVIDIA_VISION_ENABLED', 'NVIDIA_MAX_IMAGES', 'NVIDIA_IMAGE_MAX_EDGE',
               'NVIDIA_DEV_WORKER')
    values.update({key: os.environ[key] for key in allowed if key in os.environ})
    config = NvidiaEnvironment()
    return {
        'API_KEY': config('NVIDIA_API_KEY', default=config('nvidia_api', default='')),
        'MODEL': config('NVIDIA_MODEL', default='nvidia/nemotron-3-nano-omni-30b-a3b-reasoning'),
        'BASE_URL': config('NVIDIA_BASE_URL', default='https://integrate.api.nvidia.com/v1').rstrip('/'),
        'ENABLED': config.bool('NVIDIA_ENABLED', default=True),
        'AUTO_ANALYZE': config.bool('NVIDIA_AUTO_ANALYZE', default=True),
        'TIMEOUT_SECONDS': min(45, max(5, config.int('NVIDIA_TIMEOUT_SECONDS', default=30))),
        'MAX_TOKENS': min(3000, max(500, config.int('NVIDIA_MAX_TOKENS', default=1600))),
        'VISION_ENABLED': config.bool('NVIDIA_VISION_ENABLED', default='omni' in config('NVIDIA_MODEL', default='omni')),
        'MAX_IMAGES': min(3, max(1, config.int('NVIDIA_MAX_IMAGES', default=2))),
        'IMAGE_MAX_EDGE': min(1600, max(640, config.int('NVIDIA_IMAGE_MAX_EDGE', default=1280))),
        'DEV_WORKER': config.bool('NVIDIA_DEV_WORKER', default=True),
    }
