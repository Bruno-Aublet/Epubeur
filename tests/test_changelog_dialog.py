import sys
from pathlib import Path

from ui.changelog_dialog import ChangelogDialog, _changelog_path
from ui.main_window import MainWindow


def test_changelog_path_resolves_to_repo_root_in_dev_mode():
    path = _changelog_path()
    assert path.name == "CHANGELOG.md"
    assert path.exists()


def test_changelog_path_resolves_under_meipass_when_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", r"C:\Epubeur\_internal", raising=False)

    path = _changelog_path()

    assert path == Path(r"C:\Epubeur\_internal") / "CHANGELOG.md"


def test_changelog_dialog_shows_file_content(qapp):
    from PySide6.QtWidgets import QTextEdit

    dialog = ChangelogDialog()

    text_edits = dialog.findChildren(QTextEdit)
    assert any("Epubeur" in te.toPlainText() for te in text_edits)


def test_changelog_dialog_falls_back_when_file_missing(qapp, monkeypatch):
    from PySide6.QtWidgets import QTextEdit

    monkeypatch.setattr("ui.changelog_dialog._changelog_path", lambda: Path("C:/does/not/exist/CHANGELOG.md"))

    dialog = ChangelogDialog()

    text_edits = dialog.findChildren(QTextEdit)
    assert any("introuvable" in te.toPlainText() for te in text_edits)


def test_main_window_has_help_menu_with_changelog_action(qapp):
    window = MainWindow()
    help_menu = next(a.menu() for a in window.menuBar().actions() if a.text() == "Aide")
    action_texts = [a.text() for a in help_menu.actions()]
    assert "Historique des versions" in action_texts


def test_show_changelog_dialog_does_not_raise(qapp, monkeypatch):
    window = MainWindow()
    monkeypatch.setattr(ChangelogDialog, "exec", lambda self: None)
    window._show_changelog_dialog()  # ne doit pas lever
