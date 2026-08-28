import zipfile
from pathlib import Path

from model.assets import AssetStore
from odt.chapter_detector import split_into_chapters
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver

NS_ATTRS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"'
)

CONTENT_WITH_DESC = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>
        <draw:frame draw:name="Image1">
          <draw:image xlink:href="Pictures/perso1.png"/>
          <svg:desc>Un gobelin brandissant une épée</svg:desc>
        </draw:frame>
      </text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

CONTENT_WITHOUT_DESC = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>
        <draw:frame draw:name="Image1">
          <draw:image xlink:href="Pictures/perso1.png"/>
        </draw:frame>
      </text:p>
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


def _make_fixture(tmp_path: Path, content_xml: str) -> Path:
    fixture_path = tmp_path / "fixture.odt"
    with zipfile.ZipFile(fixture_path, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        zf.writestr("content.xml", content_xml)
        zf.writestr("styles.xml", STYLES_XML)
        zf.writestr("META-INF/manifest.xml", MANIFEST_XML)
        zf.writestr("Pictures/perso1.png", b"\x89PNG\r\n\x1a\n fake png data")
    return fixture_path


def _split(tmp_path: Path, content_xml: str):
    fixture = _make_fixture(tmp_path, content_xml)
    asset_store = AssetStore(tmp_path / "assets")
    source = OdtSource(fixture)
    resolver = StyleResolver(source)
    return split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)


def test_svg_desc_is_read_as_alt_text(tmp_path):
    chapters = _split(tmp_path, CONTENT_WITH_DESC)
    image_para = next(p for p in chapters[0].paragraphs if p.image is not None)

    assert image_para.image.alt_text == "Un gobelin brandissant une épée"


def test_missing_svg_desc_leaves_alt_text_empty(tmp_path):
    chapters = _split(tmp_path, CONTENT_WITHOUT_DESC)
    image_para = next(p for p in chapters[0].paragraphs if p.image is not None)

    assert image_para.image.alt_text == ""


def test_import_odt_backfills_image_alt_texts_from_svg_desc(tmp_path, qapp):
    from controller import ProjectController

    fixture = _make_fixture(tmp_path, CONTENT_WITH_DESC)
    controller = ProjectController()
    controller.import_odt(fixture)

    asset_id = next(iter(controller.asset_store.all_assets())).id
    assert controller.project.document.image_alt_texts[asset_id] == "Un gobelin brandissant une épée"


def test_import_odt_without_svg_desc_leaves_image_alt_texts_empty(tmp_path, qapp):
    from controller import ProjectController

    fixture = _make_fixture(tmp_path, CONTENT_WITHOUT_DESC)
    controller = ProjectController()
    controller.import_odt(fixture)

    asset_id = next(iter(controller.asset_store.all_assets())).id
    assert asset_id not in controller.project.document.image_alt_texts


def test_manual_alt_text_takes_priority_over_svg_desc_in_rendered_html(tmp_path, qapp):
    from controller import ProjectController
    from epub.builder import build_epub
    from model.book_metadata import BookMetadata
    import zipfile

    fixture = _make_fixture(tmp_path, CONTENT_WITH_DESC)
    controller = ProjectController()
    controller.import_odt(fixture)

    asset_id = next(iter(controller.asset_store.all_assets())).id
    controller.set_image_alt_text(asset_id, "Description manuelle")

    out = build_epub(controller.project, controller.asset_store, tmp_path / "out.epub",
                      metadata=BookMetadata(title="Test"))
    with zipfile.ZipFile(out) as zf:
        xhtml_name = [n for n in zf.namelist() if "chapter_0" in n][0]
        xhtml = zf.read(xhtml_name).decode()

    assert 'alt="Description manuelle"' in xhtml
    assert "Un gobelin brandissant une épée" not in xhtml


def test_image_alt_text_candidates_deduplicates_and_preserves_order():
    from model.document import Chapter, Document, ImageAnchor, Paragraph

    document = Document()
    chapter_a = Chapter.create(title="A")
    chapter_a.paragraphs = [Paragraph(image=ImageAnchor(asset_id="x", alt_text="Premier"))]
    chapter_b = Chapter.create(title="B")
    chapter_b.paragraphs = [
        Paragraph(image=ImageAnchor(asset_id="x", alt_text="Premier")),  # doublon, ignoré
        Paragraph(image=ImageAnchor(asset_id="x", alt_text="Second")),
    ]
    document.chapters[chapter_a.id] = chapter_a
    document.chapters[chapter_b.id] = chapter_b

    assert document.image_alt_text_candidates("x") == ["Premier", "Second"]


def test_image_alt_text_candidates_ignores_empty_and_other_assets():
    from model.document import Chapter, Document, ImageAnchor, Paragraph

    document = Document()
    chapter = Chapter.create(title="A")
    chapter.paragraphs = [
        Paragraph(image=ImageAnchor(asset_id="x", alt_text="")),
        Paragraph(image=ImageAnchor(asset_id="y", alt_text="Autre image")),
        Paragraph(image=ImageAnchor(asset_id="x", alt_text="Description x")),
    ]
    document.chapters[chapter.id] = chapter

    assert document.image_alt_text_candidates("x") == ["Description x"]
