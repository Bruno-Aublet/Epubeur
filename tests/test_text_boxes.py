import zipfile
from pathlib import Path

from model.assets import AssetStore
from odt.chapter_detector import split_into_chapters
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver

MANIFEST_XML = ('<?xml version="1.0"?>'
                 '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>')

NS_ATTRS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"'
)

STYLES_XML = """<?xml version="1.0"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0">
  <office:styles>
    <style:style style:name="Heading_20_1" style:display-name="Heading 1" style:family="paragraph"/>
  </office:styles>
</office:document-styles>
"""

# Régression : une zone de texte Writer (Insertion > Zone de texte) est un <draw:frame> contenant
# un <draw:text-box>, PAS une <draw:image> — ni _find_image (aucune image trouvée, href=None) ni
# aucune autre branche ne reconnaissaient ce cas : le texte de la zone disparaissait silencieusement,
# même mécanisme que le bug déjà corrigé pour text:section.
TEXT_BOX_ANCHORED_TO_PAGE_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>Avant.</text:p>
      <draw:frame>
        <draw:text-box>
          <text:p>Premier paragraphe de la zone de texte.</text:p>
          <text:p>Second paragraphe.</text:p>
        </draw:text-box>
      </draw:frame>
      <text:p>Après.</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

TEXT_BOX_ANCHORED_INLINE_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>Avant<draw:frame><draw:text-box><text:p>Texte encadré</text:p></draw:text-box></draw:frame>Après.</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

IMAGE_FRAME_UNAFFECTED_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}
    xmlns:xlink="http://www.w3.org/1999/xlink">
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <draw:frame>
        <draw:image xlink:href="Pictures/img.png"/>
      </draw:frame>
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
        zf.writestr("Pictures/img.png", b"\x89PNG fake bytes")
    return fixture_path


def _split(tmp_path: Path, content_xml: str, name: str = "fixture.odt"):
    fixture = _make_fixture(tmp_path, content_xml, name)
    asset_store = AssetStore(tmp_path / f"assets_{name}")
    source = OdtSource(fixture)
    resolver = StyleResolver(source)
    return split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)


def test_text_box_anchored_to_page_is_not_lost(tmp_path):
    chapters = _split(tmp_path, TEXT_BOX_ANCHORED_TO_PAGE_CONTENT_XML)
    texts = [p.plain_text() for p in chapters[0].paragraphs]

    assert texts == ["Avant.", "Premier paragraphe de la zone de texte.", "Second paragraphe.",
                      "Après."]


def test_text_box_anchored_inline_is_not_lost(tmp_path):
    chapters = _split(tmp_path, TEXT_BOX_ANCHORED_INLINE_CONTENT_XML)
    texts = [p.plain_text() for p in chapters[0].paragraphs]

    assert len(texts) == 1
    assert "Texte encadré" in texts[0]
    assert texts[0].startswith("Avant")
    assert texts[0].endswith("Après.")


def test_image_frame_still_handled_normally(tmp_path):
    """Non-régression : un draw:frame contenant une vraie draw:image (pas une zone de texte)
    doit continuer à être traité comme une image, pas comme une zone de texte vide."""
    chapters = _split(tmp_path, IMAGE_FRAME_UNAFFECTED_CONTENT_XML)
    paragraphs = chapters[0].paragraphs

    assert len(paragraphs) == 1
    assert paragraphs[0].image is not None
