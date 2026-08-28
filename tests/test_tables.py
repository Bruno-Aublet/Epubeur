import zipfile
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from epub.accessibility import build_accessibility_metadata
from epub.builder import EpubBuildError, build_epub, split_chapter_into_segments
from epub.css_resolve import CssResolver
from epub.html_normalize import html_to_paragraphs
from epub.html_render import paragraphs_to_html, table_to_html
from epub.importer import import_epub
from model.assets import AssetRole, AssetStore
from model.book_metadata import BookMetadata
from model.document import (
    Chapter,
    Document,
    ImageAnchor,
    Paragraph,
    Part,
    Run,
    Table,
    TableCell,
    TableRow,
    iter_all_paragraphs,
)
from model.font_scan import scan_fonts_in_document
from model.project import ProjectMeta
from model.serialization import document_from_dict, document_to_dict
from model.styles import CharFormat, ParagraphKind
from odt.chapter_detector import split_into_chapters
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver

MANIFEST_XML = ('<?xml version="1.0"?>'
                 '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>')

NS_ATTRS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
)

STYLES_XML = """<?xml version="1.0"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0">
  <office:styles>
    <style:style style:name="Heading_20_1" style:display-name="Heading 1" style:family="paragraph"/>
  </office:styles>
</office:document-styles>
"""

SIMPLE_TABLE_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <table:table table:name="Table1">
        <table:table-column/>
        <table:table-column/>
        <table:table-row>
          <table:table-cell><text:p>A1</text:p></table:table-cell>
          <table:table-cell><text:p>B1</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>A2</text:p></table:table-cell>
          <table:table-cell><text:p>B2</text:p></table:table-cell>
        </table:table-row>
      </table:table>
    </office:text>
  </office:body>
</office:document-content>
"""

MERGED_CELLS_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <table:table table:name="Table1">
        <table:table-row>
          <table:table-cell table:number-columns-spanned="2"><text:p>Fusion horizontale</text:p></table:table-cell>
          <table:covered-table-cell/>
        </table:table-row>
        <table:table-row>
          <table:table-cell table:number-rows-spanned="2"><text:p>Fusion verticale</text:p></table:table-cell>
          <table:table-cell><text:p>Normale</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:covered-table-cell/>
          <table:table-cell><text:p>Autre</text:p></table:table-cell>
        </table:table-row>
      </table:table>
    </office:text>
  </office:body>
</office:document-content>
"""

FORMATTED_CELL_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}
    xmlns:xlink="http://www.w3.org/1999/xlink">
  <office:automatic-styles>
    <style:style style:name="Bold" style:family="text">
      <style:text-properties fo:font-weight="bold"
          xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"/>
    </style:style>
  </office:automatic-styles>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <table:table table:name="Table1">
        <table:table-row>
          <table:table-cell>
            <text:p><text:span text:style-name="Bold">Gras</text:span> normal
            <text:a xlink:href="https://example.com">lien</text:a></text:p>
          </table:table-cell>
        </table:table-row>
      </table:table>
    </office:text>
  </office:body>
</office:document-content>
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


# --- 1. Tableau simple ---

def test_odt_simple_table_produces_table_block(tmp_path):
    chapters = _split(tmp_path, SIMPLE_TABLE_CONTENT_XML)
    paragraphs = chapters[0].paragraphs

    assert len(paragraphs) == 1
    table = paragraphs[0]
    assert isinstance(table, Table)
    assert len(table.rows) == 2
    assert len(table.rows[0].cells) == 2
    assert table.rows[0].cells[0].paragraphs[0].plain_text() == "A1"
    assert table.rows[0].cells[1].paragraphs[0].plain_text() == "B1"
    assert table.rows[1].cells[0].paragraphs[0].plain_text() == "A2"
    assert table.rows[1].cells[1].paragraphs[0].plain_text() == "B2"


# --- 2. Cellules fusionnées ---

def test_odt_merged_cells_colspan_and_rowspan(tmp_path):
    chapters = _split(tmp_path, MERGED_CELLS_CONTENT_XML)
    table = chapters[0].paragraphs[0]
    assert isinstance(table, Table)

    assert len(table.rows[0].cells) == 1
    assert table.rows[0].cells[0].colspan == 2
    assert table.rows[0].cells[0].paragraphs[0].plain_text() == "Fusion horizontale"

    assert len(table.rows[1].cells) == 2
    assert table.rows[1].cells[0].rowspan == 2
    assert table.rows[1].cells[0].paragraphs[0].plain_text() == "Fusion verticale"
    assert table.rows[1].cells[1].paragraphs[0].plain_text() == "Normale"

    assert len(table.rows[2].cells) == 1
    assert table.rows[2].cells[0].paragraphs[0].plain_text() == "Autre"


# --- 3. Texte formaté dans une cellule ---

def test_odt_cell_preserves_formatting_and_links(tmp_path):
    chapters = _split(tmp_path, FORMATTED_CELL_CONTENT_XML)
    table = chapters[0].paragraphs[0]
    assert isinstance(table, Table)

    runs = table.rows[0].cells[0].paragraphs[0].runs
    assert any(r.fmt.bold and r.text == "Gras" for r in runs)
    assert any(r.link_url == "https://example.com" for r in runs)


# --- 4. Rendu HTML ---

def _cell(text: str, colspan: int = 1, rowspan: int = 1, is_header: bool = False) -> TableCell:
    return TableCell(paragraphs=[Paragraph(runs=[Run(text=text, fmt=CharFormat())])],
                      colspan=colspan, rowspan=rowspan, is_header=is_header)


def test_table_to_html_simple_structure():
    table = Table(rows=[TableRow(cells=[_cell("A1"), _cell("B1")])])
    html = table_to_html(table)
    assert html == "<table><tr><td><p>A1</p></td><td><p>B1</p></td></tr></table>"


def test_table_to_html_omits_span_attrs_when_one():
    table = Table(rows=[TableRow(cells=[_cell("A1")])])
    html = table_to_html(table)
    assert "colspan" not in html
    assert "rowspan" not in html


def test_table_to_html_includes_span_attrs_when_greater_than_one():
    table = Table(rows=[TableRow(cells=[_cell("A1", colspan=2, rowspan=3)])])
    html = table_to_html(table)
    assert 'colspan="2"' in html
    assert 'rowspan="3"' in html


def test_table_to_html_header_cell_uses_th():
    table = Table(rows=[TableRow(cells=[_cell("En-tête", is_header=True)])])
    html = table_to_html(table)
    assert "<th>" in html
    assert "</th>" in html


def test_table_intercalated_between_lists_does_not_merge_them():
    list_item = Paragraph(kind=ParagraphKind.LIST_ITEM_BULLET, runs=[Run(text="x", fmt=CharFormat())],
                           list_level=1, list_group_id="gA")
    another_list_item = Paragraph(kind=ParagraphKind.LIST_ITEM_BULLET, runs=[Run(text="y", fmt=CharFormat())],
                                   list_level=1, list_group_id="gB")
    table = Table(rows=[TableRow(cells=[_cell("Z")])])

    html = paragraphs_to_html([list_item, table, another_list_item])
    soup = BeautifulSoup(html, "lxml")

    uls = soup.body.find_all("ul", recursive=False)
    assert len(uls) == 2
    assert soup.find("table") is not None


# --- 5. Réimport HTML -> pivot ---

def test_reimport_simple_table():
    xhtml = ('<html><body><div class="epubeur-chapter">'
              '<table><tr><td colspan="2"><p>X</p></td></tr></table>'
              '</div></body></html>')
    resolver = CssResolver([])
    result, _footnotes, _image_wraps = html_to_paragraphs(xhtml, resolver)

    assert len(result) == 1
    table = result[0]
    assert isinstance(table, Table)
    assert table.rows[0].cells[0].colspan == 2
    assert table.rows[0].cells[0].paragraphs[0].plain_text() == "X"


def test_reimport_table_with_thead_tbody_external_epub():
    xhtml = ('<html><body>'
             '<table><thead><tr><th>En-tête</th></tr></thead>'
             '<tbody><tr><td>Valeur</td></tr></tbody></table>'
             '</body></html>')
    resolver = CssResolver([])
    result, _footnotes, _image_wraps = html_to_paragraphs(xhtml, resolver)

    table = result[0]
    assert isinstance(table, Table)
    assert len(table.rows) == 2
    assert table.rows[0].cells[0].is_header is True
    assert table.rows[0].cells[0].paragraphs[0].plain_text() == "En-tête"
    assert table.rows[1].cells[0].is_header is False
    assert table.rows[1].cells[0].paragraphs[0].plain_text() == "Valeur"


def test_reimport_cell_without_inner_p_external_epub():
    xhtml = '<html><body><table><tr><td>Texte nu</td></tr></table></body></html>'
    resolver = CssResolver([])
    result, _footnotes, _image_wraps = html_to_paragraphs(xhtml, resolver)

    table = result[0]
    assert isinstance(table, Table)
    assert len(table.rows[0].cells[0].paragraphs) == 1
    assert table.rows[0].cells[0].paragraphs[0].plain_text() == "Texte nu"


# --- 6. Round-trip complet ODT -> EPUB -> réimport ---

def test_round_trip_odt_to_epub_to_reimport_preserves_merged_table(tmp_path):
    chapters = _split(tmp_path, MERGED_CELLS_CONTENT_XML)
    asset_store = AssetStore(tmp_path / "assets_src")

    project = ProjectMeta()
    for ch in chapters:
        project.document.chapters[ch.id] = ch
    part = Part.create(title="Partie I")
    part.chapter_ids = [c.id for c in chapters]
    project.document.structure.items.append(part)

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))

    asset_store2 = AssetStore(tmp_path / "assets_import")
    imported_doc, _imported_metadata, _warnings = import_epub(out, asset_store2)

    imported_table = next(iter(imported_doc.chapters.values())).paragraphs[0]
    assert isinstance(imported_table, Table)
    assert len(imported_table.rows[0].cells) == 1
    assert imported_table.rows[0].cells[0].colspan == 2
    assert imported_table.rows[0].cells[0].paragraphs[0].plain_text() == "Fusion horizontale"
    assert len(imported_table.rows[1].cells) == 2
    assert imported_table.rows[1].cells[0].rowspan == 2
    assert imported_table.rows[1].cells[0].paragraphs[0].plain_text() == "Fusion verticale"
    assert imported_table.rows[1].cells[1].paragraphs[0].plain_text() == "Normale"
    assert len(imported_table.rows[2].cells) == 1
    assert imported_table.rows[2].cells[0].paragraphs[0].plain_text() == "Autre"


# --- 7. Non-régression des sites défensifs ---

def _document_with_table_between_paragraphs(image_asset_id: str | None = None) -> Document:
    document = Document()
    cell_paragraphs = [Paragraph(runs=[Run(text="Cellule", fmt=CharFormat())])]
    if image_asset_id is not None:
        cell_paragraphs.append(Paragraph(image=ImageAnchor(asset_id=image_asset_id, alt_text="")))
    table = Table(rows=[TableRow(cells=[TableCell(paragraphs=cell_paragraphs)])])
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="avant", fmt=CharFormat(font_name="Arial"))]),
        table,
        Paragraph(runs=[Run(text="après", fmt=CharFormat(font_name="Georgia"))]),
    ]
    document.chapters[chapter.id] = chapter
    document.structure.append_free_chapter(chapter.id)
    return document


def test_font_scan_counts_fonts_inside_table_cells():
    document = _document_with_table_between_paragraphs()
    document.chapters[next(iter(document.chapters))].paragraphs[1].rows[0].cells[0].paragraphs.append(
        Paragraph(runs=[Run(text="cell text", fmt=CharFormat(font_name="Cellule Font"))])
    )
    counts = scan_fonts_in_document(document)
    assert counts["Cellule Font"] == 1
    assert counts["Arial"] == 1
    assert counts["Georgia"] == 1


def test_accessibility_metadata_counts_images_inside_table_cells():
    document = _document_with_table_between_paragraphs(image_asset_id="asset-1")
    metadata = build_accessibility_metadata(document)
    modes = [v for k, v in metadata if k == "schema:accessMode"]
    assert "visual" in modes


def test_image_alt_text_candidates_finds_images_inside_table_cells():
    document = _document_with_table_between_paragraphs(image_asset_id="asset-1")
    chapter = next(iter(document.chapters.values()))
    table = chapter.paragraphs[1]
    table.rows[0].cells[0].paragraphs[-1].image.alt_text = "Une description"
    candidates = document.image_alt_text_candidates("asset-1")
    assert candidates == ["Une description"]


def test_remove_page_break_ignores_table_block_at_index():
    from controller import ProjectController

    controller = ProjectController()
    document = _document_with_table_between_paragraphs()
    controller.project.document = document
    chapter_id = next(iter(document.chapters))

    controller.remove_page_break(chapter_id, 1)  # index 1 == la Table

    table = document.chapters[chapter_id].paragraphs[1]
    assert isinstance(table, Table)  # ne lève pas, ne modifie rien


def test_split_chapter_into_segments_treats_table_as_no_page_break():
    document = _document_with_table_between_paragraphs()
    chapter = next(iter(document.chapters.values()))
    chapter.paragraphs[1].rows  # la Table est bien à l'index 1, pas de page_break_before
    segments = split_chapter_into_segments(chapter.paragraphs)
    assert len(segments) == 1
    assert segments[0] == chapter.paragraphs


def test_chapter_split_dialog_shows_table_placeholder(qapp):
    from ui.chapter_split_dialog import ChapterSplitDialog

    document = _document_with_table_between_paragraphs()
    chapter = next(iter(document.chapters.values()))
    dialog = ChapterSplitDialog(chapter)

    assert dialog.list_widget.item(1).text() == "1. [Tableau]"


def test_epub_builder_embeds_images_inside_table_cells(tmp_path):
    project = ProjectMeta()
    asset_store = AssetStore(tmp_path / "assets")
    asset = asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fake-jpeg", "cell.jpg", AssetRole.CHAPTER_POV)

    document = _document_with_table_between_paragraphs(image_asset_id=asset.id)
    project.document = document
    part = Part.create(title="Partie I")
    part.chapter_ids = list(document.chapters.keys())
    project.document.structure.items = [part]

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "EPUB/images/cell.jpg" in names


def test_import_epub_resolves_image_href_inside_table_cells(tmp_path):
    project = ProjectMeta()
    asset_store = AssetStore(tmp_path / "assets_src")
    asset = asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fake-jpeg", "cell.jpg", AssetRole.CHAPTER_POV)

    document = _document_with_table_between_paragraphs(image_asset_id=asset.id)
    project.document = document
    part = Part.create(title="Partie I")
    part.chapter_ids = list(document.chapters.keys())
    project.document.structure.items = [part]

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))

    asset_store2 = AssetStore(tmp_path / "assets_import")
    imported_doc, _imported_metadata, _warnings = import_epub(out, asset_store2)

    imported_table = next(iter(imported_doc.chapters.values())).paragraphs[1]
    images = [p.image for p in iter_all_paragraphs([imported_table]) if p.image is not None]
    assert len(images) == 1


def test_serialization_round_trip_preserves_table_with_merged_cells():
    document = _document_with_table_between_paragraphs()
    chapter = next(iter(document.chapters.values()))
    table = chapter.paragraphs[1]
    table.rows[0].cells[0].colspan = 2
    table.rows[0].cells[0].is_header = True

    d = document_to_dict(document)
    reloaded = document_from_dict(d)

    reloaded_chapter = next(iter(reloaded.chapters.values()))
    reloaded_table = reloaded_chapter.paragraphs[1]
    assert isinstance(reloaded_table, Table)
    assert reloaded_table.rows[0].cells[0].colspan == 2
    assert reloaded_table.rows[0].cells[0].is_header is True
    assert reloaded_table.rows[0].cells[0].paragraphs[0].plain_text() == "Cellule"


def test_document_from_dict_backward_compatible_without_type_key():
    """Un projet sauvegardé avant ce chantier n'a que des dicts de paragraphe sans clé "type" —
    doit toujours se charger sans erreur, en les traitant comme des Paragraph normaux."""
    old_format_dict = {
        "chapters": {
            "ch1": {
                "id": "ch1",
                "title": "Chapitre",
                "paragraphs": [
                    {
                        "kind": "BODY",
                        "align": "LEFT",
                        "list_level": 0,
                        "list_group_id": None,
                        "runs": [{"text": "ancien paragraphe", "fmt": {
                            "bold": False, "italic": False, "underline": False,
                            "strikethrough": False, "vertical_align": "NORMAL", "font_name": None,
                        }, "link_url": None}],
                        "image": None,
                        "page_break_before": False,
                    }
                ],
            }
        },
        "structure": {"items": [{"type": "chapter", "chapter_id": "ch1"}]},
        "locked_fonts": [],
        "cover_asset_id": None,
        "back_cover_asset_id": None,
        "image_display_sizes": {},
        "image_alt_texts": {},
    }

    reloaded = document_from_dict(old_format_dict)
    para = reloaded.chapters["ch1"].paragraphs[0]
    assert isinstance(para, Paragraph)
    assert para.plain_text() == "ancien paragraphe"
