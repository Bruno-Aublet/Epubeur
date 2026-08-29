from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QTabWidget

from controller import ProjectController
from model.recent_files import (
    add_recent_file,
    format_recent_timestamp,
    get_last_project_dir,
    list_recent_files,
    list_recent_projects,
    prune_missing,
    remove_recent_file,
    remove_recent_project,
    set_last_project_dir,
)
from model.update_checker import UpdateChecker
from model.version import __version__
from ui.cover_panel import CoverPanel
from ui.epub_preview import EpubPreview
from ui.font_selector import FontSelector
from ui.generate_panel import GeneratePanel
from ui.image_gallery import ImageGallery
from ui.about_dialog import AboutDialog
from ui.changelog_dialog import ChangelogDialog
from ui.import_panel import ImportPanel, dispatch_odt_import
from ui.structure_editor import StructureEditor
from ui.update_dialog import UpdateAvailableDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Epubeur v{__version__}")
        self.resize(1100, 750)

        self.controller = ProjectController(self)

        self.tabs = QTabWidget()
        self.import_panel = ImportPanel(self.controller)
        self.structure_editor = StructureEditor(self.controller)
        self.font_selector = FontSelector(self.controller)
        self.image_gallery = ImageGallery(self.controller)
        self.cover_panel = CoverPanel(self.controller)
        self.generate_panel = GeneratePanel(self.controller)
        self.epub_preview = EpubPreview(self.controller, self.generate_panel.collect_metadata)
        self.tabs.addTab(self.import_panel, "Import")
        self.tabs.addTab(self.structure_editor, "Structure")
        self.tabs.addTab(self.font_selector, "Police de caractères")
        self.tabs.addTab(self.image_gallery, "Images")
        self.tabs.addTab(self.cover_panel, "Couverture / 4e de couverture")
        self.tabs.addTab(self.generate_panel, "Métadonnées")
        self.epub_preview_tab_index = self.tabs.addTab(self.epub_preview, "Aperçu EPUB")

        self.epub_preview.generate_controls.epub_generated.connect(self._on_epub_generated)

        self.image_gallery.chapter_activated.connect(self._on_chapter_activated_from_gallery)
        self.structure_editor.cover_tab_requested.connect(self._on_cover_tab_requested)

        self.controller.epub_imported.connect(self._on_epub_imported)
        self.import_panel.project_dropped.connect(self._open_dropped_epbz)
        self.structure_editor.project_dropped.connect(self._open_dropped_epbz)

        self.controller.error_occurred.connect(self._show_error)
        self.controller.warning_occurred.connect(self._show_warning)

        self.setCentralWidget(self.tabs)

        # Nettoyage silencieux des listes Projets/Fichiers récents AVANT de construire les menus,
        # pour qu'ils s'affichent déjà propres (aucune entrée vers un fichier disparu depuis la
        # dernière session).
        prune_missing()
        self._build_menu()

        self.controller.recent_files_changed.connect(self._refresh_recent_menus)
        self._refresh_recent_menus()

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("Projet")

        save_action = menu.addAction("Enregistrer le projet")
        save_action.triggered.connect(self._save_project_as)

        open_action = menu.addAction("Ouvrir un projet")
        open_action.triggered.connect(self._open_project)

        menu.addSeparator()

        close_action = menu.addAction("Fermer le projet")
        close_action.triggered.connect(self._close_project)

        menu.addSeparator()
        self.recent_projects_menu = menu.addMenu("Projets récents")
        self.recent_files_menu = menu.addMenu("Fichiers récents")

        edit_menu = self.menuBar().addMenu("Édition")

        self.undo_action = edit_menu.addAction("Annuler")
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.setEnabled(False)
        self.undo_action.triggered.connect(self.controller.undo)

        self.redo_action = edit_menu.addAction("Rétablir")
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.setEnabled(False)
        self.redo_action.triggered.connect(self.controller.redo)

        self.controller.undo_availability_changed.connect(self._update_undo_actions)

        help_menu = self.menuBar().addMenu("Aide")
        github_action = help_menu.addAction("Dépôt GitHub")
        github_action.triggered.connect(self._open_github_repo)
        changelog_action = help_menu.addAction("Historique des versions")
        changelog_action.triggered.connect(self._show_changelog_dialog)
        self.update_action = help_menu.addAction("Vérifier les mises à jour")
        self.update_action.triggered.connect(self._check_for_updates_manually)
        help_menu.addSeparator()
        about_action = help_menu.addAction("À propos d'Epubeur")
        about_action.triggered.connect(self._show_about_dialog)

    def _open_github_repo(self) -> None:
        QDesktopServices.openUrl(QUrl("https://github.com/Bruno-Aublet/Epubeur"))

    def _show_about_dialog(self) -> None:
        AboutDialog(self).exec()

    def _check_for_updates_manually(self) -> None:
        """Déclenchée depuis le menu Aide — contrairement à la vérification automatique au
        démarrage (silencieuse tant qu'il n'y a rien de neuf), l'utilisateur a demandé cette
        vérification explicitement et doit recevoir un retour dans tous les cas : mise à jour
        trouvée, déjà à jour, ou échec (pas de connexion, GitHub injoignable...).

        Le menu est désactivé pendant la requête pour empêcher qu'un second clic n'écrase
        self._manual_update_checker avant la fin de la première requête réseau : l'ancien
        QNetworkReply se retrouverait sans référence Python alors que Qt lit encore son socket
        SSL en interne, ce qui produit le warning console "QSslSocket: device not open"."""
        self.update_action.setEnabled(False)
        self._manual_update_checker = UpdateChecker(__version__, self)
        self._manual_update_checker.update_available.connect(
            lambda remote_version, release_url: UpdateAvailableDialog(remote_version, release_url, self).exec()
        )
        self._manual_update_checker.up_to_date.connect(
            lambda: QMessageBox.information(self, "Mise à jour", f"Epubeur {__version__} est déjà à jour.")
        )
        self._manual_update_checker.check_failed.connect(
            lambda: QMessageBox.warning(
                self, "Mise à jour", "Impossible de vérifier les mises à jour. Vérifiez votre connexion internet."
            )
        )
        for signal in (
            self._manual_update_checker.update_available,
            self._manual_update_checker.up_to_date,
            self._manual_update_checker.check_failed,
        ):
            signal.connect(lambda *_: self.update_action.setEnabled(True))
        self._manual_update_checker.check()

    def _show_changelog_dialog(self) -> None:
        ChangelogDialog(self).exec()

    def _update_undo_actions(self, can_undo: bool, can_redo: bool) -> None:
        self.undo_action.setEnabled(can_undo)
        self.redo_action.setEnabled(can_redo)

    def _confirm_discard_unsaved(self) -> bool:
        """Retourne True s'il est permis de continuer (rien à perdre, ou confirmé) — factorisé
        pour être réutilisé par _open_project, _close_project ET le glisser-déposé d'un .epbz
        (cf. _open_dropped_epbz)."""
        if not self.controller.has_unsaved_content():
            return True
        reply = QMessageBox.question(
            self, "Projet non enregistré",
            "Le projet en cours contient des modifications non enregistrées. Continuer quand même ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _default_epbz_dir(self) -> Path:
        """Dossier proposé par défaut dans les boîtes de dialogue Enregistrer/Ouvrir — le dernier
        dossier utilisé pour un projet .epbz s'il est connu et existe encore, sinon
        Documents/Epubeur (créé s'il n'existe pas encore)."""
        last_dir = get_last_project_dir()
        if last_dir is not None:
            return last_dir
        default_dir = Path.home() / "Documents" / "Epubeur"
        default_dir.mkdir(parents=True, exist_ok=True)
        return default_dir

    def _save_project_as(self) -> None:
        file_str, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le projet", str(self._default_epbz_dir()), "Projet Epubeur (*.epbz)")
        if not file_str:
            return
        epbz_path = Path(file_str)
        if epbz_path.suffix.lower() != ".epbz":
            epbz_path = epbz_path.with_suffix(".epbz")
        # Le formulaire de l'onglet Métadonnées (titre, auteur, ISBN...) n'est jamais synchronisé
        # en continu avec le projet — capturé explicitement ici, juste avant l'écriture du .epbz,
        # seul moyen pour ProjectController.save_project_as (aucune connaissance de l'UI) de
        # connaître l'état actuel du formulaire.
        self.controller.project.book_metadata = self.generate_panel.collect_metadata()
        if self.controller.save_project_as(epbz_path):
            set_last_project_dir(epbz_path.parent)
            QMessageBox.information(self, "Enregistrement", "Projet enregistré.")
        # en cas d'échec, error_occurred a déjà déclenché _show_error

    def _open_project(self) -> None:
        if not self._confirm_discard_unsaved():
            return
        file_str, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir un projet", str(self._default_epbz_dir()), "Projet Epubeur (*.epbz)")
        if not file_str:
            return
        epbz_path = Path(file_str)
        set_last_project_dir(epbz_path.parent)
        self.controller.load_project_from(epbz_path)
        # succès/échec/avertissements sont déjà remontés via error_occurred/warning_occurred

    def _open_dropped_epbz(self, path: Path) -> None:
        if not self._confirm_discard_unsaved():
            return
        self.controller.load_project_from(path)

    def _refresh_recent_menus(self) -> None:
        self.recent_projects_menu.clear()
        projects = list_recent_projects()
        if not projects:
            self.recent_projects_menu.addAction("(Aucun projet récent)").setEnabled(False)
        for entry in projects:
            path = Path(entry["path"])
            label = f"{path.name} — {format_recent_timestamp(entry['timestamp'])}"
            action = self.recent_projects_menu.addAction(label)
            action.triggered.connect(lambda checked=False, p=path: self._open_recent_project(p))

        self.recent_files_menu.clear()
        files = list_recent_files()
        if not files:
            self.recent_files_menu.addAction("(Aucun fichier récent)").setEnabled(False)
        for entry in files:
            path = Path(entry["path"])
            verb = "généré" if entry["kind"] == "generated" else "importé"
            label = f"{path.name} ({verb} {format_recent_timestamp(entry['timestamp'])})"
            action = self.recent_files_menu.addAction(label)
            action.triggered.connect(lambda checked=False, p=path: self._open_recent_file(p))

    def _open_recent_project(self, path: Path) -> None:
        if not path.exists():
            remove_recent_project(path)
            self._refresh_recent_menus()
            self._show_error(f"« {path.name} » est introuvable — il a peut-être été déplacé ou supprimé.")
            return
        if not self._confirm_discard_unsaved():
            return
        self.controller.load_project_from(path)

    def _open_recent_file(self, path: Path) -> None:
        if not path.exists():
            remove_recent_file(path)
            self._refresh_recent_menus()
            self._show_error(f"« {path.name} » est introuvable — il a peut-être été déplacé ou supprimé.")
            return
        if path.suffix.lower() == ".odt":
            dispatch_odt_import(self.controller, path, self)
        else:
            self.controller.import_epub_file(path)

    def _close_project(self) -> None:
        if not self._confirm_discard_unsaved():
            return

        self.controller.close_project()
        self.epub_preview.reset()
        self.tabs.setCurrentIndex(0)

    def _on_chapter_activated_from_gallery(self, chapter_id: str) -> None:
        self.tabs.setCurrentWidget(self.structure_editor)
        self.structure_editor.select_chapter(chapter_id)

    def _on_cover_tab_requested(self) -> None:
        self.tabs.setCurrentWidget(self.cover_panel)

    def _on_epub_generated(self, output_path: str) -> None:
        add_recent_file(Path(output_path), "generated")
        self._refresh_recent_menus()
        self.tabs.setCurrentWidget(self.epub_preview)

    def _on_epub_imported(self, epub_path: str) -> None:
        # Contrairement à _on_epub_generated, on ne bascule pas automatiquement sur l'aperçu :
        # l'utilisateur est en train d'importer, potentiellement plusieurs fichiers d'affilée.
        self.epub_preview.load_epub(epub_path)

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Erreur", message)

    def _show_warning(self, message: str) -> None:
        QMessageBox.warning(self, "Avertissement", message)
