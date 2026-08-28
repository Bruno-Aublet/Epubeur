from pathlib import Path

from controller import ProjectController
from model.document import Chapter
from model.recent_files import list_recent_files, list_recent_projects

FIXTURE = Path(__file__).parent / "fixtures" / "sample_simple.odt"


def test_import_odt_adds_to_recent_files(qapp):
    controller = ProjectController()
    signals: list[bool] = []
    controller.recent_files_changed.connect(lambda: signals.append(True))

    controller.import_odt(FIXTURE)

    entries = list_recent_files()
    assert entries[0]["path"] == str(FIXTURE)
    assert entries[0]["kind"] == "imported"
    assert signals == [True]


def test_import_odt_failure_does_not_add_to_recent_files(qapp, tmp_path):
    controller = ProjectController()
    bad_path = tmp_path / "not_a_real.odt"
    bad_path.write_bytes(b"not a zip file")

    controller.import_odt(bad_path)

    assert list_recent_files() == []


def test_replace_odt_adds_to_recent_files(qapp, tmp_path):
    import shutil
    controller = ProjectController()
    copied = tmp_path / "book.odt"
    shutil.copy(FIXTURE, copied)
    controller.import_odt(copied)

    controller.replace_odt(copied)

    entries = list_recent_files()
    assert entries[0]["path"] == str(copied)
    assert entries[0]["kind"] == "imported"


def test_import_epub_file_adds_to_recent_files(qapp, tmp_path):
    from epub.builder import build_epub
    from model.assets import AssetStore
    from model.book_metadata import BookMetadata

    controller = ProjectController()
    controller.project.document.add_chapter(Chapter.create(title="Un chapitre"))
    asset_store = AssetStore(tmp_path / "assets")
    epub_path = build_epub(controller.project, asset_store, tmp_path / "out.epub",
                            metadata=BookMetadata(title="Test"))

    controller2 = ProjectController()
    controller2.import_epub_file(epub_path)

    entries = list_recent_files()
    assert entries[0]["path"] == str(epub_path)
    assert entries[0]["kind"] == "imported"


def test_save_project_as_adds_to_recent_projects(qapp, tmp_path):
    controller = ProjectController()
    controller.project.document.add_chapter(Chapter.create(title="Un chapitre"))
    epbz_path = tmp_path / "Projet.epbz"
    signals: list[bool] = []
    controller.recent_files_changed.connect(lambda: signals.append(True))

    controller.save_project_as(epbz_path)

    entries = list_recent_projects()
    assert entries[0]["path"] == str(epbz_path)
    assert signals == [True]


def test_plain_save_also_adds_to_recent_projects(qapp, tmp_path):
    controller = ProjectController()
    controller.project.document.add_chapter(Chapter.create(title="Un chapitre"))
    epbz_path = tmp_path / "Projet.epbz"
    controller.save_project_as(epbz_path)

    controller.project.document.add_chapter(Chapter.create(title="Un deuxième chapitre"))
    controller.save_project()

    entries = list_recent_projects()
    assert len(entries) == 1  # même chemin réenregistré : remonte, pas de doublon
    assert entries[0]["path"] == str(epbz_path)


def test_load_project_from_adds_to_recent_projects(qapp, tmp_path):
    controller = ProjectController()
    controller.project.document.add_chapter(Chapter.create(title="Un chapitre"))
    epbz_path = tmp_path / "Projet.epbz"
    controller.save_project_as(epbz_path)

    controller2 = ProjectController()
    controller2.load_project_from(epbz_path)

    entries = list_recent_projects()
    assert entries[0]["path"] == str(epbz_path)


def test_load_project_from_failure_does_not_duplicate_entry(qapp, tmp_path):
    controller = ProjectController()
    corrupt_path = tmp_path / "corrompu.epbz"
    corrupt_path.write_bytes(b"not a zip")

    controller.load_project_from(corrupt_path)

    assert list_recent_projects() == []
