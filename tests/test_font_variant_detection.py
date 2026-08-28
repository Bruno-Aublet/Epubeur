from pathlib import Path

import pytest

from controller import ProjectController
from model.font_variant_detection import _guess_variant_from_filename, detect_font_variant

ARIAL = Path("C:/Windows/Fonts/arial.ttf")
ARIAL_BOLD = Path("C:/Windows/Fonts/arialbd.ttf")
ARIAL_ITALIC = Path("C:/Windows/Fonts/ariali.ttf")
ARIAL_BOLD_ITALIC = Path("C:/Windows/Fonts/arialbi.ttf")

_ALL_VARIANTS_EXIST = all(p.exists() for p in (ARIAL, ARIAL_BOLD, ARIAL_ITALIC, ARIAL_BOLD_ITALIC))


@pytest.mark.skipif(not ARIAL.exists(), reason="Police système de test introuvable")
def test_detect_font_variant_reads_regular(qapp):
    weight, italic, _ = detect_font_variant(ARIAL)
    assert weight == 400
    assert italic is False


@pytest.mark.skipif(not ARIAL_BOLD.exists(), reason="Police système de test introuvable")
def test_detect_font_variant_reads_bold(qapp):
    weight, italic, _ = detect_font_variant(ARIAL_BOLD)
    assert weight == 700
    assert italic is False


@pytest.mark.skipif(not ARIAL_ITALIC.exists(), reason="Police système de test introuvable")
def test_detect_font_variant_reads_italic(qapp):
    weight, italic, _ = detect_font_variant(ARIAL_ITALIC)
    assert weight == 400
    assert italic is True


@pytest.mark.skipif(not ARIAL_BOLD_ITALIC.exists(), reason="Police système de test introuvable")
def test_detect_font_variant_reads_bold_italic(qapp):
    weight, italic, _ = detect_font_variant(ARIAL_BOLD_ITALIC)
    assert weight == 700
    assert italic is True


@pytest.mark.skipif(not _ALL_VARIANTS_EXIST, reason="Polices système de test introuvables")
def test_detect_font_variant_isolated_calls_dont_leak_between_files(qapp):
    """Régression potentielle : QFontDatabase fusionne les styles connus par famille quand
    plusieurs fichiers sont chargés simultanément — detect_font_variant doit charger/décharger
    chaque fichier un par un pour ne jamais mélanger les résultats entre deux appels successifs."""
    results = [detect_font_variant(p) for p in (ARIAL, ARIAL_BOLD, ARIAL_ITALIC, ARIAL_BOLD_ITALIC)]
    expected = [(400, False), (700, False), (400, True), (700, True)]
    for (weight, italic, _), (exp_weight, exp_italic) in zip(results, expected):
        assert (weight, italic) == (exp_weight, exp_italic)


def test_guess_variant_from_filename_fallback():
    weight, italic, label = _guess_variant_from_filename(Path("MyFont-Black.ttf"))
    assert weight == 900
    assert italic is False

    weight, italic, _ = _guess_variant_from_filename(Path("MyFont-ThinItalic.ttf"))
    assert weight == 100
    assert italic is True

    weight, italic, _ = _guess_variant_from_filename(Path("MyFont-Regular.ttf"))
    assert weight == 400
    assert italic is False


@pytest.mark.skipif(not ARIAL.exists(), reason="Police système de test introuvable")
def test_lock_font_files_ignores_duplicate_variant_and_warns(qapp, tmp_path):
    """Deux fichiers différents sur disque mais détectés avec le même (weight, italic) —
    ex. deux copies du même contenu sous des noms différents — ne doivent produire qu'UNE
    seule entrée LockedFontFile (le premier dans l'ordre de sélection), pas un @font-face
    dupliqué silencieusement écrasé par l'ordre CSS. Le second doit déclencher warning_occurred."""
    path_a = tmp_path / "font_a.ttf"
    path_b = tmp_path / "font_b.ttf"
    path_a.write_bytes(ARIAL.read_bytes())
    path_b.write_bytes(ARIAL.read_bytes())

    controller = ProjectController()
    warnings: list[str] = []
    controller.warning_occurred.connect(warnings.append)

    controller.lock_font_files("Fam", [path_a, path_b])

    lf = controller.project.document.locked_font_for_family("Fam")
    assert lf is not None
    assert len(lf.files) == 1
    assert lf.files[0].file_path == str(path_a)
    assert len(warnings) == 1
    assert "font_b.ttf" in warnings[0]
