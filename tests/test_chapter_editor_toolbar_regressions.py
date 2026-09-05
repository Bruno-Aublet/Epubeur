"""Régressions constatées lors des tests manuels de l'éditeur de texte riche :
1. les boutons de mise en forme (gras/italique/souligné/barré) n'avaient aucun style visuel
2. Ctrl+Z/Ctrl+Y semblaient ne rien faire (undo interne de QTextEdit + auto-écrasement de
   l'état restauré par une synchro survenant après coup)
3. insérer un saut de page ne se reflétait pas tant que le focus restait dans ChapterPreview
4. insérer un saut de page l'insérait AVANT le paragraphe cliqué au lieu d'APRÈS
5. le texte d'un paragraphe qui contient aussi une image (cas fréquent : premier paragraphe
   d'un chapitre avec une image ancrée) était intégralement non éditable, alors que seule
   l'image elle-même doit l'être
6. insérer un saut de page après le DERNIER paragraphe d'un chapitre était refusé à tort —
   c'est une intention utilisateur légitime (page blanche en fin de chapitre)
7. supprimer un saut de page via le menu contextuel (clic droit) ne se reflétait pas tant que
   le focus restait dans ChapterPreview — même famille de bug que le point 3, mais touchant
   TOUTE action du menu contextuel (image, saut de page...) puisque le clic droit ne fait pas
   perdre le focus au panneau
"""
from controller import ProjectController
from model.assets import AssetRole
from model.document import Chapter, ImageAnchor, Paragraph, Run
from model.styles import CharFormat
from ui.chapter_editor_sync import block_contains_image
from ui.chapter_preview import ChapterPreview, PAGE_BREAK_MARKER_TEXT
from ui.chapter_toolbar import ChapterFormatToolbar
from ui.structure_editor import StructureEditor


def _make_editor(qapp) -> tuple[ProjectController, StructureEditor]:
    controller = ProjectController()
    editor = StructureEditor(controller)
    return controller, editor


def test_chapter_preview_disables_its_own_undo_redo(qapp):
    """Ctrl+Z ne doit jamais être absorbé par le buffer Qt local (isUndoRedoEnabled==True le
    ferait taire silencieusement sans jamais toucher au modèle pivot) — il doit remonter
    jusqu'au raccourci de menu Edit > Annuler, seule source de vérité pour l'undo de l'app."""
    controller = ProjectController()
    preview = ChapterPreview(controller)

    assert preview.isUndoRedoEnabled() is False


def test_format_buttons_have_visual_style(qapp):
    """Les boutons gras/italique/souligné/barré doivent visuellement ressembler à ce qu'ils
    produisent, pas juste porter une lettre en police normale."""
    controller, editor = _make_editor(qapp)
    toolbar = editor.format_toolbar

    assert "bold" in toolbar.bold_btn.styleSheet()
    assert "italic" in toolbar.italic_btn.styleSheet()
    assert "underline" in toolbar.underline_btn.styleSheet()
    assert "line-through" in toolbar.strike_btn.styleSheet()


def _undo_like_main_window(preview) -> None:
    """Reproduit exactement MainWindow._undo (pas juste controller.undo seul) : synchronise
    l'édition en attente, bloque toute resynchro pendant la reconstruction qui suit, puis
    annule. Nécessaire pour couvrir fidèlement le vrai point d'entrée utilisateur (Ctrl+Z)."""
    preview.sync_pending_edits()
    preview.suppress_sync_until_next_reconstruction()
    preview.controller.undo()


def _redo_like_main_window(preview) -> None:
    preview.sync_pending_edits()
    preview.suppress_sync_until_next_reconstruction()
    preview.controller.redo()


def test_undo_after_text_edit_restores_previous_state_and_display(qapp):
    """Régression (triple bug, chacun découvert en corrigeant le précédent) : taper du texte
    puis appuyer directement sur Ctrl+Z, SANS avoir cliqué ailleurs au préalable, ne faisait
    rigoureusement rien.

    Cause 1 : la frappe n'était jamais poussée sur la pile undo tant qu'aucune synchro n'avait
    eu lieu (comportement voulu : synchro seulement à la perte de focus/changement de chapitre/
    sauvegarde) — controller.undo() n'avait donc RIEN à annuler. Fixé en synchronisant
    explicitement AVANT l'undo (cf. MainWindow._undo), pour que la frappe devienne elle-même la
    dernière entrée annulable.

    Cause 2 : une fois la synchro faite avant l'undo, StructureEditor._on_selection_changed()
    (appelée par refresh(), lui-même déclenché par le chapters_changed émis par undo())
    resynchronisait le document Qt ENCORE affiché (pas encore reconstruit) vers le modèle QUI
    VENAIT D'ÊTRE RESTAURÉ — écrasant silencieusement la restauration. Fixé en ne synchronisant
    dans _on_selection_changed que si le chapitre affiché va réellement CHANGER.

    Cause 3, invisible en environnement de test offscreen (hasFocus() y retourne toujours False,
    d'où ce test qui le force explicitement) : même sans la cause 2, show_chapter() lui-même
    (ChapterPreview._show_chapter_impl, cf. section correction du menu contextuel) resynchronise
    quand le panneau garde le focus — exactement le cas réel d'un Ctrl+Z juste après une frappe.
    Fixé avec suppress_sync_until_next_reconstruction(), posé entre la synchro et l'appel undo,
    qui bloque _sync_to_model() jusqu'à la reconstruction suivante, peu importe l'appelant."""
    controller, editor = _make_editor(qapp)
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(runs=[Run(text="Original", fmt=CharFormat())])]
    controller.project.document.add_chapter(chapter)
    controller.chapters_changed.emit()

    item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(item)
    preview = editor.preview
    assert preview._chapter_id == chapter.id
    # hasFocus() reste toujours False en environnement offscreen même après setFocus() —
    # forcé ici pour emprunter le même chemin de code qu'un vrai Ctrl+Z juste après une frappe
    # (le panneau a alors nécessairement le focus), cf. cause 3 ci-dessus.
    preview.hasFocus = lambda: True

    # Frappe utilisateur, SANS perte de focus ni synchro explicite avant le Ctrl+Z — exactement
    # le scénario rapporté : taper, puis Ctrl+Z immédiatement.
    cursor = preview.document().begin().next()
    text_cursor = preview.textCursor()
    text_cursor.setPosition(cursor.position())
    text_cursor.movePosition(text_cursor.MoveOperation.EndOfBlock, text_cursor.MoveMode.KeepAnchor)
    text_cursor.insertText("Modifié")
    assert controller.project.document.chapters[chapter.id].paragraphs[0].plain_text() == "Original"

    _undo_like_main_window(preview)

    assert controller.project.document.chapters[chapter.id].paragraphs[0].plain_text() == "Original"
    assert "Modifié" not in preview.toPlainText()
    assert "Original" in preview.toPlainText()

    # Le redo symétrique doit aussi fonctionner sans être écrasé par le même mécanisme.
    _redo_like_main_window(preview)
    assert controller.project.document.chapters[chapter.id].paragraphs[0].plain_text() == "Modifié"
    assert "Modifié" in preview.toPlainText()


def test_insert_page_break_reflects_immediately_even_with_focus(qapp):
    """Régression : insérer un saut de page depuis la toolbar ne se reflétait dans l'aperçu
    qu'après avoir changé puis repris la sélection du chapitre, tant que le focus restait dans
    ChapterPreview (show_chapter différait sa reconstruction comme pour une frappe en cours)."""
    controller, editor = _make_editor(qapp)
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="Premier paragraphe", fmt=CharFormat())]),
        Paragraph(runs=[Run(text="Deuxième paragraphe", fmt=CharFormat())]),
        Paragraph(runs=[Run(text="Troisième paragraphe", fmt=CharFormat())]),
    ]
    controller.project.document.add_chapter(chapter)
    controller.chapters_changed.emit()

    item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(item)

    # Place le curseur sur le second paragraphe et simule le focus resté dans le panneau (comme
    # après un clic sur le bouton de la toolbar, qui ne fait pas perdre le focus à ChapterPreview).
    # setFocus() seul ne suffit pas en environnement offscreen (hasFocus() y reste False) : forcé
    # explicitement pour emprunter le même chemin de code qu'en usage réel.
    second_block = editor.preview.document().begin().next().next()
    cursor = editor.preview.textCursor()
    cursor.setPosition(second_block.position())
    editor.preview.setTextCursor(cursor)
    editor.preview.setFocus()
    editor.preview.hasFocus = lambda: True
    qapp.processEvents()

    toolbar = editor.format_toolbar
    toolbar._insert_page_break()

    assert PAGE_BREAK_MARKER_TEXT in editor.preview.toPlainText()
    # Le saut de page doit apparaître APRÈS le paragraphe où était le curseur (index 1), donc
    # porté par le paragraphe suivant (index 2) — pas avant celui où était le curseur.
    assert controller.project.document.chapters[chapter.id].paragraphs[1].page_break_before is False
    assert controller.project.document.chapters[chapter.id].paragraphs[2].page_break_before is True


def test_insert_page_break_on_last_paragraph_appends_carrier_paragraph(qapp):
    """Insérer un saut de page après le DERNIER paragraphe d'un chapitre est une intention
    utilisateur légitime (ex. forcer une page blanche en fin de chapitre) — il n'existe aucun
    paragraphe suivant pour porter page_break_before, donc un nouveau Paragraph vide est ajouté
    à cet effet plutôt que de refuser l'action."""
    controller, editor = _make_editor(qapp)
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="Premier paragraphe", fmt=CharFormat())]),
        Paragraph(runs=[Run(text="Dernier paragraphe", fmt=CharFormat())]),
    ]
    controller.project.document.add_chapter(chapter)
    controller.chapters_changed.emit()

    item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(item)

    last_block = editor.preview.document().begin().next().next()
    cursor = editor.preview.textCursor()
    cursor.setPosition(last_block.position())
    editor.preview.setTextCursor(cursor)
    editor.preview.setFocus()
    editor.preview.hasFocus = lambda: True
    qapp.processEvents()

    editor.format_toolbar._insert_page_break()

    paragraphs = controller.project.document.chapters[chapter.id].paragraphs
    assert len(paragraphs) == 3
    assert paragraphs[2].page_break_before is True
    assert paragraphs[2].plain_text() == ""
    assert PAGE_BREAK_MARKER_TEXT in editor.preview.toPlainText()


def _add_chapter_with_leading_image_paragraph(controller) -> Chapter:
    asset = controller.asset_store.ingest_bytes(
        b"\xff\xd8\xff\xe0fakejpeg", original_filename="perso.jpg", role=AssetRole.CHAPTER_POV
    )
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(
            image=ImageAnchor(asset_id=asset.id, alt_text="Personnage"),
            runs=[Run(text="Premier Prologue : texte du paragraphe", fmt=CharFormat())],
        ),
        Paragraph(runs=[Run(text="Deuxième paragraphe", fmt=CharFormat())]),
    ]
    controller.project.document.add_chapter(chapter)
    controller.chapters_changed.emit()
    return chapter


def test_text_block_of_paragraph_with_unwrapped_image_is_editable(qapp):
    """Régression : un paragraphe qui contient à la fois du texte et une image (sans habillage,
    donc isolée dans son propre bloc Qt par _isolate_images) était intégralement classé non
    éditable — y compris son bloc de TEXTE, qui n'a pourtant rien à voir avec l'image."""
    controller, editor = _make_editor(qapp)
    chapter = _add_chapter_with_leading_image_paragraph(controller)

    item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(item)
    preview = editor.preview

    # Le premier paragraphe est scindé en (au moins) un bloc-image puis un bloc-texte — trouve
    # le bloc qui porte le texte réel du paragraphe.
    block = preview.document().begin()
    while block.isValid() and "Premier Prologue" not in block.text():
        block = block.next()
    assert block.isValid(), "bloc de texte du premier paragraphe introuvable"

    assert preview._is_block_editable(block) is True

    cursor = preview.textCursor()
    cursor.setPosition(block.position())
    preview.setTextCursor(cursor)
    qapp.processEvents()
    assert editor.format_toolbar.bold_btn.isEnabled() is True


def test_image_block_of_paragraph_with_unwrapped_image_stays_non_editable(qapp):
    """Le bloc qui porte l'image elle-même (distinct du bloc texte, cf. test précédent) doit
    lui rester non éditable — seule son interaction via le menu contextuel dédié reste valide."""
    controller, editor = _make_editor(qapp)
    _add_chapter_with_leading_image_paragraph(controller)

    item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(item)
    preview = editor.preview

    image_block = preview.document().begin()
    while image_block.isValid() and not block_contains_image(image_block):
        image_block = image_block.next()
    assert image_block.isValid(), "bloc image introuvable"

    assert preview._is_block_editable(image_block) is False


def test_editing_text_of_paragraph_with_image_preserves_the_image(qapp):
    """La synchronisation vers le modèle après édition du texte d'un paragraphe avec image doit
    conserver l'image (ImageAnchor) inchangée, seul le texte doit refléter la frappe."""
    controller, editor = _make_editor(qapp)
    chapter = _add_chapter_with_leading_image_paragraph(controller)
    original_image = chapter.paragraphs[0].image

    item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(item)
    preview = editor.preview

    block = preview.document().begin()
    while block.isValid() and "Premier Prologue" not in block.text():
        block = block.next()
    cursor = preview.textCursor()
    cursor.setPosition(block.position() + len("Premier Prologue"))
    preview.setTextCursor(cursor)
    preview.textCursor().insertText(" MODIFIÉ")

    preview.sync_pending_edits()

    updated = controller.project.document.chapters[chapter.id].paragraphs[0]
    assert "MODIFIÉ" in updated.plain_text()
    assert updated.image == original_image


def test_paragraph_with_only_an_image_survives_unrelated_sync(qapp):
    """Régression : un paragraphe composé UNIQUEMENT d'une image (aucun texte) disparaissait
    intégralement de chapter.paragraphs à la première synchronisation déclenchée par une action
    sans rapport (ex. changer la taille d'affichage de l'image depuis l'onglet Images) — un tel
    paragraphe ne produit aucun bloc Qt de texte séparé, cf. ChapterPreview._isolate_images."""
    from model.document import ImageDisplaySize

    controller, editor = _make_editor(qapp)
    asset = controller.asset_store.ingest_bytes(
        b"\xff\xd8\xff\xe0fakejpeg", original_filename="perso.jpg", role=AssetRole.CHAPTER_POV
    )
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Personnage"))]
    controller.project.document.add_chapter(chapter)
    controller.chapters_changed.emit()

    item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(item)

    controller.set_image_display_size(asset.id, ImageDisplaySize.SMALL)

    assert len(controller.project.document.chapters[chapter.id].paragraphs) == 1
    assert controller.project.document.chapters[chapter.id].paragraphs[0].image.asset_id == asset.id


def test_removing_page_break_via_context_menu_reflects_immediately_with_focus(qapp):
    """Régression : self.hasFocus() était utilisé comme seul critère pour différer la
    reconstruction de show_chapter(), alors qu'un clic droit (menu contextuel) ne fait PAS
    perdre le focus au panneau — toute action de ce menu (ici : supprimer un saut de page)
    restait invisible tant que l'utilisateur ne changeait pas puis reprenait la sélection du
    chapitre. La correction ne différer que s'il existe RÉELLEMENT du texte non synchronisable
    (divergence de structure), jamais simplement parce que le widget a le focus."""
    controller, editor = _make_editor(qapp)
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="Avant le saut", fmt=CharFormat())]),
        Paragraph(runs=[Run(text="Après le saut", fmt=CharFormat())], page_break_before=True),
    ]
    controller.project.document.add_chapter(chapter)
    controller.chapters_changed.emit()

    item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(item)
    preview = editor.preview
    preview.setFocus()
    preview.hasFocus = lambda: True
    qapp.processEvents()

    assert PAGE_BREAK_MARKER_TEXT in preview.toPlainText()

    # marker_rank=0 : premier (et seul) marqueur de saut de page affiché, cf. _remove_page_break.
    preview._remove_page_break(0)

    assert controller.project.document.chapters[chapter.id].paragraphs[1].page_break_before is False
    assert PAGE_BREAK_MARKER_TEXT not in preview.toPlainText()
