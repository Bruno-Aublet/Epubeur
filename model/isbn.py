import re

# Tiret ASCII (U+002D) + variantes typographiques qu'un copier-coller depuis une fiche éditeur/
# librairie en ligne peut introduire (le CSS de nombreux sites rend les ISBN avec un en-dash) :
# U+2010 hyphen, U+2011 non-breaking hyphen, U+2012 figure dash, U+2013 en dash, U+2014 em dash,
# U+2212 minus sign. Sans ça, un ISBN par ailleurs valide était rejeté avec un message trompeur
# ("clé de contrôle incorrecte") qui bloquait la génération de l'EPUB.
_DASH_CHARS = "‐‑‒–—−-"  # tiret ASCII en dernier : évite une plage de caractères accidentelle
_STRIP_RE = re.compile(rf"[\s{_DASH_CHARS}]")


def normalize_isbn(raw: str) -> str:
    """Retire tirets/espaces, conserve les chiffres et le 'X' terminal (clé de contrôle ISBN-10)."""
    return _STRIP_RE.sub("", raw.strip().upper())


def _isbn10_check_digit_valid(digits: str) -> bool:
    total = sum((10 - i) * (10 if ch == "X" else int(ch)) for i, ch in enumerate(digits))
    return total % 11 == 0


def _isbn13_check_digit_valid(digits: str) -> bool:
    total = sum(int(ch) * (1 if i % 2 == 0 else 3) for i, ch in enumerate(digits))
    return total % 10 == 0


def is_valid_isbn(raw: str) -> bool:
    """Valide un ISBN-10 ou ISBN-13 (tirets/espaces ignorés), clé de contrôle comprise."""
    digits = normalize_isbn(raw)
    if len(digits) == 10:
        if not re.fullmatch(r"\d{9}[\dX]", digits):
            return False
        return _isbn10_check_digit_valid(digits)
    if len(digits) == 13:
        if not re.fullmatch(r"\d{13}", digits):
            return False
        return _isbn13_check_digit_valid(digits)
    return False
