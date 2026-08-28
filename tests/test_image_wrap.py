import zipfile
from pathlib import Path

import pytest

from epub.builder import build_epub
from epub.css import build_css
from epub.html_normalize import html_to_paragraphs
from epub.html_render import _paragraph_inner_html, paragraph_to_html
from epub.importer import import_epub
from model.assets import AssetStore
from model.book_metadata import BookMetadata
from model.document import Document, ImageAnchor, ImageWrap, Paragraph, Part, Run
from model.project import ProjectMeta
from model.serialization import document_from_dict, document_to_dict
from model.styles import CharFormat
from odt.chapter_detector import split_into_chapters
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver

MANIFEST_XML = ('<?xml version="1.0"?>'
                 '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>')

NS_ATTRS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"'
)


def _styles_xml(wrap_value: str | None) -> str:
    graphic_style = ""
    if wrap_value is not None:
        graphic_style = f"""
    <style:style style:name="GraphicWrap" style:family="graphic">
      <style:graphic-properties style:wrap="{wrap_value}"/>
    </style:style>"""
    return f"""<?xml version="1.0"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0">
  <office:styles>
    <style:style style:name="Heading_20_1" style:display-name="Heading 1" style:family="paragraph"/>{graphic_style}
  </office:styles>
</office:document-styles>
"""


def _content_xml(frame_style: str | None) -> str:
    style_attr = f' draw:style-name="{frame_style}"' if frame_style else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>Texte
        <draw:frame{style_attr}>
          <draw:image xlink:href="Pictures/img.png"/>
        </draw:frame>
      </text:p>
    </office:text>
  </office:body>
</office:document-content>
"""


def _make_fixture(tmp_path: Path, content_xml: str, styles_xml: str, name: str = "fixture.odt") -> Path:
    fixture_path = tmp_path / name
    with zipfile.ZipFile(fixture_path, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        zf.writestr("content.xml", content_xml)
        zf.writestr("styles.xml", styles_xml)
        zf.writestr("META-INF/manifest.xml", MANIFEST_XML)
        zf.writestr("Pictures/img.png", b"\x89PNG fake bytes")
    return fixture_path


def _split(tmp_path: Path, wrap_value: str | None, name: str = "fixture.odt"):
    frame_style = "GraphicWrap" if wrap_value is not None else None
    fixture = _make_fixture(tmp_path, _content_xml(frame_style), _styles_xml(wrap_value), name)
    asset_store = AssetStore(tmp_path / f"assets_{name}")
    source = OdtSource(fixture)
    resolver = StyleResolver(source)
    wraps: dict = {}
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store,
                                    image_wraps=wraps)
    return chapters, wraps, asset_store


# --- 1, 2, 3. Résolution style:wrap -> ImageWrap ---

def test_style_wrap_left_resolved_to_image_wrap_left(tmp_path):
    _chapters, wraps, _asset_store = _split(tmp_path, "left")
    assert list(wraps.values()) == [ImageWrap.LEFT]


def test_style_wrap_right_resolved_to_image_wrap_right(tmp_path):
    _chapters, wraps, _asset_store = _split(tmp_path, "right")
    assert list(wraps.values()) == [ImageWrap.RIGHT]


def test_style_wrap_none_resolved_to_image_wrap_none(tmp_path):
    _chapters, wraps, _asset_store = _split(tmp_path, "none")
    assert list(wraps.values()) == [ImageWrap.NONE]


def test_style_wrap_absent_resolved_to_image_wrap_none(tmp_path):
    _chapters, wraps, _asset_store = _split(tmp_path, None)
    assert list(wraps.values()) == [ImageWrap.NONE]


# --- 4. Valeurs sans équivalent CSS replient sur NONE ---

@pytest.mark.parametrize("wrap_value", ["parallel", "dynamic", "run-through", "biggest"])
def test_style_wrap_unsupported_values_fallback_to_none(tmp_path, wrap_value):
    _chapters, wraps, _asset_store = _split(tmp_path, wrap_value, name=f"fixture_{wrap_value}.odt")
    assert list(wraps.values()) == [ImageWrap.NONE]


# --- 5. Héritage via style:parent-style-name ---

def test_resolve_graphic_style_inherits_via_parent_style_name(tmp_path):
    styles_xml = """<?xml version="1.0"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0">
  <office:styles>
    <style:style style:name="GraphicParent" style:family="graphic">
      <style:graphic-properties style:wrap="left"/>
    </style:style>
    <style:style style:name="GraphicChild" style:family="graphic"
        style:parent-style-name="GraphicParent"/>
  </office:styles>
</office:document-styles>
"""
    fixture = _make_fixture(tmp_path, _content_xml(None), styles_xml)
    source = OdtSource(fixture)
    resolver = StyleResolver(source)

    resolved = resolver.resolve_graphic_style("GraphicChild")
    assert resolved.wrap == "left"


# --- 6. Rendu HTML : attribut data-epubeur-image-wrap ---

def test_html_render_emits_wrap_attribute_when_not_none():
    para = Paragraph(runs=[], image=ImageAnchor(asset_id="abc"))
    html = paragraph_to_html(para, image_wraps={"abc": ImageWrap.LEFT})
    assert 'data-epubeur-image-wrap="left"' in html


def test_html_render_omits_wrap_attribute_when_none():
    para = Paragraph(runs=[], image=ImageAnchor(asset_id="abc"))
    html = paragraph_to_html(para, image_wraps={"abc": ImageWrap.NONE})
    assert "data-epubeur-image-wrap" not in html


def test_html_render_omits_wrap_attribute_when_wraps_is_none():
    para = Paragraph(runs=[], image=ImageAnchor(asset_id="abc"))
    html = paragraph_to_html(para, image_wraps=None)
    assert "data-epubeur-image-wrap" not in html


# --- 7. CSS : marges asymétriques correctes ---

def test_css_contains_float_rules_with_correct_asymmetric_margins():
    css = build_css()
    left_start = css.index('img[data-epubeur-image-wrap="left"]')
    left_rule = css[left_start:css.index("}", left_start)]
    assert "float: left" in left_rule
    assert "margin: 0 1em 1em 0" in left_rule

    right_start = css.index('img[data-epubeur-image-wrap="right"]')
    right_rule = css[right_start:css.index("}", right_start)]
    assert "float: right" in right_rule
    assert "margin: 0 0 1em 1em" in right_rule


# --- 8. Réimport : lecture de l'attribut ---

def test_html_to_paragraphs_reads_wrap_attribute_on_reimport():
    xhtml = ('<html><body><div class="epubeur-chapter">'
             '<p><img data-epubeur-image="x" data-epubeur-image-wrap="left"/></p>'
             '</div></body></html>')
    from epub.css_resolve import CssResolver

    resolver = CssResolver([])
    _paragraphs, _footnotes, image_wraps = html_to_paragraphs(xhtml, resolver)

    assert image_wraps == {"x": ImageWrap.LEFT}


# --- 9. Round-trip complet ODT -> EPUB -> réimport ---

def test_image_wrap_roundtrip_through_epub(tmp_path):
    chapters, wraps, asset_store = _split(tmp_path, "left")

    project = ProjectMeta()
    for ch in chapters:
        project.document.chapters[ch.id] = ch
    project.document.image_wraps.update(wraps)
    part = Part.create(title="Partie I")
    part.chapter_ids = [c.id for c in chapters]
    project.document.structure.items.append(part)

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))

    asset_store2 = AssetStore(tmp_path / "assets_import")
    imported_doc, _imported_metadata, _warnings = import_epub(out, asset_store2)

    imported_chapter = next(iter(imported_doc.chapters.values()))
    image_para = next(p for p in imported_chapter.paragraphs if p.image is not None)
    assert imported_doc.image_wrap(image_para.image.asset_id) == ImageWrap.LEFT


# --- 10. Sérialisation round-trip ---

def test_serialization_round_trip_preserves_image_wraps():
    document = Document()
    document.image_wraps["asset-1"] = ImageWrap.RIGHT

    d = document_to_dict(document)
    reloaded = document_from_dict(d)

    assert reloaded.image_wrap("asset-1") == ImageWrap.RIGHT
