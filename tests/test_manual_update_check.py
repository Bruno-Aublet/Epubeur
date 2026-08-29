from PySide6.QtWidgets import QMessageBox

from ui.main_window import MainWindow
from ui.update_dialog import UpdateAvailableDialog


def test_help_menu_has_update_check_action(qapp):
    window = MainWindow()
    help_menu = next(a.menu() for a in window.menuBar().actions() if a.text() == "Aide")
    action_texts = [a.text() for a in help_menu.actions()]
    assert "Vérifier les mises à jour" in action_texts


def test_manual_update_check_shows_dialog_when_update_available(qapp, monkeypatch):
    window = MainWindow()
    monkeypatch.setattr(UpdateAvailableDialog, "exec", lambda self: None)

    window._check_for_updates_manually()
    window._manual_update_checker.update_available.emit("9.9.9", "https://github.com/Bruno-Aublet/Epubeur/releases/latest")


def test_manual_update_check_shows_up_to_date_message(qapp, monkeypatch):
    window = MainWindow()
    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: calls.append(a))

    window._check_for_updates_manually()
    window._manual_update_checker.up_to_date.emit()

    assert len(calls) == 1


def test_manual_update_check_shows_failure_message(qapp, monkeypatch):
    window = MainWindow()
    calls = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: calls.append(a))

    window._check_for_updates_manually()
    window._manual_update_checker.check_failed.emit()

    assert len(calls) == 1
