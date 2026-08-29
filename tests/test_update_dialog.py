from PySide6.QtWidgets import QLabel

from ui.update_dialog import UpdateAvailableDialog


def test_update_dialog_shows_remote_version(qapp):
    dialog = UpdateAvailableDialog("1.2.0", "https://github.com/Bruno-Aublet/Epubeur/releases/latest")
    texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert any("1.2.0" in text for text in texts)


def test_update_dialog_shows_clickable_release_link(qapp):
    url = "https://github.com/Bruno-Aublet/Epubeur/releases/latest"
    dialog = UpdateAvailableDialog("1.2.0", url)
    texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert any(f'href="{url}"' in text for text in texts)
