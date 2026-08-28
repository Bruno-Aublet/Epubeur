from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout

from model.document import Chapter


class ChapterRenameDialog(QDialog):
    """Renommage d'un chapitre, avec contrôle explicite de l'affichage du titre dans le texte
    (title_visible) — séparé du simple fait de donner un titre, pour ne jamais faire apparaître
    un titre dans le texte du chapitre sans action explicite de l'utilisateur."""

    def __init__(self, chapter: Chapter, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Renommer le chapitre")
        self.title: str = chapter.title
        self.title_visible: bool = chapter.title_visible

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Titre :"))
        self.title_edit = QLineEdit(chapter.title)
        layout.addWidget(self.title_edit)

        self.visible_checkbox = QCheckBox("Afficher ce titre dans le texte du chapitre")
        self.visible_checkbox.setChecked(chapter.title_visible)
        layout.addWidget(self.visible_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        self.title = self.title_edit.text()
        self.title_visible = self.visible_checkbox.isChecked()
        self.accept()
