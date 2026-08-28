import zipfile
from pathlib import Path

from model.assets import AssetStore
from odt.chapter_detector import split_into_chapters
from odt.font_scanner import scan_fonts
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver

CONTENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0">
  <office:automatic-styles>
    <style:style style:name="FixedFontPara" style:family="paragraph">
      <style:text-properties style:font-name="JMH Typewriter"/>
    </style:style>
    <style:style style:name="Bold" style:family="text">
      <style:text-properties fo:font-weight="bold"/>
    </style:style>
    <style:style style:name="BoldOverride" style:family="text">
      <style:text-properties fo:font-weight="bold" style:font-name="OverrideFont"/>
    </style:style>
    <style:style style:name="Italic" style:family="text">
      <style:text-properties fo:font-style="italic"/>
    </style:style>
  </office:automatic-styles>
  <office:body>
    <office:text>
      <text:p text:style-name="FixedFontPara">Texte normal <text:span text:style-name="Bold">mot en gras</text:span> suite.</text:p>
      <text:p text:style-name="FixedFontPara">Texte <text:span text:style-name="BoldOverride">mot surchargé</text:span> suite.</text:p>
      <text:p text:style-name="FixedFontPara">Texte <text:span text:style-name="Bold"><text:span text:style-name="Italic">gras et italique imbriqué</text:span></text:span> suite.</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

STYLES_XML = """<?xml version="1.0"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"/>
"""

MANIFEST_XML = ('<?xml version="1.0"?>'
                 '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>')


def _make_fixture(tmp_path: Path) -> Path:
    fixture_path = tmp_path / "char_style_inheritance.odt"
    with zipfile.ZipFile(fixture_path, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        zf.writestr("content.xml", CONTENT_XML)
        zf.writestr("styles.xml", STYLES_XML)
        zf.writestr("META-INF/manifest.xml", MANIFEST_XML)
    return fixture_path


def _load(tmp_path):
    fixture = _make_fixture(tmp_path)
    asset_store = AssetStore(tmp_path / "assets")
    source = OdtSource(fixture)
    resolver = StyleResolver(source)
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)
    return source, resolver, chapters


def test_span_without_own_font_inherits_paragraph_font_name(tmp_path):
    """Régression : un <text:span> stylé "Bold" (fo:font-weight seul, pas de font-name propre)
    perdait entièrement le font_name du paragraphe englobant (devenait None), alors que Writer
    l'affiche visuellement avec la police du paragraphe (JMH Typewriter)."""
    _, _, chapters = _load(tmp_path)
    runs = chapters[0].paragraphs[0].runs
    bold_runs = [r for r in runs if r.fmt.bold]
    assert len(bold_runs) == 1
    assert bold_runs[0].text == "mot en gras"
    assert bold_runs[0].fmt.font_name == "JMH Typewriter"


def test_span_with_own_font_name_overrides_paragraph_font(tmp_path):
    """Non-régression : un span qui redéfinit explicitement font-name doit garder SA police,
    pas celle du paragraphe englobant."""
    _, _, chapters = _load(tmp_path)
    runs = chapters[0].paragraphs[1].runs
    override_runs = [r for r in runs if r.fmt.bold]
    assert len(override_runs) == 1
    assert override_runs[0].text == "mot surchargé"
    assert override_runs[0].fmt.font_name == "OverrideFont"


def test_nested_span_inherits_through_two_levels(tmp_path):
    """Un span dans un span (Bold > Italic) doit hériter le font_name du paragraphe à travers
    les deux niveaux d'imbrication, tout en cumulant bold ET italic."""
    _, _, chapters = _load(tmp_path)
    runs = chapters[0].paragraphs[2].runs
    nested_runs = [r for r in runs if r.fmt.bold and r.fmt.italic]
    assert len(nested_runs) == 1
    assert nested_runs[0].text == "gras et italique imbriqué"
    assert nested_runs[0].fmt.font_name == "JMH Typewriter"


def test_scan_fonts_counts_inherited_font_on_span_without_own_font(tmp_path):
    """scan_fonts ne doit pas sous-compter : le span sans font_name propre doit compter pour
    la police du paragraphe englobant (JMH Typewriter), tout comme le texte simple du même
    paragraphe."""
    source, resolver, _ = _load(tmp_path)
    counts = scan_fonts(source, resolver)
    assert counts["JMH Typewriter"] >= 5
    assert counts["OverrideFont"] >= 1
