"""Reglas pequeñas en PostgreSQL, independientes de categorías y del proveedor."""
import re
import unicodedata


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.lower()) if unicodedata.category(c) != 'Mn')


def context_of(text, start, end, *, allow_distant=False):
    before = text[max(0, start - 65):start]
    before = re.split(r'[.;!?\n]|\bpero\b|\bsin embargo\b', before)[-1]
    after = text[end:end + 45]
    if re.search(r'\b(simulacro|simulacion|ejercicio)\b.{0,25}$', before):
        return 'drill'
    if re.search(r'\b(no hay|no existe|sin|no se observa|no se detecta|no veo)\b[^,]{0,35}$', before):
        return 'negated'
    if re.search(r'\b(ayer|antes|la semana pasada)\b.{0,35}$', before) or re.match(r'\s*(ya (fue|esta) (apagado|controlado|resuelto))', after):
        return 'past'
    if allow_distant and re.search(r'\b(lejos|a salvo|fuera de peligro)\b', after):
        return 'distant'
    return 'present'


def evaluate(text, rules):
    text = normalized(text)
    findings = []
    floor = 0
    score = 0
    for rule in rules:
        for pattern in rule.conditions.get('patterns', [])[:15]:
            try:
                matches = list(re.finditer(pattern, text))[:10]
            except re.error:
                continue
            for match in matches:
                context = context_of(text, match.start(), match.end(), allow_distant=rule.entity_type == 'PERSON')
                active = context == 'present'
                findings.append({'rule': rule.code, 'name': rule.name, 'evidence': match.group()[:240],
                                 'context': context, 'active': active,
                                 'min_rank': int(rule.conditions.get('min_rank', 0)) if active else 0})
                if active:
                    floor = max(floor, int(rule.conditions.get('min_rank', 0)))
                    score = max(score, float(rule.weight))
                    break
            if matches and active:
                break
    return findings, floor, min(100, score)
