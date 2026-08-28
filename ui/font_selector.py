import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from controller import ProjectController

FONT_FILE_EXTENSIONS = ("*.ttf", "*.otf")
FONT_PREVIEW_POINT_SIZE = 20

SAMPLE_TEXT = "Portez ce vieux whisky au juge blond qui fume : voici un aperçu de la police sélectionnée."


def _default_fonts_dir() -> str:
    """Dossier de polices proposé par défaut dans le sélecteur de fichier :
    le dossier utilisateur (polices installées sans droits admin), avec repli
    sur le dossier système si celui-ci n'existe pas ou est vide."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        user_fonts_dir = Path(local_app_data) / "Microsoft" / "Windows" / "Fonts"
        if user_fonts_dir.is_dir():
            return str(user_fonts_dir)

    system_fonts_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    if system_fonts_dir.is_dir():
        return str(system_fonts_dir)

    return ""


def find_matching_font_files(fonts_dir: str, wanted_family: str) -> list[Path]:
    """Scanne fonts_dir et retourne les fichiers .ttf/.otf dont le nom de police INTERNE
    (pas le nom de fichier, qui peut être arbitraire) correspond à wanted_family."""
    if not fonts_dir:
        return []
    directory = Path(fonts_dir)
    if not directory.is_dir():
        return []

    matches: list[Path] = []
    wanted_lower = wanted_family.strip().lower()
    for pattern in FONT_FILE_EXTENSIONS:
        for font_path in directory.glob(pattern):
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            if font_id == -1:
                continue
            families = QFontDatabase.applicationFontFamilies(font_id)
            QFontDatabase.removeApplicationFont(font_id)
            if any(f.strip().lower() == wanted_lower for f in families):
                matches.append(font_path)
    return matches


class FontMatchDialog(QDialog):
    """Liste les fichiers de police trouvés dont le nom interne correspond à la police
    recherchée, pour éviter de fouiller à la main parmi des centaines de fichiers. Sélection
    multiple (Ctrl/Maj+clic) : une police peut avoir plusieurs variantes physiques (Regular,
    Bold, Italic...) à embarquer ensemble. Les fichiers déjà figés pour cette famille sont
    marqués et pré-sélectionnés, pour qu'on voie d'un coup d'œil ce qui est déjà retenu plutôt
    que de travailler à l'aveugle."""

    def __init__(self, wanted_family: str, matches: list[Path], already_locked: set[str] | None = None,
                 parent=None):
        super().__init__(parent)
        already_locked = already_locked or set()
        self.setWindowTitle(f"Fichiers correspondant à « {wanted_family} »")
        self.setMinimumSize(560, 320)
        self.selected_paths: list[Path] = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"{len(matches)} fichier(s) trouvé(s) portant le nom de police « {wanted_family} » — "
            "Ctrl+clic ou Maj+clic pour en choisir plusieurs (ex. Regular + Bold) :"
        ))

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for path in matches:
            label = f"{path.name}  —  {path.parent}"
            already = str(path) in already_locked
            if already:
                label += "  [déjà figée]"
            item = QListWidgetItem(label)
            item.setToolTip(str(path))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.list_widget.addItem(item)
            if already:
                item.setSelected(True)
        if matches and not already_locked:
            self.list_widget.setCurrentRow(0)
        layout.addWidget(self.list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        browse_btn = buttons.addButton("Parcourir manuellement…", QDialogButtonBox.ButtonRole.ActionRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        browse_btn.clicked.connect(self._browse_manually)
        layout.addWidget(buttons)

        self._browse_manually_requested = False

    def _accept(self) -> None:
        self.selected_paths = [
            Path(item.data(Qt.ItemDataRole.UserRole)) for item in self.list_widget.selectedItems()
        ]
        self.accept()

    def _browse_manually(self) -> None:
        self._browse_manually_requested = True
        self.reject()


class FontSelector(QWidget):
    """Arbre dépliable à gauche : une ligne par police détectée, avec un enfant par fichier
    physique déjà figé pour cette police (nom du fichier + graisse/style) — pour voir d'un
    coup d'œil, sans cliquer, ce qui est réellement figé et avec quels fichiers, notamment
    pour les polices à plusieurs variantes (Regular/Bold/Italic...). Cliquer sur une ligne de
    police (pas un fichier enfant) sélectionne cette police et met à jour l'aperçu à droite.
    Figer/déverrouiller la police actuellement sélectionnée se fait via les boutons sous
    l'aperçu, une action à la fois. Plusieurs polices différentes peuvent être figées au fil
    des sélections successives."""

    def __init__(self, controller: ProjectController, parent=None):
        super().__init__(parent)
        self.controller = controller

        layout = QHBoxLayout(self)

        left = QVBoxLayout()
        left.addWidget(QLabel("Polices détectées dans les fichiers importés :\n"
                               "cliquer sur une police pour voir un aperçu, déplier pour voir "
                               "les fichiers figés."))
        self.font_tree = QTreeWidget()
        self.font_tree.setHeaderHidden(True)
        left.addWidget(self.font_tree)
        layout.addLayout(left, 1)

        right = QVBoxLayout()
        right.addWidget(QLabel("Aperçu :"))
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlainText(SAMPLE_TEXT)
        right.addWidget(self.preview)

        actions = QHBoxLayout()
        self.lock_btn = QPushButton("Figer cette police…")
        self.unlock_btn = QPushButton("Déverrouiller cette police")
        actions.addWidget(self.lock_btn)
        actions.addWidget(self.unlock_btn)
        right.addLayout(actions)

        self.unlock_all_btn = QPushButton("Tout déverrouiller")
        right.addWidget(self.unlock_all_btn)

        layout.addLayout(right, 1)

        self.font_tree.currentItemChanged.connect(self._on_selection_changed)
        self.lock_btn.clicked.connect(self._on_lock_clicked)
        self.unlock_btn.clicked.connect(self._on_unlock_clicked)
        self.unlock_all_btn.clicked.connect(self._unlock_all)
        self.controller.fonts_changed.connect(self.refresh)

        self.refresh()

    def refresh(self) -> None:
        previous_name = self._current_family()
        self.font_tree.clear()
        counts = self.controller.font_counts()

        selected_item = None
        for name, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            lf = self.controller.project.document.locked_font_for_family(name)
            label = f"{name} — {count} occurrence(s)"
            if lf is not None:
                label += f"  [figée, {len(lf.files)} fichier(s)]" if len(lf.files) > 1 else "  [figée]"
            item = QTreeWidgetItem([label])
            item.setData(0, 1000, name)
            self.font_tree.addTopLevelItem(item)

            if lf is not None:
                if not lf.files:
                    child = QTreeWidgetItem(["— aucun fichier associé —"])
                    item.addChild(child)
                for f in lf.files:
                    style_label = f.style_name or ("Italique" if f.italic else "Regular")
                    child = QTreeWidgetItem([f"{Path(f.file_path).name}  —  {style_label} ({f.weight})"])
                    item.addChild(child)

            if name == previous_name:
                selected_item = item

        self.font_tree.expandAll()

        if selected_item is not None:
            self.font_tree.setCurrentItem(selected_item)
        elif self.font_tree.topLevelItemCount() > 0:
            self.font_tree.setCurrentItem(self.font_tree.topLevelItem(0))
        else:
            self._update_action_state(None)

    def _current_family(self) -> str | None:
        item = self.font_tree.currentItem()
        if item is None:
            return None
        # Un item enfant (fichier figé) n'a pas de famille propre : remonter au parent.
        if item.parent() is not None:
            item = item.parent()
        return item.data(0, 1000)

    def _on_selection_changed(self, current: QTreeWidgetItem, _previous) -> None:
        name = self._current_family()
        if name is None:
            self._update_action_state(None)
            return
        self.preview.setFont(QFont(name, FONT_PREVIEW_POINT_SIZE))
        self._update_action_state(name)

    def _update_action_state(self, family: str | None) -> None:
        if family is None:
            self.lock_btn.setEnabled(False)
            self.unlock_btn.setEnabled(False)
            return
        is_locked = self.controller.is_font_locked(family)
        self.lock_btn.setEnabled(True)
        self.unlock_btn.setEnabled(is_locked)

    def _on_lock_clicked(self) -> None:
        family = self._current_family()
        if family is not None:
            self._choose_font_file(family)

    def _on_unlock_clicked(self) -> None:
        family = self._current_family()
        if family is not None:
            self.controller.unlock_font(family)

    def _unlock_all(self) -> None:
        self.controller.unlock_all_fonts()

    def _choose_font_file(self, family: str) -> None:
        fonts_dir = _default_fonts_dir()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            matches = find_matching_font_files(fonts_dir, family)
        finally:
            QApplication.restoreOverrideCursor()

        lf = self.controller.project.document.locked_font_for_family(family)
        already_locked = {f.file_path for f in lf.files} if lf else set()

        paths: list[Path] = []
        if matches:
            dialog = FontMatchDialog(family, matches, already_locked, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                paths = dialog.selected_paths
            elif not dialog._browse_manually_requested:
                return  # annulé, pas de repli demandé — l'état actuel reste inchangé
        if not paths:
            path_str, _ = QFileDialog.getOpenFileName(self, "Choisir le fichier de police", fonts_dir,
                                                        "Polices (*.ttf *.otf)")
            if not path_str:
                return
            paths = [Path(path_str)]

        font_id = QFontDatabase.addApplicationFont(str(paths[0]))
        families = QFontDatabase.applicationFontFamilies(font_id)
        display_family = families[0] if families else family
        self.preview.setFont(QFont(display_family, FONT_PREVIEW_POINT_SIZE))

        self.controller.lock_font_files(family, paths)
