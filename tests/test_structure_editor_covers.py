from PySide6.QtCore import Qt

from controller import ProjectController
from model.assets import AssetRole
from model.document import Chapter
from ui.structure_editor import COVER_ROLE, StructureEditor


def _make_editor(qapp) -> tuple[ProjectController, StructureEditor]:
    controller = ProjectController()
    editor = StructureEditor(controller)
    return controller, editor


def _add_cover(controller: ProjectController) -> str:
    asset = controller.asset_store.ingest_bytes(b"fake-cover-bytes", "cover.jpg", AssetRole.COVER)
    controller.project.document.cover_asset_id = asset.id
    return asset.id


def _add_back_cover(controller: ProjectController) -> str:
    asset = controller.asset_store.ingest_bytes(b"fake-back-cover-bytes", "back.jpg", AssetRole.BACK_COVER)
    controller.project.document.back_cover_asset_id = asset.id
    return asset.id


def test_cover_appears_as_first_top_level_item(qapp):
    controller, editor = _make_editor(qapp)
    _add_cover(controller)
    chapter = Chapter.create(title="Chapitre Un")
    controller.project.document.add_chapter(chapter)
    controller.chapters_changed.emit()
    controller.assets_changed.emit()

    first_item = editor.tree.topLevelItem(0)
    assert first_item.data(0, COVER_ROLE) == "cover"


def test_back_cover_appears_as_last_top_level_item(qapp):
    controller, editor = _make_editor(qapp)
    _add_back_cover(controller)
    chapter = Chapter.create(title="Chapitre Un")
    controller.project.document.add_chapter(chapter)
    controller.chapters_changed.emit()
    controller.assets_changed.emit()

    last_index = editor.tree.topLevelItemCount() - 1
    last_item = editor.tree.topLevelItem(last_index)
    assert last_item.data(0, COVER_ROLE) == "back_cover"


def test_cover_and_back_cover_absent_when_not_set(qapp):
    controller, editor = _make_editor(qapp)
    chapter = Chapter.create(title="Chapitre Un")
    controller.project.document.add_chapter(chapter)
    controller.chapters_changed.emit()

    assert editor.tree.topLevelItemCount() == 1
    assert editor.tree.topLevelItem(0).data(0, COVER_ROLE) is None


def test_cover_item_is_not_draggable(qapp):
    controller, editor = _make_editor(qapp)
    _add_cover(controller)
    controller.assets_changed.emit()

    cover_item = editor.tree.topLevelItem(0)
    assert not (cover_item.flags() & Qt.ItemFlag.ItemIsDragEnabled)


def test_selecting_cover_shows_cover_preview(qapp):
    controller, editor = _make_editor(qapp)
    _add_cover(controller)
    controller.assets_changed.emit()

    cover_item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(cover_item)

    assert editor.preview_stack.currentWidget() is editor.cover_image_preview


def test_context_menu_on_cover_offers_go_to_tab_and_delete(qapp):
    controller, editor = _make_editor(qapp)
    _add_cover(controller)
    controller.assets_changed.emit()

    cover_item = editor.tree.topLevelItem(0)
    menu = editor._build_context_menu(cover_item)
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts == ["Aller à l'onglet Couverture", "Supprimer"]


def test_context_menu_cover_action_emits_cover_tab_requested(qapp):
    controller, editor = _make_editor(qapp)
    _add_cover(controller)
    controller.assets_changed.emit()

    cover_item = editor.tree.topLevelItem(0)
    menu = editor._build_context_menu(cover_item)
    emitted = []
    editor.cover_tab_requested.connect(lambda: emitted.append(True))
    actions = [a for a in menu.actions() if not a.isSeparator()]
    actions[0].trigger()

    assert emitted == [True]


def test_delete_selected_removes_cover(qapp):
    controller, editor = _make_editor(qapp)
    _add_cover(controller)
    controller.assets_changed.emit()

    cover_item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(cover_item)

    from PySide6.QtWidgets import QMessageBox
    original = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    try:
        editor._delete_selected()
    finally:
        QMessageBox.question = original

    assert controller.project.document.cover_asset_id is None


def test_delete_selected_removes_back_cover(qapp):
    controller, editor = _make_editor(qapp)
    _add_back_cover(controller)
    controller.assets_changed.emit()

    back_cover_item = editor.tree.topLevelItem(editor.tree.topLevelItemCount() - 1)
    editor.tree.setCurrentItem(back_cover_item)

    from PySide6.QtWidgets import QMessageBox
    original = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    try:
        editor._delete_selected()
    finally:
        QMessageBox.question = original

    assert controller.project.document.back_cover_asset_id is None


def test_removing_cover_from_controller_refreshes_tree(qapp):
    controller, editor = _make_editor(qapp)
    _add_cover(controller)
    controller.assets_changed.emit()
    assert editor.tree.topLevelItem(0).data(0, COVER_ROLE) == "cover"

    controller.remove_cover_asset()

    assert editor.tree.topLevelItemCount() == 0 or editor.tree.topLevelItem(0).data(0, COVER_ROLE) != "cover"
