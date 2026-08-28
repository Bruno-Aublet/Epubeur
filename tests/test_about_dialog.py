import sys
from pathlib import Path

from PySide6.QtWidgets import QLabel

from ui.about_dialog import AboutDialog, COPYRIGHT_NOTICE, _license_path
from ui.main_window import MainWindow


def test_license_path_resolves_to_repo_root_in_dev_mode():
    path = _license_path()
    assert path.name == "LICENSE"
    assert path.exists()


def test_license_path_resolves_next_to_exe_when_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Epubeur\Epubeur.exe")

    path = _license_path()

    assert path == Path(r"C:\Epubeur") / "LICENSE"


def test_license_file_contains_copyright_notice_and_gpl_text():
    content = _license_path().read_text(encoding="utf-8")
    assert "Copyright 2026 Bruno Aublet" in content
    assert "GNU GENERAL PUBLIC LICENSE" in content
    assert "Version 3, 29 June 2007" in content


def test_about_dialog_shows_copyright_notice(qapp):
    dialog = AboutDialog()
    texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert any(COPYRIGHT_NOTICE in text for text in texts)


def test_about_dialog_shows_version_and_license_mention(qapp):
    from model.version import __version__
    dialog = AboutDialog()
    texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert any(__version__ in text for text in texts)
    assert any("GPL" in text for text in texts)


def test_show_license_falls_back_to_gnu_url_when_file_missing(qapp, monkeypatch):
    from PySide6.QtWidgets import QDialog, QTextEdit

    monkeypatch.setattr("ui.about_dialog._license_path", lambda: Path("C:/does/not/exist/LICENSE"))
    monkeypatch.setattr(QDialog, "exec", lambda self: None)

    dialog = AboutDialog()
    dialog._show_license()

    text_edits = dialog.findChildren(QTextEdit)
    assert any("gnu.org" in te.toPlainText() for te in text_edits)


def test_show_license_displays_full_text_when_file_present(qapp, monkeypatch):
    from PySide6.QtWidgets import QDialog, QTextEdit

    monkeypatch.setattr(QDialog, "exec", lambda self: None)

    dialog = AboutDialog()
    dialog._show_license()

    text_edits = dialog.findChildren(QTextEdit)
    assert any("GNU GENERAL PUBLIC LICENSE" in te.toPlainText() for te in text_edits)


def test_main_window_has_help_menu_with_about_action(qapp):
    window = MainWindow()
    menu_bar = window.menuBar()
    menu_titles = [action.text() for action in menu_bar.actions()]
    assert "Aide" in menu_titles

    help_menu = next(a.menu() for a in menu_bar.actions() if a.text() == "Aide")
    action_texts = [a.text() for a in help_menu.actions()]
    assert "À propos d'Epubeur…" in action_texts


def test_show_about_dialog_does_not_raise(qapp, monkeypatch):
    window = MainWindow()
    monkeypatch.setattr(AboutDialog, "exec", lambda self: None)
    window._show_about_dialog()  # ne doit pas lever


# --- Régression : présence des fichiers/mentions légales requises par la distribution du
# projet — protège contre une suppression ou un oubli accidentel de LICENSE ou de la mention de
# copyright dans version_info.txt (utilisée par PyInstaller pour les métadonnées Windows de
# l'exe, onglet Propriétés > Détails). Vérifie directement la racine du dépôt, indépendamment de
# ui/about_dialog.py::_license_path, pour ne pas dépendre de la logique de résolution testée
# séparément plus haut.

PROJECT_ROOT = Path(__file__).parent.parent


def test_license_file_exists_at_repo_root():
    assert (PROJECT_ROOT / "LICENSE").exists(), (
        "Le fichier LICENSE a disparu de la racine du projet — requis pour la distribution "
        "sous GNU GPL v3 (cf. README.md)."
    )


def test_version_info_declares_legal_copyright():
    content = (PROJECT_ROOT / "version_info.txt").read_text(encoding="utf-8")
    assert 'StringStruct("LegalCopyright", "Copyright 2026 Bruno Aublet")' in content, (
        "La mention LegalCopyright a disparu de version_info.txt — sans elle, l'exécutable "
        "compilé n'affiche plus de copyright dans Propriétés > Détails sous Windows."
    )
