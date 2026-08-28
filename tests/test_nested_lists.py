import zipfile
from pathlib import Path

from bs4 import BeautifulSoup

from epub.builder import build_epub
from epub.css_resolve import CssResolver
from epub.html_normalize import html_to_paragraphs
from epub.html_render import paragraphs_to_html
from epub.importer import import_epub
from model.assets import AssetStore
from model.book_metadata import BookMetadata
from model.document import Part, Paragraph, Run
from model.project import ProjectMeta
from model.styles import CharFormat, ParagraphAlign, ParagraphKind
from odt.chapter_detector import split_into_chapters
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver

MANIFEST_XML = ('<?xml version="1.0"?>'
                 '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>')

NS_ATTRS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"'
)

NESTED_LIST_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:automatic-styles>
    <text:list-style style:name="L1">
      <text:list-level-style-bullet text:level="1" text:bullet-char="-"/>
    </text:list-style>
  </office:automatic-styles>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:list text:style-name="L1">
        <text:list-item>
          <text:p>Item1</text:p>
          <text:list text:style-name="L1">
            <text:list-item>
              <text:p>Item1.1</text:p>
            </text:list-item>
            <text:list-item>
              <text:p>Item1.2</text:p>
            </text:list-item>
          </text:list>
        </text:list-item>
        <text:list-item>
          <text:p>Item2</text:p>
        </text:list-item>
      </text:list>
    </office:text>
  </office:body>
</office:document-content>
"""

ADJACENT_LISTS_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:automatic-styles>
    <text:list-style style:name="L1">
      <text:list-level-style-number text:level="1"/>
    </text:list-style>
  </office:automatic-styles>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:list text:style-name="L1">
        <text:list-item>
          <text:p>Liste A - item1</text:p>
        </text:list-item>
      </text:list>
      <text:list text:style-name="L1">
        <text:list-item>
          <text:p>Liste B - item1</text:p>
        </text:list-item>
      </text:list>
    </office:text>
  </office:body>
</office:document-content>
"""

MULTI_LEVEL_STYLE_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:automatic-styles>
    <text:list-style style:name="L2">
      <text:list-level-style-bullet text:level="1" text:bullet-char="-"/>
      <text:list-level-style-number text:level="2"/>
    </text:list-style>
  </office:automatic-styles>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:list text:style-name="L2">
        <text:list-item>
          <text:p>Item1</text:p>
          <text:list text:style-name="L2">
            <text:list-item>
              <text:p>Item1.1</text:p>
            </text:list-item>
          </text:list>
        </text:list-item>
      </text:list>
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


def _make_fixture(tmp_path: Path, content_xml: str, name: str = "fixture.odt") -> Path:
    fixture_path = tmp_path / name
    with zipfile.ZipFile(fixture_path, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        zf.writestr("content.xml", content_xml)
        zf.writestr("styles.xml", STYLES_XML)
        zf.writestr("META-INF/manifest.xml", MANIFEST_XML)
    return fixture_path


def _split(tmp_path: Path, content_xml: str, name: str = "fixture.odt"):
    fixture = _make_fixture(tmp_path, content_xml, name)
    asset_store = AssetStore(tmp_path / f"assets_{name}")
    source = OdtSource(fixture)
    resolver = StyleResolver(source)
    return split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)


def test_odt_nested_list_produces_correct_list_levels_and_groups(tmp_path):
    chapters = _split(tmp_path, NESTED_LIST_CONTENT_XML)
    paragraphs = chapters[0].paragraphs

    assert [p.list_level for p in paragraphs] == [1, 2, 2, 1]

    item1, item11, item12, item2 = paragraphs
    assert item11.list_group_id == item12.list_group_id
    assert item11.list_group_id != item1.list_group_id
    assert item2.list_group_id == item1.list_group_id


def test_odt_adjacent_lists_have_different_group_ids(tmp_path):
    chapters = _split(tmp_path, ADJACENT_LISTS_CONTENT_XML)
    paragraphs = chapters[0].paragraphs

    assert len(paragraphs) == 2
    list_a_item, list_b_item = paragraphs
    assert list_a_item.list_group_id != list_b_item.list_group_id


def test_odt_multi_level_style_resolves_correct_kind_per_level(tmp_path):
    chapters = _split(tmp_path, MULTI_LEVEL_STYLE_CONTENT_XML)
    paragraphs = chapters[0].paragraphs

    item1, item11 = paragraphs
    assert item1.list_level == 1
    assert item1.kind == ParagraphKind.LIST_ITEM_BULLET
    assert item11.list_level == 2
    assert item11.kind == ParagraphKind.LIST_ITEM_NUMBER


def test_is_list_style_ordered_falls_back_to_closest_lower_level(tmp_path):
    fixture = _make_fixture(tmp_path, MULTI_LEVEL_STYLE_CONTENT_XML)
    source = OdtSource(fixture)
    resolver = StyleResolver(source)

    assert resolver.is_list_style_ordered("L2", level=1) is False
    assert resolver.is_list_style_ordered("L2", level=2) is True
    # Niveau 3 non défini explicitement : replie sur le plus grand niveau défini <= 3 (niveau 2, numéroté).
    assert resolver.is_list_style_ordered("L2", level=3) is True
    assert resolver.is_list_style_ordered(None) is False
    assert resolver.is_list_style_ordered("inexistant") is False


def _para(kind, level, group_id, text="x"):
    return Paragraph(kind=kind, align=ParagraphAlign.LEFT, runs=[Run(text=text, fmt=CharFormat())],
                      list_level=level, list_group_id=group_id)


def test_render_nested_list_produces_ul_nested_inside_li():
    paragraphs = [
        _para(ParagraphKind.LIST_ITEM_BULLET, 1, "g1", "Item1"),
        _para(ParagraphKind.LIST_ITEM_BULLET, 2, "g2", "Item1.1"),
        _para(ParagraphKind.LIST_ITEM_BULLET, 2, "g2", "Item1.2"),
        _para(ParagraphKind.LIST_ITEM_BULLET, 1, "g1", "Item2"),
    ]
    html = paragraphs_to_html(paragraphs)
    soup = BeautifulSoup(html, "lxml")

    top_ul = soup.find("ul")
    assert top_ul is not None
    top_lis = top_ul.find_all("li", recursive=False)
    assert len(top_lis) == 2

    nested_ul = top_lis[0].find("ul", recursive=False)
    assert nested_ul is not None
    nested_lis = nested_ul.find_all("li", recursive=False)
    assert [li.get_text(strip=True) for li in nested_lis] == ["Item1.1", "Item1.2"]
    assert top_lis[1].get_text(strip=True) == "Item2"


def test_render_adjacent_lists_same_type_not_merged():
    paragraphs = [
        _para(ParagraphKind.LIST_ITEM_NUMBER, 1, "gA", "A1"),
        _para(ParagraphKind.LIST_ITEM_NUMBER, 1, "gB", "B1"),
    ]
    html = paragraphs_to_html(paragraphs)
    soup = BeautifulSoup(html, "lxml")

    ols = soup.body.find_all("ol", recursive=False)
    assert len(ols) == 2
    assert [li.get_text(strip=True) for li in ols[0].find_all("li")] == ["A1"]
    assert [li.get_text(strip=True) for li in ols[1].find_all("li")] == ["B1"]


def test_render_flat_list_unchanged_from_previous_behavior():
    paragraphs = [
        _para(ParagraphKind.LIST_ITEM_BULLET, 1, "g", "a"),
        _para(ParagraphKind.LIST_ITEM_BULLET, 1, "g", "b"),
    ]
    html = paragraphs_to_html(paragraphs)
    assert html == "<ul><li>a</li><li>b</li></ul>"


def test_reimport_nested_list_reconstructs_levels_and_groups():
    xhtml = """<html><body><div class="epubeur-chapter">
<ul><li>Item1<ul><li>Item1.1</li></ul></li></ul>
</div></body></html>"""
    resolver = CssResolver([])
    paragraphs, _footnotes, _image_wraps = html_to_paragraphs(xhtml, resolver)

    assert [p.list_level for p in paragraphs] == [1, 2]
    assert paragraphs[0].list_group_id != paragraphs[1].list_group_id
    assert paragraphs[0].plain_text() == "Item1"
    assert paragraphs[1].plain_text() == "Item1.1"


def test_round_trip_odt_to_epub_to_reimport_preserves_nested_list_structure(tmp_path):
    chapters = _split(tmp_path, NESTED_LIST_CONTENT_XML)
    asset_store = AssetStore(tmp_path / "assets_src")

    project = ProjectMeta()
    for ch in chapters:
        project.document.chapters[ch.id] = ch
    part = Part.create(title="Partie I")
    part.chapter_ids = [c.id for c in chapters]
    project.document.structure.items.append(part)

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))

    asset_store2 = AssetStore(tmp_path / "assets_import")
    imported_doc, _imported_metadata, warnings = import_epub(out, asset_store2)

    imported_paragraphs = [p for c in imported_doc.chapters.values() for p in c.paragraphs]
    assert [p.list_level for p in imported_paragraphs] == [1, 2, 2, 1]
    assert [p.plain_text() for p in imported_paragraphs] == ["Item1", "Item1.1", "Item1.2", "Item2"]

    item1, item11, item12, item2 = imported_paragraphs
    assert item11.list_group_id == item12.list_group_id
    assert item11.list_group_id != item1.list_group_id
    assert item2.list_group_id == item1.list_group_id
