import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget
from PySide6.QtWebEngineWidgets import QWebEngineView

from ebooklib import epub

from controller import ProjectController
from epub.font_obfuscation import deobfuscate_extracted_epub
from ui.generate_controls import GenerateControls
from ui.no_scroll_combo import NoScrollComboBox

_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


class EpubPreview(QWidget):
    """Charge un EPUB généré et permet de naviguer chapitre par chapitre via QWebEngineView.
    Contient aussi son propre bouton de génération (GenerateControls) : l'onglet est accessible
    dès le début, pas seulement après une première génération — tant qu'aucun EPUB n'a été
    chargé, un message d'invitation remplace la zone de lecture."""

    def __init__(self, controller: ProjectController, metadata_provider, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._extract_dir: Path | None = None
        self._chapter_files: list[tuple[str, str]] = []  # (titre, chemin_absolu)

        layout = QVBoxLayout(self)

        self.generate_controls = GenerateControls(controller, metadata_provider)
        self.generate_controls.epub_generated.connect(self.load_epub)
        layout.addWidget(self.generate_controls)

        self.content_stack = QStackedWidget()

        self.empty_label = QLabel("Aucun EPUB généré pour l'instant. Cliquez sur « Générer l'EPUB » ci-dessus.")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet("color: #888; font-size: 18pt;")
        self.content_stack.addWidget(self.empty_label)

        self.reader = QWidget()
        reader_layout = QVBoxLayout(self.reader)
        reader_layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Chapitre :"))
        self.chapter_combo = NoScrollComboBox()
        toolbar.addWidget(self.chapter_combo, 1)
        self.prev_btn = QPushButton("←")
        self.next_btn = QPushButton("→")
        toolbar.addWidget(self.prev_btn)
        toolbar.addWidget(self.next_btn)
        reader_layout.addLayout(toolbar)

        self.view = QWebEngineView()
        reader_layout.addWidget(self.view)
        self.content_stack.addWidget(self.reader)

        layout.addWidget(self.content_stack)

        self.chapter_combo.currentIndexChanged.connect(self._show_chapter_at)
        self.prev_btn.clicked.connect(self._go_prev)
        self.next_btn.clicked.connect(self._go_next)

    def load_epub(self, epub_path: str) -> None:
        self.content_stack.setCurrentWidget(self.reader)
        previous_extract_dir = self._extract_dir
        self._extract_dir = Path(tempfile.mkdtemp(prefix="epubeur_preview_"))
        with zipfile.ZipFile(epub_path) as zf:
            zf.extractall(self._extract_dir)
        # Nettoyé seulement maintenant, une fois le nouveau dossier prêt à remplacer l'ancien
        # dans self.view — sinon régénérer l'EPUB plusieurs fois par session (flux normal de
        # relecture) accumule un dossier temp complet par génération, jamais supprimé.
        if previous_extract_dir is not None:
            shutil.rmtree(previous_extract_dir, ignore_errors=True)

        book = epub.read_epub(epub_path)

        identifiers = book.get_metadata("DC", "identifier")
        book_uid = identifiers[0][0] if identifiers else None
        if book_uid:
            # QWebEngineView n'est pas un vrai lecteur EPUB : il ne sait pas désobfusquer les
            # polices via encryption.xml comme le ferait Kobo/Apple Books, donc on le fait nous-mêmes
            # sur les fichiers extraits pour que l'aperçu affiche la police figée correctement.
            deobfuscate_extracted_epub(self._extract_dir, book_uid)
        self._chapter_files = []
        for item in book.get_items_of_type(9):  # ITEM_DOCUMENT = 9
            if item.file_name == "nav.xhtml":
                continue
            candidates = list(self._extract_dir.rglob(Path(item.file_name).name))
            if not candidates:
                continue
            file_path = candidates[0]
            title = getattr(item, "title", None) or self._extract_title(file_path) or item.file_name
            self._chapter_files.append((title, str(file_path)))

        self.chapter_combo.blockSignals(True)
        self.chapter_combo.clear()
        for title, _ in self._chapter_files:
            self.chapter_combo.addItem(title)
        self.chapter_combo.blockSignals(False)

        if self._chapter_files:
            self.chapter_combo.setCurrentIndex(0)
            self._show_chapter_at(0)

    def reset(self) -> None:
        """Revient à l'état vide (message d'invitation) — appelé à la fermeture du projet,
        pour ne pas laisser l'aperçu d'un projet précédent visible après sa fermeture."""
        if self._extract_dir is not None:
            shutil.rmtree(self._extract_dir, ignore_errors=True)
        self._extract_dir = None
        self._chapter_files = []
        self.chapter_combo.clear()
        self.content_stack.setCurrentWidget(self.empty_label)

    @staticmethod
    def _extract_title(path: Path) -> str | None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        match = _TITLE_RE.search(text)
        return match.group(1).strip() if match else None

    def _show_chapter_at(self, index: int) -> None:
        if index < 0 or index >= len(self._chapter_files):
            return
        _, path = self._chapter_files[index]
        self.view.load(QUrl.fromLocalFile(path))

    def _go_prev(self) -> None:
        idx = self.chapter_combo.currentIndex()
        if idx > 0:
            self.chapter_combo.setCurrentIndex(idx - 1)

    def _go_next(self) -> None:
        idx = self.chapter_combo.currentIndex()
        if idx < self.chapter_combo.count() - 1:
            self.chapter_combo.setCurrentIndex(idx + 1)
