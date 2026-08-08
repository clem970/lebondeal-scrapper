import re

UNIT_MAP = {
    "s": 1, "sec": 1, "secs": 1, "seconde": 1, "secondes": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "heure": 3600, "heures": 3600,
}

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def parse_interval(text: str) -> int | None:
    """Parse '60 secondes' / '5 minutes' / '1 heures' -> nombre de secondes. None si invalide."""
    if not text:
        return None
    text = text.strip().lower()
    m = re.match(r"^(\d+)\s*([a-zéû]+)$", text)
    if not m:
        return None
    value, unit = m.groups()
    mult = UNIT_MAP.get(unit)
    if mult is None:
        return None
    return max(5, int(value) * mult)


def format_interval(seconds: int) -> str:
    """Formate un nombre de secondes vers un texte ré-injectable dans parse_interval (arrondi à l'unité la plus lisible)."""
    if seconds and seconds % 3600 == 0:
        return f"{seconds // 3600} heures"
    if seconds and seconds % 60 == 0:
        return f"{seconds // 60} minutes"
    return f"{seconds} secondes"


def to_float(text: str) -> float | None:
    text = (text or "").strip().replace(",", ".")
    return float(text) if text else None


def to_int(text: str) -> int | None:
    text = (text or "").strip()
    return int(text) if text else None
