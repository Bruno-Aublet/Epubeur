from model.chapter_reorder_detection import detect_reordered_chapters
from model.document import Chapter, Paragraph, Run
from model.styles import CharFormat


def _chapter(text: str) -> Chapter:
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(runs=[Run(text=text, fmt=CharFormat())])]
    return chapter


def test_no_reorder_when_texts_unchanged():
    old = [_chapter("Le loup entra dans la forêt sombre."), _chapter("Le soleil se leva sur la vallée.")]
    new = [_chapter("Le loup entra dans la forêt sombre."), _chapter("Le soleil se leva sur la vallée.")]

    assert detect_reordered_chapters(old, new) is False


def test_no_reorder_when_text_lightly_corrected():
    old = [_chapter("Le loup entra dans la forêt sombre et froide."), _chapter("Le soleil se leva sur la vallée verte.")]
    new = [_chapter("Le loup entra dans la forêt sombre et glaciale."), _chapter("Le soleil se leva sur la vallée verdoyante.")]

    assert detect_reordered_chapters(old, new) is False


def test_detects_two_chapters_swapped():
    old = [_chapter("Le loup entra dans la forêt sombre et froide, cherchant une proie."),
           _chapter("Le soleil se leva sur la vallée verte, illuminant les collines.")]
    new = [_chapter("Le soleil se leva sur la vallée verte, illuminant les collines."),
           _chapter("Le loup entra dans la forêt sombre et froide, cherchant une proie.")]

    assert detect_reordered_chapters(old, new) is True


def test_no_detection_when_lengths_differ():
    old = [_chapter("Un texte quelconque assez long pour être significatif ici.")]
    new = [_chapter("Un texte quelconque assez long pour être significatif ici."), _chapter("Autre.")]

    assert detect_reordered_chapters(old, new) is False


def test_no_detection_on_empty_lists():
    assert detect_reordered_chapters([], []) is False


def test_no_false_positive_when_all_chapters_are_short_and_similar():
    """Des chapitres très courts/similaires (ex: tous vides ou juste un titre) ne doivent pas
    déclencher de faux positif par manque de signal distinctif."""
    old = [_chapter(""), _chapter("")]
    new = [_chapter(""), _chapter("")]

    assert detect_reordered_chapters(old, new) is False
