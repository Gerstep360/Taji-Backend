"""Cliente visual aislado. Nunca registra el cuerpo de NVIDIA ni credenciales."""
import base64
import json
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

COSMOS = 'nvidia/cosmos3-nano-reasoner'
OMNI = 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning'
HOSTED = 'https://integrate.api.nvidia.com/v1'


class ProviderError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request_visual(endpoint, key, model, media, mode, prompt, timeout, *, tokens=900, structured=False):
    url = urlsplit(endpoint)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ProviderError('endpoint_invalid')
    if not key:
        raise ProviderError('key_missing')
    part = 'video_url' if mode == 'video' else 'image_url'
    mime = 'video/mp4' if mode == 'video' else 'image/jpeg'
    content = [{'type': 'text', 'text': prompt}, {
        'type': part, part: {'url': f'data:{mime};base64,' + base64.b64encode(media).decode('ascii')},
    }]
    payload = {'model': model, 'messages': [{'role': 'user', 'content': content}],
               'max_tokens': tokens, 'temperature': 0.1, 'stream': False}
    if model == OMNI:
        payload['chat_template_kwargs'] = {'enable_thinking': False}
        if structured:
            payload['response_format'] = {'type': 'json_object'}
        if mode == 'video':
            payload['mm_processor_kwargs'] = {'use_audio_in_video': False}
    req = Request(endpoint + '/chat/completions', json.dumps(payload).encode(), {
        'Authorization': f'Bearer {key}', 'Content-Type': 'application/json', 'Accept': 'application/json',
    })
    start = monotonic()
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=timeout) as resp:
            raw = resp.read(131_073)
            if len(raw) > 131_072:
                raise ProviderError('response_too_large')
            data = json.loads(raw)
        answer = data['choices'][0]['message']['content']
        if not isinstance(answer, str) or not answer.strip():
            raise ProviderError('empty_response')
        return answer, str(data.get('model') or model)[:120], round((monotonic() - start) * 1000)
    except HTTPError as exc:
        exc.close()
        raise ProviderError(f'http_{exc.code}') from None
    except (TimeoutError, URLError, OSError) as exc:
        reason = getattr(exc, 'reason', exc)
        raise ProviderError('timeout' if isinstance(reason, TimeoutError) else 'connection_error') from None
    except (KeyError, IndexError, TypeError, ValueError):
        raise ProviderError('invalid_response') from None
