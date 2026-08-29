from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from controller import ProjectController
from model.assets import AssetRole
from model.document import ImageDisplaySize, ImageWrap, iter_all_paragraphs
from ui.no_scroll_combo import NoScrollComboBox

THUMB_SIZE = 96
ALT_TEXT_EDIT_HEIGHT = 60  # QTextEdit compact (~3 lignes) : une description peut être une phrase

SIZE_LABELS: dict[ImageDisplaySize, str] = {
    ImageDisplaySize.SMALL: "Petite (25%)",
    ImageDisplaySize.MEDIUM: "Moyenne (50%)",
    ImageDisplaySize.LARGE: "Grande (75%)",
    ImageDisplaySize.FULL: "Pleine largeur (100%)",
}

WRAP_LABELS: dict[ImageWrap, str] = {
    ImageWrap.NONE: "Aucun (bloc centré)",
    ImageWrap.LEFT: "Habillage à gauche",
    ImageWrap.RIGHT: "Habillage à droite",
}


class _AltTextEdit(QTextEdit):
    """QTextEdit (multi-lignes, retour à la ligne automatique) plutôt que QLineEdit : une
    description d'image (texte alternatif) est souvent une phrase complète, illisible tronquée/
    défilant horizontalement dans un champ mono-ligne. editingFinished n'existe que sur
    QLineEdit — émulé ici via la perte de focus, seul déclencheur pertinent pour un champ
    multi-lignes où Entrée doit rester un retour à la ligne normal, pas une validation."""

    editingFinished = Signal()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.editingFinished.emit()


INVALID_FILENAME_CHARS = '/\\:*?"<>|'


class _RenameWidget(QWidget):
    """Nom de fichier affiché + bouton "Renommer" : au clic, le label devient un QLineEdit
    éditable pré-rempli avec le nom SANS extension (l'extension reste affichée à côté, jamais
    éditable — cf. AssetStore.rename qui la conserve toujours telle quelle). Validation par
    Entrée ou perte de focus ; un nom vide après filtrage revient au nom précédent (no-op)."""

    renamed = Signal(str, str)  # (asset_id, new_stem)

    def __init__(self, asset_id: str, filename: str, bold: bool = False, parent=None):
        super().__init__(parent)
        self.asset_id = asset_id
        self._stem = Path(filename).stem
        self._extension = Path(filename).suffix  # inclut le point, ex. ".jpg"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._stack = QStackedLayout()

        label_text = f"<b>{filename}</b>" if bold else filename
        self.name_label = QLabel(label_text, self)
        self._stack.addWidget(self.name_label)

        edit_row = QWidget(self)
        edit_row_layout = QHBoxLayout(edit_row)
        edit_row_layout.setContentsMargins(0, 0, 0, 0)
        self.name_edit = QLineEdit(edit_row)
        self.name_edit.textEdited.connect(self._strip_invalid_chars)
        self.name_edit.editingFinished.connect(self._commit)
        edit_row_layout.addWidget(self.name_edit)
        edit_row_layout.addWidget(QLabel(self._extension, edit_row))
        self._stack.addWidget(edit_row)

        layout.addLayout(self._stack, 1)

        self.rename_btn = QPushButton("Renommer")
        self.rename_btn.clicked.connect(self._start_rename)
        layout.addWidget(self.rename_btn)

    def _start_rename(self) -> None:
        self.name_edit.setText(self._stem)
        self._stack.setCurrentIndex(1)
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def _strip_invalid_chars(self, text: str) -> None:
        cleaned = "".join(c for c in text if c not in INVALID_FILENAME_CHARS)
        if cleaned != text:
            cursor_pos = self.name_edit.cursorPosition()
            self.name_edit.setText(cleaned)
            self.name_edit.setCursorPosition(min(cursor_pos, len(cleaned)))

    def _commit(self) -> None:
        if self._stack.currentIndex() != 1:
            return
        new_stem = self.name_edit.text().strip()
        self._stack.setCurrentIndex(0)
        if not new_stem or new_stem == self._stem:
            return
        self._stem = new_stem
        self.name_label.setText(f"{new_stem}{self._extension}")
        # QTimer.singleShot(0, ...) : émettre renamed ici, en plein traitement du signal
        # editingFinished du QLineEdit (donc en plein changement de focus Qt), déclenche en
        # cascade ImageGallery.refresh() qui détruit CE widget (et son QLineEdit encore en train
        # de gérer son propre évènement de focus) — source du clignotement de fenêtres observé à
        # chaque renommage. Différer d'un tick d'event loop laisse Qt terminer proprement le
        # changement de focus avant que la reconstruction de la galerie ne commence.
        asset_id, stem = self.asset_id, new_stem
        QTimer.singleShot(0, lambda: self.renamed.emit(asset_id, stem))


class _OrphanImageBlock(QWidget):
    """Bloc simplifié pour une image "orpheline" (non référencée par aucun chapitre/couverture,
    ex. après un retrait via _ImageBlock.remove_btn) : vignette + nom + bouton de suppression
    définitive uniquement — pas de combos taille/habillage/description, qui n'ont plus rien à
    quoi s'appliquer tant qu'elle n'est pas réutilisée."""

    delete_requested = Signal(str)  # asset_id
    renamed = Signal(str, str)  # (asset_id, new_stem)
    copy_requested = Signal(str)  # asset_id

    def __init__(self, asset_id: str, thumbnail: QPixmap, filename: str, parent=None):
        super().__init__(parent)
        self.asset_id = asset_id

        layout = QHBoxLayout(self)

        thumb_label = QLabel(self)  # parent=self dès la construction, cf. commentaire _ImageBlock
        if not thumbnail.isNull():
            thumb_label.setPixmap(thumbnail.scaled(THUMB_SIZE, THUMB_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))
        thumb_label.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(thumb_label)

        right = QVBoxLayout()
        self.rename_widget = _RenameWidget(asset_id, filename)
        self.rename_widget.renamed.connect(self.renamed)
        right.addWidget(self.rename_widget)
        empty_label = QLabel("Utilisée dans aucun chapitre", self)
        empty_label.setStyleSheet("color: #c0392b; font-weight: bold;")
        right.addWidget(empty_label)
        layout.addLayout(right, 1)

        self.copy_btn = QPushButton("Copier l'image")
        self.copy_btn.clicked.connect(lambda: self.copy_requested.emit(self.asset_id))
        layout.addWidget(self.copy_btn)

        self.delete_btn = QPushButton("Supprimer définitivement")
        self.delete_btn.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold;")
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        layout.addWidget(self.delete_btn)

    def _on_delete_clicked(self) -> None:
        reply = QMessageBox.question(
            self, "Supprimer l'image",
            "Supprimer définitivement cette image du projet ? Le fichier sera effacé du disque "
            "et cette action ne peut pas être annulée (Ctrl+Z).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.delete_requested.emit(self.asset_id)


class _ImageBlock(QWidget):
    """Un bloc par image : vignette à gauche, nom + liste dépliable des chapitres qui
    l'utilisent à droite — chaque titre de chapitre est un bouton cliquable qui navigue
    directement vers ce chapitre dans l'onglet Structure."""

    chapter_activated = Signal(str)  # chapter_id
    size_changed = Signal(str, object)  # (asset_id, ImageDisplaySize)
    wrap_changed = Signal(str, object)  # (asset_id, ImageWrap)
    alt_text_changed = Signal(str, str)  # (asset_id, alt_text)
    remove_requested = Signal(str)  # asset_id
    renamed = Signal(str, str)  # (asset_id, new_stem)
    copy_requested = Signal(str)  # asset_id

    def __init__(self, asset_id: str, thumbnail: QPixmap, filename: str,
                 chapters_using: list[tuple[str, str]], current_size: ImageDisplaySize,
                 current_wrap: ImageWrap, current_alt_text: str, alt_text_candidates: list[str], parent=None):
        """chapters_using : liste de (chapter_id, titre_affiché). alt_text_candidates : toutes
        les descriptions distinctes trouvées dans les fichiers sources pour cette image (voir
        Document.image_alt_text_candidates) — permet de cycler entre elles quand plusieurs
        fichiers ODT fondus dans le projet décrivent la même image différemment."""
        super().__init__(parent)
        self.asset_id = asset_id
        self.current_alt_text = current_alt_text
        self.alt_text_candidates = alt_text_candidates
        # Index dans alt_text_candidates actuellement affiché dans le champ (navigation par
        # flèches) — indépendant de current_alt_text tant que "Valider" n'a pas été cliqué.
        self._browse_index = alt_text_candidates.index(current_alt_text) if current_alt_text in alt_text_candidates else 0

        layout = QHBoxLayout(self)

        # parent=self dès la construction (pas seulement via layout.addWidget ensuite) : un
        # QLabel/QWidget créé sans parent existe, ne serait-ce que brièvement, comme une fenêtre
        # top-level à part entière pour Qt — sur Windows, ça peut se traduire par un flash de
        # petite fenêtre blanche vide visible à l'écran pendant une reconstruction massive de
        # blocs (ex. import .odt avec plusieurs images, ou refresh() de la galerie), constaté
        # empiriquement (diagnostic : QLabel sans parent rapporté comme fenêtre top-level
        # visible=True avec une géométrie réelle à l'écran).
        thumb_label = QLabel(self)
        if not thumbnail.isNull():
            thumb_label.setPixmap(thumbnail.scaled(THUMB_SIZE, THUMB_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))
        thumb_label.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(thumb_label)

        right = QVBoxLayout()
        name_row = QHBoxLayout()
        self.rename_widget = _RenameWidget(asset_id, filename, bold=True)
        self.rename_widget.renamed.connect(self.renamed)
        name_row.addWidget(self.rename_widget, 1)
        self.copy_btn = QPushButton("Copier l'image")
        self.copy_btn.clicked.connect(lambda: self.copy_requested.emit(self.asset_id))
        name_row.addWidget(self.copy_btn)
        self.remove_btn = QPushButton("Retirer cette image du livre")
        self.remove_btn.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold;")
        self.remove_btn.clicked.connect(self._on_remove_clicked)
        name_row.addWidget(self.remove_btn)
        right.addLayout(name_row)

        if not chapters_using:
            empty_label = QLabel("Utilisée dans aucun chapitre")
            empty_label.setStyleSheet("color: #c0392b; font-weight: bold;")
            right.addWidget(empty_label)
        else:
            right.addWidget(QLabel(f"Utilisée dans {len(chapters_using)} chapitre(s) :"))
            for chapter_id, title in chapters_using:
                link_btn = QPushButton(f"→ {title}")
                link_btn.setStyleSheet("text-align: left; border: none; color: #2a6fdb;")
                link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                link_btn.clicked.connect(lambda _checked=False, cid=chapter_id: self.chapter_activated.emit(cid))
                right.addWidget(link_btn)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Taille d'affichage :"))
        self.size_combo = NoScrollComboBox()
        for size, label in SIZE_LABELS.items():
            self.size_combo.addItem(label, size)
        self.size_combo.setCurrentIndex(list(SIZE_LABELS.keys()).index(current_size))
        self.size_combo.currentIndexChanged.connect(self._on_size_changed)
        size_row.addWidget(self.size_combo)
        size_row.addStretch()
        right.addLayout(size_row)

        wrap_row = QHBoxLayout()
        wrap_row.addWidget(QLabel("Habillage du texte :"))
        self.wrap_combo = NoScrollComboBox()
        for wrap, label in WRAP_LABELS.items():
            self.wrap_combo.addItem(label, wrap)
        self.wrap_combo.setCurrentIndex(list(WRAP_LABELS.keys()).index(current_wrap))
        self.wrap_combo.currentIndexChanged.connect(self._on_wrap_changed)
        wrap_row.addWidget(self.wrap_combo)
        wrap_row.addStretch()
        right.addLayout(wrap_row)

        right.addWidget(QLabel("Description (texte alternatif, accessibilité) :"))

        alt_row = QHBoxLayout()
        has_multiple_candidates = len(alt_text_candidates) > 1
        if has_multiple_candidates:
            self.prev_alt_btn = QPushButton("←")
            self.prev_alt_btn.setFixedWidth(30)
            self.prev_alt_btn.clicked.connect(self._on_prev_alt_text)
            alt_row.addWidget(self.prev_alt_btn)

        self.alt_text_edit = _AltTextEdit()
        self.alt_text_edit.setPlainText(current_alt_text)
        self.alt_text_edit.setPlaceholderText("ex. Un gobelin brandissant une épée")
        self.alt_text_edit.setFixedHeight(ALT_TEXT_EDIT_HEIGHT)
        self.alt_text_edit.editingFinished.connect(self._on_alt_text_edited)
        self.alt_text_edit.textChanged.connect(self._update_alt_text_style)
        alt_row.addWidget(self.alt_text_edit, 1)

        if has_multiple_candidates:
            self.next_alt_btn = QPushButton("→")
            self.next_alt_btn.setFixedWidth(30)
            self.next_alt_btn.clicked.connect(self._on_next_alt_text)
            alt_row.addWidget(self.next_alt_btn)

            self.validate_alt_btn = QPushButton("Valider cette description")
            self.validate_alt_btn.clicked.connect(self._on_validate_alt_text)
            alt_row.addWidget(self.validate_alt_btn)

        right.addLayout(alt_row)
        self._update_alt_text_style()

        right.addStretch()
        layout.addLayout(right, 1)

    def _update_alt_text_style(self) -> None:
        """Cadre vert quand le texte affiché correspond à la description actuellement retenue
        pour l'image (self.current_alt_text) — inutile à afficher s'il n'y a qu'un seul
        candidat possible (rien à distinguer)."""
        if len(self.alt_text_candidates) <= 1:
            return
        if self.alt_text_edit.toPlainText() == self.current_alt_text:
            self.alt_text_edit.setStyleSheet("border: 2px solid #2e7d32;")
        else:
            self.alt_text_edit.setStyleSheet("")

    def _on_prev_alt_text(self) -> None:
        self._browse_index = (self._browse_index - 1) % len(self.alt_text_candidates)
        self.alt_text_edit.setPlainText(self.alt_text_candidates[self._browse_index])

    def _on_next_alt_text(self) -> None:
        self._browse_index = (self._browse_index + 1) % len(self.alt_text_candidates)
        self.alt_text_edit.setPlainText(self.alt_text_candidates[self._browse_index])

    def _on_validate_alt_text(self) -> None:
        text = self.alt_text_edit.toPlainText()
        reply = QMessageBox.question(
            self, "Valider la description",
            "Cette description sera retenue pour cette image partout où elle apparaît. "
            "Les autres descriptions trouvées dans les fichiers sources ne seront plus "
            "proposées. Continuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.current_alt_text = text
        if text in self.alt_text_candidates:
            self._browse_index = self.alt_text_candidates.index(text)
        self._update_alt_text_style()
        self.alt_text_changed.emit(self.asset_id, text)

    def _on_size_changed(self, index: int) -> None:
        self.size_changed.emit(self.asset_id, self.size_combo.itemData(index))

    def _on_wrap_changed(self, index: int) -> None:
        self.wrap_changed.emit(self.asset_id, self.wrap_combo.itemData(index))

    def _on_alt_text_edited(self) -> None:
        text = self.alt_text_edit.toPlainText()
        self.current_alt_text = text
        self._update_alt_text_style()
        self.alt_text_changed.emit(self.asset_id, text)

    def _on_remove_clicked(self) -> None:
        reply = QMessageBox.question(
            self, "Retirer l'image",
            "Retirer cette image de TOUTES ses occurrences dans le livre ? Si un chapitre entier "
            "n'était constitué que de cette image, il sera également supprimé.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.remove_requested.emit(self.asset_id)


class ImageGallery(QWidget):
    """Une ligne par image de chapitre unique (dédupliquée), avec sous chaque image la liste
    dépliable des chapitres qui la réutilisent, cliquables pour y naviguer directement."""

    chapter_activated = Signal(str)  # chapter_id — relayé par MainWindow vers StructureEditor

    def __init__(self, controller: ProjectController, parent=None):
        super().__init__(parent)
        self.controller = controller

        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Images présentes dans le livre (dédupliquées automatiquement) :"))

        self.add_image_btn = QPushButton("Ajouter une image")
        self.add_image_btn.clicked.connect(self._on_add_image_clicked)
        layout.addWidget(self.add_image_btn)

        global_row = QHBoxLayout()
        global_row.addWidget(QLabel("Appliquer une taille à toutes les images :"))
        self.global_size_combo = NoScrollComboBox()
        for size, label in SIZE_LABELS.items():
            self.global_size_combo.addItem(label, size)
        # Doit correspondre à la valeur par défaut réelle d'une image (ImageDisplaySize.FULL,
        # cf. Document.image_display_size) — sinon le bouton affiche "25%" sans qu'aucune image
        # n'ait jamais été réglée à cette taille, ce qui est déstabilisant pour l'utilisateur.
        self.global_size_combo.setCurrentIndex(list(SIZE_LABELS.keys()).index(ImageDisplaySize.FULL))
        global_row.addWidget(self.global_size_combo)
        self.apply_all_btn = QPushButton("Appliquer")
        self.apply_all_btn.clicked.connect(self._on_apply_all_clicked)
        global_row.addWidget(self.apply_all_btn)
        global_row.addStretch()
        layout.addLayout(global_row)

        global_wrap_row = QHBoxLayout()
        global_wrap_row.addWidget(QLabel("Appliquer un habillage à toutes les images :"))
        self.global_wrap_combo = NoScrollComboBox()
        for wrap, label in WRAP_LABELS.items():
            self.global_wrap_combo.addItem(label, wrap)
        self.global_wrap_combo.setCurrentIndex(list(WRAP_LABELS.keys()).index(ImageWrap.NONE))
        global_wrap_row.addWidget(self.global_wrap_combo)
        self.apply_all_wrap_btn = QPushButton("Appliquer")
        self.apply_all_wrap_btn.clicked.connect(self._on_apply_all_wrap_clicked)
        global_wrap_row.addWidget(self.apply_all_wrap_btn)
        global_wrap_row.addStretch()
        layout.addLayout(global_wrap_row)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.addStretch()
        self.scroll_area.setWidget(self.content)
        layout.addWidget(self.scroll_area)

        self.controller.assets_changed.connect(self.refresh)
        self.controller.chapters_changed.connect(self.refresh)
        self.refresh()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                self.controller.add_image_as_chapter(Path(local))
                break
        event.acceptProposedAction()

    def _on_add_image_clicked(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(self, "Ajouter une image", "", "Images (*.png *.jpg *.jpeg)")
        if path_str:
            self.controller.add_image_as_chapter(Path(path_str))

    def _on_apply_all_clicked(self) -> None:
        size = self.global_size_combo.currentData()
        self.controller.set_all_images_display_size(size)

    def _on_apply_all_wrap_clicked(self) -> None:
        wrap = self.global_wrap_combo.currentData()
        self.controller.set_all_images_wrap(wrap)

    def refresh(self) -> None:
        # refresh() reconstruit tous les blocs à chaque changement (ex. un simple renommage) —
        # sans ça, la QScrollArea revient en haut à chaque fois, ultra pénible pour renommer une
        # image loin dans une longue galerie. La restauration doit être différée : la hauteur
        # réelle du nouveau contenu n'est connue qu'une fois que Qt a fini de layouter les blocs
        # qu'on s'apprête à recréer ci-dessous, donc pas encore au moment de cet appel.
        scroll_pos = self.scroll_area.verticalScrollBar().value()
        QTimer.singleShot(0, lambda: self.scroll_area.verticalScrollBar().setValue(scroll_pos))

        # setUpdatesEnabled(False) sur toute la fenêtre (pas seulement self.content) : refresh()
        # détruit et recrée tous les blocs à chaque appel — même un simple renommage en déclenche
        # un. Désactiver le rendu du seul widget local ne suffit pas à empêcher Windows/Qt de
        # repeindre la fenêtre top-level pendant la reconstruction (constaté empiriquement : des
        # dizaines de cycles Show/Hide/WindowActivate sur la fenêtre principale pendant un
        # refresh, visibles comme un flash) — il faut couper au niveau de la fenêtre elle-même.
        window = self.window()
        window.setUpdatesEnabled(False)
        try:
            while self.content_layout.count() > 1:
                item = self.content_layout.takeAt(0)
                if item.widget() is not None:
                    item.widget().deleteLater()

            self._rebuild_blocks()
        finally:
            window.setUpdatesEnabled(True)

    def _rebuild_blocks(self) -> None:
        document = self.controller.project.document

        usage: dict[str, list[tuple[str, str]]] = {}
        for chapter in document.chapters.values():
            seen_in_chapter: set[str] = set()
            for para in iter_all_paragraphs(chapter.paragraphs):
                for image in para.all_images():
                    if image.asset_id in seen_in_chapter:
                        continue
                    seen_in_chapter.add(image.asset_id)
                    usage.setdefault(image.asset_id, []).append(
                        (chapter.id, chapter.title or "(chapitre sans titre)"))

        chapter_pov_assets = [a for a in self.controller.asset_store.all_assets() if a.role == AssetRole.CHAPTER_POV]
        # is_asset_referenced() couvre aussi la couverture/4e de couverture — un asset CHAPTER_POV
        # n'a normalement pas ce rôle-là, mais le test reste correct dans tous les cas.
        used_assets = [a for a in chapter_pov_assets if document.is_asset_referenced(a.id)]
        orphan_assets = [a for a in chapter_pov_assets if not document.is_asset_referenced(a.id)]

        for asset in used_assets:
            path = self.controller.asset_store.path_for(asset.id)
            pix = QPixmap(str(path))

            block = _ImageBlock(asset.id, pix, asset.original_filename, usage.get(asset.id, []),
                                 document.image_display_size(asset.id), document.image_wrap(asset.id),
                                 document.image_alt_text(asset.id), document.image_alt_text_candidates(asset.id))
            block.chapter_activated.connect(self.chapter_activated)
            block.size_changed.connect(self.controller.set_image_display_size)
            block.wrap_changed.connect(self.controller.set_image_wrap)
            block.alt_text_changed.connect(self.controller.set_image_alt_text)
            block.remove_requested.connect(self.controller.remove_image_everywhere)
            block.renamed.connect(self.controller.rename_image)
            block.copy_requested.connect(self.controller.copy_image_to_clipboard)
            self.content_layout.insertWidget(self.content_layout.count() - 1, block)

        if orphan_assets:
            # parent=self dès la construction : recréé à chaque refresh() (assets_changed/
            # chapters_changed), un QLabel construit sans parent flashe brièvement comme fenêtre
            # top-level Windows tant qu'il n'est pas reparenté par insertWidget ci-dessous.
            self.orphans_label = QLabel(
                "Images orphelines (retirées du livre, non utilisées — n'apparaîtront jamais "
                "dans l'EPUB généré tant qu'elles ne sont pas réutilisées) :", self)
            self.orphans_label.setStyleSheet("color: #888; margin-top: 1em;")
            self.orphans_label.setWordWrap(True)
            self.content_layout.insertWidget(self.content_layout.count() - 1, self.orphans_label)

            for asset in orphan_assets:
                path = self.controller.asset_store.path_for(asset.id)
                pix = QPixmap(str(path))
                orphan_block = _OrphanImageBlock(asset.id, pix, asset.original_filename)
                orphan_block.delete_requested.connect(self.controller.delete_orphaned_asset)
                orphan_block.renamed.connect(self.controller.rename_image)
                orphan_block.copy_requested.connect(self.controller.copy_image_to_clipboard)
                self.content_layout.insertWidget(self.content_layout.count() - 1, orphan_block)
