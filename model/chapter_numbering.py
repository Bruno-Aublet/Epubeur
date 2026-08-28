import re

_NUMBER_RE = re.compile(r"\d+")


def extract_chapter_number(title: str) -> int | None:
    """Extrait le premier nombre trouvé dans un titre de chapitre (ex: 'Chapitre 7' -> 7,
    'CHAPITRE 12 : Le message' -> 12). Retourne None si aucun nombre n'est présent
    (ex: 'Premier Prologue', 'Épilogue')."""
    match = _NUMBER_RE.search(title)
    if match is None:
        return None
    return int(match.group())
