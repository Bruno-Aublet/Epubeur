from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from model.document import Chapter
from model.project import SourceOdtFile
from model.recent_files import add_recent_file, add_recent_project, list_recent_files
from ui.main_window import MainWindow
from ui.reimport_choice_dialog import ReimportChoice, ReimportChoiceDialog


def test_confirm_discard_unsaved_true_when_nothing_to_lose(qapp):
    window = MainWindow()
    assert window._confirm_discard_unsaved() is True


def test_confirm_discard_unsaved_prompts_and_respects_cancel(qapp, monkeypatch):
    window = MainWindow()
    window.controller.project.document.add_chapter(Chapter.create(title="Un chapitre"))
    assert window.controller.has_unsaved_content()

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    assert window._confirm_discard_unsaved() is False


def test_confirm_discard_unsaved_prompts_and_respects_yes(qapp, monkeypatch):
    window = MainWindow()
    window.controller.project.document.add_chapter(Chapter.create(title="Un chapitre"))

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    assert window._confirm_discard_unsaved() is True


def test_open_project_guard_blocks_load_when_cancelled(qapp, monkeypatch, tmp_path):
    window = MainWindow()
    original_chapter = Chapter.create(title="Chapitre existant")
    window.controller.project.document.add_chapter(original_chapter)

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)

    load_calls = []
    monkeypatch.setattr(window.controller, "load_project_from", lambda p: load_calls.append(p))

    window._open_dropped_epbz(tmp_path / "autre_projet.epbz")

    assert load_calls == []
    assert original_chapter.id in window.controller.project.document.chapters


def test_open_dropped_epbz_loads_when_no_unsaved_content(qapp, monkeypatch, tmp_path):
    window = MainWindow()

    load_calls = []
    monkeypatch.setattr(window.controller, "load_project_from", lambda p: load_calls.append(p))

    epbz_path = tmp_path / "projet.epbz"
    window._open_dropped_epbz(epbz_path)

    assert load_calls == [epbz_path]


def test_import_panel_project_dropped_routes_to_open_dropped_epbz(qapp, monkeypatch, tmp_path):
    window = MainWindow()

    load_calls = []
    monkeypatch.setattr(window.controller, "load_project_from", lambda p: load_calls.append(p))

    epbz_path = tmp_path / "projet.epbz"
    window.import_panel.project_dropped.emit(epbz_path)

    assert load_calls == [epbz_path]


def test_default_epbz_dir_creates_documents_epubeur(qapp, monkeypatch, tmp_path):
    window = MainWindow()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    result = window._default_epbz_dir()

    assert result == tmp_path / "Documents" / "Epubeur"
    assert result.is_dir()


def test_open_recent_project_guard_blocks_load_when_cancelled(qapp, monkeypatch, tmp_path):
    window = MainWindow()
    original_chapter = Chapter.create(title="Chapitre existant")
    window.controller.project.document.add_chapter(original_chapter)
    epbz_path = tmp_path / "recent.epbz"
    epbz_path.write_bytes(b"fake zip")

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    load_calls = []
    monkeypatch.setattr(window.controller, "load_project_from", lambda p: load_calls.append(p))

    window._open_recent_project(epbz_path)

    assert load_calls == []
    assert original_chapter.id in window.controller.project.document.chapters


def test_open_recent_project_missing_file_shows_error_and_removes_entry(qapp, tmp_path):
    window = MainWindow()
    missing_path = tmp_path / "disparu.epbz"
    add_recent_project(missing_path)

    errors = []
    window._show_error = lambda msg: errors.append(msg)

    window._open_recent_project(missing_path)

    assert len(errors) == 1
    assert "introuvable" in errors[0]
    from model.recent_files import list_recent_projects
    assert list_recent_projects() == []


def test_open_recent_project_loads_when_existing_and_no_unsaved_content(qapp, monkeypatch, tmp_path):
    window = MainWindow()
    epbz_path = tmp_path / "recent.epbz"
    epbz_path.write_bytes(b"fake zip")

    load_calls = []
    monkeypatch.setattr(window.controller, "load_project_from", lambda p: load_calls.append(p))

    window._open_recent_project(epbz_path)

    assert load_calls == [epbz_path]


def test_open_recent_file_missing_shows_error_and_removes_entry(qapp, tmp_path):
    window = MainWindow()
    missing_path = tmp_path / "disparu.odt"
    add_recent_file(missing_path, "imported")

    errors = []
    window._show_error = lambda msg: errors.append(msg)

    window._open_recent_file(missing_path)

    assert len(errors) == 1
    assert list_recent_files() == []


def test_open_recent_file_odt_not_in_current_project_imports_directly(qapp, monkeypatch, tmp_path):
    window = MainWindow()
    odt_path = tmp_path / "chapitre.odt"
    odt_path.write_bytes(b"fake odt")

    import_calls = []
    monkeypatch.setattr(window.controller, "import_odt", lambda p: import_calls.append(p))

    def fail_if_shown(*a, **k):
        raise AssertionError("le dialogue ne doit pas s'ouvrir pour un .odt inconnu du projet actuel")
    monkeypatch.setattr(ReimportChoiceDialog, "exec", fail_if_shown)

    window._open_recent_file(odt_path)

    assert import_calls == [odt_path]


def test_open_recent_file_odt_already_in_current_project_shows_dialog(qapp, monkeypatch, tmp_path):
    window = MainWindow()
    odt_path = tmp_path / "chapitre.odt"
    odt_path.write_bytes(b"fake odt")
    window.controller.project.source_odt_files.append(SourceOdtFile.create(odt_path, 0))

    from PySide6.QtWidgets import QDialog
    monkeypatch.setattr(ReimportChoiceDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(ReimportChoiceDialog, "result_choice", lambda self: ReimportChoice.REPLACE)

    calls = []
    monkeypatch.setattr(window.controller, "replace_odt", lambda p: calls.append(p))

    window._open_recent_file(odt_path)

    assert calls == [odt_path]


def test_open_recent_file_epub_calls_import_epub_file(qapp, monkeypatch, tmp_path):
    window = MainWindow()
    epub_path = tmp_path / "livre.epub"
    epub_path.write_bytes(b"fake epub")

    calls = []
    monkeypatch.setattr(window.controller, "import_epub_file", lambda p: calls.append(p))

    window._open_recent_file(epub_path)

    assert calls == [epub_path]


def test_on_epub_generated_adds_to_recent_files(qapp, tmp_path):
    window = MainWindow()
    output_path = tmp_path / "MonRoman.epub"

    window._on_epub_generated(str(output_path))

    entries = list_recent_files()
    assert entries[0]["path"] == str(output_path)
    assert entries[0]["kind"] == "generated"


def test_refresh_recent_menus_shows_placeholder_when_empty(qapp):
    window = MainWindow()
    window._refresh_recent_menus()

    assert window.recent_projects_menu.actions()[0].text() == "(Aucun projet récent)"
    assert not window.recent_projects_menu.actions()[0].isEnabled()
    assert window.recent_files_menu.actions()[0].text() == "(Aucun fichier récent)"
