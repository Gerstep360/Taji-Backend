"""Prueba opt-in; genera solo imágenes y un MP4 sintéticos, sin datos de TAJI."""
from io import BytesIO
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from time import monotonic

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from PIL import Image, ImageDraw

from paquetes.paquete3_incidencias_ia.cu32_webcam.visual_provider import (
    COSMOS, HOSTED, OMNI, ProviderError, request_visual,
)
from paquetes.paquete3_incidencias_ia.cu32_webcam.visual_reasoning import PROMPT, normalize


class Command(BaseCommand):
    help = 'Verifica NVIDIA con medios sintéticos; --live consume hasta cinco llamadas.'

    def add_arguments(self, parser):
        parser.add_argument('--live', action='store_true')

    def handle(self, *args, **options):
        if not options['live']:
            raise CommandError('Usa --live para autorizar el envío de medios sintéticos a NVIDIA.')
        config = settings.TAJI_VISION
        image = Image.new('RGB', (320, 180), 'white')
        ImageDraw.Draw(image).rectangle((70, 35, 250, 145), fill='red')
        buffer = BytesIO()
        image.save(buffer, format='JPEG', quality=82)
        prompt = 'Respond with only the color of the large rectangle, in English.'

        def probe(endpoint, key, model, media, mode, question, marker):
            start = monotonic()
            try:
                answer, actual, ms = request_visual(endpoint, key, model, media, mode, question, config['TIMEOUT'])
                verified = marker(answer.casefold()) if callable(marker) else marker in answer.casefold()
                self.stdout.write(f'{actual} {mode}: HTTP 200; {ms} ms; {len(media)} bytes; contenido verificado={verified}')
            except ProviderError as exc:
                self.stdout.write(f'{model} {mode}: {exc.code}; {round((monotonic() - start) * 1000)} ms; {len(media)} bytes')

        probe(config['COSMOS_URL'], config['COSMOS_KEY'], COSMOS, buffer.getvalue(), 'image', prompt, 'red')
        try:
            with TemporaryDirectory() as directory:
                clip = Path(directory) / 'probe.mp4'
                subprocess.run(['ffmpeg', '-loglevel', 'error', '-f', 'lavfi', '-i',
                                'color=c=red:s=320x180:r=4:d=3', '-f', 'lavfi', '-i',
                                'color=c=blue:s=320x180:r=4:d=3', '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0',
                                '-an', '-c:v', 'libx264',
                                '-pix_fmt', 'yuv420p', str(clip)], check=True, timeout=10, capture_output=True)
                data = clip.read_bytes()
                question = 'Name the first color and then the final color. Reply only with the two English colors in order.'
                ordered = lambda answer: 'red' in answer and 'blue' in answer and answer.index('red') < answer.index('blue')
                probe(config['COSMOS_URL'], config['COSMOS_KEY'], COSMOS, data, 'video', question, ordered)
                probe(HOSTED, config['FALLBACK_KEY'], OMNI, data, 'video', question, ordered)
                try:
                    answer, actual, ms = request_visual(HOSTED, config['FALLBACK_KEY'], OMNI, data, 'video', PROMPT, config['TIMEOUT'], structured=True)
                    normalize(answer, 'video')
                    self.stdout.write(f'{actual} video estructurado: HTTP 200; {ms} ms; JSON válido.')
                except (ProviderError, ValueError) as exc:
                    self.stdout.write(f'{OMNI} video estructurado: {getattr(exc, "code", "invalid_response")}')
        except (OSError, subprocess.SubprocessError):
            self.stdout.write('MP4: no se pudo generar el medio sintético con ffmpeg.')
        probe(HOSTED, config['FALLBACK_KEY'], OMNI, buffer.getvalue(), 'image', prompt, 'red')
