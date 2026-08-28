from pathlib import Path

from controller import ProjectController
from model.book_metadata import BookMetadata
from ui.epub_preview import EpubPreview
from ui.generate_panel import GeneratePanel


def test_preview_starts_with_empty_message(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)
    preview = EpubPreview(controller, panel.collect_metadata)

    assert preview.content_stack.currentWidget() is preview.empty_label


def test_preview_switches_to_reader_after_load_epub(qapp, tmp_path):
    controller = ProjectController()
    controller.import_odt(Path(__file__).parent / "fixtures" / "sample_simple.odt")
    panel = GeneratePanel(controller)
    preview = EpubPreview(controller, panel.collect_metadata)

    from epub.builder import build_epub
    out = build_epub(controller.project, controller.asset_store, tmp_path / "out.epub",
                      metadata=BookMetadata(title="Mon Roman"))

    preview.load_epub(str(out))

    assert preview.content_stack.currentWidget() is preview.reader


def test_preview_reset_returns_to_empty_message(qapp, tmp_path):
    controller = ProjectController()
    controller.import_odt(Path(__file__).parent / "fixtures" / "sample_simple.odt")
    panel = GeneratePanel(controller)
    preview = EpubPreview(controller, panel.collect_metadata)

    from epub.builder import build_epub
    out = build_epub(controller.project, controller.asset_store, tmp_path / "out.epub",
                      metadata=BookMetadata(title="Mon Roman"))
    preview.load_epub(str(out))

    preview.reset()

    assert preview.content_stack.currentWidget() is preview.empty_label
    assert preview.chapter_combo.count() == 0


def test_preview_has_generate_controls(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)
    preview = EpubPreview(controller, panel.collect_metadata)

    assert preview.generate_controls is not None
