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
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    xmlns:xlink="http://www.w3.org/1999/xlink">
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>Voir <text:a xlink:href="https://example.com/page">ce site</text:a> pour plus.</text:p>
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
    fixture_path = tmp_path / "hyperlink.odt"
    with zipfile.ZipFile(fixture_path, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        zf.writestr("content.xml", CONTENT_XML)
        zf.writestr("styles.xml", STYLES_XML)
        zf.writestr("META-INF/manifest.xml", MANIFEST_XML)
    return fixture_path


def test_odt_hyperlink_text_is_preserved(tmp_path):
    """Régression : <text:a> n'était reconnu par aucune branche de _iter_runs, donc le texte
    à l'intérieur du lien était purement perdu à l'import (pas seulement 'non cliquable')."""
    fixture = _make_fixture(tmp_path)
    asset_store = AssetStore(tmp_path / "assets")
    source = OdtSource(fixture)
    resolver = StyleResolver(source)
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)

    para = chapters[0].paragraphs[0]
    assert para.plain_text() == "Voir ce site pour plus."


def test_odt_hyperlink_run_carries_url(tmp_path):
    fixture = _make_fixture(tmp_path)
    asset_store = AssetStore(tmp_path / "assets")
    source = OdtSource(fixture)
    resolver = StyleResolver(source)
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)

    runs = chapters[0].paragraphs[0].runs
    link_runs = [r for r in runs if r.link_url is not None]
    assert len(link_runs) == 1
    assert link_runs[0].text == "ce site"
    assert link_runs[0].link_url == "https://example.com/page"

    non_link_runs = [r for r in runs if r.link_url is None]
    assert "".join(r.text for r in non_link_runs) == "Voir  pour plus."


def test_run_to_html_wraps_text_in_anchor_tag():
    run = Run(text="ce site", fmt=CharFormat(), link_url="https://example.com/page")
    html = run_to_html(run, family_to_css_class=None)
    assert html == '<a href="https://example.com/page">ce site</a>'


def test_run_to_html_without_link_has_no_anchor():
    run = Run(text="texte simple", fmt=CharFormat())
    html = run_to_html(run, family_to_css_class=None)
    assert "<a " not in html


def test_round_trip_preserves_hyperlink(tmp_path):
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

    with zipfile.ZipFile(out) as zf:
        xhtml = zf.read("EPUB/text/chapter_0.xhtml").decode()
        assert '<a href="https://example.com/page">ce site</a>' in xhtml

    asset_store2 = AssetStore(tmp_path / "assets_import")
    imported_doc, _imported_metadata, warnings = import_epub(out, asset_store2)

    imported_runs = [r for c in imported_doc.chapters.values() for p in c.paragraphs for r in p.runs]
    link_runs = [r for r in imported_runs if r.link_url == "https://example.com/page"]
    assert len(link_runs) == 1
    assert link_runs[0].text == "ce site"
