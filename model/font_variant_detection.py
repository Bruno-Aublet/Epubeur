from pathlib import Path

from PySide6.QtGui import QFontDatabase

_FILENAME_HINTS = [
    (("thin",), 100), (("extralight", "ultralight"), 200), (("light",), 300),
    (("medium",), 500), (("semibold", "demibold"), 600),
    # extrabold/ultrabold AVANT bold : "bold" est une sous-chaîne de "extrabold"/"ultrabold", et
    # la boucle s'arrête au premier match — les tester dans le mauvais ordre classerait
    # "SuperFont-ExtraBold.ttf" en poids 700 (Bold) au lieu de 800 (ExtraBold).
    (("extrabold", "ultrabold"), 800), (("bold",), 700), (("black", "heavy"), 900),
]


def detect_font_variant(font_path: Path) -> tuple[int, bool, str]:
    """Charge font_path seul dans QFontDatabase, lit son (weight, italic, style_name) embarqué,
    puis le décharge immédiatement — ne doit jamais être appelé pendant que d'autres variantes
    de la même famille sont déjà chargées (styles() se recouperait entre fichiers). Retourne
    (weight_css, italic, style_name). Repli sur heuristique de nom de fichier uniquement si Qt
    échoue à charger le fichier (id == -1) ou ne rapporte aucun style."""
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    if font_id == -1:
        return _guess_variant_from_filename(font_path)
    try:
        families = QFontDatabase.applicationFontFamilies(font_id)
        if not families:
            return _guess_variant_from_filename(font_path)
        family = families[0]
        styles = QFontDatabase.styles(family)
        if not styles:
            return _guess_variant_from_filename(font_path)
        style_name = styles[0]
        weight = QFontDatabase.weight(family, style_name)
        italic = QFontDatabase.italic(family, style_name)
        return weight, italic, style_name
    finally:
        QFontDatabase.removeApplicationFont(font_id)


def _guess_variant_from_filename(font_path: Path) -> tuple[int, bool, str]:
    name = font_path.stem.lower()
    weight = 400
    for keywords, w in _FILENAME_HINTS:
        if any(k in name for k in keywords):
            weight = w
            break
    italic = any(k in name for k in ("italic", "oblique"))
    label = "Italic" if italic else "Regular"
    return weight, italic, label
