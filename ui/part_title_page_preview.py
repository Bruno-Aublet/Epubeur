from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

NO_TITLE_PAGE_MESSAGE = ("Cette partie n'a pas de page de garde.\n"
                          "Cochez la case à gauche pour en ajouter une.")


class PartTitlePagePreview(QWidget):
    """Aperçu de la page de garde d'une partie : titre centré horizontalement et
    verticalement, via un vrai layout Qt (fiable), pas du HTML/CSS bricolé dans un
    QTextBrowser dont le moteur Rich Text limité ne supporte pas le centrage vertical.
    Affiche aussi un message explicatif (gris pâle, jamais confondu avec un vrai titre)
    quand la partie sélectionnée n'a pas de page de garde activée."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.title_label = QLabel("")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)
        self._title_font = self.title_label.font()
        self._title_font.setPointSize(22)
        self._title_font.setFamily("Serif")

        layout.addStretch(1)
        layout.addWidget(self.title_label)
        layout.addStretch(1)

    def set_title(self, title: str) -> None:
        self.title_label.setFont(self._title_font)
        self.title_label.setStyleSheet("")
        self.title_label.setText(title)

    def show_no_title_page(self) -> None:
        self.title_label.setFont(self.font())
        self.title_label.setStyleSheet("color: #bbb;")
        self.title_label.setText(NO_TITLE_PAGE_MESSAGE)
