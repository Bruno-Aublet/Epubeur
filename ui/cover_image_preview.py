from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget


class CoverImagePreview(QWidget):
    """Aperçu en lecture seule d'une image de couverture/4e de couverture, centrée et mise à
    l'échelle — pas de QTextBrowser ici, ce n'est pas du texte formaté comme ChapterPreview."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.image_label = QLabel("")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Un QLabel avec un pixmap réclame une taille minimale/préférée basée sur le contenu de
        # l'image (sizeHint), ce qui poussait le splitter/la fenêtre parente à grandir pour
        # l'accommoder — et comme _rescale() se base sur self.size(), chaque agrandissement
        # relançait un nouveau calcul, créant une boucle d'agrandissement incontrôlable.
        # Ignored + setMinimumSize(0, 0) : le label ne dicte plus jamais sa taille au parent,
        # c'est toujours lui qui s'adapte à l'espace déjà alloué, jamais l'inverse.
        self.image_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.image_label.setMinimumSize(1, 1)
        layout.addWidget(self.image_label, 1)

        self._pixmap: QPixmap | None = None

    def show_image(self, path: Path) -> None:
        self._pixmap = QPixmap(str(path))
        self._rescale()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            self.image_label.setText("Image introuvable")
            return
        scaled = self._pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
        self.image_label.setPixmap(scaled)
