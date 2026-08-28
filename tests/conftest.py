import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    """QApplication minimale requise pour instancier des QObject (ex: ProjectController)
    en dehors de l'app réelle. Pas de dépendance à pytest-qt : fixture locale suffisante
    puisqu'on n'a pas besoin de piloter de vrais widgets, juste que QObject/Signal existent."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def isolate_recent_files(monkeypatch):
    """Redirige model.recent_files vers un dossier temporaire pour TOUTE la suite — sans ça,
    n'importe quel test qui construit un ProjectController réel et déclenche import_odt/
    save_project_as/etc. écrirait un vrai recent_files.json sur la machine (QStandardPaths
    résout %APPDATA%\\Roaming directement tant qu'aucun QApplication de test ne fixe
    setApplicationName, contrairement à main.py::main() en conditions réelles). autouse=True :
    protection systématique, pas seulement pour les tests dédiés à model/recent_files.py."""
    import model.recent_files as recent_files_module

    fake_path = Path(tempfile.mkdtemp(prefix="epubeur_test_recent_")) / "recent_files.json"
    monkeypatch.setattr(recent_files_module, "_recent_files_path", lambda: fake_path)
