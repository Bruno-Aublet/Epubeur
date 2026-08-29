import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from model.file_association import ensure_epbz_association
from ui.main_window import MainWindow

DEFAULT_FONT_POINT_SIZE = 11


def _icons_dir() -> Path:
    """Localise le dossier Icons/ aussi bien en développement (racine du dépôt) qu'une fois
    compilé — même logique que ui/about_dialog.py::_license_path pour LICENSE."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "Icons"
    return Path(__file__).parent / "Icons"


def _window_icon_path() -> Path:
    """Icône de fenêtre (barre de titre) — Epubeur.ico."""
    return _icons_dir() / "Epubeur.ico"


def _splash_image_path() -> Path:
    """Image du splash screen de démarrage — Epubeur.png."""
    return _icons_dir() / "Epubeur.png"


def epbz_argument(argv: list[str]) -> Path | None:
    """Cherche un chemin .epbz existant dans les arguments de ligne de commande — c'est ce que
    Windows Explorer passe au lancement d'un double-clic sur un fichier associé (cf.
    model.file_association.ensure_epbz_association). Factorisé hors de main() pour rester
    testable sans construire une vraie QApplication."""
    for arg in argv:
        if arg.lower().endswith(".epbz") and Path(arg).exists():
            return Path(arg)
    return None


def main():
    app = QApplication(sys.argv)
    # Nécessaire pour que QStandardPaths.AppDataLocation résolve un dossier dédié à l'appli
    # (%APPDATA%\Epubeur\Epubeur\) plutôt qu'un dossier générique — utilisé par
    # model/recent_files.py pour stocker les listes Projets/Fichiers récents.
    app.setOrganizationName("Epubeur")
    app.setApplicationName("Epubeur")
    app.setWindowIcon(QIcon(str(_window_icon_path())))

    splash = QSplashScreen(QPixmap(str(_splash_image_path())))
    splash.show()
    app.processEvents()

    ensure_epbz_association()

    # Sans ça, les boutons standards (Oui/Non/Annuler/OK) des QMessageBox et les menus
    # contextuels natifs (Copier/Coller/Sélectionner tout) des champs de texte restent dans
    # la langue du système au lieu du français — Qt fournit ses propres traductions officielles
    # (qtbase_fr.qm), il suffit de les charger explicitement, elles ne le sont jamais par défaut.
    qt_translator = QTranslator(app)
    translations_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if qt_translator.load(QLocale("fr"), "qtbase", "_", translations_path):
        app.installTranslator(qt_translator)

    font = app.font()
    font.setPointSize(DEFAULT_FONT_POINT_SIZE)
    app.setFont(font)

    window = MainWindow()

    epbz_path = epbz_argument(sys.argv[1:])
    if epbz_path is not None:
        window.controller.load_project_from(epbz_path)

    window.show()
    splash.finish(window)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
