from pathlib import Path

from model.assets import AssetStore
from model.styles import ParagraphAlign, ParagraphKind, VerticalAlign
from odt.chapter_detector import split_into_chapters
from odt.font_scanner import scan_fonts
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver

FIXTURE = Path(__file__).parent / "fixtures" / "sample_simple.odt"


def _load(tmp_path):
    source = OdtSource(FIXTURE)
    resolver = StyleResolver(source)
    asset_store = AssetStore(tmp_path / "assets")
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)
    return source, resolver, chapters, asset_store


def test_splits_into_two_chapters(tmp_path):
    _, _, chapters, _ = _load(tmp_path)
    assert len(chapters) == 2
    assert chapters[0].title == "Chapitre un"
    assert chapters[1].title == "Chapitre deux"


def test_bold_and_italic_runs_detected(tmp_path):
    _, _, chapters, _ = _load(tmp_path)
    first_chapter = chapters[0]
    runs = first_chapter.paragraphs[0].runs
    bold_runs = [r for r in runs if r.fmt.bold]
    italic_runs = [r for r in runs if r.fmt.italic]
    assert any("gras" in r.text for r in bold_runs)
    assert any("italique" in r.text for r in italic_runs)


def test_paragraph_alignment_center(tmp_path):
    _, _, chapters, _ = _load(tmp_path)
    centered = [p for p in chapters[0].paragraphs if p.align == ParagraphAlign.CENTER]
    assert len(centered) == 1
    assert "centré" in centered[0].plain_text()


def test_quote_paragraph_detected(tmp_path):
    _, _, chapters, _ = _load(tmp_path)
    quotes = [p for p in chapters[0].paragraphs if p.kind == ParagraphKind.QUOTE]
    assert len(quotes) == 1
    assert "mémorable" in quotes[0].plain_text()


def test_list_items_detected(tmp_path):
    _, _, chapters, _ = _load(tmp_path)
    list_items = [p for p in chapters[0].paragraphs if p.kind == ParagraphKind.LIST_ITEM_BULLET]
    assert len(list_items) == 2
    assert list_items[0].plain_text() == "Premier élément de liste"


def test_narrative_font_detected_on_run(tmp_path):
    _, _, chapters, _ = _load(tmp_path)
    all_runs = [r for p in chapters[0].paragraphs for r in p.runs]
    narrative_runs = [r for r in all_runs if r.fmt.font_name == "SpecialNarrative"]
    assert any("murmure spectral" in r.text for r in narrative_runs)


def test_image_deduplicated_across_chapters(tmp_path):
    _, _, chapters, asset_store = _load(tmp_path)
    assert chapters[0].pov_image_asset_id is not None
    assert chapters[0].pov_image_asset_id == chapters[1].pov_image_asset_id
    assert len(asset_store.all_assets()) == 1


def test_font_scanner_counts_occurrences(tmp_path):
    source, resolver, _, _ = _load(tmp_path)
    counts = scan_fonts(source, resolver)
    assert counts["SpecialNarrative"] >= 1
