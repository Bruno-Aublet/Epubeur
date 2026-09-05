from controller import ProjectController
from model.document import Chapter, Paragraph, Run
from model.styles import CharFormat, ParagraphAlign, ParagraphKind, VerticalAlign
from ui.chapter_editor_sync import KIND_TO_INT, EPUBEUR_PARAGRAPH_KIND_PROPERTY, extract_paragraphs_from_document
from ui.chapter_preview import ChapterPreview


def _make_preview(paragraphs: list[Paragraph]) -> ChapterPreview:
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = paragraphs
    controller.project.document.chapters[chapter.id] = chapter
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)
    return preview


def _extract(preview: ChapterPreview, chapter_paragraphs: list[Paragraph]) -> list:
    return extract_paragraphs_from_document(preview.document(), chapter_paragraphs,
                                             preview._eligible_paragraph_block_ranks)


def _cursor_on_first_paragraph(preview: ChapterPreview):
    """Le curseur par défaut après show_chapter() tombe sur le bloc du TITRE (rang 0), jamais
    sur le premier paragraphe de texte (rang 1 dès qu'un titre est affiché) — la plupart des
    tests ont besoin d'un curseur positionné sur du texte réel du chapitre."""
    block = preview.document().begin().next()
    cursor = preview.textCursor()
    cursor.setPosition(block.position())
    return cursor


def test_no_edit_round_trips_to_identical_paragraphs(qapp):
    original = [Paragraph(runs=[Run(text="Un texte simple", fmt=CharFormat())])]
    preview = _make_preview(original)

    result = _extract(preview, original)

    assert result == original


def test_bold_applied_via_cursor_is_extracted(qapp):
    from PySide6.QtGui import QFont, QTextCharFormat

    original = [Paragraph(runs=[Run(text="Un texte simple", fmt=CharFormat())])]
    preview = _make_preview(original)

    cursor = preview.textCursor()
    cursor.movePosition(cursor.MoveOperation.Start)
    cursor.movePosition(cursor.MoveOperation.End, cursor.MoveMode.KeepAnchor)
    fmt = QTextCharFormat()
    fmt.setFontWeight(QFont.Weight.Bold)
    cursor.mergeCharFormat(fmt)

    result = _extract(preview, original)

    assert len(result) == 1
    assert result[0].runs[0].fmt.bold is True
    assert result[0].runs[0].text == "Un texte simple"


def test_alignment_change_is_extracted(qapp):
    from PySide6.QtCore import Qt

    original = [Paragraph(runs=[Run(text="Texte", fmt=CharFormat())], align=ParagraphAlign.LEFT)]
    preview = _make_preview(original)

    cursor = _cursor_on_first_paragraph(preview)
    block_format = cursor.blockFormat()
    block_format.setAlignment(Qt.AlignmentFlag.AlignCenter)
    cursor.mergeBlockFormat(block_format)

    result = _extract(preview, original)

    assert result[0].align == ParagraphAlign.CENTER


def test_paragraph_kind_property_is_extracted(qapp):
    original = [Paragraph(runs=[Run(text="Texte", fmt=CharFormat())], kind=ParagraphKind.BODY)]
    preview = _make_preview(original)

    cursor = _cursor_on_first_paragraph(preview)
    block_format = cursor.blockFormat()
    block_format.setProperty(EPUBEUR_PARAGRAPH_KIND_PROPERTY, KIND_TO_INT[ParagraphKind.QUOTE])
    cursor.mergeBlockFormat(block_format)

    result = _extract(preview, original)

    assert result[0].kind == ParagraphKind.QUOTE


def test_typing_at_end_extends_existing_paragraph(qapp):
    original = [Paragraph(runs=[Run(text="Bonjour", fmt=CharFormat())])]
    preview = _make_preview(original)

    cursor = preview.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    preview.setTextCursor(cursor)
    preview.textCursor().insertText(" le monde")

    result = _extract(preview, original)

    assert len(result) == 1
    assert result[0].plain_text() == "Bonjour le monde"


def test_pressing_enter_mid_paragraph_inserts_new_paragraph(qapp):
    original = [
        Paragraph(runs=[Run(text="AAAA", fmt=CharFormat())]),
        Paragraph(runs=[Run(text="BBBB", fmt=CharFormat())]),
    ]
    preview = _make_preview(original)

    # Place le curseur au milieu du premier bloc de texte ("AA|AA") et insère un saut de ligne
    # de bloc (équivalent à Entrée), pour scinder ce paragraphe en deux.
    first_text_block = preview.document().begin()
    while first_text_block.isValid() and first_text_block.text() != "AAAA":
        first_text_block = first_text_block.next()
    cursor = preview.textCursor()
    cursor.setPosition(first_text_block.position() + 2)
    cursor.insertBlock()

    result = _extract(preview, original)

    assert len(result) == 3
    assert result[0].plain_text() == "AA"
    assert result[1].plain_text() == "AA"
    assert result[2].plain_text() == "BBBB"


def test_deleting_across_two_paragraphs_merges_them(qapp):
    original = [
        Paragraph(runs=[Run(text="AAAA", fmt=CharFormat())]),
        Paragraph(runs=[Run(text="BBBB", fmt=CharFormat())]),
    ]
    preview = _make_preview(original)

    first_text_block = preview.document().begin()
    while first_text_block.isValid() and first_text_block.text() != "AAAA":
        first_text_block = first_text_block.next()
    second_text_block = first_text_block.next()
    while second_text_block.isValid() and second_text_block.text() != "BBBB":
        second_text_block = second_text_block.next()

    cursor = preview.textCursor()
    cursor.setPosition(first_text_block.position() + 2)
    cursor.setPosition(second_text_block.position() + 2, cursor.MoveMode.KeepAnchor)
    cursor.removeSelectedText()

    result = _extract(preview, original)

    assert len(result) == 1
    assert result[0].plain_text() == "AABB"


def test_superscript_is_extracted(qapp):
    from PySide6.QtGui import QTextCharFormat

    original = [Paragraph(runs=[Run(text="m2", fmt=CharFormat())])]
    preview = _make_preview(original)

    cursor = preview.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.movePosition(cursor.MoveOperation.Left, cursor.MoveMode.KeepAnchor)
    fmt = QTextCharFormat()
    fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignSuperScript)
    cursor.mergeCharFormat(fmt)

    result = _extract(preview, original)

    runs = result[0].runs
    assert any(r.text == "2" and r.fmt.vertical_align == VerticalAlign.SUPERSCRIPT for r in runs)


def test_adjacent_runs_of_same_format_round_trip_without_spurious_diff(qapp):
    """Régression critique (undo/redo silencieusement cassé sur de vrais chapitres) : deux Run
    consécutifs de MÊME format (cas réel après import ODT, ex. deux <text:span> successifs de
    même style, ou texte + queue d'un lien) redevenaient un SEUL fragment Qt après un simple
    aller-retour setHtml()/extraction, sans aucune frappe utilisateur — extract_paragraphs_from_
    document() devait donc produire un résultat au moins ÉQUIVALENT (même texte/formatage
    effectif) à l'original pour être comparé correctement, cf. normalize_paragraphs_for_
    comparison() utilisée par ChapterPreview._sync_to_model(). Sans cette normalisation, CHAQUE
    paragraphe ayant ce genre de découpage de runs comparait comme "modifié" à la moindre
    reconstruction (undo/redo, changement de chapitre), déclenchant une réécriture parasite du
    modèle qui vidait silencieusement redo_stack juste avant que controller.redo() ne soit
    appelé : Ctrl+Y semblait ne plus rien faire, sur un vrai document de plusieurs centaines de
    paragraphes."""
    from ui.chapter_editor_sync import normalize_paragraphs_for_comparison

    fmt = CharFormat(bold=True)
    original = [Paragraph(runs=[Run(text="Bonjour ", fmt=fmt), Run(text="le monde.", fmt=fmt)])]
    preview = _make_preview(original)

    result = _extract(preview, original)

    assert result == normalize_paragraphs_for_comparison(original)
    assert result[0].plain_text() == "Bonjour le monde."


def test_quote_paragraph_italic_does_not_leak_from_blockquote_css(qapp):
    """Régression : ParagraphKind.QUOTE est rendu en <blockquote> avec un style CSS
    font-style: italic (cf. _show_chapter_impl) — QTextCharFormat.fontItalic() ne distingue pas
    cet italique hérité du style de bloc d'un <em> explicitement tapé (vérifié empiriquement),
    si bien que TOUT run d'un paragraphe QUOTE ressortait italic=True après un simple aller-
    retour setHtml()/extraction, même sans aucun <em> dans le HTML généré. Même conséquence que
    le bug des runs adjacents ci-dessus : chaque paragraphe QUOTE comparait comme "modifié" à
    la moindre reconstruction, déclenchant une réécriture parasite du modèle et vidant
    silencieusement redo_stack."""
    original = [Paragraph(kind=ParagraphKind.QUOTE, runs=[Run(text="Une citation.", fmt=CharFormat())])]
    preview = _make_preview(original)

    result = _extract(preview, original)

    assert result == original
    assert result[0].runs[0].fmt.italic is False


def test_justify_alignment_round_trips_without_spurious_diff(qapp):
    """Régression critique (undo/redo silencieusement cassé sur de vrais chapitres justifiés,
    cas normal pour un roman) : epub/html_render.py::ALIGN_CLASS n'exprime l'alignement QUE via
    une classe CSS (align-justify) — correct pour l'EPUB réel (vrai moteur CSS) mais le moteur
    Rich Text de Qt ignore silencieusement `text-align: justify` posé par une règle de <style>
    (classe ou style inline, peu importe), qu'il vienne d'une classe CSS ou d'un style inline —
    seul l'attribut HTML natif align="justify" est honoré (vérifié empiriquement : centré/droite
    fonctionnent très bien via une classe CSS, seul justify échoue). Sans le correctif
    (ChapterPreview._JUSTIFY_CLASS_RE, qui réinjecte l'attribut align="justify" dans le HTML
    juste avant setHtml()), TOUT paragraphe justifié ressortait align=LEFT après un simple
    aller-retour setHtml()/extraction, même sans aucune frappe utilisateur — sur un vrai chapitre
    de plusieurs centaines de paragraphes tous justifiés (cas normal), cela déclenchait une
    réécriture parasite du modèle à chaque undo/redo, vidant silencieusement redo_stack juste
    avant que Ctrl+Y ne s'exécute."""
    original = [Paragraph(align=ParagraphAlign.JUSTIFY, runs=[Run(text="Un texte justifié.", fmt=CharFormat())])]
    preview = _make_preview(original)

    result = _extract(preview, original)

    assert result == original
    assert result[0].align == ParagraphAlign.JUSTIFY
