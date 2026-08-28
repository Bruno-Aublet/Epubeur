from pathlib import Path

from controller import ProjectController
from model.document import Chapter, Document, ImageAnchor, Paragraph, Part, Table, TableCell, TableRow

FIXTURE = Path(__file__).parent / "fixtures" / "sample_simple.odt"


def test_document_delete_chapter_removes_it_and_its_text():
    document = Document()
    chapter = Chapter.create(title="À supprimer")
    document.add_chapter(chapter)

    document.delete_chapter(chapter.id)

    assert chapter.id not in document.chapters
    assert chapter.id not in document.structure.all_referenced_chapter_ids()


def test_document_delete_chapter_removes_it_from_its_part():
    document = Document()
    chapter = Chapter.create(title="Dans une partie")
    document.chapters[chapter.id] = chapter
    part = Part.create(title="Partie I")
    part.chapter_ids = [chapter.id]
    document.structure.items.append(part)

    document.delete_chapter(chapter.id)

    assert chapter.id not in document.chapters
    assert part.chapter_ids == []


def test_document_delete_part_keeps_its_chapters_as_free():
    document = Document()
    chap_a = Chapter.create(title="A")
    chap_b = Chapter.create(title="B")
    document.chapters[chap_a.id] = chap_a
    document.chapters[chap_b.id] = chap_b
    part = Part.create(title="Partie I")
    part.chapter_ids = [chap_a.id, chap_b.id]
    document.structure.items.append(part)

    document.delete_part(part.id)

    assert chap_a.id in document.chapters
    assert chap_b.id in document.chapters
    assert document.structure.items == [chap_a.id, chap_b.id]


def test_document_delete_part_preserves_position_among_other_items():
    document = Document()
    chap_before = Chapter.create(title="Avant")
    chap_in_part = Chapter.create(title="Dans la partie")
    chap_after = Chapter.create(title="Après")
    for c in (chap_before, chap_in_part, chap_after):
        document.chapters[c.id] = c
    part = Part.create(title="Partie I")
    part.chapter_ids = [chap_in_part.id]
    document.structure.items = [chap_before.id, part, chap_after.id]

    document.delete_part(part.id)

    assert document.structure.items == [chap_before.id, chap_in_part.id, chap_after.id]


def test_controller_delete_chapter_is_undoable(qapp):
    controller = ProjectController()
    controller.import_odt(FIXTURE)
    chapter_id = next(iter(controller.project.document.chapters))

    controller.delete_chapter(chapter_id)
    assert chapter_id not in controller.project.document.chapters

    controller.undo()
    assert chapter_id in controller.project.document.chapters


def test_controller_delete_part_is_undoable(qapp):
    controller = ProjectController()
    controller.import_odt(FIXTURE)
    controller.create_part("Partie I")
    part_id = controller.project.document.structure.parts()[0].id
    chapter_ids = list(controller.project.document.chapters.keys())
    controller.assign_chapters_to_part(chapter_ids, part_id)

    controller.delete_part(part_id)
    assert len(controller.project.document.structure.parts()) == 0
    for cid in chapter_ids:
        assert cid in controller.project.document.chapters

    controller.undo()
    assert len(controller.project.document.structure.parts()) == 1


def test_controller_delete_chapter_on_unknown_id_is_noop(qapp):
    controller = ProjectController()
    controller.import_odt(FIXTURE)
    assert controller.can_undo() is False

    controller.delete_chapter("nonexistent-id")

    assert controller.can_undo() is False


# --- Document.is_asset_referenced ---

def test_is_asset_referenced_true_when_used_in_chapter_paragraph():
    document = Document()
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id="abc"))]
    document.chapters[chapter.id] = chapter

    assert document.is_asset_referenced("abc") is True


def test_is_asset_referenced_true_when_used_in_table_cell():
    document = Document()
    chapter = Chapter.create(title="Chapitre")
    table = Table(rows=[TableRow(cells=[TableCell(paragraphs=[Paragraph(image=ImageAnchor(asset_id="abc"))])])])
    chapter.paragraphs = [table]
    document.chapters[chapter.id] = chapter

    assert document.is_asset_referenced("abc") is True


def test_is_asset_referenced_true_when_used_as_cover():
    document = Document()
    document.cover_asset_id = "abc"

    assert document.is_asset_referenced("abc") is True


def test_is_asset_referenced_true_when_used_as_back_cover():
    document = Document()
    document.back_cover_asset_id = "abc"

    assert document.is_asset_referenced("abc") is True


def test_is_asset_referenced_false_when_unused_anywhere():
    document = Document()
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id="other"))]
    document.chapters[chapter.id] = chapter

    assert document.is_asset_referenced("abc") is False
