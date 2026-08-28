from enum import Enum

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout


class ReimportChoice(Enum):
    REPLACE = "replace"
    ADD_AS_NEW = "add_as_new"


class ReimportChoiceDialog(QDialog):
    """Affichée quand un fichier .odt glissé-déposé a un chemin déjà présent dans le projet
    (cf. controller.py::find_source_odt_by_path) — jamais de remplacement ou de duplication
    automatique/silencieuse. `result_choice()` retourne None si la boîte a été annulée."""

    def __init__(self, filename: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fichier déjà importé")
        self._choice: ReimportChoice | None = None

        layout = QVBoxLayout(self)
        message = QLabel(
            f"« {filename} » a déjà été importé dans ce projet. Voulez-vous remplacer les "
            "chapitres existants par une nouvelle lecture du fichier corrigé, ou les ajouter "
            "comme nouveaux chapitres (doublon volontaire) ?"
        )
        message.setWordWrap(True)
        layout.addWidget(message)

        replace_btn = QPushButton("Remplacer les chapitres existants")
        replace_btn.clicked.connect(lambda: self._select(ReimportChoice.REPLACE))
        layout.addWidget(replace_btn)

        add_btn = QPushButton("Ajouter comme nouveaux chapitres")
        add_btn.clicked.connect(lambda: self._select(ReimportChoice.ADD_AS_NEW))
        layout.addWidget(add_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _select(self, choice: ReimportChoice) -> None:
        self._choice = choice
        self.accept()

    def result_choice(self) -> ReimportChoice | None:
        return self._choice
