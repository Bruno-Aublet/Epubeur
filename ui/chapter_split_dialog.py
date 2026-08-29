from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QVBoxLayout

from model.document import Chapter, Table


class ChapterSplitDialog(QDialog):
    """Choix du paragraphe à partir duquel scinder un chapitre en deux."""

    def __init__(self, chapter: Chapter, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Scinder : {chapter.title or 'chapitre'}")
        self.chapter = chapter
        self.selected_index: int | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Sélectionnez le paragraphe qui commencera le second chapitre :"))

        # Le paragraphe 0 est exclu : le proposer scinderait le chapitre en un premier chapitre
        # totalement vide (juste son titre) et un second qui récupère tout le texte mais sans
        # titre — un chapitre fantôme silencieux plutôt qu'une vraie scission.
        self.list_widget = QListWidget()
        for i, para in enumerate(chapter.paragraphs):
            if i == 0:
                continue
            if isinstance(para, Table):
                preview = "[Tableau]"
            else:
                preview = para.plain_text()[:60] or "(paragraphe vide)"
            item = QListWidgetItem(f"{i}. {preview}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        self.selected_index = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
