from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QWidget

from controller import ProjectController
from epub.builder import EpubBuildError, build_epub
from model.book_metadata import BookMetadata
from model.error_messages import describe_epub_generation_error


class _BuildWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, controller: ProjectController, output_path: Path, metadata: BookMetadata):
        super().__init__()
        self.controller = controller
        self.output_path = output_path
        self.metadata = metadata

    def run(self) -> None:
        try:
            out = build_epub(
                self.controller.project,
                self.controller.asset_store,
                self.output_path,
                metadata=self.metadata,
            )
            self.finished.emit(str(out))
        except EpubBuildError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # sécurité : ne jamais planter le thread silencieusement
            self.failed.emit(describe_epub_generation_error(exc))


class GenerateControls(QWidget):
    """Bouton « Générer l'EPUB… » + statut, réutilisable dans plusieurs onglets (Métadonnées,
    Aperçu EPUB) sans dupliquer la logique de génération (thread, gestion d'erreurs, choix du
    fichier de sortie). `metadata_provider` est appelée au moment du clic pour récupérer les
    métadonnées courantes — pas de couplage direct entre les widgets qui hébergent ce contrôle."""

    epub_generated = Signal(str)

    def __init__(self, controller: ProjectController, metadata_provider: Callable[[], BookMetadata],
                 parent=None):
        super().__init__(parent)
        self.controller = controller
        self.metadata_provider = metadata_provider
        self._thread: QThread | None = None
        self._worker: _BuildWorker | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.generate_btn = QPushButton("Générer l'EPUB")
        self.generate_btn.setStyleSheet("font-size: 14pt; padding: 6px 16px;")
        layout.addWidget(self.generate_btn)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 14pt;")
        layout.addWidget(self.status_label, 1)

        self.generate_btn.clicked.connect(self._on_generate_clicked)
        # Sinon un statut "EPUB généré : ..." ou "Échec : ..." d'un projet précédent reste
        # affiché après "Fermer le projet" (close_project émet aussi project_loaded).
        self.controller.project_loaded.connect(lambda: self.status_label.setText(""))
        self.controller.project_loaded.connect(self._update_generate_enabled)
        self.controller.chapters_changed.connect(self._update_generate_enabled)
        self._update_generate_enabled()

    def _update_generate_enabled(self) -> None:
        self.generate_btn.setEnabled(bool(self.controller.project.document.chapters))

    def _default_output_dir(self) -> str:
        """Propose par défaut le dossier des fichiers .odt sources, pas un dossier arbitraire."""
        source_files = self.controller.project.source_odt_files
        if source_files:
            return str(source_files[0].path.parent)
        return ""

    def _on_generate_clicked(self) -> None:
        metadata = self.metadata_provider()

        default_dir = self._default_output_dir()
        default_name = f"{metadata.title}.epub" if metadata.title else "livre.epub"
        default_path = str(Path(default_dir) / default_name) if default_dir else default_name

        path_str, _ = QFileDialog.getSaveFileName(self, "Enregistrer l'EPUB", default_path, "EPUB (*.epub)")
        if not path_str:
            return
        output_path = Path(path_str)
        if output_path.suffix.lower() != ".epub":
            output_path = output_path.with_suffix(".epub")

        self.generate_btn.setEnabled(False)
        self.status_label.setText("Génération en cours")

        self._thread = QThread()
        self._worker = _BuildWorker(self.controller, output_path, metadata)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        # Pattern Qt standard : le worker et le thread ne sont explicitement libérés qu'une fois
        # le thread arrêté (thread.finished, pas worker.finished — ce dernier peut être émis
        # avant que la boucle d'événements du thread ait fini de traiter quit()). Sans ça, les
        # anciens objets restaient référencés jusqu'au passage du ramasse-miettes Python plutôt
        # que d'être explicitement nettoyés à chaque génération.
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_finished(self, output_path: str) -> None:
        self._update_generate_enabled()
        self.status_label.setText(f"EPUB généré : {output_path}")
        self.epub_generated.emit(output_path)

    def _on_failed(self, message: str) -> None:
        self._update_generate_enabled()
        self.status_label.setText(f"Échec : {message}")
        QMessageBox.warning(self, "Génération EPUB", message)
