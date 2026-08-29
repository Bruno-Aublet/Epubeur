import sys
from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextEdit, QVBoxLayout


def _changelog_path() -> Path:
    """Localise CHANGELOG.md aussi bien en développement (racine du dépôt) qu'une fois compilé —
    même logique que ui/about_dialog.py::_license_path pour LICENSE."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "CHANGELOG.md"
    return Path(__file__).parent.parent / "CHANGELOG.md"


class ChangelogDialog(QDialog):
    """Menu Aide > Historique des versions — affiche le contenu de CHANGELOG.md."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Historique des versions")
        self.resize(700, 600)

        layout = QVBoxLayout(self)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        try:
            text_edit.setMarkdown(_changelog_path().read_text(encoding="utf-8"))
        except OSError:
            text_edit.setPlainText("Le fichier CHANGELOG.md est introuvable.")
        layout.addWidget(text_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
