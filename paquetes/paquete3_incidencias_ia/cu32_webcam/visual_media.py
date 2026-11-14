import json
import subprocess
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from PIL import Image, UnidentifiedImageError
from rest_framework.exceptions import ValidationError

IMAGE_MAX = 200_000
VIDEO_MAX = 900_000


def clean_media(upload, mode):
    size = VIDEO_MAX if mode == 'video' else IMAGE_MAX
    if not upload or not 0 < upload.size <= size:
        raise ValidationError('El archivo supera el límite de la captura o está vacío.')
    data = upload.read(size + 1)
    if len(data) > size:
        raise ValidationError('El archivo supera el límite de la captura.')
    if mode == 'video':
        return validate_video(data)
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != 'JPEG' or not (16 <= image.width <= 960 and 16 <= image.height <= 720):
                raise ValueError
            image.load()
            output = BytesIO()
            image.convert('RGB').save(output, format='JPEG', quality=78)
            result = output.getvalue()
            if len(result) > IMAGE_MAX:
                raise ValueError
            return result, 0
    except (OSError, ValueError, Image.DecompressionBombError, UnidentifiedImageError):
        raise ValidationError('Se necesita una imagen JPEG válida y de tamaño acotado.') from None


def validate_video(data):
    if len(data) < 12 or data[4:8] != b'ftyp':
        raise ValidationError('Se necesita un MP4 válido y sin audio.')
    try:
        with TemporaryDirectory() as directory:
            file = Path(directory) / 'capture.mp4'
            file.write_bytes(data)
            raw = subprocess.run([settings.TAJI_VISION['FFPROBE'], '-v', 'error',
                                  '-protocol_whitelist', 'file', '-f', 'mov', '-show_entries',
                                  'format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate',
                                  '-of', 'json', str(file)], capture_output=True, timeout=3, check=True)
            probe = json.loads(raw.stdout)
            stream, = probe['streams']
            duration = float(probe['format']['duration'])
            numerator, denominator = map(int, stream['avg_frame_rate'].split('/'))
            if not (stream['codec_type'] == 'video' and stream['codec_name'] == 'h264'
                    and 16 <= stream['width'] <= 960 and 16 <= stream['height'] <= 720
                    and 4.5 <= duration <= 8.5 and 1 <= numerator / denominator <= 8):
                raise ValueError
            # MediaRecorder produces fragmented MP4. Remux to a conventional, seekable MP4
            # without transcoding or preserving arbitrary browser metadata.
            normalized = Path(directory) / 'normalized.mp4'
            subprocess.run([settings.TAJI_VISION['FFMPEG'], '-nostdin', '-v', 'error',
                            '-protocol_whitelist', 'file', '-f', 'mov', '-i', str(file),
                            '-map', '0:v:0', '-c:v', 'copy', '-an', '-map_metadata', '-1',
                            '-movflags', '+faststart', '-f', 'mp4', str(normalized)],
                           check=True, timeout=4, capture_output=True)
            if not 0 < normalized.stat().st_size <= VIDEO_MAX:
                raise ValueError
            return normalized.read_bytes(), duration
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError, subprocess.SubprocessError):
        raise ValidationError('El clip debe ser MP4/H.264, sin audio, de 5–8 segundos y alrededor de 4 FPS.') from None
