from controller import ProjectController
from model.assets import AssetRole
from ui.cover_panel import CoverPanel


def test_remove_cover_asset_clears_document_field(qapp):
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"fake-cover", "cover.jpg", AssetRole.COVER)
    controller.set_cover_asset(asset.id)

    controller.remove_cover_asset()

    assert controller.project.document.cover_asset_id is None


def test_remove_back_cover_asset_clears_document_field(qapp):
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"fake-back-cover", "back.jpg", AssetRole.BACK_COVER)
    controller.set_back_cover_asset(asset.id)

    controller.remove_back_cover_asset()

    assert controller.project.document.back_cover_asset_id is None


def test_remove_cover_asset_is_undoable(qapp):
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"fake-cover", "cover.jpg", AssetRole.COVER)
    controller.set_cover_asset(asset.id)

    controller.remove_cover_asset()
    assert controller.project.document.cover_asset_id is None

    controller.undo()
    assert controller.project.document.cover_asset_id == asset.id


def test_cover_panel_refresh_clears_zone_when_no_cover(qapp):
    controller = ProjectController()
    panel = CoverPanel(controller)

    assert panel.cover_col.technical_label.text() == ""

    asset = controller.asset_store.ingest_bytes(b"fake-cover", "cover.jpg", AssetRole.COVER)
    controller.set_cover_asset(asset.id)
    assert panel.cover_col.zone.pixmap() is not None
    assert panel.cover_col.technical_label.text() == "cover.jpg"

    controller.remove_cover_asset()

    assert panel.cover_col.zone.text() != ""
    assert panel.cover_col.technical_label.text() == ""


def test_cover_panel_remove_button_clears_cover(qapp):
    controller = ProjectController()
    panel = CoverPanel(controller)
    asset = controller.asset_store.ingest_bytes(b"fake-cover", "cover.jpg", AssetRole.COVER)
    controller.set_cover_asset(asset.id)

    panel._on_cover_removed()

    assert controller.project.document.cover_asset_id is None


def test_cover_panel_remove_button_clears_back_cover(qapp):
    controller = ProjectController()
    panel = CoverPanel(controller)
    asset = controller.asset_store.ingest_bytes(b"fake-back-cover", "back.jpg", AssetRole.BACK_COVER)
    controller.set_back_cover_asset(asset.id)

    panel._on_back_cover_removed()

    assert controller.project.document.back_cover_asset_id is None
