from pathlib import Path

from controller import ProjectController
from model.assets import AssetRole
from model.document import ImageDisplaySize

FIXTURE = Path(__file__).parent / "fixtures" / "sample_simple.odt"


def _make_controller(qapp_placeholder=None) -> ProjectController:
    return ProjectController()


def test_no_undo_available_initially(qapp):
    controller = _make_controller()
    assert controller.can_undo() is False
    assert controller.can_redo() is False


def test_create_part_is_undoable(qapp):
    controller = _make_controller()
    controller.import_odt(FIXTURE)

    assert len(controller.project.document.structure.parts()) == 0
    controller.create_part("Partie I")
    assert len(controller.project.document.structure.parts()) == 1
    assert controller.can_undo() is True

    controller.undo()
    assert len(controller.project.document.structure.parts()) == 0
    assert controller.can_redo() is True

    controller.redo()
    assert len(controller.project.document.structure.parts()) == 1


def test_assign_chapters_is_undoable(qapp):
    controller = _make_controller()
    controller.import_odt(FIXTURE)
    chapter_ids = list(controller.project.document.chapters.keys())

    controller.create_part("Partie I")
    part_id = controller.project.document.structure.parts()[0].id

    assert len(controller.project.document.structure.free_chapter_ids()) == 2
    controller.assign_chapters_to_part(chapter_ids, part_id)
    assert len(controller.project.document.structure.free_chapter_ids()) == 0

    controller.undo()
    assert len(controller.project.document.structure.free_chapter_ids()) == 2

    controller.redo()
    assert len(controller.project.document.structure.free_chapter_ids()) == 0


def test_unassign_chapters_is_undoable(qapp):
    controller = _make_controller()
    controller.import_odt(FIXTURE)
    chapter_ids = list(controller.project.document.chapters.keys())

    controller.create_part("Partie I")
    part_id = controller.project.document.structure.parts()[0].id
    controller.assign_chapters_to_part(chapter_ids, part_id)
    assert len(controller.project.document.structure.free_chapter_ids()) == 0

    controller.unassign_chapters(chapter_ids)
    assert len(controller.project.document.structure.free_chapter_ids()) == 2

    controller.undo()
    assert len(controller.project.document.structure.free_chapter_ids()) == 0

    controller.redo()
    assert len(controller.project.document.structure.free_chapter_ids()) == 2


def test_merge_chapters_is_undoable(qapp):
    controller = _make_controller()
    controller.import_odt(FIXTURE)
    chapter_ids = list(controller.project.document.chapters.keys())
    id_a, id_b = chapter_ids[0], chapter_ids[1]

    assert len(controller.project.document.chapters) == 2
    controller.merge_chapters(id_a, id_b)
    assert len(controller.project.document.chapters) == 1

    controller.undo()
    assert len(controller.project.document.chapters) == 2
    assert id_a in controller.project.document.chapters
    assert id_b in controller.project.document.chapters


def test_new_action_clears_redo_stack(qapp):
    controller = _make_controller()
    controller.import_odt(FIXTURE)

    controller.create_part("Partie I")
    controller.undo()
    assert controller.can_redo() is True

    controller.create_part("Autre Partie")
    assert controller.can_redo() is False


def test_undo_stack_size_is_bounded(qapp):
    controller = _make_controller()
    controller.import_odt(FIXTURE)

    from controller import MAX_UNDO_HISTORY
    for i in range(MAX_UNDO_HISTORY + 10):
        controller.create_part(f"Partie {i}")

    assert len(controller._undo_stack) == MAX_UNDO_HISTORY


def test_rename_part_is_undoable(qapp):
    controller = _make_controller()
    controller.import_odt(FIXTURE)
    controller.create_part("Titre initial")
    part_id = controller.project.document.structure.parts()[0].id

    controller.rename_part(part_id, "Titre modifié")
    assert controller.project.document.structure.parts()[0].title == "Titre modifié"

    controller.undo()
    assert controller.project.document.structure.parts()[0].title == "Titre initial"


def test_set_part_title_page_is_undoable(qapp):
    controller = _make_controller()
    controller.import_odt(FIXTURE)
    controller.create_part("Prologues")
    part_id = controller.project.document.structure.parts()[0].id

    assert controller.project.document.structure.parts()[0].has_title_page is False
    controller.set_part_title_page(part_id, True)
    assert controller.project.document.structure.parts()[0].has_title_page is True

    controller.undo()
    assert controller.project.document.structure.parts()[0].has_title_page is False


def test_set_image_display_size_is_undoable(qapp):
    controller = _make_controller()
    asset = controller.asset_store.ingest_bytes(b"fake-image-bytes", original_filename="img.png",
                                                  role=AssetRole.CHAPTER_POV)

    assert controller.project.document.image_display_size(asset.id) == ImageDisplaySize.FULL
    controller.set_image_display_size(asset.id, ImageDisplaySize.SMALL)
    assert controller.project.document.image_display_size(asset.id) == ImageDisplaySize.SMALL

    controller.undo()
    assert controller.project.document.image_display_size(asset.id) == ImageDisplaySize.FULL
