import zipfile
from pathlib import Path

from epub.builder import build_epub
from epub.html_render import chapter_to_xhtml, title_html_block, title_single_line
from epub.importer import import_epub
from model.assets import AssetStore
from model.book_metadata import BookMetadata
from model.document import Chapter, Part
from model.project import ProjectMeta
from model.text_utils import flatten_to_single_line
from odt.chapter_detector import split_into_chapters
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver

CONTENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un<text:line-break/>Sous-titre</text:h>
      <text:p>Contenu du chapitre.</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

STYLES_XML = """<?xml version="1.0"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0">
  <office:styles>
    <style:style style:name="Heading_20_1" style:display-name="Heading 1" style:family="paragraph"/>
  </office:styles>
</office:document-styles>
"""

MANIFEST_XML = ('<?xml version="1.0"?>'
                 '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>')


def _make_fixture(tmp_path: Path) -> Path:
    fixture_path = tmp_path / "linebreak.odt"
    with zipfile.ZipFile(fixture_path, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        zf.writestr("content.xml", CONTENT_XML)
        zf.writestr("styles.xml", STYLES_XML)
        zf.writestr("META-INF/manifest.xml", MANIFEST_XML)
    return fixture_path


def test_line_break_produces_newline_in_title(tmp_path):
    """Régression : text:line-break n'était pas géré du tout — les deux fragments de texte
    de part et d'autre se retrouvaient concaténés sans aucun séparateur (ni saut de ligne,
    ni espace)."""
    fixture = _make_fixture(tmp_path)
    asset_store = AssetStore(tmp_path / "assets")
    source = OdtSource(fixture)
    resolver = StyleResolver(source)
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)

    assert len(chapters) == 1
    assert chapters[0].title == "Chapitre Un\nSous-titre"


def test_title_html_block_renders_line_break_as_br():
    html = title_html_block("Chapitre Un\nSous-titre")
    assert html == "Chapitre Un<br/>Sous-titre"


def test_title_single_line_flattens_line_break():
    flat = title_single_line("Chapitre Un\nSous-titre")
    assert flat == "Chapitre Un Sous-titre"
    assert "\n" not in flat


def test_flatten_to_single_line_utility():
    assert flatten_to_single_line("A\nB\nC") == "A B C"
    assert flatten_to_single_line("no break") == "no break"


def test_chapter_to_xhtml_h1_has_br_but_title_tag_is_single_line():
    chapter = Chapter.create(title="Chapitre Un\nSous-titre")
    xhtml = chapter_to_xhtml(chapter, css_href="style.css")
    assert "Chapitre Un<br/>Sous-titre" in xhtml
    assert "<title>Chapitre Un Sous-titre</title>" in xhtml


def test_round_trip_preserves_line_break_in_title(tmp_path):
    """Le titre généré avec <br/> doit redevenir '\\n' après réimport, pas le texte
    littéral '<br/>', et les entités HTML échappées doivent être désescapées."""
    fixture = _make_fixture(tmp_path)
    asset_store = AssetStore(tmp_path / "assets_src")
    source = OdtSource(fixture)
    resolver = StyleResolver(source)
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)

    project = ProjectMeta()
    for ch in chapters:
        project.document.chapters[ch.id] = ch  # pas add_chapter() : structure posée explicitement ensuite
    part = Part.create(title="Partie I")
    part.chapter_ids = [c.id for c in chapters]
    project.document.structure.items.append(part)

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))

    asset_store2 = AssetStore(tmp_path / "assets_import")
    imported_doc, _imported_metadata, warnings = import_epub(out, asset_store2)

    imported_titles = [c.title for c in imported_doc.chapters.values()]
    assert "Chapitre Un\nSous-titre" in imported_titles
