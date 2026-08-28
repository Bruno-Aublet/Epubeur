from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QAbstractItemView, QDialog, QListWidget, QListWidgetItem, QVBoxLayout, QLabel, QWidget

from controller import ProjectController
from model.text_utils import natural_sort_key
from ui.reimport_choice_dialog import ReimportChoice, ReimportChoiceDialog


def dispatch_odt_import(controller: ProjectController, path: Path, parent_widget) -> None:
    """Décide comment traiter un .odt : import direct si jamais vu dans le projet actuellement
    ouvert, sinon ReimportChoiceDialog (remplacer/ajouter) — logique partagée entre le
    glisser-déposé (_handle_dropped_files) et un clic sur une entrée « Fichiers récents »
    (ui/main_window.py::_open_recent_file), pour ne jamais dupliquer ces 3 branches."""
    existing = controller.find_source_odt_by_path(path)
    if existing is not None:
        dialog = ReimportChoiceDialog(path.name, parent_widget)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.result_choice() == ReimportChoice.REPLACE:
            controller.replace_odt(path)
        else:
            controller.import_odt(path)
    else:
        controller.import_odt(path)


class ImportListWidget(QListWidget):
    """Liste des fichiers .odt/.epub importés, affichée en lecture seule (triée
    alphabétiquement) : l'ordre narratif se règle dans l'onglet Structure, pas ici."""

    files_dropped = Signal(list)
    project_dropped = Signal(Path)  # .epbz déposé : jamais mélangé avec un import odt/epub —
                                     # ouvrir un projet remplace tout, un seul à la fois a du sens
    image_dropped = Signal(Path)  # tout fichier qui n'est ni .epbz ni .odt/.epub : même
                                   # comportement que le drop sur l'arbre de Structure
                                   # (_on_external_image_dropped) — pas de filtrage d'extension
                                   # ici non plus, controller.add_image_as_chapter refuse lui-même
                                   # (avec avertissement) tout format hors PNG/JPEG, sans rien
                                   # ajouter au projet dans ce cas.

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        # Placeholder affiché en fond tant que la liste est vide, pour indiquer la zone de
        # glisser-déposer — enfant du viewport (pas de la liste elle-même) pour rester visible
        # par-dessus le fond blanc de la QListWidget sans interférer avec les items.
        self._placeholder_label = QLabel("Déposez ici vos fichiers ODT, EPUB ou images", self.viewport())
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder_label.setStyleSheet("color: #b0b0b0; font-size: 28pt;")
        self._placeholder_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.model().rowsInserted.connect(self._update_placeholder_visibility)
        self.model().rowsRemoved.connect(self._update_placeholder_visibility)
        self._update_placeholder_visibility()

    def _update_placeholder_visibility(self) -> None:
        self._placeholder_label.setVisible(self.count() == 0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._placeholder_label.setGeometry(self.viewport().rect())

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            paths = []
            epbz_paths = []
            image_paths = []
            for url in event.mimeData().urls():
                local = url.toLocalFile()
                if not local:
                    continue
                if local.lower().endswith(".epbz"):
                    epbz_paths.append(Path(local))
                elif local.lower().endswith((".odt", ".epub")):
                    paths.append(Path(local))
                else:
                    image_paths.append(Path(local))
            if epbz_paths:
                self.project_dropped.emit(epbz_paths[0])
            if paths:
                self.files_dropped.emit(paths)
            for image_path in image_paths:
                self.image_dropped.emit(image_path)
            event.acceptProposedAction()


class ImportPanel(QWidget):
    epub_imported = Signal(str)  # chemin du .epub importé avec succès
    project_dropped = Signal(Path)  # .epbz déposé : MainWindow décide d'ouvrir (avec garde
                                     # modifs non enregistrées), ce panneau n'a pas accès à cette
                                     # notion (has_unsaved_content vit côté controller/MainWindow)

    def __init__(self, controller: ProjectController, parent=None):
        super().__init__(parent)
        self.controller = controller

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Fichiers importés (glisser-déposer des .odt/.epub) — triés par nom de fichier. "
            "L'ordre narratif se règle dans l'onglet Structure. Glisser un .epbz ouvre ce projet "
            "(remplace le projet en cours)."))

        self.list_widget = ImportListWidget()
        layout.addWidget(self.list_widget)

        # Les imports .epub n'ont pas d'entrée dans project.source_odt_files (ce champ ne trace
        # que les .odt, cf. controller.import_odt) — on garde donc une trace locale, propre à ce
        # panneau, pour les afficher malgré tout : sans elle, _refresh() (déclenché par le même
        # chapters_changed qu'émet import_epub_file EN COURS D'APPEL, pas après son retour)
        # effacerait la ligne, puisqu'il ne connaît que source_odt_files. On enregistre donc le nom
        # de fichier AVANT l'appel (pas un label déjà formaté après coup, calculé trop tard par
        # rapport au chapters_changed déclenché pendant l'appel) ; le compte de chapitres est
        # recalculé à chaque _refresh() à partir de ce que le projet contient alors. Éphémère (non
        # persisté dans le projet), cohérent avec le fait que les métadonnées d'import EPUB ne sont
        # pas sauvegardées ailleurs non plus.
        self._epub_import_names: list[str] = []

        self.list_widget.files_dropped.connect(self._handle_dropped_files)
        self.list_widget.project_dropped.connect(self.project_dropped)
        self.list_widget.image_dropped.connect(self.controller.add_image_as_chapter)
        self.controller.chapters_changed.connect(self._refresh)

    def _handle_dropped_files(self, paths: list[Path]) -> None:
        # setUpdatesEnabled(False) sur toute la fenêtre : chaque import_odt/import_epub_file émet
        # chapters_changed/assets_changed, qui déclenche un refresh() complet (destruction +
        # recréation de tous les widgets) dans StructureEditor ET ImageGallery — avec plusieurs
        # fichiers glissés d'un coup, ça fait autant de reconstructions complètes que de fichiers,
        # chacune brièvement visible à l'écran (symptôme signalé : "petites fenêtres qui
        # flashent"). On coupe le rendu de toute la fenêtre le temps de la boucle, un seul repaint
        # final une fois tous les fichiers traités.
        window = self.window()
        window.setUpdatesEnabled(False)
        try:
            for path in paths:
                if path.suffix.lower() == ".odt":
                    dispatch_odt_import(self.controller, path, self)
                elif path.suffix.lower() == ".epub":
                    self._epub_import_names.append(path.name)
                    self.controller.import_epub_file(path)
        finally:
            window.setUpdatesEnabled(True)

    def _refresh(self) -> None:
        self.list_widget.clear()
        sorted_entries = sorted(self.controller.project.source_odt_files,
                                 key=lambda entry: natural_sort_key(entry.path.name))
        for entry in sorted_entries:
            n_chapters = len(entry.chapter_ids)
            label = f"{entry.path.name} — {n_chapters} chapitre(s) détecté(s)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            self.list_widget.addItem(item)
        for name in self._epub_import_names:
            self.list_widget.addItem(QListWidgetItem(f"{name} (importé, voir onglet Structure)"))
