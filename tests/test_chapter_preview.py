from pathlib import Path

from controller import ProjectController
from model.assets import AssetRole
from model.document import (
    Chapter,
    ImageAnchor,
    ImageDisplaySize,
    ImageWrap,
    Paragraph,
    Run,
    Table,
    TableCell,
    TableRow,
)
from model.styles import CharFormat, ParagraphAlign, ParagraphKind
from ui.chapter_preview import ChapterPreview


def _make_chapter_with_page_break() -> Chapter:
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="Avant le saut", fmt=CharFormat())]),
        Paragraph(runs=[Run(text="Après le saut", fmt=CharFormat())], page_break_before=True),
    ]
    return chapter


def test_preview_shows_marker_for_manual_page_break(qapp):
    controller = ProjectController()
    chapter = _make_chapter_with_page_break()
    controller.project.document.chapters[chapter.id] = chapter

    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    assert "2a6fdb" in preview.toHtml()


def test_preview_shows_no_marker_without_page_break(qapp):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="Un seul paragraphe", fmt=CharFormat())]),
    ]
    controller.project.document.chapters[chapter.id] = chapter

    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    assert "2a6fdb" not in preview.toHtml()


def test_preview_tracks_paragraph_index_per_marker(qapp):
    controller = ProjectController()
    chapter = _make_chapter_with_page_break()
    controller.project.document.chapters[chapter.id] = chapter

    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    assert preview._page_break_paragraph_indexes == [1]


def test_preview_tracks_multiple_markers_in_order(qapp):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="A", fmt=CharFormat())]),
        Paragraph(runs=[Run(text="B", fmt=CharFormat())], page_break_before=True),
        Paragraph(runs=[Run(text="C", fmt=CharFormat())]),
        Paragraph(runs=[Run(text="D", fmt=CharFormat())], page_break_before=True),
    ]
    controller.project.document.chapters[chapter.id] = chapter

    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    assert preview._page_break_paragraph_indexes == [1, 3]


def test_controller_remove_page_break_clears_flag(qapp):
    controller = ProjectController()
    chapter = _make_chapter_with_page_break()
    controller.project.document.chapters[chapter.id] = chapter

    controller.remove_page_break(chapter.id, 1)

    assert chapter.paragraphs[1].page_break_before is False


def test_controller_remove_page_break_is_undoable(qapp):
    controller = ProjectController()
    chapter = _make_chapter_with_page_break()
    chapter_id = chapter.id
    controller.project.document.chapters[chapter_id] = chapter

    controller.remove_page_break(chapter_id, 1)
    assert controller.project.document.chapters[chapter_id].paragraphs[1].page_break_before is False

    controller.undo()
    assert controller.project.document.chapters[chapter_id].paragraphs[1].page_break_before is True


def test_controller_remove_page_break_out_of_range_is_noop(qapp):
    controller = ProjectController()
    chapter = _make_chapter_with_page_break()
    controller.project.document.chapters[chapter.id] = chapter

    controller.remove_page_break(chapter.id, 99)

    assert controller.can_undo() is False


def test_context_menu_removes_correct_page_break_via_right_click(qapp):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="A", fmt=CharFormat())]),
        Paragraph(runs=[Run(text="B", fmt=CharFormat())], page_break_before=True),
        Paragraph(runs=[Run(text="C", fmt=CharFormat())]),
        Paragraph(runs=[Run(text="D", fmt=CharFormat())], page_break_before=True),
    ]
    controller.project.document.chapters[chapter.id] = chapter

    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    # Simule directement l'action "Supprimer" pour le second marqueur (rank=1), sans passer
    # par un vrai clic (positionnement pixel-perfect non fiable en environnement headless).
    preview._remove_page_break(1)

    assert chapter.paragraphs[1].page_break_before is True   # premier saut intact
    assert chapter.paragraphs[3].page_break_before is False  # second saut supprimé


def test_preview_preserves_consecutive_empty_paragraphs_as_distinct_blocks(qapp):
    """QTextBrowser (moteur Rich Text de Qt) supprime purement et simplement tout bloc <p>
    totalement vide au lieu de collapser sa marge — sans contournement, plusieurs paragraphes
    vides consécutifs (Entrée simple répétée dans Writer) disparaîtraient complètement de
    l'aperçu, alors qu'ils sont bien présents dans le document."""
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="Texte1", fmt=CharFormat())]),
        Paragraph(runs=[]),
        Paragraph(runs=[]),
        Paragraph(runs=[Run(text="Texte2", fmt=CharFormat())]),
    ]
    controller.project.document.chapters[chapter.id] = chapter

    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    block_texts = []
    block = preview.document().begin()
    while block.isValid():
        block_texts.append(block.text())
        block = block.next()

    assert block_texts == ["Chapitre Un", "Texte1", "\xa0", "\xa0", "Texte2"]


def test_preview_preserves_empty_paragraphs_with_non_default_alignment(qapp):
    """Régression : un paragraphe vide avec un alignement non-défaut (centré, droit, justifié)
    produit <p class="align-center"></p>, pas <p></p> nu — un remplacement par correspondance
    de chaîne littérale échouait silencieusement pour ce cas, laissant le paragraphe disparaître
    de l'aperçu malgré le contournement déjà en place pour le cas <p></p> simple."""
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="Texte1", fmt=CharFormat())], align=ParagraphAlign.CENTER),
        Paragraph(runs=[], align=ParagraphAlign.CENTER),
        Paragraph(runs=[], align=ParagraphAlign.CENTER),
        Paragraph(runs=[Run(text="Texte2", fmt=CharFormat())], align=ParagraphAlign.CENTER),
    ]
    controller.project.document.chapters[chapter.id] = chapter

    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    block_texts = []
    block = preview.document().begin()
    while block.isValid():
        block_texts.append(block.text())
        block = block.next()

    assert block_texts == ["Chapitre Un", "Texte1", "\xa0", "\xa0", "Texte2"]


def test_preview_resolves_image_to_real_file_path(qapp):
    """Régression : paragraph_to_html émet src="../images/{id}.{ext}", un chemin relatif
    valable uniquement dans la structure du zip EPUB final — QTextBrowser.setHtml() n'a pas de
    base URL correspondante, donc ce chemin ne résolvait jamais vers un fichier réel et les
    images n'apparaissaient jamais dans cet aperçu."""
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", original_filename="perso.jpg",
                                                  role=AssetRole.CHAPTER_POV)
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Personnage")),
    ]
    controller.project.document.chapters[chapter.id] = chapter

    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    html = preview.toHtml()
    real_path = controller.asset_store.path_for(asset.id)
    assert real_path.name in html
    assert "../images/" not in html


def test_preview_applies_configured_image_display_size(qapp):
    """Régression : la taille d'affichage réglée dans l'onglet Images (ImageDisplaySize,
    appliquée via une règle CSS ciblée par asset_id pour l'EPUB réel) n'était jamais injectée
    dans le <style> de cet aperçu — une image réglée à une taille réduite s'affichait quand
    même en pleine largeur."""
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", original_filename="perso.jpg",
                                                  role=AssetRole.CHAPTER_POV)
    controller.project.document.image_display_sizes[asset.id] = ImageDisplaySize.SMALL

    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Personnage")),
    ]
    controller.project.document.chapters[chapter.id] = chapter

    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    html = preview.toHtml()
    assert "max-width:25%" in html


def test_preview_does_not_constrain_image_left_at_default_size(qapp):
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", original_filename="perso.jpg",
                                                  role=AssetRole.CHAPTER_POV)
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Personnage")),
    ]
    controller.project.document.chapters[chapter.id] = chapter

    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    html = preview.toHtml()
    assert "max-width" not in html


def test_preview_isolates_image_from_accompanying_text(qapp):
    """Régression : paragraph_to_html insère l'<img> en tête du <p> qui contient aussi le texte
    du même paragraphe. Un vrai moteur CSS (Chromium/liseuses) détache visuellement l'image
    grâce à img { display: block; margin: auto; } (epub/css.py) même dans ce HTML techniquement
    imbriqué, mais Qt Rich Text ignore ces deux propriétés et rendait l'image collée au texte,
    en ligne avec lui."""
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", original_filename="perso.jpg",
                                                  role=AssetRole.CHAPTER_POV)
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Personnage"),
                  runs=[Run(text="Légende de l'image", fmt=CharFormat())]),
    ]
    controller.project.document.chapters[chapter.id] = chapter

    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    doc = preview.document()
    block = doc.begin()
    block_texts = []
    while block.isValid():
        block_texts.append(block.text())
        block = block.next()

    # Le texte "Légende de l'image" doit être dans un bloc SÉPARÉ de celui contenant l'image
    # (un bloc avec une image seule a un texte vide côté QTextDocument.blockFormat, mais le
    # bloc lui-même existe distinctement de celui du texte qui l'accompagnait).
    assert "Légende de l'image" in block_texts
    assert len(block_texts) >= 3  # titre + bloc image + bloc texte, au minimum


# --- Habillage de texte (ImageWrap) dans l'aperçu ---
# Régression : image_wraps n'était jamais transmis à paragraphs_to_html ni la règle CSS
# correspondante (float) injectée dans le <style> de cet aperçu — le réglage n'avait donc AUCUN
# effet visuel ici, contrairement à l'EPUB généré (où il fonctionne, epub/css.py::IMAGE_WRAP_CSS).

def test_preview_injects_wrap_css_rule(qapp):
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", original_filename="perso.jpg",
                                                  role=AssetRole.CHAPTER_POV)
    controller.project.document.image_wraps[asset.id] = ImageWrap.LEFT
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Personnage"))]
    controller.project.document.chapters[chapter.id] = chapter

    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    # QTextDocument.toHtml() re-sérialise le document interne : les attributs HTML custom (dont
    # data-epubeur-image-wrap, posé dans le HTML source injecté via setHtml) ne survivent pas,
    # seule la propriété CSS réellement appliquée (float) est reportée en style inline sur l'img
    # — c'est donc la preuve la plus fiable que Qt a bien appliqué la règle.
    assert "float:left" in preview.toHtml().replace(" ", "")


def test_isolate_images_does_not_split_wrapped_image_from_its_text(qapp):
    """Contrairement à une image sans habillage (toujours isolée dans son propre
    <p align="center">, cf. test_preview_isolates_image_from_accompanying_text) : une image AVEC
    un habillage réglé (gauche/droite) doit rester dans le MÊME <p> que son texte, sinon le texte
    ne peut pas s'enrouler autour d'elle (float, cf. IMAGE_WRAP_CSS) — l'isolement forcerait deux
    blocs empilés verticalement, annulant l'effet visuel."""
    controller = ProjectController()
    preview = ChapterPreview(controller)

    html_in = ('<p><img src="file:///x.jpg" data-epubeur-image-wrap="left"/>'
               "Légende de l'image</p>")
    html_out = preview._isolate_images(html_in)

    assert html_out == html_in  # inchangé : pas de séparation en deux <p>


def test_isolate_images_still_splits_unwrapped_image_from_its_text(qapp):
    controller = ProjectController()
    preview = ChapterPreview(controller)

    html_in = '<p><img src="file:///x.jpg"/>Légende de l\'image</p>'
    html_out = preview._isolate_images(html_in)

    assert html_out.startswith('<p align="center"><img src="file:///x.jpg"/></p>')
    assert "Légende de l'image" in html_out
    assert html_out != html_in


def test_preview_refreshes_when_image_display_size_changes(qapp):
    """Régression : changer la taille d'une image dans l'onglet Images (assets_changed) ne
    déclenchait aucun rafraîchissement de l'aperçu Structure, qui restait affiché avec l'ancienne
    taille tant que la sélection de l'arbre ne changeait pas explicitement."""
    from ui.structure_editor import StructureEditor

    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", original_filename="perso.jpg",
                                                  role=AssetRole.CHAPTER_POV)
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Personnage")),
    ]
    controller.project.document.add_chapter(chapter)
    controller.chapters_changed.emit()

    editor = StructureEditor(controller)
    item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(item)
    assert "max-width" not in editor.preview.toHtml()

    controller.set_image_display_size(asset.id, ImageDisplaySize.SMALL)

    assert "max-width:25%" in editor.preview.toHtml()


# --- Menu contextuel (clic droit) sur une image de l'aperçu ---
# Régression : les réglages de taille/positionnement d'une image (déjà disponibles dans l'onglet
# Images) doivent aussi être accessibles par clic droit directement sur l'image, dans l'aperçu de
# l'onglet Structure — sans avoir à changer d'onglet.

def _make_chapter_with_image(controller: ProjectController):
    asset = controller.asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", original_filename="perso.jpg",
                                                  role=AssetRole.CHAPTER_POV)
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Personnage")),
    ]
    controller.project.document.chapters[chapter.id] = chapter
    return chapter, asset


def _find_image_position(preview: ChapterPreview, qapp):
    """Localise une position (coordonnées viewport) qui tombe sur l'image affichée — pas de
    positionnement pixel-perfect fiable en environnement headless, donc on balaie la hauteur du
    document rendu jusqu'à trouver un format image. cursorForPosition() ne renvoie des positions
    fiables qu'une fois le widget réellement affiché et son layout calculé (show() +
    processEvents()), sinon tout retombe systématiquement sur le tout début du document."""
    from PySide6.QtCore import QPoint

    preview.show()
    qapp.processEvents()
    for y in range(0, 600, 5):
        pos = QPoint(50, y)
        cursor = preview.cursorForPosition(pos)
        if cursor.charFormat().isImageFormat():
            return pos
    return None


def test_asset_id_at_resolves_the_clicked_image(qapp):
    controller = ProjectController()
    chapter, asset = _make_chapter_with_image(controller)
    preview = ChapterPreview(controller)
    preview.resize(400, 600)
    preview.show_chapter(chapter.id)

    pos = _find_image_position(preview, qapp)
    assert pos is not None
    assert preview._asset_id_at(pos) == asset.id


def test_asset_id_at_returns_none_off_image(qapp):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(runs=[Run(text="Texte seul", fmt=CharFormat())])]
    controller.project.document.chapters[chapter.id] = chapter

    preview = ChapterPreview(controller)
    preview.resize(400, 600)
    preview.show_chapter(chapter.id)
    preview.show()
    qapp.processEvents()

    from PySide6.QtCore import QPoint
    assert preview._asset_id_at(QPoint(10, 10)) is None


def test_set_image_display_size_from_preview_updates_document(qapp):
    controller = ProjectController()
    chapter, asset = _make_chapter_with_image(controller)
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    preview._set_image_display_size(asset.id, ImageDisplaySize.SMALL)

    assert controller.project.document.image_display_size(asset.id) == ImageDisplaySize.SMALL


def test_set_image_wrap_from_preview_updates_document(qapp):
    controller = ProjectController()
    chapter, asset = _make_chapter_with_image(controller)
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    preview._set_image_wrap(asset.id, ImageWrap.LEFT)

    assert controller.project.document.image_wrap(asset.id) == ImageWrap.LEFT


def test_set_image_display_size_from_preview_is_undoable(qapp):
    controller = ProjectController()
    chapter, asset = _make_chapter_with_image(controller)
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    preview._set_image_display_size(asset.id, ImageDisplaySize.SMALL)
    assert controller.can_undo() is True

    controller.undo()
    assert controller.project.document.image_display_size(asset.id) == ImageDisplaySize.FULL


# --- Mapping bloc Qt -> index de paragraphe (_paragraph_index_at) ---
# Sous-tend "Insérer une image ici" et "Supprimer cette image".

def test_paragraph_index_at_resolves_simple_paragraph(qapp):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="Un", fmt=CharFormat())]),
        Paragraph(runs=[Run(text="Deux", fmt=CharFormat())]),
        Paragraph(runs=[Run(text="Trois", fmt=CharFormat())]),
    ]
    controller.project.document.chapters[chapter.id] = chapter
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    # rang 0 = h1 titre, rang 1 = "Un", rang 2 = "Deux", rang 3 = "Trois"
    assert preview._eligible_paragraph_block_ranks == {1: 0, 2: 1, 3: 2}


def test_paragraph_index_at_returns_none_for_list_item(qapp):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="Avant liste", fmt=CharFormat())]),
        Paragraph(runs=[Run(text="Item", fmt=CharFormat())],
                  kind=ParagraphKind.LIST_ITEM_BULLET, list_level=1),
        Paragraph(runs=[Run(text="Après liste", fmt=CharFormat())]),
    ]
    controller.project.document.chapters[chapter.id] = chapter
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    # index 1 (l'item de liste) ne doit apparaître dans aucune valeur du mapping
    assert 1 not in preview._eligible_paragraph_block_ranks.values()
    assert set(preview._eligible_paragraph_block_ranks.values()) == {0, 2}


def test_paragraph_index_at_returns_none_on_image_click(qapp):
    """C'est _asset_id_at qui gère le cas d'un clic sur une image, pas ce fallback texte."""
    controller = ProjectController()
    chapter, asset = _make_chapter_with_image(controller)
    preview = ChapterPreview(controller)
    preview.resize(400, 300)
    preview.show_chapter(chapter.id)
    preview.show()
    qapp.processEvents()

    pos = _find_image_position(preview, qapp)
    assert pos is not None
    assert preview._asset_id_at(pos) == asset.id


def test_paragraph_index_at_resolves_same_index_for_image_and_text_blocks_of_same_paragraph(qapp):
    """Une image SANS habillage avec légende est scindée par _isolate_images en 2 blocs Qt
    distincts (image isolée + texte séparé) — les deux doivent pointer vers le même
    paragraph_index, sinon les paragraphes suivants seraient décalés dans le mapping."""
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", original_filename="perso.jpg",
                                                  role=AssetRole.CHAPTER_POV)
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(image=ImageAnchor(asset_id=asset.id), runs=[Run(text="Légende", fmt=CharFormat())]),
        Paragraph(runs=[Run(text="Suite", fmt=CharFormat())]),
    ]
    controller.project.document.chapters[chapter.id] = chapter
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    # 2 rangs (1 pour l'image, 1 pour le texte de légende) pointent vers l'index 0, puis
    # "Suite" (index 1) sur le rang suivant, non décalé.
    ranks_for_zero = [r for r, idx in preview._eligible_paragraph_block_ranks.items() if idx == 0]
    assert len(ranks_for_zero) == 2
    ranks_for_one = [r for r, idx in preview._eligible_paragraph_block_ranks.items() if idx == 1]
    assert len(ranks_for_one) == 1
    assert ranks_for_one[0] == max(ranks_for_zero) + 1


def test_paragraph_index_at_resolves_correctly_for_wrapped_image_with_text(qapp):
    """Une image AVEC habillage (gauche/droite) n'est PAS scindée par _isolate_images (reste
    dans le même <p> que son texte pour permettre le float) — un seul bloc Qt, le paragraphe
    suivant ne doit pas être décalé."""
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", original_filename="perso.jpg",
                                                  role=AssetRole.CHAPTER_POV)
    controller.project.document.image_wraps[asset.id] = ImageWrap.LEFT
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(image=ImageAnchor(asset_id=asset.id), runs=[Run(text="Légende", fmt=CharFormat())]),
        Paragraph(runs=[Run(text="Suite", fmt=CharFormat())]),
    ]
    controller.project.document.chapters[chapter.id] = chapter
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    ranks_for_zero = [r for r, idx in preview._eligible_paragraph_block_ranks.items() if idx == 0]
    assert len(ranks_for_zero) == 1
    ranks_for_one = [r for r, idx in preview._eligible_paragraph_block_ranks.items() if idx == 1]
    assert ranks_for_one[0] == ranks_for_zero[0] + 1


def _make_table(cells_per_row: list[int], multi_paragraph_cell: bool = False) -> Table:
    rows = []
    for count in cells_per_row:
        cells = []
        for _ in range(count):
            if multi_paragraph_cell:
                cells.append(TableCell(paragraphs=[
                    Paragraph(runs=[Run(text="L1", fmt=CharFormat())]),
                    Paragraph(runs=[Run(text="L2", fmt=CharFormat())]),
                ]))
            else:
                cells.append(TableCell(paragraphs=[Paragraph(runs=[Run(text="C", fmt=CharFormat())])]))
        rows.append(TableRow(cells=cells))
    return Table(rows=rows)


def test_paragraph_index_at_resolves_paragraph_after_a_table_with_multiple_cells(qapp):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="Avant", fmt=CharFormat())]),
        _make_table([2, 2]),  # 4 cellules -> 4 blocs + 1 bloc fantôme = 5 rangs consommés
        Paragraph(runs=[Run(text="Après", fmt=CharFormat())]),
    ]
    controller.project.document.chapters[chapter.id] = chapter
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    # rang 0 = h1, rang 1 = "Avant" (index 0), rangs 2-5 = table (4 cellules + 1 fantôme),
    # rang 7 = "Après" (index 2)
    assert preview._eligible_paragraph_block_ranks == {1: 0, 7: 2}


def test_paragraph_index_at_resolves_paragraph_after_a_table_with_merged_cells(qapp):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    table = Table(rows=[
        TableRow(cells=[TableCell(paragraphs=[Paragraph(runs=[Run(text="A", fmt=CharFormat())])], colspan=2)]),
        TableRow(cells=[TableCell(paragraphs=[Paragraph(runs=[Run(text="C", fmt=CharFormat())])]),
                        TableCell(paragraphs=[Paragraph(runs=[Run(text="D", fmt=CharFormat())])])]),
    ])
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="Avant", fmt=CharFormat())]),
        table,  # 3 vraies cellules (A, C, D) -> 3 blocs + 1 fantôme = 4 rangs consommés
        Paragraph(runs=[Run(text="Après", fmt=CharFormat())]),
    ]
    controller.project.document.chapters[chapter.id] = chapter
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    # rang 0 = h1, rang 1 = "Avant", rangs 2-5 = table (3 cellules + 1 fantôme), rang 6 = "Après"
    assert preview._eligible_paragraph_block_ranks == {1: 0, 6: 2}


def test_paragraph_index_at_resolves_paragraph_after_a_table_with_empty_cell(qapp):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    table = Table(rows=[TableRow(cells=[TableCell(paragraphs=[]), TableCell(paragraphs=[
        Paragraph(runs=[Run(text="B", fmt=CharFormat())])])])])
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="Avant", fmt=CharFormat())]),
        table,  # cellule vide (min 1 bloc) + cellule B (1 bloc) + 1 fantôme = 3 rangs
        Paragraph(runs=[Run(text="Après", fmt=CharFormat())]),
    ]
    controller.project.document.chapters[chapter.id] = chapter
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    # rang 0 = h1, rang 1 = "Avant", rangs 2-4 = table (2 blocs + 1 fantôme), rang 5 = "Après"
    assert preview._eligible_paragraph_block_ranks == {1: 0, 5: 2}


def test_paragraph_index_at_resolves_paragraph_after_a_table_with_multi_paragraph_cell(qapp):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="Avant", fmt=CharFormat())]),
        _make_table([1], multi_paragraph_cell=True),  # 1 cellule à 2 paragraphes + 1 fantôme = 3 rangs
        Paragraph(runs=[Run(text="Après", fmt=CharFormat())]),
    ]
    controller.project.document.chapters[chapter.id] = chapter
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    # rang 0 = h1, rang 1 = "Avant", rangs 2-4 = table (2 blocs + 1 fantôme), rang 5 = "Après"
    assert preview._eligible_paragraph_block_ranks == {1: 0, 5: 2}


# --- "Insérer une image ici" ---

def test_context_menu_insert_image_action_present_on_simple_paragraph(qapp):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(runs=[Run(text="Texte", fmt=CharFormat())])]
    controller.project.document.chapters[chapter.id] = chapter
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    assert preview._eligible_paragraph_block_ranks.get(1) == 0


def test_insert_image_after_paragraph_inserts_new_paragraph_at_correct_position(qapp, tmp_path):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="Un", fmt=CharFormat())]),
        Paragraph(runs=[Run(text="Deux", fmt=CharFormat())]),
    ]
    controller.project.document.chapters[chapter.id] = chapter

    image_path = tmp_path / "img.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    controller.insert_image_after_paragraph(chapter.id, 0, image_path)

    assert len(chapter.paragraphs) == 3
    assert chapter.paragraphs[0].plain_text() == "Un"
    assert chapter.paragraphs[1].image is not None
    assert chapter.paragraphs[2].plain_text() == "Deux"


def test_insert_image_after_paragraph_defaults_to_full_size_and_no_wrap(qapp, tmp_path):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(runs=[Run(text="Un", fmt=CharFormat())])]
    controller.project.document.chapters[chapter.id] = chapter

    image_path = tmp_path / "img.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    controller.insert_image_after_paragraph(chapter.id, 0, image_path)

    asset_id = chapter.paragraphs[1].image.asset_id
    assert asset_id not in controller.project.document.image_display_sizes
    assert asset_id not in controller.project.document.image_wraps
    assert controller.project.document.image_display_size(asset_id) == ImageDisplaySize.FULL
    assert controller.project.document.image_wrap(asset_id) == ImageWrap.NONE


def test_insert_image_after_paragraph_is_undoable(qapp, tmp_path):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(runs=[Run(text="Un", fmt=CharFormat())])]
    controller.project.document.chapters[chapter.id] = chapter

    image_path = tmp_path / "img.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    controller.insert_image_after_paragraph(chapter.id, 0, image_path)
    assert len(chapter.paragraphs) == 2

    controller.undo()
    assert len(controller.project.document.chapters[chapter.id].paragraphs) == 1


def test_insert_image_after_paragraph_out_of_range_is_noop(qapp, tmp_path):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(runs=[Run(text="Un", fmt=CharFormat())])]
    controller.project.document.chapters[chapter.id] = chapter

    image_path = tmp_path / "img.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    controller.insert_image_after_paragraph(chapter.id, 99, image_path)

    assert controller.can_undo() is False
    assert len(chapter.paragraphs) == 1


# --- "Supprimer cette image" (menu contextuel) ---

def test_image_context_menu_has_remove_action(qapp):
    """Vérifie indirectement, via _paragraph_index_at, que l'occurrence cliquée est bien
    résolue — l'action réelle est câblée dans _show_image_context_menu, déjà couverte par les
    tests de remove_image_occurrence ci-dessous (pas d'exécution de QMenu en environnement
    headless)."""
    controller = ProjectController()
    chapter, asset = _make_chapter_with_image(controller)
    preview = ChapterPreview(controller)
    preview.resize(400, 300)
    preview.show_chapter(chapter.id)
    preview.show()
    qapp.processEvents()

    pos = _find_image_position(preview, qapp)
    assert pos is not None
    assert preview._paragraph_index_at(pos) == 0


def test_image_context_menu_works_on_image_only_chapter_without_visible_title(qapp):
    """Régression : un chapitre-image (add_image_as_chapter, title_visible=False) rend un
    <h1></h1> totalement vide, que Qt Rich Text supprime purement et simplement du document
    (même piège que les <p> vides, déjà contourné ailleurs avec &nbsp;, mais pas appliqué au
    h1) — le mapping bloc->paragraphe supposait à tort un rang 0 occupé par le titre, décalant
    tout le comptage et empêchant "Supprimer cette image"/"Insérer une image ici" de se
    déclencher sur ce type de chapitre."""
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", original_filename="perso.jpg",
                                                  role=AssetRole.CHAPTER_POV)
    chapter = Chapter.create(title="perso")
    chapter.title_visible = False
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id))]
    controller.project.document.chapters[chapter.id] = chapter

    preview = ChapterPreview(controller)
    preview.resize(400, 300)
    preview.show_chapter(chapter.id)
    preview.show()
    qapp.processEvents()

    pos = _find_image_position(preview, qapp)
    assert pos is not None
    assert preview._asset_id_at(pos) == asset.id
    assert preview._paragraph_index_at(pos) == 0


def test_clicking_remove_this_image_action_calls_remove_image_occurrence_with_correct_index(qapp):
    controller = ProjectController()
    chapter, asset = _make_chapter_with_image(controller)

    controller.remove_image_occurrence(chapter.id, 0)

    assert chapter.id not in controller.project.document.chapters


def test_remove_image_occurrence_only_clears_the_clicked_paragraph(qapp):
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", original_filename="perso.jpg",
                                                  role=AssetRole.CHAPTER_POV)
    chap_a = Chapter.create(title="Chapitre A")
    chap_a.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id)), Paragraph(runs=[])]
    chap_b = Chapter.create(title="Chapitre B")
    chap_b.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id)), Paragraph(runs=[])]
    controller.project.document.chapters[chap_a.id] = chap_a
    controller.project.document.chapters[chap_b.id] = chap_b

    controller.remove_image_occurrence(chap_a.id, 0)

    assert chap_a.paragraphs[0].image is None
    assert chap_b.paragraphs[0].image.asset_id == asset.id


def test_remove_image_occurrence_deletes_pure_image_chapter_left_empty(qapp):
    controller = ProjectController()
    chapter, asset = _make_chapter_with_image(controller)

    controller.remove_image_occurrence(chapter.id, 0)

    assert chapter.id not in controller.project.document.chapters


def test_remove_image_occurrence_does_not_delete_multi_paragraph_chapter(qapp):
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", original_filename="perso.jpg",
                                                  role=AssetRole.CHAPTER_POV)
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id)), Paragraph(runs=[])]
    controller.project.document.chapters[chapter.id] = chapter

    controller.remove_image_occurrence(chapter.id, 0)

    assert chapter.id in controller.project.document.chapters
    assert chapter.paragraphs[0].image is None


def test_remove_image_occurrence_noop_on_table_block(qapp):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [_make_table([1])]
    controller.project.document.chapters[chapter.id] = chapter

    controller.remove_image_occurrence(chapter.id, 0)

    assert controller.can_undo() is False


def test_remove_image_occurrence_noop_on_paragraph_without_image(qapp):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(runs=[Run(text="Texte", fmt=CharFormat())])]
    controller.project.document.chapters[chapter.id] = chapter

    controller.remove_image_occurrence(chapter.id, 0)

    assert controller.can_undo() is False


def test_remove_image_occurrence_noop_out_of_range(qapp):
    controller = ProjectController()
    chapter, asset = _make_chapter_with_image(controller)

    controller.remove_image_occurrence(chapter.id, 99)

    assert controller.can_undo() is False


# --- Curseur visible au clic gauche (readOnly QTextBrowser n'en montre pas par défaut) ---

def test_left_click_positions_visible_text_cursor(qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QMouseEvent

    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(runs=[Run(text="Un peu de texte", fmt=CharFormat())])]
    controller.project.document.chapters[chapter.id] = chapter

    preview = ChapterPreview(controller)
    preview.resize(400, 300)
    preview.show_chapter(chapter.id)
    preview.show()
    preview.setFocus()
    qapp.processEvents()

    pos = QPoint(10, 40)  # tombe dans le paragraphe de texte, sous le titre
    expected = preview.cursorForPosition(pos).position()
    event = QMouseEvent(QMouseEvent.Type.MouseButtonPress, pos, preview.mapToGlobal(pos),
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    preview.mousePressEvent(event)

    assert preview.textCursor().position() == expected
    # QTextBrowser en lecture seule ne peint jamais le curseur nativement (isReadOnly()==True) —
    # ChapterPreview le simule via un QTimer de clignotement + paintEvent() surchargé (cf.
    # __init__). Un clic doit immédiatement rendre le curseur visible (pas attendre le prochain
    # tick du timer), sinon l'utilisateur ne voit rien tant que le minuteur n'a pas basculé.
    assert preview._cursor_blink_visible is True
    assert preview.hasFocus()


# --- Position de scroll préservée quand show_chapter() est rappelé pour le MÊME chapitre ---
# Régression : setHtml() (appelé par show_chapter, y compris via refresh() après une action comme
# "Insérer une image ici") remet toujours le scroll à zéro, faisant remonter la vue tout en haut
# alors que l'utilisateur regardait un endroit précis du chapitre.

def test_show_chapter_preserves_scroll_position_for_same_chapter(qapp):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(runs=[Run(text=f"Ligne {i}", fmt=CharFormat())]) for i in range(60)]
    controller.project.document.chapters[chapter.id] = chapter

    preview = ChapterPreview(controller)
    preview.resize(300, 150)
    preview.show_chapter(chapter.id)
    preview.show()
    qapp.processEvents()

    scrollbar = preview.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum())
    scroll_value = scrollbar.value()
    assert scroll_value > 0

    preview.show_chapter(chapter.id)

    assert scrollbar.value() == scroll_value


def test_show_chapter_resets_scroll_when_switching_chapter(qapp):
    controller = ProjectController()
    chapter_a = Chapter.create(title="Chapitre A")
    chapter_a.paragraphs = [Paragraph(runs=[Run(text=f"Ligne {i}", fmt=CharFormat())]) for i in range(60)]
    chapter_b = Chapter.create(title="Chapitre B")
    chapter_b.paragraphs = [Paragraph(runs=[Run(text="Texte", fmt=CharFormat())])]
    controller.project.document.chapters[chapter_a.id] = chapter_a
    controller.project.document.chapters[chapter_b.id] = chapter_b

    preview = ChapterPreview(controller)
    preview.resize(300, 150)
    preview.show_chapter(chapter_a.id)
    preview.show()
    qapp.processEvents()

    scrollbar = preview.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum())
    assert scrollbar.value() > 0

    preview.show_chapter(chapter_b.id)

    assert scrollbar.value() == 0


# --- Copier / Couper / Coller une image (menu contextuel de la preview) ---

def test_copy_image_writes_file_to_clipboard_and_remembers_asset(qapp):
    controller = ProjectController()
    chapter, asset = _make_chapter_with_image(controller)
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    preview._copy_image(asset.id)

    from PySide6.QtGui import QGuiApplication
    mime = QGuiApplication.clipboard().mimeData()
    assert mime.hasUrls()
    assert Path(mime.urls()[0].toLocalFile()) == controller.asset_store.path_for(asset.id)
    assert preview._paste_image_source() == asset.id


def test_copy_image_does_not_remove_original_occurrence(qapp):
    controller = ProjectController()
    chapter, asset = _make_chapter_with_image(controller)
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    preview._copy_image(asset.id)

    assert chapter.id in controller.project.document.chapters
    assert controller.can_undo() is False


def test_cut_image_removes_original_occurrence_and_remembers_asset(qapp):
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", original_filename="perso.jpg",
                                                  role=AssetRole.CHAPTER_POV)
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id)), Paragraph(runs=[])]
    controller.project.document.chapters[chapter.id] = chapter
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    preview._cut_image(asset.id, 0)

    assert chapter.paragraphs[0].image is None
    assert preview._paste_image_source() == asset.id


def test_paste_image_source_is_none_with_empty_clipboard(qapp):
    controller = ProjectController()
    preview = ChapterPreview(controller)

    from PySide6.QtGui import QGuiApplication
    QGuiApplication.clipboard().clear()
    qapp.processEvents()

    assert preview._paste_image_source() is None


def test_external_clipboard_change_forgets_internal_copied_asset(qapp):
    """Régression : copier une image DANS l'appli puis copier un fichier externe (Explorateur,
    sans repasser par l'appli) doit faire que "Coller l'image ici" utilise ce nouveau fichier,
    pas l'ancien asset mémorisé — sinon on collerait la mauvaise image sans que rien ne le
    signale à l'utilisateur."""
    controller = ProjectController()
    chapter, asset = _make_chapter_with_image(controller)
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)
    preview._copy_image(asset.id)
    assert preview._paste_image_source() == asset.id

    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QGuiApplication
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("C:/ailleurs/photo.png")])
    QGuiApplication.clipboard().setMimeData(mime)
    qapp.processEvents()

    assert controller._copied_asset_id is None


def test_paste_image_source_reads_external_supported_file_from_clipboard(qapp, tmp_path):
    controller = ProjectController()
    preview = ChapterPreview(controller)

    image_path = tmp_path / "externe.png"
    image_path.write_bytes(b"\x89PNGfakepng")

    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QGuiApplication
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(image_path))])
    QGuiApplication.clipboard().setMimeData(mime)
    qapp.processEvents()

    assert preview._paste_image_source() == image_path


def test_paste_image_source_ignores_unsupported_external_file(qapp, tmp_path):
    controller = ProjectController()
    preview = ChapterPreview(controller)

    doc_path = tmp_path / "document.pdf"
    doc_path.write_bytes(b"%PDF-fake")

    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QGuiApplication
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(doc_path))])
    QGuiApplication.clipboard().setMimeData(mime)
    qapp.processEvents()

    assert preview._paste_image_source() is None


def test_paste_image_after_with_internal_asset_reuses_existing_asset(qapp):
    """Coller depuis un Copier/Couper interne ne doit jamais créer un second asset pour la même
    image — insert_existing_asset_after_paragraph réutilise l'asset_id tel quel."""
    controller = ProjectController()
    chapter, asset = _make_chapter_with_image(controller)
    chapter.paragraphs.append(Paragraph(runs=[Run(text="Fin", fmt=CharFormat())]))
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)
    preview._copy_image(asset.id)

    preview._paste_image_after(0, preview._paste_image_source())

    assert len(chapter.paragraphs) == 3
    assert chapter.paragraphs[1].image.asset_id == asset.id
    assert len(controller.asset_store.all_assets()) == 1


def test_paste_image_after_with_external_file_imports_new_asset(qapp, tmp_path):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(runs=[Run(text="Un", fmt=CharFormat())])]
    controller.project.document.chapters[chapter.id] = chapter
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)

    image_path = tmp_path / "externe.png"
    image_path.write_bytes(b"\x89PNGfakepng")

    preview._paste_image_after(0, image_path)

    assert len(chapter.paragraphs) == 2
    assert chapter.paragraphs[1].image is not None


def test_paste_image_after_is_undoable(qapp):
    controller = ProjectController()
    chapter, asset = _make_chapter_with_image(controller)
    preview = ChapterPreview(controller)
    preview.show_chapter(chapter.id)
    preview._copy_image(asset.id)

    preview._paste_image_after(0, asset.id)
    assert len(chapter.paragraphs) == 2

    controller.undo()
    assert len(controller.project.document.chapters[chapter.id].paragraphs) == 1


def test_insert_existing_asset_after_paragraph_noop_on_unknown_asset(qapp):
    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(runs=[Run(text="Un", fmt=CharFormat())])]
    controller.project.document.chapters[chapter.id] = chapter

    controller.insert_existing_asset_after_paragraph(chapter.id, 0, "asset-inconnu")

    assert len(chapter.paragraphs) == 1
    assert controller.can_undo() is False


def test_remove_image_occurrence_is_undoable(qapp):
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", original_filename="perso.jpg",
                                                  role=AssetRole.CHAPTER_POV)
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id)), Paragraph(runs=[])]
    controller.project.document.chapters[chapter.id] = chapter

    controller.remove_image_occurrence(chapter.id, 0)
    assert chapter.paragraphs[0].image is None

    controller.undo()
    assert controller.project.document.chapters[chapter.id].paragraphs[0].image.asset_id == asset.id
