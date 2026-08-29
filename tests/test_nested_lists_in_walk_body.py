import zipfile
from pathlib import Path

from model.assets import AssetStore
from model.styles import ParagraphKind
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

# Style à deux niveaux : puces au niveau 1, numéros au niveau 2 — même style que
# tests/test_nested_lists.py::MULTI_LEVEL_STYLE_CONTENT_XML, réutilisé ici imbriqué dans une
# note de bas de page, une cellule de tableau et une zone de texte (les trois entrées de
# _walk_body) plutôt que dans le flux principal du document (collect(), déjà correct).
MULTI_LEVEL_LIST_STYLE_XML = """
    <text:list-style style:name="L2">
      <text:list-level-style-bullet text:level="1" text:bullet-char="-"/>
      <text:list-level-style-number text:level="2"/>
    </text:list-style>
"""

NESTED_LIST_IN_NOTE_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:automatic-styles>{MULTI_LEVEL_LIST_STYLE_XML}</office:automatic-styles>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>Texte<text:note text:id="ftn1" text:note-class="footnote">
        <text:note-citation>1</text:note-citation>
        <text:note-body>
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
        </text:note-body>
      </text:note></text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

NESTED_LIST_IN_TABLE_CELL_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:automatic-styles>{MULTI_LEVEL_LIST_STYLE_XML}</office:automatic-styles>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <table:table>
        <table:table-row>
          <table:table-cell>
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


def _split(tmp_path: Path, content_xml: str, name: str = "fixture.odt", **kwargs):
    fixture = _make_fixture(tmp_path, content_xml, name)
    asset_store = AssetStore(tmp_path / f"assets_{name}")
    source = OdtSource(fixture)
    resolver = StyleResolver(source)
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store, **kwargs)
    return chapters, kwargs.get("document_footnotes")


def test_nested_list_in_footnote_resolves_correct_kind_per_level(tmp_path):
    """Régression : _walk_body (corps de note, cellule de tableau, zone de texte) n'incrémentait
    jamais `level` lors de la récursion sur une sous-liste imbriquée, contrairement à collect()
    (flux principal) qui le fait correctement — une sous-liste numérotée dans une note pouvait
    donc être rendue à puces (résolution systématique du niveau 1 du style, quel que soit le
    niveau réel de la sous-liste)."""
    footnotes: dict = {}
    fixture = _make_fixture(tmp_path, NESTED_LIST_IN_NOTE_CONTENT_XML)
    asset_store = AssetStore(tmp_path / "assets")
    source = OdtSource(fixture)
    resolver = StyleResolver(source)
    split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store,
                         document_footnotes=footnotes)

    note_id = next(iter(footnotes))
    body = footnotes[note_id]
    assert len(body) == 2
    assert body[0].plain_text() == "Item1"
    assert body[0].kind == ParagraphKind.LIST_ITEM_BULLET  # niveau 1 : puce
    assert body[0].list_level == 1
    assert body[1].plain_text() == "Item1.1"
    assert body[1].kind == ParagraphKind.LIST_ITEM_NUMBER  # niveau 2 : numéroté
    assert body[1].list_level == 2


def test_nested_list_in_table_cell_resolves_correct_kind_per_level(tmp_path):
    """Même régression que la note, mais pour une cellule de tableau (l'autre entrée de
    _walk_body en dehors du flux principal du document)."""
    chapters, _ = _split(tmp_path, NESTED_LIST_IN_TABLE_CELL_CONTENT_XML)
    table = chapters[0].paragraphs[0]
    cell_paragraphs = table.rows[0].cells[0].paragraphs

    assert len(cell_paragraphs) == 2
    assert cell_paragraphs[0].plain_text() == "Item1"
    assert cell_paragraphs[0].kind == ParagraphKind.LIST_ITEM_BULLET
    assert cell_paragraphs[0].list_level == 1
    assert cell_paragraphs[1].plain_text() == "Item1.1"
    assert cell_paragraphs[1].kind == ParagraphKind.LIST_ITEM_NUMBER
    assert cell_paragraphs[1].list_level == 2
