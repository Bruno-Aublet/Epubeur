from pathlib import Path

from controller import ProjectController

FIXTURE = Path(__file__).parent / "fixtures" / "sample_simple.odt"


def test_close_project_resets_document(qapp):
    controller = ProjectController()
    controller.import_odt(FIXTURE)
    controller.create_part("Partie I")

    assert len(controller.project.document.chapters) == 2
    assert len(controller.project.document.structure.parts()) == 1

    controller.close_project()

    assert len(controller.project.document.chapters) == 0
    assert len(controller.project.document.structure.parts()) == 0
    assert controller.project.source_odt_files == []


def test_close_project_clears_undo_history(qapp):
    controller = ProjectController()
    controller.import_odt(FIXTURE)
    controller.create_part("Partie I")

    assert controller.can_undo() is True
    controller.close_project()
    assert controller.can_undo() is False
    assert controller.can_redo() is False


def test_has_unsaved_content_reflects_state(qapp):
    controller = ProjectController()
    assert controller.has_unsaved_content() is False

    controller.import_odt(FIXTURE)
    assert controller.has_unsaved_content() is True

    controller.close_project()
    assert controller.has_unsaved_content() is False


def test_opening_saved_project_is_not_flagged_unsaved(qapp, tmp_path):
    """Régression : ouvrir un .epbz déjà enregistré remplit document.chapters, mais rien n'a
    été modifié depuis l'ouverture — has_unsaved_content() ne doit donc PAS avertir à la
    fermeture (l'ancienne logique se basait sur bool(document.chapters), toujours vrai après
    une ouverture)."""
    controller = ProjectController()
    controller.import_odt(FIXTURE)
    epbz_path = tmp_path / "projet.epbz"
    assert controller.save_project_as(epbz_path) is True

    controller.close_project()
    assert controller.has_unsaved_content() is False

    controller.load_project_from(epbz_path)
    assert len(controller.project.document.chapters) == 2
    assert controller.has_unsaved_content() is False


def test_can_import_again_after_close(qapp):
    controller = ProjectController()
    controller.import_odt(FIXTURE)
    controller.close_project()

    controller.import_odt(FIXTURE)
    assert len(controller.project.document.chapters) == 2


def test_close_project_removes_previous_temp_dir(qapp):
    """Régression : close_project() créait un nouveau dossier temporaire sans jamais supprimer
    le précédent — plusieurs fermetures dans la même session accumulaient des dossiers
    orphelins dans %TEMP%."""
    controller = ProjectController()
    first_temp_dir = controller._temp_assets_dir
    assert first_temp_dir.exists()

    controller.close_project()

    assert not first_temp_dir.exists()
    assert controller._temp_assets_dir.exists()
    assert controller._temp_assets_dir != first_temp_dir


def test_cleanup_temp_dir_removes_current_temp_dir(qapp):
    """cleanup_temp_dir() (appelée à la fermeture de l'app, cf. main.py) doit supprimer le
    dernier dossier temporaire encore en usage, qu'aucun remplacement ultérieur ne nettoiera."""
    controller = ProjectController()
    temp_dir = controller._temp_assets_dir
    assert temp_dir.exists()

    controller.cleanup_temp_dir()

    assert not temp_dir.exists()
