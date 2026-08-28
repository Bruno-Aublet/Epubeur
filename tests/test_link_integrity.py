from pathlib import Path

import pytest
from ebooklib import epub

from epub.builder import EpubBuildError, build_epub
from epub.link_integrity import check_internal_link_integrity
from model.assets import AssetStore
from model.book_metadata import BookMetadata
from model.document import Chapter, Paragraph, Part, Run
from model.project import ProjectMeta
from model.styles import CharFormat
from odt.chapter_detector import split_into_chapters
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver

FIXTURE = Path(__file__).parent / "fixtures" / "sample_simple.odt"

XHTML_HEAD = ('<html xmlns="http://www.w3.org/1999/xhtml"><head><title>T</title></head><body>')
XHTML_TAIL = "</body></html>"


def _html_item(uid: str, file_name: str, body: str) -> epub.EpubHtml:
    item = epub.EpubHtml(uid=uid, file_name=file_name, content=XHTML_HEAD + body + XHTML_TAIL)
    return item


def _book_with_items(*items: epub.EpubHtml) -> epub.EpubBook:
    book = epub.EpubBook()
    for item in items:
        book.add_item(item)
    return book


def test_no_errors_when_no_ids_or_internal_links():
    book = _book_with_items(_html_item("c1", "text/chapter_0.xhtml", "<p>Bonjour</p>"))
    assert check_internal_link_integrity(book) == []


def test_detects_duplicate_id_within_same_file():
    book = _book_with_items(
        _html_item("c1", "text/chapter_0.xhtml", '<p id="a">Un</p><p id="a">Deux</p>')
    )
    errors = check_internal_link_integrity(book)
    assert any("plusieurs fois" in e and "chapter_0.xhtml" in e for e in errors)


def test_allows_same_id_reused_across_different_files():
    """epubcheck ne contraint l'unicité des id qu'à l'intérieur d'un même document XML —
    deux fichiers différents peuvent chacun avoir un id="intro" sans conflit."""
    book = _book_with_items(
        _html_item("c1", "text/chapter_0.xhtml", '<p id="intro">Un</p>'),
        _html_item("c2", "text/chapter_1.xhtml", '<p id="intro">Deux</p>'),
    )
    assert check_internal_link_integrity(book) == []


def test_detects_broken_same_file_fragment_link():
    book = _book_with_items(
        _html_item("c1", "text/chapter_0.xhtml", '<p id="a">Un</p><a href="#inexistant">lien</a>')
    )
    errors = check_internal_link_integrity(book)
    assert any("Lien interne cassé" in e and "#inexistant" in e for e in errors)


def test_accepts_valid_same_file_fragment_link():
    book = _book_with_items(
        _html_item("c1", "text/chapter_0.xhtml", '<p id="a">Un</p><a href="#a">lien</a>')
    )
    assert check_internal_link_integrity(book) == []


def test_detects_broken_cross_file_fragment_link():
    book = _book_with_items(
        _html_item("c1", "text/chapter_0.xhtml", '<a href="chapter_1.xhtml#note1">note</a>'),
        _html_item("c2", "text/chapter_1.xhtml", "<p>Sans ancre</p>"),
    )
    errors = check_internal_link_integrity(book)
    assert any("Lien interne cassé" in e and "chapter_1.xhtml#note1" in e for e in errors)


def test_accepts_valid_cross_file_fragment_link():
    book = _book_with_items(
        _html_item("c1", "text/chapter_0.xhtml", '<a href="chapter_1.xhtml#note1">note</a>'),
        _html_item("c2", "text/chapter_1.xhtml", '<p id="note1">Corps de note</p>'),
    )
    assert check_internal_link_integrity(book) == []


def test_ignores_external_and_fragmentless_links():
    book = _book_with_items(
        _html_item("c1", "text/chapter_0.xhtml",
                   '<a href="https://example.com/page">externe</a><a href="chapter_1.xhtml">sans ancre</a>')
    )
    assert check_internal_link_integrity(book) == []


def _make_project(tmp_path) -> tuple[ProjectMeta, AssetStore]:
    asset_store = AssetStore(tmp_path / "assets")
    source = OdtSource(FIXTURE)
    resolver = StyleResolver(source)
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)

    project = ProjectMeta()
    for ch in chapters:
        project.document.chapters[ch.id] = ch
    part = Part.create(title="Partie I")
    part.chapter_ids = [c.id for c in chapters]
    project.document.structure.items.append(part)
    return project, asset_store


def test_build_epub_raises_cleanly_on_broken_internal_link(tmp_path):
    """Un lien interne (#ancre) tapé manuellement dans Writer et recopié tel quel via
    run.link_url, sans ancre correspondante nulle part dans le livre généré, doit être détecté
    plutôt que produire silencieusement un EPUB avec un lien mort."""
    project, asset_store = _make_project(tmp_path)
    chapter = next(iter(project.document.chapters.values()))
    chapter.paragraphs.append(
        Paragraph(runs=[Run(text="lien", fmt=CharFormat(), link_url="#ancre-inexistante")])
    )

    with pytest.raises(EpubBuildError):
        build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))
