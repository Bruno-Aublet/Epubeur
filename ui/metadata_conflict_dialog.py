from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

FIELD_LABELS = {
    "title": "Titre",
    "author": "Auteur",
    "language": "Langue",
    "description": "Description / résumé",
    "publication_date": "Date de publication",
}


class _WrappingRadioButton(QWidget):
    """QRadioButton ne retourne jamais son texte à la ligne (setWordWrap n'existe pas sur
    QAbstractButton en Qt) — nécessaire ici car une description peut être longue. Contournement
    standard : un vrai QRadioButton sans texte, accolé à un QLabel séparé en wordwrap ; cliquer
    sur le label coche aussi le bouton, pour rester utilisable comme un radio bouton normal."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._button = QRadioButton()
        layout.addWidget(self._button, 0)

        label = QLabel(text)
        label.setWordWrap(True)
        label.mousePressEvent = lambda _event: self._button.setChecked(True)
        layout.addWidget(label, 1)

    def setChecked(self, checked: bool) -> None:
        self._button.setChecked(checked)

    @property
    def button(self) -> QRadioButton:
        return self._button


class MetadataConflictDialog(QDialog):
    """Affichée quand un import ODT propose, pour un champ déjà rempli dans l'onglet Générer,
    une valeur différente de celle déjà en place — l'utilisateur choisit, champ par champ, entre
    « garder l'ancienne » et « prendre la nouvelle » (jamais de fusion automatique pour ces champs
    texte simple : contrairement aux mots-clés, une fusion titre+titre ou auteur+auteur n'aurait
    aucun sens). `conflicts` : dict field_name -> (ancienne_valeur, nouvelle_valeur)."""

    def __init__(self, conflicts: dict[str, tuple[str, str]], source_file_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Métadonnées différentes détectées")
        self._groups: dict[str, QButtonGroup] = {}

        self.setMinimumWidth(480)
        self.resize(480, self.height())

        layout = QVBoxLayout(self)
        intro_label = QLabel(
            f"Le fichier « {source_file_name} » contient des métadonnées différentes de celles "
            "déjà renseignées dans l'onglet Métadonnées. Choisissez la valeur à conserver pour "
            "chaque champ concerné :"
        )
        intro_label.setWordWrap(True)
        layout.addWidget(intro_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        for field_name, (old_value, new_value) in conflicts.items():
            box = QGroupBox(FIELD_LABELS.get(field_name, field_name))
            box_layout = QVBoxLayout(box)
            group = QButtonGroup(box)

            keep_old = _WrappingRadioButton(f"Garder : « {old_value} »")
            keep_old.setChecked(True)
            group.addButton(keep_old.button, 0)
            box_layout.addWidget(keep_old)

            take_new = _WrappingRadioButton(f"Remplacer par : « {new_value} »")
            group.addButton(take_new.button, 1)
            box_layout.addWidget(take_new)

            content_layout.addWidget(box)
            self._groups[field_name] = group

        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def resolved_choices(self) -> dict[str, bool]:
        """Retourne field_name -> True si l'utilisateur a choisi la NOUVELLE valeur (à appliquer),
        False s'il a gardé l'ancienne (rien à faire pour ce champ)."""
        return {name: group.checkedId() == 1 for name, group in self._groups.items()}
