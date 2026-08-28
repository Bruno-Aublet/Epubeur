from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QVBoxLayout

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

        self.list_widget = QListWidget()
        for i, para in enumerate(chapter.paragraphs):
            if isinstance(para, Table):
                preview = "[Tableau]"
            else:
                preview = para.plain_text()[:60] or "(paragraphe vide)"
            self.list_widget.addItem(f"{i}. {preview}")
        layout.addWidget(self.list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            return
        self.selected_index = row
        self.accept()
