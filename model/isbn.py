import re


def normalize_isbn(raw: str) -> str:
    """Retire tirets/espaces, conserve les chiffres et le 'X' terminal (clé de contrôle ISBN-10)."""
    return re.sub(r"[\s-]", "", raw.strip().upper())


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
