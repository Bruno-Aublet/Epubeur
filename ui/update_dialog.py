from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout


class UpdateAvailableDialog(QDialog):
    """Prévient l'utilisateur qu'une nouvelle version est disponible sur GitHub, avec un lien
    cliquable direct vers la page de la release — affichée seulement quand model.update_checker
    détecte une version plus récente que model.version.__version__."""

    def __init__(self, remote_version: str, release_url: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mise à jour disponible")

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"La version {remote_version} d'Epubeur est disponible."))

        link_label = QLabel(f'<a href="{release_url}">{release_url}</a>')
        link_label.setOpenExternalLinks(True)
        link_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        layout.addWidget(link_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
