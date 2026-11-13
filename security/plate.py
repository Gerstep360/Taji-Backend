import re


def normalize_plate(value):
    """Solo retira separadores; no sustituye letras por números."""
    if not isinstance(value, str):
        return ""
    value = re.sub(r"[\s-]+", "", value).upper()
    return value if re.fullmatch(r"[A-Z0-9]{2,20}", value, re.ASCII) else ""
