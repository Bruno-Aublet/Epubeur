import sys
from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QTextEdit, QVBoxLayout

from model.version import __version__

COPYRIGHT_NOTICE = "Copyright 2026 Bruno Aublet"


def _license_path() -> Path:
    """Localise le fichier LICENSE aussi bien en développement (racine du dépôt) qu'une fois
    compilé — en mode onedir, PyInstaller place les fichiers déclarés dans datas= (epubeur.spec)
    au même niveau que l'exe, pas besoin de sys._MEIPASS (propre au mode onefile)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "LICENSE"
    return Path(__file__).parent.parent / "LICENSE"


class AboutDialog(QDialog):
    """Menu Aide > À propos d'Epubeur — nom, version, copyright, et accès au texte complet de la
    licence (GPLv3) depuis un seul endroit, plutôt que deux entrées de menu séparées."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("À propos d'Epubeur")
        self.resize(400, 200)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>Epubeur</b> — version {__version__}"))
        layout.addWidget(QLabel("Convertit des manuscrits LibreOffice Writer (.odt) en EPUB."))
        layout.addWidget(QLabel(COPYRIGHT_NOTICE))
        layout.addWidget(QLabel("Distribué sous licence GNU GPL v3."))

        license_btn = QPushButton("Voir la licence…")
        license_btn.clicked.connect(self._show_license)
        layout.addWidget(license_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _show_license(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Licence GNU GPL v3")
        dialog.resize(700, 600)
        layout = QVBoxLayout(dialog)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setFontFamily("Consolas")
        try:
            text_edit.setPlainText(_license_path().read_text(encoding="utf-8"))
        except OSError:
            text_edit.setPlainText(
                "Le fichier LICENSE est introuvable. Le texte complet de la GNU GPL v3 est "
                "disponible sur https://www.gnu.org/licenses/gpl-3.0.txt"
            )
        layout.addWidget(text_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)

        dialog.exec()
