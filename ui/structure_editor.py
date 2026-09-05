from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from controller import ProjectController
from model.document import Chapter, Part
from model.text_utils import natural_sort_key
from ui.chapter_preview import ChapterPreview
from ui.chapter_rename_dialog import ChapterRenameDialog
from ui.chapter_toolbar import ChapterFormatToolbar
from ui.chapter_split_dialog import ChapterSplitDialog
from ui.cover_image_preview import CoverImagePreview
from ui.import_panel import dispatch_odt_import
from ui.part_title_page_preview import PartTitlePagePreview

PART_ROLE = Qt.ItemDataRole.UserRole
CHAPTER_ROLE = Qt.ItemDataRole.UserRole + 1
# Valeurs "cover" / "back_cover" (pas de rôle numérique dédié) : ces deux items ne sont ni une
# Part ni un Chapter, ils ne référencent aucun id de document — juste un marqueur de nature.
COVER_ROLE = Qt.ItemDataRole.UserRole + 2


class _StructureTreeWidget(QTreeWidget):
    """QTreeWidget dont dropEvent() est surchargé pour resynchroniser le modèle de données
    juste après un glisser-déposer interne : QTreeWidget/QTreeModel n'implémente pas moveRows
    et n'émet donc jamais rowsMoved (ni entre parents différents, ni au sein du même parent,
    vérifié empiriquement) — dropEvent() est le seul point d'accroche fiable pour détecter la
    fin d'un déplacement."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_drop_finished = None  # callback assigné par StructureEditor
        self.on_external_file_dropped = None  # callback(Path), assigné par StructureEditor

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            if self.on_external_file_dropped is not None:
                for url in event.mimeData().urls():
                    local = url.toLocalFile()
                    if local:
                        self.on_external_file_dropped(Path(local))
            event.acceptProposedAction()
            return
        super().dropEvent(event)
        if self.on_drop_finished is not None:
            self.on_drop_finished()


class StructureEditor(QWidget):
    cover_tab_requested = Signal()  # relayé par MainWindow vers l'onglet Couverture / 4e de couverture
    project_dropped = Signal(Path)  # .epbz déposé sur l'arbre : même relais que
                                     # ImportPanel.project_dropped, MainWindow décide d'ouvrir
                                     # (avec garde modifs non enregistrées)

    def __init__(self, controller: ProjectController, parent=None):
        super().__init__(parent)
        self.controller = controller

        root_layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self.new_part_btn = QPushButton("Nouvelle partie")
        self.rename_btn = QPushButton("Renommer")
        self.assign_btn = QPushButton("Assigner à une partie")
        self.unassign_btn = QPushButton("Retirer de la partie")
        self.merge_btn = QPushButton("Fusionner avec le chapitre suivant")
        self.split_btn = QPushButton("Scinder le chapitre")
        self.delete_btn = QPushButton("Supprimer")
        toolbar.addWidget(self.new_part_btn)
        toolbar.addWidget(self.rename_btn)
        toolbar.addWidget(self.assign_btn)
        toolbar.addWidget(self.unassign_btn)
        toolbar.addWidget(self.merge_btn)
        toolbar.addWidget(self.split_btn)
        toolbar.addWidget(self.delete_btn)
        toolbar.addStretch()
        root_layout.addLayout(toolbar)

        hint = QLabel("Astuce : sélectionnez plusieurs chapitres (Ctrl+clic ou Shift+clic), "
                       "puis cliquez sur « Assigner à une partie ».")
        hint.setStyleSheet("color: #888;")
        root_layout.addWidget(hint)

        title_page_hint = QLabel(
            "☑ La case à côté du nom d'une partie insère une page de garde avec son titre "
            "(centré) avant ses chapitres, et l'ajoute au sommaire du livre."
        )
        title_page_hint.setStyleSheet("color: #888;")
        title_page_hint.setWordWrap(True)
        root_layout.addWidget(title_page_hint)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = _StructureTreeWidget()
        self.tree.on_drop_finished = self._on_rows_moved
        self.tree.on_external_file_dropped = self._on_external_file_dropped
        self.tree.setHeaderHidden(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        # DragDropMode.InternalMove forçait implicitement Qt::MoveAction pour tout glisser-
        # déposer — passer à DragDrop (nécessaire pour accepter un drop externe, cf.
        # _StructureTreeWidget.dropEvent) fait retomber defaultDropAction sur IgnoreAction, ce
        # qui pouvait laisser Qt choisir une copie plutôt qu'un déplacement pour un drag interne
        # (l'item source restait affiché en plus du nouvel emplacement, dupliquant le chapitre
        # dans structure.items sans dupliquer l'asset — d'où une image visible deux fois dans
        # l'arbre mais une seule fois dans la galerie, qui liste des assets, pas des chapitres).
        self.tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        splitter.addWidget(self.tree)

        self.preview = ChapterPreview(controller)
        self.format_toolbar = ChapterFormatToolbar(controller, self.preview)
        self._preview_container = QWidget()
        preview_container_layout = QVBoxLayout(self._preview_container)
        preview_container_layout.setContentsMargins(0, 0, 0, 0)
        preview_container_layout.addWidget(self.format_toolbar)
        preview_container_layout.addWidget(self.preview, 1)

        self.part_title_page_preview = PartTitlePagePreview()
        self.cover_image_preview = CoverImagePreview()
        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(self._preview_container)
        self.preview_stack.addWidget(self.part_title_page_preview)
        self.preview_stack.addWidget(self.cover_image_preview)
        splitter.addWidget(self.preview_stack)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        root_layout.addWidget(splitter, 1)

        self.new_part_btn.clicked.connect(self._create_part)
        self.rename_btn.clicked.connect(self._rename_selected)
        self.assign_btn.clicked.connect(self._assign_selected_to_part)
        self.unassign_btn.clicked.connect(self._unassign_selected)
        self.merge_btn.clicked.connect(self._merge_selected_with_next)
        self.split_btn.clicked.connect(self._split_selected)
        self.delete_btn.clicked.connect(self._delete_selected)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)

        self.controller.chapters_changed.connect(self.refresh)
        self.controller.structure_changed.connect(self.refresh)
        # Un changement de taille d'affichage d'image (onglet Images) n'affecte ni les
        # chapitres ni la structure, mais doit quand même rafraîchir l'aperçu si le chapitre
        # affiché contient cette image — refresh() reconstruit tout l'arbre (un peu de travail
        # inutile ici) mais préserve déjà la sélection courante et rappelle _on_selection_changed
        # en fin de course, ce qui suffit à réafficher l'aperçu à jour.
        self.controller.assets_changed.connect(self.refresh)

        self.refresh()

    def _document(self):
        return self.controller.project.document

    def _file_and_position_sort_key(self, chapter_id: str) -> tuple:
        """Ordre par défaut : nom de fichier ODT source (tri naturel — "Chapitre2" avant
        "Chapitre12", cf. model.text_utils.natural_sort_key, pas un tri texte brut qui les
        inverserait), puis position du chapitre dans ce fichier. Utilisé uniquement pour décider
        un ordre la première fois qu'un groupe de chapitres est affiché/assigné sans ordre
        préexistant — jamais pour re-trier un ordre déjà choisi par l'utilisateur
        (part.chapter_ids fait foi une fois les chapitres assignés à une partie)."""
        chapter = self._document().chapters[chapter_id]
        file_name = ""
        for f in self.controller.project.source_odt_files:
            if f.id == chapter.source_odt_id:
                file_name = f.path.name
                break
        return (natural_sort_key(file_name), chapter.source_order_index)

    def refresh(self) -> None:
        # tree.clear() détruit tous les QTreeWidgetItem, y compris celui actuellement
        # sélectionné : on mémorise l'identité logique (part_id/chapter_id, pas l'item Qt
        # lui-même, qui n'existera plus) pour retrouver et resélectionner l'équivalent après
        # reconstruction — sans ça, toute action structurelle (cocher une case, scinder,
        # fusionner, supprimer, renommer…) qui déclenche refresh() ferait retomber l'aperçu à
        # vide, même quand l'élément regardé existe toujours.
        previously_selected_part_id = self._selected_part_id()
        previously_selected_chapter_id = self._selected_chapter_id()
        previously_selected_cover_kind = self._selected_cover_kind()

        self.tree.blockSignals(True)
        self.tree.clear()
        document = self._document()

        part_items: dict[str, QTreeWidgetItem] = {}
        chapter_items: dict[str, QTreeWidgetItem] = {}
        cover_items: dict[str, QTreeWidgetItem] = {}

        # La couverture, quand elle existe, est toujours le tout premier élément affiché — pas
        # un chapitre, pas déplaçable (ni ItemIsDragEnabled ni ItemIsDropEnabled), aucune donnée
        # PART_ROLE/CHAPTER_ROLE. Symétrique de la 4e de couverture tout en bas, après la boucle.
        if document.cover_asset_id:
            cover_item = QTreeWidgetItem(["Couverture"])
            cover_item.setData(0, COVER_ROLE, "cover")
            cover_item.setFlags(cover_item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled & ~Qt.ItemFlag.ItemIsDropEnabled)
            self.tree.addTopLevelItem(cover_item)
            cover_items["cover"] = cover_item

        # document.structure.items est la source de vérité de l'ordre affiché : c'est
        # exactement l'ordre utilisé par epub/builder.py pour générer le spine. On ne le
        # retrie jamais ici — un réordonnancement manuel (drag & drop) ou l'ordre choisi à
        # l'assignation doit survivre intact à tout refresh(), y compris ceux déclenchés par
        # une action sans rapport (ex. renommer une autre partie). Un chapitre libre (str
        # directement dans items) apparaît comme top-level item au même niveau qu'une Part,
        # exactement à sa position — pas regroupé dans une zone séparée.
        for item in document.structure.items:
            if isinstance(item, Part):
                part = item
                base_label = part.title or "(partie sans titre)"
                suffix = "  —  page de garde activée" if part.has_title_page else ""
                part_item = QTreeWidgetItem([base_label + suffix])
                part_item.setData(0, PART_ROLE, part.id)
                part_item.setFlags(part_item.flags() | Qt.ItemFlag.ItemIsDropEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                part_item.setCheckState(0, Qt.CheckState.Checked if part.has_title_page else Qt.CheckState.Unchecked)
                part_item.setToolTip(0, "Cocher pour insérer une page de garde avec le titre de la partie, "
                                         "centré, avant ses chapitres.")
                self.tree.addTopLevelItem(part_item)
                part_items[part.id] = part_item
                for chapter_id in part.chapter_ids:
                    if chapter_id in document.chapters:
                        chapter_items[chapter_id] = self._add_chapter_item(part_item, document.chapters[chapter_id])
            else:
                chapter_id = item
                chapter = document.chapters.get(chapter_id)
                if chapter is None:
                    continue
                # Chapitre libre : top-level item SANS PART_ROLE ni enfants, mais avec
                # CHAPTER_ROLE directement dessus (au lieu de le porter dans un item enfant
                # comme pour les parties).
                label = " ".join(chapter.title.split("\n")) if chapter.title else "(chapitre sans titre)"
                free_item = QTreeWidgetItem([label])
                free_item.setData(0, CHAPTER_ROLE, chapter.id)
                free_item.setFlags(free_item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
                self.tree.addTopLevelItem(free_item)
                chapter_items[chapter.id] = free_item

        if document.back_cover_asset_id:
            back_cover_item = QTreeWidgetItem(["4e de couverture"])
            back_cover_item.setData(0, COVER_ROLE, "back_cover")
            back_cover_item.setFlags(
                back_cover_item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled & ~Qt.ItemFlag.ItemIsDropEnabled)
            self.tree.addTopLevelItem(back_cover_item)
            cover_items["back_cover"] = back_cover_item

        self.tree.expandAll()

        restored_item = (
            chapter_items.get(previously_selected_chapter_id)
            or part_items.get(previously_selected_part_id)
            or cover_items.get(previously_selected_cover_kind)
        )
        if restored_item is not None:
            self.tree.setCurrentItem(restored_item)

        self.tree.blockSignals(False)
        # Signaux réactivés seulement maintenant : appelé explicitement plutôt que de compter
        # sur itemSelectionChanged (setCurrentItem ci-dessus ne l'émet pas forcément si l'item
        # occupe la même position visuelle qu'avant clear()), et aussi pour le cas où la
        # sélection n'a pas pu être restaurée (élément supprimé) — l'aperçu doit alors retomber
        # à vide, jamais rester sur un contenu périmé.
        self._on_selection_changed()

    def _add_chapter_item(self, parent_item: QTreeWidgetItem, chapter: Chapter) -> QTreeWidgetItem:
        # Un titre de chapitre peut contenir un saut de ligne manuel (Maj+Entrée dans Writer) ;
        # dans une liste à ligne unique comme l'arbre, on l'aplatit en espace.
        label = " ".join(chapter.title.split("\n")) if chapter.title else "(chapitre sans titre)"
        item = QTreeWidgetItem([label])
        item.setData(0, CHAPTER_ROLE, chapter.id)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
        parent_item.addChild(item)
        return item

    def _create_part(self) -> None:
        title, ok = QInputDialog.getText(self, "Nouvelle partie", "Titre de la partie :")
        if not ok:
            return
        self.controller.create_part(title)

    def sync_pending_editor_state(self) -> None:
        """Force la synchronisation vers le modèle de toute édition de texte en attente dans
        ChapterPreview — appelé avant une sauvegarde de projet (cf. MainWindow._save_project_as),
        pour ne jamais enregistrer un .epbz sans le texte tapé juste avant."""
        self.preview.sync_pending_edits()

    def select_chapter(self, chapter_id: str) -> None:
        """Sélectionne et affiche le chapitre donné dans l'arbre — pour une navigation
        programmatique depuis un autre onglet (ex. galerie d'images)."""
        def _find(parent_item: QTreeWidgetItem | None) -> QTreeWidgetItem | None:
            count = parent_item.childCount() if parent_item else self.tree.topLevelItemCount()
            for i in range(count):
                item = parent_item.child(i) if parent_item else self.tree.topLevelItem(i)
                if item.data(0, CHAPTER_ROLE) == chapter_id:
                    return item
                found = _find(item)
                if found is not None:
                    return found
            return None

        item = _find(None)
        if item is not None:
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)

    def _selected_chapter_id(self) -> str | None:
        items = self.tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, CHAPTER_ROLE)

    def _selected_chapter_ids(self) -> list[str]:
        ids = []
        for item in self.tree.selectedItems():
            chapter_id = item.data(0, CHAPTER_ROLE)
            if chapter_id:
                ids.append(chapter_id)
        return ids

    def _selected_part_id(self) -> str | None:
        items = self.tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, PART_ROLE)

    def _selected_cover_kind(self) -> str | None:
        """"cover" ou "back_cover" si l'item sélectionné est l'un de ces deux repères
        spéciaux, None sinon."""
        items = self.tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, COVER_ROLE)

    def _rename_selected(self) -> None:
        part_id = self._selected_part_id()
        if part_id:
            part = next((p for p in self._document().structure.parts() if p.id == part_id), None)
            if part is None:
                return
            title, ok = QInputDialog.getText(self, "Renommer la partie", "Titre :", text=part.title)
            if ok:
                self.controller.rename_part(part_id, title)
            return

        chapter_id = self._selected_chapter_id()
        if chapter_id:
            chapter = self._document().chapters.get(chapter_id)
            if chapter is None:
                return
            dialog = ChapterRenameDialog(chapter, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.controller.rename_chapter(chapter_id, dialog.title, dialog.title_visible)

    def _assign_selected_to_part(self) -> None:
        chapter_ids = self._selected_chapter_ids()
        if not chapter_ids:
            QMessageBox.information(self, "Assigner à une partie",
                                     "Sélectionnez d'abord un ou plusieurs chapitres (Ctrl+clic ou Shift+clic).")
            return

        parts = self._document().structure.parts()
        if not parts:
            title, ok = QInputDialog.getText(self, "Nouvelle partie",
                                              "Aucune partie n'existe encore. Titre de la première partie :")
            if not ok:
                return
            # create_part + assign_chapters_to_part sont deux actions annulables distinctes ;
            # acceptable ici (un Ctrl+Z ramène juste l'assignation, un second la partie vide).
            self.controller.create_part(title)
            part_id = self._document().structure.parts()[-1].id
        else:
            labels = [p.title or "(partie sans titre)" for p in parts]
            label, ok = QInputDialog.getItem(self, "Assigner à une partie",
                                              f"{len(chapter_ids)} chapitre(s) sélectionné(s). Choisir la partie :",
                                              labels, editable=False)
            if not ok:
                return
            part_id = parts[labels.index(label)].id

        chapter_ids = sorted(chapter_ids, key=self._file_and_position_sort_key)
        self.controller.assign_chapters_to_part(chapter_ids, part_id)

    def _unassign_selected(self) -> None:
        chapter_ids = self._selected_chapter_ids()
        if not chapter_ids:
            QMessageBox.information(self, "Retirer de la partie",
                                     "Sélectionnez d'abord un ou plusieurs chapitres (Ctrl+clic ou Shift+clic).")
            return
        self.controller.unassign_chapters(chapter_ids)

    def _delete_selected(self) -> None:
        """Suppression définitive (chapitre : texte compris ; partie : groupement seul, ses
        chapitres redeviennent libres) — n'affecte jamais le fichier .odt source, uniquement
        le projet Epubeur en cours. Ctrl+Z permet de revenir en arrière tant que le projet
        n'est pas fermé/rouvert."""
        cover_kind = self._selected_cover_kind()
        if cover_kind is not None:
            label = "la couverture" if cover_kind == "cover" else "la 4e de couverture"
            reply = QMessageBox.question(
                self, "Supprimer", f"Retirer {label} du livre ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Yes:
                if cover_kind == "cover":
                    self.controller.remove_cover_asset()
                else:
                    self.controller.remove_back_cover_asset()
            return

        part_id = self._selected_part_id()
        if part_id:
            part = next((p for p in self._document().structure.parts() if p.id == part_id), None)
            if part is None:
                return
            reply = QMessageBox.question(
                self, "Supprimer la partie",
                f"Supprimer la partie « {part.title or '(sans titre)'} » ?\n\n"
                "Ses chapitres ne seront pas supprimés : ils redeviendront des chapitres libres.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.controller.delete_part(part_id)
            return

        chapter_ids = self._selected_chapter_ids()
        if not chapter_ids:
            QMessageBox.information(self, "Supprimer", "Sélectionnez d'abord un ou plusieurs chapitres.")
            return

        if len(chapter_ids) == 1:
            chapter = self._document().chapters.get(chapter_ids[0])
            label = chapter.title if chapter and chapter.title else "(chapitre sans titre)"
            message = f"Supprimer définitivement le chapitre « {label} » et tout son texte ?"
        else:
            message = f"Supprimer définitivement ces {len(chapter_ids)} chapitres et tout leur texte ?"

        reply = QMessageBox.question(
            self, "Supprimer", message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for chapter_id in chapter_ids:
            self.controller.delete_chapter(chapter_id)

    def _merge_selected_with_next(self) -> None:
        chapter_id = self._selected_chapter_id()
        if not chapter_id:
            QMessageBox.information(self, "Fusion", "Sélectionnez d'abord un chapitre.")
            return

        item = self.tree.selectedItems()[0]
        parent_item = item.parent()
        if parent_item is None:
            return
        index = parent_item.indexOfChild(item)
        if index + 1 >= parent_item.childCount():
            QMessageBox.information(self, "Fusion", "Pas de chapitre suivant dans cette partie.")
            return
        next_item = parent_item.child(index + 1)
        next_chapter_id = next_item.data(0, CHAPTER_ROLE)
        if not next_chapter_id:
            return

        self.controller.merge_chapters(chapter_id, next_chapter_id)

    def _split_selected(self) -> None:
        chapter_id = self._selected_chapter_id()
        if not chapter_id:
            QMessageBox.information(self, "Scission", "Sélectionnez d'abord un chapitre.")
            return
        chapter = self._document().chapters.get(chapter_id)
        if chapter is None or len(chapter.paragraphs) < 2:
            QMessageBox.information(self, "Scission", "Ce chapitre n'a pas assez de paragraphes à scinder.")
            return

        dialog = ChapterSplitDialog(chapter, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_index is not None:
            self.controller.split_chapter(chapter_id, dialog.selected_index)

    def _build_context_menu(self, item: QTreeWidgetItem | None) -> QMenu:
        """Construit le menu contextuel pour l'item cliqué (ou None pour un clic sur du vide) —
        séparé de l'affichage (exec) pour rester testable sans ouvrir une boucle modale."""
        menu = QMenu(self)
        chapter_id = item.data(0, CHAPTER_ROLE) if item is not None else None
        part_id = item.data(0, PART_ROLE) if item is not None else None
        cover_kind = item.data(0, COVER_ROLE) if item is not None else None

        if cover_kind is not None:
            menu.addAction("Aller à l'onglet Couverture", self.cover_tab_requested.emit)
            menu.addSeparator()
            menu.addAction("Supprimer", self._delete_selected)
        elif chapter_id is not None:
            menu.addAction("Renommer", self._rename_selected)
            menu.addAction("Assigner à une partie", self._assign_selected_to_part)
            menu.addAction("Retirer de la partie", self._unassign_selected)
            menu.addSeparator()
            menu.addAction("Fusionner avec le chapitre suivant", self._merge_selected_with_next)
            menu.addAction("Scinder le chapitre", self._split_selected)
            menu.addSeparator()
            menu.addAction("Supprimer", self._delete_selected)
        elif part_id is not None:
            menu.addAction("Renommer", self._rename_selected)
            menu.addSeparator()
            menu.addAction("Nouvelle partie", self._create_part)
            menu.addSeparator()
            menu.addAction("Supprimer", self._delete_selected)
        else:
            menu.addAction("Nouvelle partie", self._create_part)

        return menu

    def _show_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        # Clic droit sur un item non sélectionné : on le sélectionne d'abord, sinon le menu
        # agirait sur une sélection différente de celle visée par l'utilisateur. Un clic droit
        # sur du vide (item is None) conserve la sélection courante telle quelle.
        if item is not None and item not in self.tree.selectedItems():
            self.tree.setCurrentItem(item)

        menu = self._build_context_menu(item)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _on_selection_changed(self) -> None:
        # Synchronise toute édition de texte en attente AVANT de changer de chapitre affiché
        # dans ChapterPreview — sinon un clic direct de l'éditeur vers l'arbre pourrait perdre
        # le texte en cours (l'ordre entre le traitement de la sélection et focusOutEvent n'est
        # pas garanti). Seulement si le chapitre affiché va RÉELLEMENT changer : cette méthode
        # est aussi appelée par refresh() pour un chapters_changed qui laisse la sélection
        # inchangée (ex. undo()/redo(), ou toute mutation du modèle courant) — y synchroniser
        # quand même comparerait le document Qt encore affiché (pas reconstruit) à un modèle qui
        # vient de changer sous ses pieds pour une tout autre raison, et réécrirait dessus
        # l'ancien contenu affiché, annulant silencieusement la mutation qui vient d'avoir lieu
        # (constaté avec Ctrl+Z : le undo semblait ne rien faire). show_chapter() (ligne 584)
        # gère seul et correctement la reconstruction dans ce cas, sans synchro préalable.
        if self._selected_chapter_id() != self.preview._chapter_id:
            self.preview.sync_pending_edits()

        cover_kind = self._selected_cover_kind()
        if cover_kind is not None:
            document = self._document()
            asset_id = document.cover_asset_id if cover_kind == "cover" else document.back_cover_asset_id
            if asset_id is not None:
                self.cover_image_preview.show_image(self.controller.asset_store.path_for(asset_id))
            self.preview_stack.setCurrentWidget(self.cover_image_preview)
            return

        part_id = self._selected_part_id()
        if part_id is not None:
            part = next((p for p in self._document().structure.parts() if p.id == part_id), None)
            if part is not None and part.has_title_page:
                title = part.title or "(partie sans titre)"
                self.part_title_page_preview.set_title(title)
            else:
                # Pas de page de garde pour cette partie : rien ne sera inséré dans l'EPUB à cet
                # endroit. Un panneau vide serait ambigu (on pourrait croire à une page blanche
                # bug/chargement) — un message explicite (gris pâle, jamais confondu avec un vrai
                # titre) rappelle l'état ET l'action pour en ajouter une.
                self.part_title_page_preview.show_no_title_page()
            self.preview_stack.setCurrentWidget(self.part_title_page_preview)
            return
        self.preview_stack.setCurrentWidget(self._preview_container)
        self.preview.show_chapter(self._selected_chapter_id())

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        part_id = item.data(0, PART_ROLE)
        if part_id is None:
            return  # ce n'est pas un item de partie (les chapitres n'ont pas de checkbox)
        has_title_page = item.checkState(0) == Qt.CheckState.Checked
        # Qt est encore en train de traiter l'événement itemChanged sur cet item : appeler
        # set_part_title_page() directement ici déclenche structure_changed -> refresh() ->
        # tree.clear(), qui détruit l'item en cours de traitement et fait planter l'app
        # (crash natif Qt, sans trace Python). On diffère l'appel après la fin du traitement.
        QTimer.singleShot(0, lambda: self.controller.set_part_title_page(part_id, has_title_page))

    def _on_rows_moved(self, *args) -> None:
        document = self._document()
        parts_by_id = {p.id: p for p in document.structure.parts()}
        new_items: list = []

        for i in range(self.tree.topLevelItemCount()):
            top_item = self.tree.topLevelItem(i)
            part_id = top_item.data(0, PART_ROLE)
            if part_id is not None:
                part = parts_by_id.get(part_id)
                if part is None:
                    continue
                # On persiste l'ordre affiché tel quel : c'est le geste de l'utilisateur
                # (drag & drop) qui fait foi, aucun retri automatique n'est appliqué ni ici
                # ni dans refresh().
                new_chapter_ids = []
                for j in range(top_item.childCount()):
                    child = top_item.child(j)
                    chapter_id = child.data(0, CHAPTER_ROLE)
                    if chapter_id:
                        new_chapter_ids.append(chapter_id)
                new_items.append(Part(id=part.id, title=part.title, chapter_ids=new_chapter_ids,
                                       has_title_page=part.has_title_page))
            else:
                # Top-level item sans PART_ROLE : un chapitre libre — contribue directement à
                # la séquence, à sa position exacte, comme n'importe quelle Part.
                chapter_id = top_item.data(0, CHAPTER_ROLE)
                if chapter_id:
                    new_items.append(chapter_id)

        # L'état de l'arbre est lu ci-dessus de façon synchrone (nécessaire : il doit refléter
        # le drop qui vient d'avoir lieu). Mais appliquer la mutation tout de suite peut arriver
        # alors que Qt n'a pas fini de stabiliser son propre état interne après le drop (sélection,
        # focus) — observé : un premier drag&drop vers une partie semblait ne pas "prendre"
        # avant un second geste. On diffère donc l'application au tour d'event loop suivant,
        # même principe que pour la checkbox de page de garde (cf. _on_item_changed).
        QTimer.singleShot(0, lambda: self.controller.apply_reordered_structure(new_items))

    def _on_external_file_dropped(self, path: Path) -> None:
        """Un fichier externe déposé sur l'arbre de Structure : .odt/.epub routés vers le même
        import que l'onglet Import (dispatch_odt_import / import_epub_file), .epbz relayé en
        ouverture de projet (project_dropped, cf. ImportListWidget) — sans cette discrimination,
        déposer un .odt ici déclenchait à tort le chemin image (add_image_as_chapter), qui refuse
        maintenant tout format hors PNG/JPEG et affichait donc une alerte absurde pour un .odt."""
        suffix = path.suffix.lower()
        if suffix == ".epbz":
            self.project_dropped.emit(path)
        elif suffix == ".odt":
            dispatch_odt_import(self.controller, path, self)
        elif suffix == ".epub":
            self.controller.import_epub_file(path)
        else:
            self.controller.add_image_as_chapter(path)
