import zipfile
from pathlib import Path

from model.assets import AssetStore
from model.document import Table
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

# Régression : Writer place fréquemment du texte dans des <text:section> (colonnes, zones liées,
# encadrés) — un document réel constaté avec 229 sections contenant la quasi-totalité du texte du
# livre voyait tout ce contenu disparaître silencieusement à l'import (seuls les paragraphes hors
# section, ex. page de garde/crédits, survivaient), sans aucune erreur ni avertissement.
SECTION_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>Avant section.</text:p>
      <text:section text:name="Section1">
        <text:p>Premier paragraphe de la section.</text:p>
        <text:p>Second paragraphe de la section.</text:p>
      </text:section>
      <text:p>Après section.</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

NESTED_SECTION_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:section text:name="Outer">
        <text:p>Texte externe.</text:p>
        <text:section text:name="Inner">
          <text:p>Texte interne.</text:p>
        </text:section>
      </text:section>
    </office:text>
  </office:body>
</office:document-content>
"""

SECTION_WITH_TABLE_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:section text:name="Section1">
        <table:table>
          <table:table-row>
            <table:table-cell><text:p>Cellule</text:p></table:table-cell>
          </table:table-row>
        </table:table>
      </text:section>
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


def test_text_inside_section_is_not_lost(tmp_path):
    chapters = _split(tmp_path, SECTION_CONTENT_XML)
    texts = [p.plain_text() for p in chapters[0].paragraphs]

    assert texts == ["Avant section.", "Premier paragraphe de la section.",
                      "Second paragraphe de la section.", "Après section."]


def test_nested_sections_are_both_traversed(tmp_path):
    chapters = _split(tmp_path, NESTED_SECTION_CONTENT_XML)
    texts = [p.plain_text() for p in chapters[0].paragraphs]

    assert texts == ["Texte externe.", "Texte interne."]


def test_table_inside_section_is_still_detected_as_table(tmp_path):
    chapters = _split(tmp_path, SECTION_WITH_TABLE_CONTENT_XML)
    paragraphs = chapters[0].paragraphs

    assert len(paragraphs) == 1
    assert isinstance(paragraphs[0], Table)
    assert paragraphs[0].rows[0].cells[0].paragraphs[0].plain_text() == "Cellule"
