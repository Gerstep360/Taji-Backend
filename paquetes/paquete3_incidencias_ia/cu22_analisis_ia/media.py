"""Prepara fotos privadas sin URLs públicas, EXIF ni pesos de modelos locales."""
import base64
from io import BytesIO
import warnings
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.exceptions import SuspiciousFileOperation
from PIL import Image, ImageOps


def prepare_images(descriptors, *, storage_prefix):
    config = settings.NVIDIA
    images, manifest = [], []
    for item in descriptors[:20]:
        entry = {'attachment_id': item['id'], 'status': 'skipped', 'reason': ''}
        manifest.append(entry)
        path = item.get('file_path', '')
        if not path.startswith(storage_prefix) or '\\' in path or '..' in path.split('/'):
            entry['reason'] = 'outside_incident_storage'
            continue
        if not config.get('VISION_ENABLED', False):
            entry['reason'] = 'vision_disabled'
            continue
        if len(images) >= config.get('MAX_IMAGES', 2):
            entry['reason'] = 'image_limit'
            continue
        try:
            # Nunca se abre una URL del reporte; únicamente el storage del backend.
            with default_storage.open(item['file_path'], 'rb') as source:
                data = source.read(10 * 1024 * 1024 + 1)
            if len(data) > 10 * 1024 * 1024:
                entry['reason'] = 'file_too_large'
                continue
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(BytesIO(data)) as image:
                    if image.format not in ('JPEG', 'PNG', 'WEBP') or image.width * image.height > 20000000:
                        entry['reason'] = 'unsupported_image'
                        continue
                    edge = config.get('IMAGE_MAX_EDGE', 1280)
                    image.draft('RGB', (edge, edge))
                    image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
                    ImageOps.exif_transpose(image, in_place=True)
                    output = BytesIO()
                    with image.convert('RGB') as rgb:
                        rgb.save(output, format='JPEG', quality=75, optimize=True)
                    if output.tell() > 768000:
                        entry['reason'] = 'image_too_complex'
                        continue
                    images.append({'id': item['id'], 'data_url': 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode('ascii')})
            entry.update(status='sent', reason='')
        except (OSError, ValueError, SuspiciousFileOperation, Image.DecompressionBombWarning, Image.DecompressionBombError):
            entry['reason'] = 'unreadable_image'
    return images, manifest
