"""Two advisory features, neither of which changes records or authorizes work."""
import json
import re
from decimal import Decimal
from time import monotonic
from urllib.parse import urlsplit

import httpx
from django.conf import settings
from rest_framework.exceptions import ValidationError

from .serializers import CHECKS


HOST = "integrate.api.nvidia.com"
PROMPTS = {
    "quotes": "Compara solamente costo total, plazo y garantía de las opciones entregadas. "
    "Explica las compensaciones y qué confirmar antes de decidir. No declares ganador, "
    "no autorices compras y no asumas que el alcance de las cotizaciones es idéntico.",
    "inspections": "Propón a quién derivar los puntos marcados attention y cómo verificar su cierre. "
    "Separa los no revisados de los hallazgos. Indica revisión visual o personal competente; "
    "no diagnostiques causas ni enseñes reparaciones peligrosas.",
}


class AdvisorUnavailable(Exception):
    pass


def inputs(kind, records):
    if kind == "quotes":
        if len(records) < 2:
            raise ValidationError("Selecciona entre dos y cinco cotizaciones.")
        if len({(r.details["request_code"], r.details["currency"]) for r in records}) != 1:
            raise ValidationError("Compara cotizaciones de la misma solicitud y moneda.")
        facts = [
            {"option": chr(65 + i), "amount": r.details["amount"], "currency": r.details["currency"],
             "delivery_days": r.details["delivery_days"], "warranty_months": r.details["warranty_months"]}
            for i, r in enumerate(records)
        ]
        return {
            "options": facts,
            "lowest_amount": str(min(Decimal(f["amount"]) for f in facts)),
            "fastest_delivery_days": min(f["delivery_days"] for f in facts),
            "longest_warranty_months": max(f["warranty_months"] for f in facts),
        }
    if len(records) != 1:
        raise ValidationError("Selecciona una inspección.")
    checks = records[0].details["checks"]
    if not any(value != "ok" for value in checks.values()):
        raise ValidationError("Esa inspección no tiene hallazgos ni puntos pendientes.")
    return {"checks": {label: checks[key] for key, label in CHECKS.items()}}


def advise(kind, facts, *, transport=None):
    config = settings.NVIDIA
    base = config["BASE_URL"]
    url = urlsplit(base)
    if (not config["ENABLED"] or not config["API_KEY"] or url.scheme != "https"
            or url.netloc != HOST or url.path.rstrip("/") != "/v1" or url.query or url.fragment):
        raise AdvisorUnavailable
    budget = min(10, config["TIMEOUT_SECONDS"])
    payload = {
        "model": config["MODEL"], "max_tokens": 450, "temperature": 0.1,
        "stream": False, "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": PROMPTS[kind] + " Responde en español con un JSON "
             "con summary (máximo 450 caracteres) y actions (1 a 5 textos de hasta 220 caracteres)."},
            {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
        ],
    }
    started = monotonic()
    try:
        with httpx.Client(transport=transport, follow_redirects=False, trust_env=False) as client:
            with client.stream("POST", base.rstrip("/") + "/chat/completions", json=payload,
                               headers={"Authorization": "Bearer " + config["API_KEY"]},
                               timeout=httpx.Timeout(budget, connect=min(3, budget))) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=8192):
                    if len(body) + len(chunk) > 32768 or monotonic() - started > budget:
                        raise AdvisorUnavailable
                    body.extend(chunk)
        choice = json.loads(body)["choices"][0]
        if choice["finish_reason"] != "stop":
            raise AdvisorUnavailable
        data = json.loads(choice["message"]["content"])
        summary, actions = data["summary"], data["actions"]
        if not isinstance(actions, list) or not 1 <= len(actions) <= 5:
            raise AdvisorUnavailable
        return {"summary": clean(summary, 450), "actions": [clean(action, 220) for action in actions]}
    except (httpx.HTTPError, KeyError, ValueError, IndexError, TypeError, AttributeError, RecursionError):
        raise AdvisorUnavailable from None


def clean(value, limit):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
        raise AdvisorUnavailable
    return re.sub(r"\s+", " ", value).strip()
