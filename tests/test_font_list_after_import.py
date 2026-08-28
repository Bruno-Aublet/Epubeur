from pathlib import Path

from controller import ProjectController
from epub.builder import build_epub
from model.assets import AssetStore
from model.book_metadata import BookMetadata
from model.document import Chapter, LockedFont, LockedFontFile, Paragraph, Part, Run
from model.font_scan import scan_fonts_in_document
from model.project import ProjectMeta
from model.styles import CharFormat
from odt.chapter_detector import split_into_chapters
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver

FIXTURE = Path(__file__).parent / "fixtures" / "sample_simple.odt"


def test_scan_fonts_in_document_counts_run_font_names():
    from model.document import Document

    document = Document()
    chapter = Chapter.create(title="Test")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="a", fmt=CharFormat(font_name="Narrative")),
                         Run(text="b", fmt=CharFormat(font_name="Narrative"))]),
        Paragraph(runs=[Run(text="c", fmt=CharFormat(font_name=None))]),
    ]
    document.add_chapter(chapter)

    counts = scan_fonts_in_document(document)
    assert counts["Narrative"] == 2
    assert None not in counts


def test_font_counts_populated_after_epub_import(qapp, tmp_path):
    """Régression : la liste des polices détectées restait vide après un import EPUB —
    _font_counts n'était repeuplé que par import_odt, jamais par import_epub_file.
    Note : seule une police FIGÉE est récupérable au réimport (marquée dans le CSS via
    .epubeur-locked-font) — une police "libre" non figée n'est jamais écrite dans l'EPUB
    généré (comportement voulu : le lecteur doit pouvoir la changer), donc son nom est
    perdu de façon définitive dès la génération, pas seulement à l'import."""
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
    project.document.locked_fonts = [
        LockedFont(family="SpecialNarrative", files=[LockedFontFile(file_path="C:/Windows/Fonts/arial.ttf")])
    ]

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))

    controller = ProjectController()
    controller.import_epub_file(out)

    assert controller.font_counts().get("SpecialNarrative", 0) >= 1


def test_font_counts_populated_after_project_reload(qapp, tmp_path):
    """Régression symétrique : load_project_from vidait _font_counts sans jamais le
    repeupler depuis le document restauré."""
    controller = ProjectController()
    controller.import_odt(FIXTURE)
    assert controller.font_counts().get("SpecialNarrative", 0) >= 1

    epbz_path = tmp_path / "MyProject.epbz"
    controller.save_project_as(epbz_path)

    controller2 = ProjectController()
    controller2.load_project_from(epbz_path)

    assert controller2.font_counts().get("SpecialNarrative", 0) >= 1
