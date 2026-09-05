from pathlib import Path

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox

from model.document import Chapter
from model.project import SourceOdtFile
from model.recent_files import (
    add_recent_file,
    add_recent_project,
    get_last_project_dir,
    list_recent_files,
    list_recent_projects,
    set_last_project_dir,
)
from ui.main_window import MainWindow
from ui.reimport_choice_dialog import ReimportChoice, ReimportChoiceDialog


def test_confirm_discard_unsaved_true_when_nothing_to_lose(qapp):
    window = MainWindow()
    assert window._confirm_discard_unsaved() is True


def _click_unsaved_dialog_button(monkeypatch, label: str) -> None:
    """Simule un clic sur le bouton `label` ("Enregistrer" / "Ne pas enregistrer" / "Annuler")
    du QMessageBox à 3 boutons construit par _confirm_discard_unsaved."""
    monkeypatch.setattr(QMessageBox, "exec", lambda self: None)
    monkeypatch.setattr(
        QMessageBox,
        "clickedButton",
        lambda self: next(b for b in self.buttons() if b.text() == label),
    )


def test_confirm_discard_unsaved_prompts_and_respects_cancel(qapp, monkeypatch):
    window = MainWindow()
    window.controller.project.document.add_chapter(Chapter.create(title="Un chapitre"))
    window.controller._dirty = True
    assert window.controller.has_unsaved_content()

    _click_unsaved_dialog_button(monkeypatch, "Annuler")
    assert window._confirm_discard_unsaved() is False


def test_confirm_discard_unsaved_prompts_and_respects_discard(qapp, monkeypatch):
    window = MainWindow()
    window.controller.project.document.add_chapter(Chapter.create(title="Un chapitre"))
    window.controller._dirty = True

    _click_unsaved_dialog_button(monkeypatch, "Ne pas enregistrer")
    assert window._confirm_discard_unsaved() is True


def test_confirm_discard_unsaved_save_button_saves_and_continues(qapp, monkeypatch, tmp_path):
    window = MainWindow()
    window.controller.project.document.add_chapter(Chapter.create(title="Un chapitre"))
    window.controller._dirty = True
    epbz_path = tmp_path / "projet.epbz"
    window.controller.project.epbz_path = epbz_path

    _click_unsaved_dialog_button(monkeypatch, "Enregistrer")
    monkeypatch.setattr(window.controller, "save_project", lambda: True)

    assert window._confirm_discard_unsaved() is True


def test_close_event_ignored_when_unsaved_and_cancelled(qapp, monkeypatch):
    window = MainWindow()
    window.controller.project.document.add_chapter(Chapter.create(title="Un chapitre"))
    window.controller._dirty = True

    _click_unsaved_dialog_button(monkeypatch, "Annuler")
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted() is False


def test_close_event_accepted_when_nothing_unsaved(qapp):
    window = MainWindow()
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted() is True


def test_open_project_guard_blocks_load_when_cancelled(qapp, monkeypatch, tmp_path):
    window = MainWindow()
    original_chapter = Chapter.create(title="Chapitre existant")
    window.controller.project.document.add_chapter(original_chapter)
    window.controller._dirty = True

    _click_unsaved_dialog_button(monkeypatch, "Annuler")

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


def test_default_epbz_dir_uses_last_project_dir_when_available(qapp, monkeypatch, tmp_path):
    window = MainWindow()
    last_dir = tmp_path / "MesProjets"
    last_dir.mkdir()
    set_last_project_dir(last_dir)

    result = window._default_epbz_dir()

    assert result == last_dir


def test_default_epbz_dir_falls_back_when_last_project_dir_missing(qapp, monkeypatch, tmp_path):
    window = MainWindow()
    missing_dir = tmp_path / "Disparu"
    set_last_project_dir(missing_dir)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    result = window._default_epbz_dir()

    assert result == tmp_path / "Documents" / "Epubeur"


def test_save_project_as_remembers_chosen_directory(qapp, monkeypatch, tmp_path):
    window = MainWindow()
    chosen_dir = tmp_path / "SonDossier"
    chosen_dir.mkdir()
    epbz_path = chosen_dir / "projet.epbz"

    monkeypatch.setattr(
        "ui.main_window.QFileDialog.getSaveFileName", lambda *a, **k: (str(epbz_path), ""))
    monkeypatch.setattr(window.controller, "save_project_as", lambda p: True)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    window._save_project_as()

    assert get_last_project_dir() == chosen_dir


def test_open_project_remembers_chosen_directory(qapp, monkeypatch, tmp_path):
    window = MainWindow()
    chosen_dir = tmp_path / "SonAutreDossier"
    chosen_dir.mkdir()
    epbz_path = chosen_dir / "projet.epbz"

    monkeypatch.setattr(
        "ui.main_window.QFileDialog.getOpenFileName", lambda *a, **k: (str(epbz_path), ""))
    load_calls = []
    monkeypatch.setattr(window.controller, "load_project_from", lambda p: load_calls.append(p))

    window._open_project()

    assert get_last_project_dir() == chosen_dir
    assert load_calls == [epbz_path]


def test_open_recent_project_guard_blocks_load_when_cancelled(qapp, monkeypatch, tmp_path):
    window = MainWindow()
    original_chapter = Chapter.create(title="Chapitre existant")
    window.controller.project.document.add_chapter(original_chapter)
    window.controller._dirty = True
    epbz_path = tmp_path / "recent.epbz"
    epbz_path.write_bytes(b"fake zip")

    _click_unsaved_dialog_button(monkeypatch, "Annuler")
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

    clear_projects_action = window.recent_projects_menu.actions()[-1]
    assert clear_projects_action.text() == "Vider la liste"
    assert not clear_projects_action.isEnabled()
    clear_files_action = window.recent_files_menu.actions()[-1]
    assert clear_files_action.text() == "Vider la liste"
    assert not clear_files_action.isEnabled()


def test_clear_recent_menu_action_enabled_when_lists_not_empty(qapp, tmp_path):
    project_path = tmp_path / "roman.epbz"
    project_path.write_bytes(b"fake")
    add_recent_project(project_path)
    epub_path = tmp_path / "roman.epub"
    epub_path.write_bytes(b"fake")
    add_recent_file(epub_path, kind="generated")

    window = MainWindow()

    assert window.recent_projects_menu.actions()[-1].isEnabled()
    assert window.recent_files_menu.actions()[-1].isEnabled()


def test_clear_recent_projects_confirmed_empties_list(qapp, monkeypatch, tmp_path):
    project_path = tmp_path / "roman.epbz"
    project_path.write_bytes(b"fake")
    add_recent_project(project_path)
    window = MainWindow()

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window._clear_recent_projects()

    assert list_recent_projects() == []
    assert project_path.exists()
    assert window.recent_projects_menu.actions()[0].text() == "(Aucun projet récent)"


def test_clear_recent_projects_cancelled_keeps_list(qapp, monkeypatch, tmp_path):
    project_path = tmp_path / "roman.epbz"
    project_path.write_bytes(b"fake")
    add_recent_project(project_path)
    window = MainWindow()

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    window._clear_recent_projects()

    assert len(list_recent_projects()) == 1


def test_clear_recent_files_confirmed_empties_list(qapp, monkeypatch, tmp_path):
    epub_path = tmp_path / "roman.epub"
    epub_path.write_bytes(b"fake")
    add_recent_file(epub_path, kind="generated")
    window = MainWindow()

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window._clear_recent_files()

    assert list_recent_files() == []
    assert epub_path.exists()
    assert window.recent_files_menu.actions()[0].text() == "(Aucun fichier récent)"
