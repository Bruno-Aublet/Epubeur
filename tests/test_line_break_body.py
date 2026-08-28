import zipfile
from pathlib import Path

from epub.builder import build_epub
from epub.html_render import run_to_html
from epub.importer import import_epub
from model.assets import AssetStore
from model.book_metadata import BookMetadata
from model.document import Part, Run
from model.project import ProjectMeta
from model.styles import CharFormat
from odt.chapter_detector import split_into_chapters
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver

CONTENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>Première ligne<text:line-break/>Deuxième ligne du même paragraphe.</text:p>
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
    fixture_path = tmp_path / "body_linebreak.odt"
    with zipfile.ZipFile(fixture_path, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        zf.writestr("content.xml", CONTENT_XML)
        zf.writestr("styles.xml", STYLES_XML)
        zf.writestr("META-INF/manifest.xml", MANIFEST_XML)
    return fixture_path


def test_line_break_in_body_paragraph_produces_newline(tmp_path):
    """Régression : text:line-break dans un paragraphe normal (pas un titre) produisait
    le même bug — les deux fragments concaténés sans aucun séparateur."""
    fixture = _make_fixture(tmp_path)
    asset_store = AssetStore(tmp_path / "assets")
    source = OdtSource(fixture)
    resolver = StyleResolver(source)
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)

    para = chapters[0].paragraphs[0]
    assert para.plain_text() == "Première ligne\nDeuxième ligne du même paragraphe."


def test_run_to_html_renders_line_break_as_br():
    run = Run(text="Première ligne\nDeuxième ligne.", fmt=CharFormat())
    html = run_to_html(run, family_to_css_class=None)
    assert html == "Première ligne<br/>Deuxième ligne."


def test_round_trip_preserves_line_break_in_body_text(tmp_path):
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

    imported_texts = [p.plain_text() for c in imported_doc.chapters.values() for p in c.paragraphs]
    assert "Première ligne\nDeuxième ligne du même paragraphe." in imported_texts
