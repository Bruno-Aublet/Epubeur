from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from controller import ProjectController
from model.assets import AssetRole


class DropZone(QLabel):
    """Zone de dépôt d'image : occupe tout l'espace disponible (Expanding) plutôt qu'une taille
    fixe, pour rester lisible même sur une grande fenêtre. Le pixmap est re-scalé à chaque
    resizeEvent puisque la taille du widget n'est plus connue à l'avance."""

    def __init__(self, title: str, on_file_dropped, on_remove_requested, parent=None):
        super().__init__(parent)
        self.title = title
        self.on_file_dropped = on_file_dropped
        self.on_remove_requested = on_remove_requested
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(200, 200)
        self.setStyleSheet("border: 2px dashed #888; color: #888;")
        self.setText("(glisser une image ici)")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self._pixmap: QPixmap | None = None
        self._has_image = False

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                self.on_file_dropped(Path(local))
                break
        event.acceptProposedAction()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._pixmap is not None:
            self._rescale()

    def _rescale(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            return
        self.setPixmap(self._pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))

    def show_pixmap(self, path: Path) -> None:
        self._pixmap = QPixmap(str(path))
        self._has_image = True
        self._rescale()

    def clear_pixmap(self) -> None:
        self._pixmap = None
        self._has_image = False
        self.setPixmap(QPixmap())
        self.setText("(glisser une image ici)")

    def _show_context_menu(self, pos) -> None:
        if not self._has_image:
            return
        menu = QMenu(self)
        remove_action = QAction("Supprimer l'image", self)
        remove_action.triggered.connect(self.on_remove_requested)
        menu.addAction(remove_action)
        menu.exec(self.mapToGlobal(pos))


class CoverColumn(QVBoxLayout):
    """Colonne compacte pour une image (couverture ou 4e de couverture) : titre fixe (toujours
    visible, même une fois l'image chargée — contrairement au texte interne de la DropZone qui
    disparaît sous le pixmap), zone de dépôt, nom technique du fichier dans l'EPUB généré (avec
    extension réelle — visible SEULEMENT quand une image est chargée, vide sinon), puis les
    boutons d'action directement collés — plus d'espace vide entre l'image et les commandes qui
    s'y rapportent. Le titre en haut est le libellé FRANÇAIS ("Couverture" / "4e de couverture") ;
    le nom technique sous l'image est celui que l'EPUB généré impose toujours
    ("cover.<ext>"/"back_cover.<ext>", cf. epub/builder.py), indépendant du nom du fichier
    d'origine importé."""

    def __init__(self, title: str, technical_name_prefix: str, on_file_dropped, on_removed, parent_widget: QWidget):
        super().__init__()
        self.on_removed = on_removed
        self.technical_name_prefix = technical_name_prefix

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-weight: bold;")
        self.addWidget(title_label)

        self.zone = DropZone(title, on_file_dropped, on_removed)
        self.addWidget(self.zone, 1)

        self.technical_label = QLabel("")
        self.technical_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.technical_label.setStyleSheet("color: #666;")
        self.addWidget(self.technical_label)

        buttons_row = QHBoxLayout()
        self.browse_btn = QPushButton("Parcourir")
        self.browse_btn.clicked.connect(lambda: parent_widget._browse(on_file_dropped))
        buttons_row.addWidget(self.browse_btn)
        self.remove_btn = QPushButton("Retirer")
        self.remove_btn.clicked.connect(on_removed)
        buttons_row.addWidget(self.remove_btn)
        self.addLayout(buttons_row)

    def set_extension(self, extension: str | None) -> None:
        self.technical_label.setText(f"{self.technical_name_prefix}.{extension}" if extension else "")


class CoverPanel(QWidget):
    def __init__(self, controller: ProjectController, parent=None):
        super().__init__(parent)
        self.controller = controller

        layout = QHBoxLayout(self)

        self.cover_col = CoverColumn("Couverture", "cover", self._on_cover_dropped, self._on_cover_removed, self)
        layout.addLayout(self.cover_col, 1)

        self.back_col = CoverColumn("4e de couverture", "back_cover", self._on_back_cover_dropped,
                                     self._on_back_cover_removed, self)
        layout.addLayout(self.back_col, 1)

        self.controller.assets_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        """Synchronise l'affichage avec l'état réel du document — source unique de vérité,
        appelée après toute action locale ET après toute mutation venue d'ailleurs (retrait
        depuis l'onglet Structure, undo/redo)."""
        document = self.controller.project.document

        if document.cover_asset_id:
            self.cover_col.zone.show_pixmap(self.controller.asset_store.path_for(document.cover_asset_id))
            self.cover_col.set_extension(self.controller.asset_store.get(document.cover_asset_id).extension)
        else:
            self.cover_col.zone.clear_pixmap()
            self.cover_col.set_extension(None)

        if document.back_cover_asset_id:
            self.back_col.zone.show_pixmap(self.controller.asset_store.path_for(document.back_cover_asset_id))
            self.back_col.set_extension(self.controller.asset_store.get(document.back_cover_asset_id).extension)
        else:
            self.back_col.zone.clear_pixmap()
            self.back_col.set_extension(None)

    def _browse(self, handler) -> None:
        path_str, _ = QFileDialog.getOpenFileName(self, "Choisir une image", "", "Images (*.png *.jpg *.jpeg)")
        if path_str:
            handler(Path(path_str))

    def _on_cover_dropped(self, path: Path) -> None:
        if not self.controller.warn_and_reject_if_unsupported(path):
            return
        asset = self.controller.asset_store.ingest_bytes(path.read_bytes(), path.name, AssetRole.COVER)
        self.controller.set_cover_asset(asset.id)  # émet assets_changed -> refresh()

    def _on_back_cover_dropped(self, path: Path) -> None:
        if not self.controller.warn_and_reject_if_unsupported(path):
            return
        asset = self.controller.asset_store.ingest_bytes(path.read_bytes(), path.name, AssetRole.BACK_COVER)
        self.controller.set_back_cover_asset(asset.id)  # émet assets_changed -> refresh()

    def _on_cover_removed(self) -> None:
        self.controller.remove_cover_asset()  # émet assets_changed -> refresh()

    def _on_back_cover_removed(self) -> None:
        self.controller.remove_back_cover_asset()  # émet assets_changed -> refresh()
