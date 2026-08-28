from pathlib import Path

from PySide6.QtWidgets import QDialog

from controller import ProjectController
from model.document import Chapter
from model.project import SourceOdtFile
from ui.import_panel import ImportPanel
from ui.reimport_choice_dialog import ReimportChoice, ReimportChoiceDialog


def test_epub_import_line_survives_the_chapters_changed_refresh_it_triggers(qapp, monkeypatch):
    """Régression : glisser un .epub ajoutait une ligne à la liste, mais import_epub_file émet
    lui-même chapters_changed, qui déclenche _refresh() — lequel ne reconstruit la liste qu'à
    partir de project.source_odt_files (jamais alimenté pour un .epub), effaçant la ligne juste
    ajoutée. La ligne doit rester visible après ce même cycle chapters_changed."""
    controller = ProjectController()

    def fake_import_epub_file(path):
        chapter = Chapter.create(title="Chapitre importé")
        controller.project.document.chapters[chapter.id] = chapter
        controller.project.document.structure.append_free_chapter(chapter.id)
        controller.chapters_changed.emit()
        return []

    monkeypatch.setattr(controller, "import_epub_file", fake_import_epub_file)

    panel = ImportPanel(controller)
    panel._handle_dropped_files([Path("livre.epub")])

    items = [panel.list_widget.item(i).text() for i in range(panel.list_widget.count())]
    assert any("livre.epub" in text for text in items)


def test_dropping_already_imported_odt_prompts_dialog_and_routes_to_replace(qapp, monkeypatch):
    controller = ProjectController()
    path = Path("book.odt")
    controller.project.source_odt_files.append(SourceOdtFile.create(path, 0))

    monkeypatch.setattr(ReimportChoiceDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(ReimportChoiceDialog, "result_choice", lambda self: ReimportChoice.REPLACE)

    calls: list[str] = []
    monkeypatch.setattr(controller, "replace_odt", lambda p: calls.append(("replace", p)))
    monkeypatch.setattr(controller, "import_odt", lambda p: calls.append(("import", p)))

    panel = ImportPanel(controller)
    panel._handle_dropped_files([path])

    assert calls == [("replace", path)]


def test_dropping_already_imported_odt_can_be_routed_to_add_as_new(qapp, monkeypatch):
    controller = ProjectController()
    path = Path("book.odt")
    controller.project.source_odt_files.append(SourceOdtFile.create(path, 0))

    monkeypatch.setattr(ReimportChoiceDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(ReimportChoiceDialog, "result_choice", lambda self: ReimportChoice.ADD_AS_NEW)

    calls: list[str] = []
    monkeypatch.setattr(controller, "replace_odt", lambda p: calls.append(("replace", p)))
    monkeypatch.setattr(controller, "import_odt", lambda p: calls.append(("import", p)))

    panel = ImportPanel(controller)
    panel._handle_dropped_files([path])

    assert calls == [("import", path)]


def test_dropping_already_imported_odt_cancelled_dialog_does_nothing(qapp, monkeypatch):
    controller = ProjectController()
    path = Path("book.odt")
    controller.project.source_odt_files.append(SourceOdtFile.create(path, 0))

    monkeypatch.setattr(ReimportChoiceDialog, "exec", lambda self: QDialog.DialogCode.Rejected)

    calls: list[str] = []
    monkeypatch.setattr(controller, "replace_odt", lambda p: calls.append(("replace", p)))
    monkeypatch.setattr(controller, "import_odt", lambda p: calls.append(("import", p)))

    panel = ImportPanel(controller)
    panel._handle_dropped_files([path])

    assert calls == []


def test_project_dropped_relayed_from_list_widget_to_panel(qapp):
    """Le signal project_dropped de ImportListWidget (émis par dropEvent quand un .epbz est
    déposé) doit être relayé tel quel par ImportPanel — c'est MainWindow qui décide ensuite
    d'ouvrir (avec la garde modifications non enregistrées), ce panneau n'a pas cette notion."""
    controller = ProjectController()
    panel = ImportPanel(controller)

    received: list[Path] = []
    panel.project_dropped.connect(received.append)

    epbz_path = Path("mon_projet.epbz")
    panel.list_widget.project_dropped.emit(epbz_path)

    assert received == [epbz_path]


def test_image_dropped_relayed_to_add_image_as_chapter(qapp, monkeypatch):
    """Le signal image_dropped de ImportListWidget (émis par dropEvent pour tout fichier qui
    n'est ni .epbz ni .odt/.epub) doit router vers controller.add_image_as_chapter, comme le
    drop sur l'arbre de l'onglet Structure."""
    controller = ProjectController()

    calls: list[Path] = []
    monkeypatch.setattr(controller, "add_image_as_chapter", lambda p: calls.append(p))

    panel = ImportPanel(controller)
    image_path = Path("perso.jpg")
    panel.list_widget.image_dropped.emit(image_path)

    assert calls == [image_path]


def test_dropping_new_odt_path_never_prompts_dialog(qapp, monkeypatch):
    controller = ProjectController()

    calls: list[str] = []
    monkeypatch.setattr(controller, "import_odt", lambda p: calls.append(("import", p)))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("le dialogue ne doit pas s'ouvrir pour un chemin jamais importé")
    monkeypatch.setattr(ReimportChoiceDialog, "exec", fail_if_called)

    panel = ImportPanel(controller)
    panel._handle_dropped_files([Path("nouveau.odt")])

    assert calls == [("import", Path("nouveau.odt"))]
