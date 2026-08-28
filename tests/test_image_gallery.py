from controller import ProjectController
from model.assets import AssetRole
from model.document import Chapter, ImageAnchor, ImageDisplaySize, Paragraph, Part
from ui.image_gallery import ImageGallery, _ImageBlock, _OrphanImageBlock


def _make_controller_with_image(qapp):
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", original_filename="perso.jpg",
                                                  role=AssetRole.CHAPTER_POV)
    return controller, asset


def _make_controller_with_used_image(qapp):
    """Comme _make_controller_with_image, mais l'image est rattachée à un chapitre — pour les
    tests qui exercent le rendu/comportement normal d'un _ImageBlock (combos taille/habillage/
    description), qui n'a de sens que sur une image "utilisée" depuis l'ajout de la section
    Images orphelines (une image sans usage devient un _OrphanImageBlock simplifié)."""
    controller, asset = _make_controller_with_image(qapp)
    chapter = Chapter.create(title="Chapitre porteur")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id))]
    controller.project.document.chapters[chapter.id] = chapter
    return controller, asset


def test_image_used_in_one_chapter_shows_one_link(qapp):
    controller, asset = _make_controller_with_image(qapp)
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id))]
    controller.project.document.chapters[chapter.id] = chapter
    controller.chapters_changed.emit()
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    assert gallery.content_layout.count() == 2  # 1 bloc image + le stretch final
    block = gallery.content_layout.itemAt(0).widget()
    assert isinstance(block, _ImageBlock)


def test_clicking_chapter_link_emits_chapter_activated(qapp):
    controller, asset = _make_controller_with_image(qapp)
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id))]
    controller.project.document.chapters[chapter.id] = chapter
    controller.chapters_changed.emit()
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()

    emitted = []
    gallery.chapter_activated.connect(emitted.append)

    # Le bouton de lien est le dernier widget ajouté à droite du bloc (après vignette + labels).
    link_buttons = [w for w in block.findChildren(object) if hasattr(w, "text") and callable(w.text)
                    and w.text().startswith("→")]
    assert len(link_buttons) == 1
    link_buttons[0].click()

    assert emitted == [chapter.id]


def test_image_used_in_multiple_chapters_shows_multiple_links(qapp):
    controller, asset = _make_controller_with_image(qapp)
    chap_a = Chapter.create(title="Chapitre A")
    chap_a.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id))]
    chap_b = Chapter.create(title="Chapitre B")
    chap_b.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id))]
    controller.project.document.chapters[chap_a.id] = chap_a
    controller.project.document.chapters[chap_b.id] = chap_b
    controller.chapters_changed.emit()
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()
    link_buttons = [w for w in block.findChildren(object) if hasattr(w, "text") and callable(w.text)
                    and w.text().startswith("→")]
    assert len(link_buttons) == 2


def test_image_used_in_no_chapter_appears_as_orphan_block(qapp):
    """Une image sans aucun usage est classée orpheline (_OrphanImageBlock, pas de liens de
    chapitre à afficher) plutôt que rendue comme une _ImageBlock "utilisée dans 0 chapitre"."""
    controller, asset = _make_controller_with_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(1).widget()  # itemAt(0) = label de section
    assert isinstance(block, _OrphanImageBlock)


def test_image_block_shows_size_combo_with_full_selected_by_default(qapp):
    controller, asset = _make_controller_with_used_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()
    assert block.size_combo.currentData() == ImageDisplaySize.FULL


def test_changing_size_combo_calls_controller_set_image_display_size(qapp):
    controller, asset = _make_controller_with_used_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()

    small_index = list(block.size_combo.itemData(i) for i in range(block.size_combo.count())).index(
        ImageDisplaySize.SMALL)
    block.size_combo.setCurrentIndex(small_index)

    assert controller.project.document.image_display_sizes[asset.id] == ImageDisplaySize.SMALL


def test_controller_set_all_images_display_size_applies_to_every_asset(qapp):
    controller = ProjectController()
    asset_a = controller.asset_store.ingest_bytes(b"a", "a.jpg", AssetRole.CHAPTER_POV)
    asset_b = controller.asset_store.ingest_bytes(b"b", "b.jpg", AssetRole.CHAPTER_POV)

    controller.set_all_images_display_size(ImageDisplaySize.SMALL)

    assert controller.project.document.image_display_sizes[asset_a.id] == ImageDisplaySize.SMALL
    assert controller.project.document.image_display_sizes[asset_b.id] == ImageDisplaySize.SMALL


def test_controller_set_all_images_display_size_ignores_non_chapter_pov_assets(qapp):
    controller = ProjectController()
    chapter_asset = controller.asset_store.ingest_bytes(b"a", "a.jpg", AssetRole.CHAPTER_POV)
    cover_asset = controller.asset_store.ingest_bytes(b"b", "cover.jpg", AssetRole.COVER)

    controller.set_all_images_display_size(ImageDisplaySize.SMALL)

    assert controller.project.document.image_display_sizes[chapter_asset.id] == ImageDisplaySize.SMALL
    assert cover_asset.id not in controller.project.document.image_display_sizes


def test_controller_set_all_images_display_size_is_undoable(qapp):
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"a", "a.jpg", AssetRole.CHAPTER_POV)

    controller.set_all_images_display_size(ImageDisplaySize.SMALL)
    assert controller.project.document.image_display_sizes[asset.id] == ImageDisplaySize.SMALL

    controller.undo()
    assert asset.id not in controller.project.document.image_display_sizes


def test_controller_set_all_images_display_size_noop_when_no_images(qapp):
    controller = ProjectController()

    controller.set_all_images_display_size(ImageDisplaySize.SMALL)

    assert controller.can_undo() is False


def test_gallery_apply_all_button_calls_controller(qapp):
    from PySide6.QtCore import Qt

    controller, asset = _make_controller_with_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    index = list(gallery.global_size_combo.itemData(i) for i in range(gallery.global_size_combo.count())).index(
        ImageDisplaySize.SMALL)
    gallery.global_size_combo.setCurrentIndex(index)
    gallery.apply_all_btn.click()

    assert controller.project.document.image_display_sizes[asset.id] == ImageDisplaySize.SMALL


def test_global_size_combo_defaults_to_full(qapp):
    controller, asset = _make_controller_with_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)

    assert gallery.global_size_combo.currentData() == ImageDisplaySize.FULL


def test_image_block_shows_alt_text_field_empty_by_default(qapp):
    controller, asset = _make_controller_with_used_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()

    assert block.alt_text_edit.toPlainText() == ""


def test_editing_alt_text_field_calls_controller(qapp):
    controller, asset = _make_controller_with_used_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()

    block.alt_text_edit.setPlainText("Un gobelin brandissant une épée")
    block.alt_text_edit.editingFinished.emit()

    assert controller.project.document.image_alt_texts[asset.id] == "Un gobelin brandissant une épée"


def test_image_block_prefills_alt_text_from_document(qapp):
    controller, asset = _make_controller_with_used_image(qapp)
    controller.project.document.image_alt_texts[asset.id] = "Déjà décrite"
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()

    assert block.alt_text_edit.toPlainText() == "Déjà décrite"


def _make_controller_with_conflicting_descriptions(qapp):
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", original_filename="perso.jpg",
                                                  role=AssetRole.CHAPTER_POV)
    chapter_a = Chapter.create(title="A")
    chapter_a.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Description A"))]
    chapter_b = Chapter.create(title="B")
    chapter_b.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Description B"))]
    controller.project.document.chapters[chapter_a.id] = chapter_a
    controller.project.document.chapters[chapter_b.id] = chapter_b
    controller._backfill_image_alt_texts_from_paragraphs()
    return controller, asset


def test_no_arrows_when_single_alt_text_candidate(qapp):
    controller, asset = _make_controller_with_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()

    assert not hasattr(block, "next_alt_btn")
    assert not hasattr(block, "prev_alt_btn")
    assert not hasattr(block, "validate_alt_btn")


def test_arrows_shown_with_conflicting_descriptions(qapp):
    controller, asset = _make_controller_with_conflicting_descriptions(qapp)
    controller.chapters_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()

    assert hasattr(block, "next_alt_btn")
    assert hasattr(block, "prev_alt_btn")
    assert hasattr(block, "validate_alt_btn")
    assert block.alt_text_edit.toPlainText() == "Description A"


def test_next_arrow_cycles_to_next_candidate(qapp):
    controller, asset = _make_controller_with_conflicting_descriptions(qapp)
    controller.chapters_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()

    block.next_alt_btn.click()
    assert block.alt_text_edit.toPlainText() == "Description B"

    block.next_alt_btn.click()
    assert block.alt_text_edit.toPlainText() == "Description A"  # boucle


def test_prev_arrow_cycles_backwards(qapp):
    controller, asset = _make_controller_with_conflicting_descriptions(qapp)
    controller.chapters_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()

    block.prev_alt_btn.click()
    assert block.alt_text_edit.toPlainText() == "Description B"  # boucle en arrière


def test_field_has_green_frame_on_retained_description(qapp):
    controller, asset = _make_controller_with_conflicting_descriptions(qapp)
    controller.chapters_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()

    assert "2e7d32" in block.alt_text_edit.styleSheet()

    block.next_alt_btn.click()
    assert "2e7d32" not in block.alt_text_edit.styleSheet()


def test_validate_button_requires_confirmation(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    controller, asset = _make_controller_with_conflicting_descriptions(qapp)
    controller.chapters_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()
    block.next_alt_btn.click()

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Cancel))
    block.validate_alt_btn.click()

    assert controller.project.document.image_alt_texts[asset.id] == "Description A"  # inchangé


def test_validate_button_applies_selected_description_on_confirmation(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    controller, asset = _make_controller_with_conflicting_descriptions(qapp)
    controller.chapters_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()
    block.next_alt_btn.click()

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    block.validate_alt_btn.click()

    assert controller.project.document.image_alt_texts[asset.id] == "Description B"
    assert block.current_alt_text == "Description B"
    assert "2e7d32" in block.alt_text_edit.styleSheet()


# --- Ajout d'image (bouton + drop externe) ---

def test_add_image_button_creates_new_chapter_with_image(qapp, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    controller = ProjectController()
    gallery = ImageGallery(controller)

    image_path = tmp_path / "personnage.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(image_path), "")))

    gallery.add_image_btn.click()

    chapters = list(controller.project.document.chapters.values())
    assert len(chapters) == 1
    assert chapters[0].title == "personnage"
    assert len(chapters[0].paragraphs) == 1
    assert chapters[0].paragraphs[0].image is not None
    # Régression : le titre (nom de fichier) sert seulement à identifier le chapitre dans
    # l'arbre de Structure — il ne doit PAS s'afficher en <h1> dans la preview/l'EPUB généré.
    assert chapters[0].title_visible is False


def test_add_image_button_appends_chapter_as_free_item_at_end(qapp, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    controller = ProjectController()
    existing = Chapter.create(title="Chapitre existant")
    controller.project.document.add_chapter(existing)
    gallery = ImageGallery(controller)

    image_path = tmp_path / "personnage.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(image_path), "")))

    gallery.add_image_btn.click()

    new_chapter_id = [cid for cid in controller.project.document.chapters if cid != existing.id][0]
    assert controller.project.document.structure.items[-1] == new_chapter_id


def test_add_image_button_is_undoable(qapp, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    controller = ProjectController()
    gallery = ImageGallery(controller)

    image_path = tmp_path / "personnage.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(image_path), "")))

    gallery.add_image_btn.click()
    assert len(controller.project.document.chapters) == 1

    controller.undo()
    assert len(controller.project.document.chapters) == 0


def test_gallery_drop_event_creates_chapter(qapp, tmp_path):
    from unittest.mock import MagicMock

    from PySide6.QtCore import QUrl

    controller = ProjectController()
    gallery = ImageGallery(controller)

    image_path = tmp_path / "personnage.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")

    fake_event = MagicMock()
    fake_event.mimeData.return_value.urls.return_value = [QUrl.fromLocalFile(str(image_path))]

    gallery.dropEvent(fake_event)

    chapters = list(controller.project.document.chapters.values())
    assert len(chapters) == 1
    assert chapters[0].title == "personnage"


# --- Correctif du bug de calcul d'usage ---

def test_refresh_usage_scans_paragraphs_not_pov_image_field(qapp):
    """Régression : chapter.pov_image_asset_id seul (jamais resynchronisé, pas de vrai
    Paragraph.image) ne doit plus jamais compter comme un usage réel — l'image doit apparaître
    comme orpheline (_OrphanImageBlock), pas comme utilisée (_ImageBlock)."""
    controller, asset = _make_controller_with_image(qapp)
    chapter = Chapter.create(title="Chapitre Un")
    chapter.pov_image_asset_id = asset.id  # jamais resynchronisé, ne doit plus être consulté
    controller.project.document.chapters[chapter.id] = chapter
    controller.chapters_changed.emit()
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    # itemAt(0) est maintenant le label de section "Images orphelines" (aucune image utilisée) —
    # le bloc lui-même est juste après.
    block = gallery.content_layout.itemAt(1).widget()
    assert isinstance(block, _OrphanImageBlock)


def test_refresh_usage_deduplicates_same_image_twice_in_same_chapter(qapp):
    controller, asset = _make_controller_with_image(qapp)
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [
        Paragraph(image=ImageAnchor(asset_id=asset.id)),
        Paragraph(image=ImageAnchor(asset_id=asset.id)),
    ]
    controller.project.document.chapters[chapter.id] = chapter
    controller.chapters_changed.emit()
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()
    link_buttons = [w for w in block.findChildren(object) if hasattr(w, "text") and callable(w.text)
                    and w.text().startswith("→")]
    assert len(link_buttons) == 1


# --- Suppression d'image ---

def test_remove_image_everywhere_clears_image_on_every_paragraph_referencing_it(qapp):
    controller, asset = _make_controller_with_image(qapp)
    chap_a = Chapter.create(title="Chapitre A")
    chap_a.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id))]
    chap_b = Chapter.create(title="Chapitre B")
    chap_b.paragraphs = [Paragraph(runs=[]), Paragraph(image=ImageAnchor(asset_id=asset.id))]
    controller.project.document.chapters[chap_a.id] = chap_a
    controller.project.document.chapters[chap_b.id] = chap_b

    controller.remove_image_everywhere(asset.id)

    assert chap_b.paragraphs[1].image is None


def test_remove_image_everywhere_deletes_pure_image_chapter_left_empty(qapp):
    controller, asset = _make_controller_with_image(qapp)
    chapter = Chapter.create(title="Chapitre Image")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id))]
    controller.project.document.add_chapter(chapter)

    controller.remove_image_everywhere(asset.id)

    assert chapter.id not in controller.project.document.chapters


def test_remove_image_everywhere_does_not_delete_multi_paragraph_chapter(qapp):
    controller, asset = _make_controller_with_image(qapp)
    chapter = Chapter.create(title="Chapitre Mixte")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id)), Paragraph(runs=[])]
    controller.project.document.add_chapter(chapter)

    controller.remove_image_everywhere(asset.id)

    assert chapter.id in controller.project.document.chapters
    assert chapter.paragraphs[0].image is None


def test_remove_image_everywhere_clears_pov_image_asset_id(qapp):
    controller, asset = _make_controller_with_image(qapp)
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id)), Paragraph(runs=[])]
    chapter.pov_image_asset_id = asset.id
    controller.project.document.add_chapter(chapter)

    controller.remove_image_everywhere(asset.id)

    assert chapter.pov_image_asset_id is None


def test_remove_image_everywhere_keeps_asset_on_disk_when_no_longer_referenced(qapp):
    """L'asset n'est JAMAIS supprimé physiquement (limitation assumée : la pile undo ne clone
    pas asset_store — une suppression physique immédiate casserait Ctrl+Z, cf.
    controller._drop_asset_if_orphaned). Un asset non référencé reste sur le disque du projet
    mais n'est de toute façon jamais inclus dans un EPUB généré."""
    controller, asset = _make_controller_with_image(qapp)
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id)), Paragraph(runs=[])]
    controller.project.document.add_chapter(chapter)

    controller.remove_image_everywhere(asset.id)

    assert controller.asset_store.get(asset.id) is not None


def test_remove_image_everywhere_keeps_asset_physically_when_used_as_cover(qapp):
    controller, asset = _make_controller_with_image(qapp)
    controller.project.document.cover_asset_id = asset.id
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id)), Paragraph(runs=[])]
    controller.project.document.add_chapter(chapter)

    controller.remove_image_everywhere(asset.id)

    assert controller.asset_store.get(asset.id) is not None


def test_remove_image_everywhere_is_undoable(qapp):
    controller, asset = _make_controller_with_image(qapp)
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id)), Paragraph(runs=[])]
    controller.project.document.add_chapter(chapter)

    controller.remove_image_everywhere(asset.id)
    assert chapter.paragraphs[0].image is None

    controller.undo()
    assert controller.project.document.chapters[chapter.id].paragraphs[0].image.asset_id == asset.id


def test_gallery_remove_button_requires_confirmation(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    controller, asset = _make_controller_with_image(qapp)
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id))]
    controller.project.document.add_chapter(chapter)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Cancel))
    block.remove_btn.click()

    assert asset.id in [a.id for a in controller.asset_store.all_assets()]


def test_gallery_remove_button_calls_controller_on_confirmation(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    controller, asset = _make_controller_with_image(qapp)
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id)), Paragraph(runs=[])]
    controller.project.document.add_chapter(chapter)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    block.remove_btn.click()

    assert chapter.paragraphs[0].image is None


# --- Section "Images orphelines" ---

def test_gallery_shows_orphans_section_label_when_orphan_exists(qapp):
    controller, asset = _make_controller_with_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)

    assert gallery.content_layout.itemAt(0).widget().text().startswith("Images orphelines")


def test_gallery_hides_orphans_section_when_no_orphan(qapp):
    controller, asset = _make_controller_with_used_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)

    for i in range(gallery.content_layout.count() - 1):  # -1 : le stretch final
        widget = gallery.content_layout.itemAt(i).widget()
        assert not (hasattr(widget, "text") and callable(widget.text) and "orphelines" in widget.text())


def test_gallery_orphan_block_has_no_size_or_wrap_combos(qapp):
    controller, asset = _make_controller_with_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(1).widget()

    assert not hasattr(block, "size_combo")
    assert not hasattr(block, "wrap_combo")
    assert not hasattr(block, "alt_text_edit")


def test_orphan_block_shows_unused_mention_in_red_bold(qapp):
    controller, asset = _make_controller_with_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(1).widget()

    labels = [w for w in block.findChildren(object) if hasattr(w, "text") and callable(w.text)
              and w.text() == "Utilisée dans aucun chapitre"]
    assert len(labels) == 1
    assert "c0392b" in labels[0].styleSheet()
    assert "bold" in labels[0].styleSheet()


def test_orphan_block_delete_button_requires_confirmation(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    controller, asset = _make_controller_with_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(1).widget()

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Cancel))
    block.delete_btn.click()

    assert controller.asset_store.get(asset.id) is not None


def test_orphan_block_delete_button_calls_controller_on_confirmation(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    controller, asset = _make_controller_with_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(1).widget()

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    block.delete_btn.click()

    assert controller.asset_store.get(asset.id) is None


# --- controller.delete_orphaned_asset ---

def test_delete_orphaned_asset_removes_file_physically(qapp):
    controller, asset = _make_controller_with_image(qapp)

    controller.delete_orphaned_asset(asset.id)

    assert controller.asset_store.get(asset.id) is None


def test_delete_orphaned_asset_is_not_undoable(qapp):
    """Suppression physique délibérément non annulable (pas de _snapshot_structure) — cf.
    controller.delete_orphaned_asset."""
    controller, asset = _make_controller_with_image(qapp)

    controller.delete_orphaned_asset(asset.id)

    assert controller.can_undo() is False


def test_delete_orphaned_asset_refuses_to_delete_a_used_image(qapp):
    """Garde-fou : ne supprime jamais une image encore référencée, même si l'appelant se trompe."""
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", "perso.jpg", AssetRole.CHAPTER_POV)
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id))]
    controller.project.document.chapters[chapter.id] = chapter

    controller.delete_orphaned_asset(asset.id)

    assert controller.asset_store.get(asset.id) is not None


def test_delete_orphaned_asset_unknown_id_is_noop(qapp):
    controller = ProjectController()

    controller.delete_orphaned_asset("does-not-exist")  # ne lève pas


# --- Renommage d'image ---

def test_rename_button_shows_inline_editable_field(qapp):
    controller, asset = _make_controller_with_used_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()
    rename_widget = block.rename_widget

    assert rename_widget._stack.currentIndex() == 0
    rename_widget.rename_btn.click()

    assert rename_widget._stack.currentIndex() == 1
    assert rename_widget.name_edit.text() == "perso"


def test_renaming_image_calls_controller_rename_image(qapp):
    controller, asset = _make_controller_with_used_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()
    rename_widget = block.rename_widget

    rename_widget.rename_btn.click()
    rename_widget.name_edit.setText("Nouveau Nom")
    rename_widget.name_edit.editingFinished.emit()
    qapp.processEvents()  # renamed est émis via QTimer.singleShot(0, ...), cf. _RenameWidget._commit

    assert controller.asset_store.get(asset.id).original_filename == "Nouveau Nom.jpg"


def test_renaming_image_strips_invalid_filename_characters(qapp):
    controller, asset = _make_controller_with_used_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()
    rename_widget = block.rename_widget

    rename_widget.rename_btn.click()
    rename_widget.name_edit.setText('a/b\\c:d*e?f"g<h>i|j')
    rename_widget._strip_invalid_chars(rename_widget.name_edit.text())

    assert rename_widget.name_edit.text() == "abcdefghij"


def test_renaming_to_empty_name_keeps_previous_name(qapp):
    controller, asset = _make_controller_with_used_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()
    rename_widget = block.rename_widget

    rename_widget.rename_btn.click()
    rename_widget.name_edit.setText("   ")
    rename_widget.name_edit.editingFinished.emit()

    assert controller.asset_store.get(asset.id).original_filename == "perso.jpg"


def test_extension_is_never_editable(qapp):
    controller, asset = _make_controller_with_used_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()
    rename_widget = block.rename_widget

    rename_widget.rename_btn.click()

    assert ".jpg" not in rename_widget.name_edit.text()


def test_orphan_block_rename_button_calls_controller(qapp):
    controller, asset = _make_controller_with_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(1).widget()
    rename_widget = block.rename_widget

    rename_widget.rename_btn.click()
    rename_widget.name_edit.setText("Nouveau Nom")
    rename_widget.name_edit.editingFinished.emit()
    qapp.processEvents()  # renamed est émis via QTimer.singleShot(0, ...), cf. _RenameWidget._commit

    assert controller.asset_store.get(asset.id).original_filename == "Nouveau Nom.jpg"


# --- Bouton "Copier l'image" (image utilisée et image orpheline) ---

def test_used_image_block_copy_button_writes_to_clipboard(qapp):
    controller, asset = _make_controller_with_used_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()
    assert isinstance(block, _ImageBlock)

    block.copy_btn.click()

    assert controller.paste_image_source() == asset.id


def test_orphan_image_block_copy_button_writes_to_clipboard(qapp):
    controller, asset = _make_controller_with_image(qapp)
    controller.assets_changed.emit()

    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(1).widget()
    assert isinstance(block, _OrphanImageBlock)

    block.copy_btn.click()

    assert controller.paste_image_source() == asset.id


def test_copy_from_gallery_can_be_pasted_in_chapter_preview(qapp):
    """Régression : Copier/Coller partage UN SEUL système entre l'onglet Images et l'aperçu
    Structure (cf. ProjectController.copy_image_to_clipboard/paste_image_source) — copier une
    image depuis la galerie doit pouvoir être ensuite collée dans l'aperçu d'un chapitre, sans
    passer par un état séparé propre à chaque écran."""
    from model.document import Chapter, Run
    from model.styles import CharFormat
    from ui.chapter_preview import ChapterPreview

    controller, asset = _make_controller_with_used_image(qapp)
    controller.assets_changed.emit()
    gallery = ImageGallery(controller)
    block = gallery.content_layout.itemAt(0).widget()

    block.copy_btn.click()

    target_chapter = Chapter.create(title="Autre chapitre")
    target_chapter.paragraphs = [Paragraph(runs=[Run(text="Texte", fmt=CharFormat())])]
    controller.project.document.chapters[target_chapter.id] = target_chapter
    preview = ChapterPreview(controller)
    preview.show_chapter(target_chapter.id)

    source = preview._paste_image_source()
    assert source == asset.id
    preview._paste_image_after(0, source)

    assert target_chapter.paragraphs[1].image.asset_id == asset.id
