from controller import ProjectController
from model.document import Chapter, Paragraph, Run
from model.styles import CharFormat


def test_chapter_created_without_title_is_not_visible():
    chapter = Chapter.create(title="")
    assert chapter.title_visible is False


def test_chapter_created_with_title_is_visible():
    chapter = Chapter.create(title="Un titre")
    assert chapter.title_visible is True


def test_split_chapter_second_part_without_title_is_not_visible():
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre original")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="a", fmt=CharFormat())]),
        Paragraph(runs=[Run(text="b", fmt=CharFormat())]),
    ]
    controller.project.document.add_chapter(chapter)

    controller.split_chapter(chapter.id, 1)

    chapters = list(controller.project.document.chapters.values())
    first = next(c for c in chapters if c.title == "Chapitre original")
    second = next(c for c in chapters if c.id != first.id)
    assert second.title == ""
    assert second.title_visible is False


def test_rename_chapter_without_title_visible_arg_does_not_change_visibility():
    controller = ProjectController()
    chapter = Chapter.create(title="")
    controller.project.document.add_chapter(chapter)
    assert chapter.title_visible is False

    controller.rename_chapter(chapter.id, "Nouveau titre")

    assert chapter.title == "Nouveau titre"
    assert chapter.title_visible is False  # ne bascule jamais automatiquement


def test_rename_chapter_can_explicitly_make_title_visible():
    controller = ProjectController()
    chapter = Chapter.create(title="")
    controller.project.document.add_chapter(chapter)

    controller.rename_chapter(chapter.id, "Nouveau titre", title_visible=True)

    assert chapter.title == "Nouveau titre"
    assert chapter.title_visible is True


def test_rename_chapter_can_explicitly_hide_title():
    controller = ProjectController()
    chapter = Chapter.create(title="Un titre visible")
    controller.project.document.add_chapter(chapter)
    assert chapter.title_visible is True

    controller.rename_chapter(chapter.id, "Un titre visible", title_visible=False)

    assert chapter.title_visible is False
