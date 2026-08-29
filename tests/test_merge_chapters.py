import pytest

from model.document import Chapter, Document, Paragraph, Run
from model.styles import CharFormat


def _chapter_with_text(*texts: str) -> Chapter:
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(runs=[Run(text=t, fmt=CharFormat())]) for t in texts]
    return chapter


def test_merge_chapters_concatenates_paragraphs_and_removes_b():
    document = Document()
    chap_a = _chapter_with_text("Premier")
    chap_b = _chapter_with_text("Second")
    document.chapters[chap_a.id] = chap_a
    document.chapters[chap_b.id] = chap_b
    document.structure.append_free_chapter(chap_a.id)
    document.structure.append_free_chapter(chap_b.id)

    result_id = document.merge_chapters(chap_a.id, chap_b.id)

    assert result_id == chap_a.id
    assert chap_b.id not in document.chapters
    assert [p.plain_text() for p in document.chapters[chap_a.id].paragraphs] == ["Premier", "Second"]


def test_merge_chapters_rejects_same_id():
    """Régression : sans garde, fusionner un chapitre avec lui-même (id_a == id_b) supprimait
    le chapitre entièrement au lieu de ne rien faire ou de lever une erreur explicite — chap_a
    et chap_b étant le même objet, étendre ses paragraphes avec lui-même puis le supprimer
    juste après ne laissait plus rien. Aucun appelant actuel ne peut déclencher ce cas
    (structure_editor.py ne propose que "fusionner avec le suivant"), mais l'API elle-même
    doit refuser ce cas plutôt que de perdre silencieusement le chapitre pour un futur appelant."""
    document = Document()
    chapter = _chapter_with_text("Un texte")
    document.chapters[chapter.id] = chapter
    document.structure.append_free_chapter(chapter.id)

    with pytest.raises(ValueError):
        document.merge_chapters(chapter.id, chapter.id)

    # Le chapitre doit rester intact après le rejet, pas à moitié muté.
    assert chapter.id in document.chapters
    assert [p.plain_text() for p in document.chapters[chapter.id].paragraphs] == ["Un texte"]
