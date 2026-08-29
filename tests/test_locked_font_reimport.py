from pathlib import Path

import pytest

from epub.builder import build_epub
from epub.html_render import LOCKED_FONT_CLASS_PREFIX, build_family_to_css_class, paragraph_to_html, run_to_html
from epub.importer import import_epub
from model.assets import AssetStore
from model.book_metadata import BookMetadata
from model.document import LockedFont, LockedFontFile, Part, Paragraph, Run
from model.project import ProjectMeta
from model.styles import CharFormat
from odt.chapter_detector import split_into_chapters
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver

FIXTURE = Path(__file__).parent / "fixtures" / "sample_simple.odt"
ARIAL = Path("C:/Windows/Fonts/arial.ttf")
TIMES = Path("C:/Windows/Fonts/times.ttf")


def _make_project_with_locked_fonts(tmp_path, locked_fonts: list[LockedFont]) -> tuple[ProjectMeta, AssetStore]:
    asset_store = AssetStore(tmp_path / "assets_src")
    source = OdtSource(FIXTURE)
    resolver = StyleResolver(source)
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)

    project = ProjectMeta()
    for ch in chapters:
        project.document.chapters[ch.id] = ch  # pas add_chapter() : structure posée explicitement ensuite
    part = Part.create(title="Partie I")
    part.chapter_ids = [c.id for c in chapters]
    project.document.structure.items.append(part)
    project.document.locked_fonts = locked_fonts

    return project, asset_store


@pytest.mark.skipif(not ARIAL.exists(), reason="Police système de test introuvable")
def test_reimport_restores_locked_font_family_and_file(tmp_path):
    """Régression : import_epub() ne restaurait jamais document.locked_fonts — une police
    figée redevenait invisible après réimport (round-trip)."""
    project, asset_store = _make_project_with_locked_fonts(
        tmp_path, [LockedFont(family="SpecialNarrative", files=[LockedFontFile(file_path=str(ARIAL))])]
    )

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))

    asset_store2 = AssetStore(tmp_path / "assets_import")
    imported_doc, _imported_metadata, warnings = import_epub(out, asset_store2)

    assert len(imported_doc.locked_fonts) == 1
    lf = imported_doc.locked_fonts[0]
    assert lf.family == "SpecialNarrative"
    assert len(lf.files) == 1
    assert Path(lf.files[0].file_path).exists()
    assert Path(lf.files[0].file_path).read_bytes() == ARIAL.read_bytes()


@pytest.mark.skipif(not ARIAL.exists(), reason="Police système de test introuvable")
def test_reimport_restores_locked_font_when_isbn_set(tmp_path):
    """Régression : quand un ISBN est renseigné, book_uid devient urn:isbn:... (au lieu de
    urn:uuid:...) et sert de clé d'obfuscation IDPF des polices — _extract_locked_fonts ne
    reconnaissait que le motif urn:uuid: par regex, donc toute police figée devenait
    irrécupérable au réimport dès qu'un ISBN était renseigné (perte silencieuse)."""
    project, asset_store = _make_project_with_locked_fonts(
        tmp_path, [LockedFont(family="SpecialNarrative", files=[LockedFontFile(file_path=str(ARIAL))])]
    )

    out = build_epub(
        project, asset_store, tmp_path / "out.epub",
        metadata=BookMetadata(title="Test", isbn="9782070360024"),
    )

    asset_store2 = AssetStore(tmp_path / "assets_import")
    imported_doc, _imported_metadata, warnings = import_epub(out, asset_store2)

    assert warnings == []
    assert len(imported_doc.locked_fonts) == 1
    lf = imported_doc.locked_fonts[0]
    assert lf.family == "SpecialNarrative"
    assert len(lf.files) == 1
    assert Path(lf.files[0].file_path).exists()
    assert Path(lf.files[0].file_path).read_bytes() == ARIAL.read_bytes()


@pytest.mark.skipif(not (ARIAL.exists() and TIMES.exists()), reason="Polices système de test introuvables")
def test_reimport_restores_two_simultaneous_locked_fonts(tmp_path):
    """Round-trip avec 2 polices figées simultanément : chacune doit être retrouvée avec le
    bon nom de famille ET le bon fichier réel associé (pas d'appariement croisé accidentel)."""
    project, asset_store = _make_project_with_locked_fonts(tmp_path, [
        LockedFont(family="SpecialNarrative", files=[LockedFontFile(file_path=str(ARIAL))]),
        LockedFont(family="AutrePoliceFigee", files=[LockedFontFile(file_path=str(TIMES))]),
    ])

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))

    asset_store2 = AssetStore(tmp_path / "assets_import")
    imported_doc, _imported_metadata, warnings = import_epub(out, asset_store2)

    assert len(imported_doc.locked_fonts) == 2
    by_family = {lf.family: lf for lf in imported_doc.locked_fonts}

    assert "SpecialNarrative" in by_family
    assert "AutrePoliceFigee" in by_family
    assert Path(by_family["SpecialNarrative"].files[0].file_path).read_bytes() == ARIAL.read_bytes()
    assert Path(by_family["AutrePoliceFigee"].files[0].file_path).read_bytes() == TIMES.read_bytes()


@pytest.mark.skipif(not (ARIAL.exists() and Path("C:/Windows/Fonts/arialbd.ttf").exists()),
                     reason="Polices système de test introuvables")
def test_reimport_restores_two_files_for_same_family_with_correct_weight(tmp_path):
    """Round-trip avec 2 fichiers (Regular + Bold) pour LA MÊME famille : les deux doivent
    revenir avec le bon poids et les bons octets, pas de perte ni de mélange."""
    arial_bold = Path("C:/Windows/Fonts/arialbd.ttf")
    project, asset_store = _make_project_with_locked_fonts(tmp_path, [
        LockedFont(family="JMHTypewriter", files=[
            LockedFontFile(file_path=str(ARIAL), weight=400, italic=False),
            LockedFontFile(file_path=str(arial_bold), weight=700, italic=False),
        ]),
    ])

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))

    asset_store2 = AssetStore(tmp_path / "assets_import")
    imported_doc, _imported_metadata, warnings = import_epub(out, asset_store2)

    assert len(imported_doc.locked_fonts) == 1
    lf = imported_doc.locked_fonts[0]
    assert lf.family == "JMHTypewriter"
    assert len(lf.files) == 2

    by_weight = {f.weight: f for f in lf.files}
    assert 400 in by_weight and 700 in by_weight
    assert by_weight[400].italic is False
    assert by_weight[700].italic is False
    assert Path(by_weight[400].file_path).read_bytes() == ARIAL.read_bytes()
    assert Path(by_weight[700].file_path).read_bytes() == arial_bold.read_bytes()


def test_run_to_html_without_inline_style_uses_class_only():
    fmt = CharFormat(font_name="Narrative")
    run = Run(text="mot figé", fmt=fmt)
    family_to_css_class = build_family_to_css_class(["Narrative"])
    html = run_to_html(run, family_to_css_class=family_to_css_class, inline_locked_font_style=False)
    assert 'class="epubeur-locked-font-narrative"' in html
    assert "style=" not in html


def test_run_to_html_with_inline_style_adds_font_family():
    """Régression : QTextBrowser (aperçu app) applique font-family en style inline mais
    ignore les règles CSS basées sur une classe — sans style inline, la police figée
    n'apparaissait jamais visuellement dans l'aperçu de chapitre."""
    fmt = CharFormat(font_name="Narrative")
    run = Run(text="mot figé", fmt=fmt)
    family_to_css_class = build_family_to_css_class(["Narrative"])
    html = run_to_html(run, family_to_css_class=family_to_css_class, inline_locked_font_style=True)
    assert 'class="epubeur-locked-font-narrative"' in html
    assert "font-family: 'Narrative'" in html


def test_paragraph_to_html_propagates_inline_locked_font_style():
    fmt = CharFormat(font_name="Narrative")
    para = Paragraph(runs=[Run(text="texte", fmt=fmt)])
    family_to_css_class = build_family_to_css_class(["Narrative"])
    html = paragraph_to_html(para, family_to_css_class=family_to_css_class, inline_locked_font_style=True)
    assert "font-family: 'Narrative'" in html


def test_run_to_html_only_marks_run_matching_its_own_family():
    """Avec 2 polices figées, un run ne doit être marqué que par SA propre police, pas par
    l'autre — vérifie l'absence de fuite entre les deux mappings."""
    family_to_css_class = build_family_to_css_class(["Narrative", "Autre"])

    run_narrative = Run(text="a", fmt=CharFormat(font_name="Narrative"))
    run_autre = Run(text="b", fmt=CharFormat(font_name="Autre"))
    run_unlocked = Run(text="c", fmt=CharFormat(font_name="PoliceNonFigee"))

    html_narrative = run_to_html(run_narrative, family_to_css_class=family_to_css_class)
    html_autre = run_to_html(run_autre, family_to_css_class=family_to_css_class)
    html_unlocked = run_to_html(run_unlocked, family_to_css_class=family_to_css_class)

    assert family_to_css_class["Narrative"] in html_narrative
    assert family_to_css_class["Autre"] not in html_narrative

    assert family_to_css_class["Autre"] in html_autre
    assert family_to_css_class["Narrative"] not in html_autre

    assert "class=" not in html_unlocked


def test_build_family_to_css_class_disambiguates_slug_collision():
    """Deux familles distinctes qui se normalisent vers le même slug (ex : ponctuation
    différente, casse différente) ne doivent jamais partager la même classe CSS, sinon leurs
    styles @font-face se marcheraient dessus dans le CSS généré."""
    family_to_css_class = build_family_to_css_class(["Ma Police!", "Ma Police?", "ma police"])

    classes = list(family_to_css_class.values())
    assert len(classes) == len(set(classes)), f"classes CSS non uniques : {classes}"

    for css_class in classes:
        assert css_class.startswith(LOCKED_FONT_CLASS_PREFIX)
