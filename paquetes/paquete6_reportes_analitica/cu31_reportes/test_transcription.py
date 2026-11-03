import io
import wave
from unittest.mock import Mock, patch

import httpx
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from rest_framework.exceptions import ValidationError

from .transcription import TranscriptionUnavailable, transcribe


def audio(seconds=1):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b'\0\0' * int(seconds * 16000))
    return SimpleUploadedFile('consulta.wav', stream.getvalue(), content_type='audio/wav')


@override_settings(NVIDIA={'ENABLED': True, 'API_KEY': 'test-key-not-real', 'BASE_URL': 'https://integrate.api.nvidia.com/v1'})
class TranscriptionTests(SimpleTestCase):
    def test_transcribes_audio_not_filename_without_storing_it(self):
        response = Mock()
        response.json.return_value = {'choices': [{'message': {'content': '{"text":"Incidencias pendientes"}'}}]}
        with patch('httpx.Client') as client:
            client.return_value.__enter__.return_value.post.return_value = response
            self.assertEqual(transcribe(audio()), 'Incidencias pendientes')
            payload = client.return_value.__enter__.return_value.post.call_args.kwargs['json']
            self.assertTrue(payload['messages'][0]['content'][1]['audio_url']['url'].startswith('data:audio/wav;base64,'))
            self.assertFalse(payload['chat_template_kwargs']['enable_thinking'])

    def test_rejects_invalid_and_long_audio_before_network(self):
        with patch('httpx.Client') as client:
            for upload in (SimpleUploadedFile('fake.wav', b'not-a-wave'), audio(31)):
                with self.assertRaises(ValidationError):
                    transcribe(upload)
            client.assert_not_called()

    def test_timeout_does_not_leak_provider_or_key(self):
        with patch('httpx.Client') as client:
            client.return_value.__enter__.return_value.post.side_effect = httpx.ReadTimeout('secret upstream detail')
            with self.assertRaises(TranscriptionUnavailable) as error:
                transcribe(audio())
            self.assertNotIn('secret', str(error.exception))

    def test_no_speech_and_invalid_provider_response(self):
        with patch('httpx.Client') as client:
            response = client.return_value.__enter__.return_value.post.return_value
            response.json.return_value = {'choices': [{'message': {'content': '{"text":""}'}}]}
            with self.assertRaises(ValidationError):
                transcribe(audio())
            response.json.return_value = {'choices': []}
            with self.assertRaises(TranscriptionUnavailable):
                transcribe(audio())
