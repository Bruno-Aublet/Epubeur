from model.document import Chapter, Paragraph, Run
from model.styles import CharFormat
from ui.chapter_split_dialog import ChapterSplitDialog


def _chapter_with_paragraphs(*texts: str) -> Chapter:
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(runs=[Run(text=t, fmt=CharFormat())]) for t in texts]
    return chapter


def test_dialog_never_offers_paragraph_zero_as_split_point(qapp):
    """Régression : proposer l'index 0 comme point de scission produisait un premier chapitre
    totalement vide (juste son titre) et un second qui perdait son titre — un chapitre fantôme
    silencieux plutôt qu'une vraie scission."""
    chapter = _chapter_with_paragraphs("premier", "deuxième", "troisième")
    dialog = ChapterSplitDialog(chapter)

    texts = [dialog.list_widget.item(i).text() for i in range(dialog.list_widget.count())]

    assert not any(text.startswith("0.") for text in texts)
    assert texts == ["1. deuxième", "2. troisième"]


def test_dialog_selected_index_matches_real_paragraph_index(qapp):
    """selected_index doit rester l'index réel dans chapter.paragraphs, pas la position dans
    la liste affichée (qui exclut l'index 0)."""
    chapter = _chapter_with_paragraphs("premier", "deuxième", "troisième")
    dialog = ChapterSplitDialog(chapter)

    dialog.list_widget.setCurrentRow(1)  # "2. troisième", deuxième ligne affichée
    dialog._accept()

    assert dialog.selected_index == 2


def test_dialog_with_minimum_two_paragraphs_still_offers_one_split_point(qapp):
    """Cas limite : un chapitre à exactement 2 paragraphes (le minimum autorisé par
    _split_selected) ne doit proposer que l'unique scission valide (avant le dernier)."""
    chapter = _chapter_with_paragraphs("premier", "deuxième")
    dialog = ChapterSplitDialog(chapter)

    assert dialog.list_widget.count() == 1
    assert dialog.list_widget.item(0).text() == "1. deuxième"
