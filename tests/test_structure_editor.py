from pathlib import Path

from PySide6.QtCore import Qt

from controller import ProjectController
from model.document import Chapter, Part
from model.project import SourceOdtFile
from ui.structure_editor import StructureEditor


def _make_editor(qapp) -> tuple[ProjectController, StructureEditor]:
    controller = ProjectController()
    editor = StructureEditor(controller)
    return controller, editor


def test_chapters_in_part_are_displayed_in_storage_order_not_by_title_number(qapp):
    """Le tri par numéro de titre a été supprimé : l'affichage doit refléter fidèlement
    l'ordre brut stocké dans part.chapter_ids, même si les titres contiennent des numéros
    qui suggéreraient un ordre différent."""
    controller, editor = _make_editor(qapp)
    doc = controller.project.document

    for i in range(7, 0, -1):
        chapter = Chapter.create(title=f"Chapitre {i}", source_order_index=i)
        doc.chapters[chapter.id] = chapter  # pas add_chapter() : structure posée explicitement ensuite
    controller.chapters_changed.emit()

    part = Part.create(title="Partie 2")
    stored_order = list(doc.chapters.keys())  # ordre d'insertion : Chapitre 7 .. Chapitre 1
    part.chapter_ids = stored_order
    doc.structure.items.append(part)
    controller.structure_changed.emit()

    part_item = editor.tree.topLevelItem(0)
    displayed_titles = [part_item.child(j).text(0) for j in range(part_item.childCount())]
    assert displayed_titles == [f"Chapitre {i}" for i in range(7, 0, -1)]


def test_default_order_is_by_filename_then_position_ignoring_title_numbers(qapp):
    """Ordre par défaut avec 2 fichiers ODT dont les numéros de chapitres se chevauchent :
    doit respecter (nom de fichier, position dans le fichier), jamais le numéro extrait
    du titre — sinon des chapitres de fichiers différents se retrouvent entrelacés."""
    controller, editor = _make_editor(qapp)
    doc = controller.project.document

    file_a = SourceOdtFile.create(Path("a_premier.odt"), controller.project.next_import_order())
    controller.project.source_odt_files.append(file_a)
    file_b = SourceOdtFile.create(Path("b_second.odt"), controller.project.next_import_order())
    controller.project.source_odt_files.append(file_b)

    chap_b2 = Chapter.create(title="Chapitre 1", source_odt_id=file_b.id, source_order_index=1)
    chap_b1 = Chapter.create(title="Chapitre 9", source_odt_id=file_b.id, source_order_index=0)
    chap_a2 = Chapter.create(title="Chapitre 2", source_odt_id=file_a.id, source_order_index=1)
    chap_a1 = Chapter.create(title="Chapitre 5", source_odt_id=file_a.id, source_order_index=0)
    for c in (chap_b2, chap_b1, chap_a2, chap_a1):
        doc.chapters[c.id] = c  # pas add_chapter() : structure posée explicitement ensuite
    controller.chapters_changed.emit()

    part = Part.create(title="Partie unique")
    part.chapter_ids = sorted(
        [chap_b2.id, chap_b1.id, chap_a2.id, chap_a1.id],
        key=editor._file_and_position_sort_key,
    )
    doc.structure.items.append(part)
    controller.structure_changed.emit()

    part_item = editor.tree.topLevelItem(0)
    displayed_titles = [part_item.child(j).text(0) for j in range(part_item.childCount())]
    assert displayed_titles == ["Chapitre 5", "Chapitre 2", "Chapitre 9", "Chapitre 1"]


def test_manual_reorder_survives_unrelated_refresh(qapp):
    """Un réordonnancement manuel (drag & drop, simulé ici via apply_reordered_structure)
    doit survivre à un refresh() déclenché par une action sans rapport."""
    controller, editor = _make_editor(qapp)
    doc = controller.project.document

    chapters = [Chapter.create(title=f"Chapitre {i}") for i in (1, 2, 3)]
    for c in chapters:
        doc.chapters[c.id] = c  # pas add_chapter() : structure posée explicitement ensuite
    controller.chapters_changed.emit()

    part = Part.create(title="Partie 1")
    part.chapter_ids = [c.id for c in chapters]
    other_part = Part.create(title="Autre partie")
    doc.structure.items.extend([part, other_part])
    controller.structure_changed.emit()

    manually_reordered_ids = [chapters[2].id, chapters[0].id, chapters[1].id]
    reordered_part = Part(id=part.id, title=part.title, chapter_ids=manually_reordered_ids,
                           has_title_page=part.has_title_page)
    controller.apply_reordered_structure([reordered_part, other_part])

    controller.rename_part(other_part.id, "Autre partie renommée")

    part_item = editor.tree.topLevelItem(0)
    displayed_titles = [part_item.child(j).text(0) for j in range(part_item.childCount())]
    assert displayed_titles == ["Chapitre 3", "Chapitre 1", "Chapitre 2"]


def test_default_order_uses_filename_not_import_click_order(qapp):
    """L'ordre alphanumérique des NOMS de fichiers prime, pas import_order (ordre de clic)."""
    controller, editor = _make_editor(qapp)
    doc = controller.project.document

    file_b = SourceOdtFile.create(Path("b_deuxieme.odt"), controller.project.next_import_order())
    controller.project.source_odt_files.append(file_b)
    file_a = SourceOdtFile.create(Path("a_premier.odt"), controller.project.next_import_order())
    controller.project.source_odt_files.append(file_a)
    assert file_b.import_order < file_a.import_order  # précondition : clic dans l'ordre inverse de l'alphabet

    chap_b = Chapter.create(title="Un chapitre", source_odt_id=file_b.id, source_order_index=0)
    chap_a = Chapter.create(title="Un autre chapitre", source_odt_id=file_a.id, source_order_index=0)
    doc.chapters[chap_b.id] = chap_b  # pas add_chapter() : structure posée explicitement ensuite
    doc.chapters[chap_a.id] = chap_a
    controller.chapters_changed.emit()

    part = Part.create(title="Partie unique")
    part.chapter_ids = sorted([chap_b.id, chap_a.id], key=editor._file_and_position_sort_key)
    doc.structure.items.append(part)
    controller.structure_changed.emit()

    part_item = editor.tree.topLevelItem(0)
    displayed_titles = [part_item.child(j).text(0) for j in range(part_item.childCount())]
    assert displayed_titles == ["Un autre chapitre", "Un chapitre"]


def test_assign_selected_to_part_orders_by_file_and_position_not_selection_order(qapp):
    """_assign_selected_to_part doit trier par (fichier, position) avant de persister,
    pas selon l'ordre de sélection Qt (qui peut être arbitraire pour un Ctrl+clic)."""
    controller, editor = _make_editor(qapp)
    controller.import_odt(str(Path(__file__).parent / "fixtures" / "sample_simple.odt"))

    chapter_ids = list(controller.project.document.chapters.keys())
    assert len(chapter_ids) >= 2

    # Sélection délibérément inversée par rapport à la position réelle dans le fichier —
    # simule un Ctrl+clic dans un ordre arbitraire, sans dépendre du rendu Qt réel de l'arbre.
    reversed_selection = list(reversed(chapter_ids))
    editor._selected_chapter_ids = lambda: reversed_selection

    doc = controller.project.document
    part = Part.create(title="Partie unique")
    doc.structure.items.append(part)
    controller.structure_changed.emit()

    from PySide6.QtWidgets import QInputDialog
    original_get_item = QInputDialog.getItem
    QInputDialog.getItem = staticmethod(lambda *a, **k: (part.title, True))
    try:
        editor._assign_selected_to_part()
    finally:
        QInputDialog.getItem = original_get_item

    expected_order = sorted(chapter_ids, key=editor._file_and_position_sort_key)
    assert controller.project.document.structure.parts()[0].chapter_ids == expected_order


def test_checkbox_label_reflects_title_page_state(qapp):
    controller, editor = _make_editor(qapp)
    controller.create_part("Prologues")
    part_id = controller.project.document.structure.parts()[0].id

    part_item = editor.tree.topLevelItem(0)
    assert part_item.text(0) == "Prologues"
    assert part_item.checkState(0) == Qt.CheckState.Unchecked

    controller.set_part_title_page(part_id, True)
    part_item = editor.tree.topLevelItem(0)  # refresh() a reconstruit l'arbre
    assert "page de garde activée" in part_item.text(0)
    assert part_item.checkState(0) == Qt.CheckState.Checked


def test_reorder_via_apply_reordered_structure_preserves_has_title_page(qapp):
    """Régression : reconstruire une Part lors d'un drag & drop sans transmettre has_title_page
    réinitialisait silencieusement la page de garde à False."""
    controller, editor = _make_editor(qapp)
    controller.import_odt(str(__import__("pathlib").Path(__file__).parent / "fixtures" / "sample_simple.odt"))
    controller.create_part("Prologues")
    part_id = controller.project.document.structure.parts()[0].id
    controller.set_part_title_page(part_id, True)

    chapter_ids = list(controller.project.document.chapters.keys())
    controller.assign_chapters_to_part(chapter_ids, part_id)
    assert controller.project.document.structure.parts()[0].has_title_page is True

    reordered_part = Part(id=part_id, title="Prologues", chapter_ids=list(reversed(chapter_ids)),
                           has_title_page=True)
    controller.apply_reordered_structure([reordered_part])

    assert controller.project.document.structure.parts()[0].has_title_page is True


def test_free_chapter_appears_as_top_level_item_among_parts(qapp):
    controller, editor = _make_editor(qapp)
    doc = controller.project.document

    chap1 = Chapter.create(title="Chapitre Un")
    chap2 = Chapter.create(title="Chapitre Deux")
    doc.chapters[chap1.id] = chap1
    doc.chapters[chap2.id] = chap2
    controller.chapters_changed.emit()

    part = Part.create(title="Partie I")
    part.chapter_ids = [chap2.id]
    doc.structure.items = [chap1.id, part]
    controller.structure_changed.emit()

    assert editor.tree.topLevelItemCount() == 2
    from ui.structure_editor import CHAPTER_ROLE, PART_ROLE
    item0 = editor.tree.topLevelItem(0)
    assert item0.data(0, PART_ROLE) is None
    assert item0.data(0, CHAPTER_ROLE) == chap1.id
    item1 = editor.tree.topLevelItem(1)
    assert item1.data(0, PART_ROLE) == part.id


def test_two_rapid_drops_before_timer_fires_apply_in_call_order(qapp):
    """_on_rows_moved lit l'arbre Qt de façon synchrone mais diffère l'application du résultat
    via QTimer.singleShot(0, ...) (nécessaire : Qt n'a pas fini de stabiliser son état interne
    juste après un drop). Risque théorique identifié en audit : si un second drop se produisait
    avant que le timer du premier ne se déclenche, le second appliquerait un new_items calculé
    sur un arbre plus ancien, écrasant potentiellement le résultat du premier de façon non
    intuitive. Ce test simule ce scénario directement (deux appels à _on_rows_moved avant de
    laisser tourner l'event loop) pour vérifier le comportement réel plutôt que de le supposer."""
    controller, editor = _make_editor(qapp)
    doc = controller.project.document

    chap_a = Chapter.create(title="A")
    chap_b = Chapter.create(title="B")
    doc.chapters[chap_a.id] = chap_a
    doc.chapters[chap_b.id] = chap_b
    controller.chapters_changed.emit()
    controller.apply_reordered_structure([chap_a.id, chap_b.id])

    from ui.structure_editor import CHAPTER_ROLE

    # Premier "drop" : A et B sont déjà dans cet ordre dans l'arbre affiché, on simule le
    # déclenchement de _on_rows_moved tel quel (équivalent à un drop qui ne change rien).
    editor._on_rows_moved()

    # Deuxième "drop" immédiat, avant que le timer du premier ne se soit exécuté : on modifie
    # directement l'ordre des items top-level de l'arbre Qt pour simuler un second geste,
    # puis on redéclenche _on_rows_moved sur ce nouvel état.
    editor.tree.insertTopLevelItem(0, editor.tree.takeTopLevelItem(1))
    assert editor.tree.topLevelItem(0).data(0, CHAPTER_ROLE) == chap_b.id
    editor._on_rows_moved()

    qapp.processEvents()  # laisse les deux QTimer.singleShot(0, ...) s'exécuter dans l'ordre

    # Le second appel (le plus récent geste utilisateur) doit l'emporter : B avant A.
    assert doc.structure.items == [chap_b.id, chap_a.id]


def test_drag_drop_of_free_chapter_persists_new_position(qapp):
    controller, editor = _make_editor(qapp)
    doc = controller.project.document

    chap1 = Chapter.create(title="Chapitre Un")
    free_chap = Chapter.create(title="Chapitre Libre")
    doc.chapters[chap1.id] = chap1
    doc.chapters[free_chap.id] = free_chap
    controller.chapters_changed.emit()

    part = Part.create(title="Partie I")
    part.chapter_ids = [chap1.id]
    # Départ : chapitre libre AVANT la partie.
    controller.apply_reordered_structure([free_chap.id, part])

    from ui.structure_editor import CHAPTER_ROLE, PART_ROLE
    assert editor.tree.topLevelItem(0).data(0, CHAPTER_ROLE) == free_chap.id
    assert editor.tree.topLevelItem(1).data(0, PART_ROLE) == part.id

    # Réordonnancement manuel : le chapitre libre passe APRÈS la partie.
    controller.apply_reordered_structure([part, free_chap.id])

    assert editor.tree.topLevelItem(0).data(0, PART_ROLE) == part.id
    assert editor.tree.topLevelItem(1).data(0, CHAPTER_ROLE) == free_chap.id


def test_unassign_chapter_removes_it_from_part_and_makes_it_free(qapp):
    controller, editor = _make_editor(qapp)
    controller.import_odt(str(Path(__file__).parent / "fixtures" / "sample_simple.odt"))
    chapter_ids = list(controller.project.document.chapters.keys())

    controller.create_part("Partie I")
    part_id = controller.project.document.structure.parts()[0].id
    controller.assign_chapters_to_part(chapter_ids, part_id)

    target_chapter_id = chapter_ids[0]
    controller.unassign_chapters([target_chapter_id])

    doc = controller.project.document
    assert target_chapter_id in doc.structure.free_chapter_ids()
    part = doc.structure.parts()[0]
    assert target_chapter_id not in part.chapter_ids

    part_index = doc.structure.items.index(part)
    assert doc.structure.items[part_index + 1] == target_chapter_id


def _menu_action_texts(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def test_context_menu_on_chapter_offers_chapter_actions(qapp):
    controller, editor = _make_editor(qapp)
    controller.import_odt(str(Path(__file__).parent / "fixtures" / "sample_simple.odt"))
    controller.create_part("Partie I")
    part_id = controller.project.document.structure.parts()[0].id
    chapter_ids = list(controller.project.document.chapters.keys())
    controller.assign_chapters_to_part(chapter_ids, part_id)

    part_item = editor.tree.topLevelItem(0)
    chapter_item = part_item.child(0)

    menu = editor._build_context_menu(chapter_item)
    assert _menu_action_texts(menu) == [
        "Renommer", "Assigner à une partie", "Retirer de la partie",
        "Fusionner avec le chapitre suivant", "Scinder le chapitre", "Supprimer",
    ]


def test_context_menu_on_part_offers_part_actions(qapp):
    controller, editor = _make_editor(qapp)
    controller.create_part("Partie I")
    part_item = editor.tree.topLevelItem(0)

    menu = editor._build_context_menu(part_item)
    assert _menu_action_texts(menu) == ["Renommer", "Nouvelle partie", "Supprimer"]


def test_context_menu_on_empty_area_offers_only_new_part(qapp):
    controller, editor = _make_editor(qapp)
    menu = editor._build_context_menu(None)
    assert _menu_action_texts(menu) == ["Nouvelle partie"]


def test_right_click_on_unselected_chapter_selects_it_first(qapp):
    controller, editor = _make_editor(qapp)
    controller.import_odt(str(Path(__file__).parent / "fixtures" / "sample_simple.odt"))
    controller.create_part("Partie I")
    part_id = controller.project.document.structure.parts()[0].id
    chapter_ids = list(controller.project.document.chapters.keys())
    controller.assign_chapters_to_part(chapter_ids, part_id)

    part_item = editor.tree.topLevelItem(0)
    chapter_item = part_item.child(0)
    editor.tree.clearSelection()
    assert editor.tree.currentItem() is not chapter_item

    # menu.exec() ouvrirait une vraie boucle modale bloquante sans clic utilisateur réel —
    # on la neutralise sur l'instance de menu construite (pas sur la classe QMenu : un
    # monkeypatch de classe ne s'applique pas aux méthodes C++ liées de Shiboken/PySide6).
    original_build = editor._build_context_menu

    def build_with_noop_exec(item):
        menu = original_build(item)
        menu.exec = lambda *a, **k: None
        return menu

    editor._build_context_menu = build_with_noop_exec

    pos = editor.tree.visualItemRect(chapter_item).center()
    editor._show_context_menu(pos)

    assert editor.tree.currentItem() is chapter_item


def test_selecting_part_without_title_page_shows_explanatory_message(qapp):
    """Une partie sans page de garde n'insère rien dans le livre à cet endroit — afficher un
    panneau vide serait ambigu (croyable pour un bug/une page blanche), donc un message
    explicatif remplace le titre plutôt qu'une zone vide."""
    from ui.part_title_page_preview import NO_TITLE_PAGE_MESSAGE

    controller, editor = _make_editor(qapp)
    controller.create_part("Partie sans page de garde")
    part_item = editor.tree.topLevelItem(0)

    editor.tree.setCurrentItem(part_item)

    assert editor.preview_stack.currentWidget() is editor.part_title_page_preview
    assert editor.part_title_page_preview.title_label.text() == NO_TITLE_PAGE_MESSAGE


def test_selecting_part_with_title_page_shows_title_page_preview(qapp):
    controller, editor = _make_editor(qapp)
    controller.create_part("Partie avec page de garde")
    part_id = controller.project.document.structure.parts()[0].id
    controller.set_part_title_page(part_id, True)

    part_item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(part_item)

    assert editor.preview_stack.currentWidget() is editor.part_title_page_preview
    assert editor.part_title_page_preview.title_label.text() == "Partie avec page de garde"


def test_checking_title_page_box_refreshes_preview_immediately(qapp):
    """Cocher la case pendant que la partie est sélectionnée doit immédiatement faire
    apparaître le titre dans l'aperçu, sans action supplémentaire de l'utilisateur."""
    from ui.part_title_page_preview import NO_TITLE_PAGE_MESSAGE

    controller, editor = _make_editor(qapp)
    controller.create_part("Ma Partie")
    part_id = controller.project.document.structure.parts()[0].id
    part_item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(part_item)
    assert editor.part_title_page_preview.title_label.text() == NO_TITLE_PAGE_MESSAGE

    controller.set_part_title_page(part_id, True)

    assert editor.part_title_page_preview.title_label.text() == "Ma Partie"


def test_unchecking_title_page_box_refreshes_preview_immediately(qapp):
    from ui.part_title_page_preview import NO_TITLE_PAGE_MESSAGE

    controller, editor = _make_editor(qapp)
    controller.create_part("Ma Partie")
    part_id = controller.project.document.structure.parts()[0].id
    controller.set_part_title_page(part_id, True)
    part_item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(part_item)
    assert editor.part_title_page_preview.title_label.text() == "Ma Partie"

    controller.set_part_title_page(part_id, False)

    assert editor.part_title_page_preview.title_label.text() == NO_TITLE_PAGE_MESSAGE


def test_selection_survives_refresh_after_split_chapter(qapp):
    """Scinder un chapitre déclenche structure_changed -> refresh() : le chapitre resélectionné
    doit être le premier morceau (même id que le chapitre d'origine), pas une sélection vide."""
    from model.document import Paragraph, Run
    from model.styles import CharFormat

    controller, editor = _make_editor(qapp)
    chapter = Chapter.create(title="À scinder")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="a", fmt=CharFormat())]),
        Paragraph(runs=[Run(text="b", fmt=CharFormat())]),
    ]
    controller.project.document.add_chapter(chapter)
    controller.chapters_changed.emit()
    controller.structure_changed.emit()

    free_item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(free_item)
    assert editor._selected_chapter_id() == chapter.id

    controller.split_chapter(chapter.id, 1)

    assert editor._selected_chapter_id() == chapter.id
    # editor.preview vit dans un conteneur intermédiaire (barre d'outils de formatage +
    # panneau), pas directement enfant de preview_stack — on vérifie que la page affichée
    # est bien celle qui contient editor.preview, indépendamment de ce détail de structure.
    assert editor.preview_stack.currentWidget().isAncestorOf(editor.preview)


def test_selection_cleared_after_deleting_selected_chapter(qapp):
    """Supprimer le chapitre actuellement sélectionné ne doit jamais laisser l'aperçu affiché
    sur un contenu qui n'existe plus."""
    controller, editor = _make_editor(qapp)
    chapter = Chapter.create(title="À supprimer")
    controller.project.document.add_chapter(chapter)
    controller.chapters_changed.emit()
    controller.structure_changed.emit()

    free_item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(free_item)
    assert editor._selected_chapter_id() == chapter.id

    controller.delete_chapter(chapter.id)

    assert editor._selected_chapter_id() is None
    assert editor.tree.topLevelItemCount() == 0


# --- Drop externe (fichier image depuis Windows) sur l'arbre ---

def test_tree_drag_enter_event_accepts_urls(qapp, tmp_path):
    from unittest.mock import MagicMock

    controller, editor = _make_editor(qapp)

    fake_event = MagicMock()
    fake_event.mimeData.return_value.hasUrls.return_value = True

    editor.tree.dragEnterEvent(fake_event)

    fake_event.acceptProposedAction.assert_called_once()


def test_tree_drop_event_with_urls_creates_chapter_instead_of_reordering(qapp, tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from PySide6.QtCore import QUrl

    controller, editor = _make_editor(qapp)

    reorder_calls = []
    monkeypatch.setattr(controller, "apply_reordered_structure", lambda items: reorder_calls.append(items))

    image_path = tmp_path / "illustration.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")

    fake_event = MagicMock()
    fake_event.mimeData.return_value.hasUrls.return_value = True
    fake_event.mimeData.return_value.urls.return_value = [QUrl.fromLocalFile(str(image_path))]

    editor.tree.dropEvent(fake_event)

    chapters = list(controller.project.document.chapters.values())
    assert len(chapters) == 1
    assert chapters[0].title == "illustration"
    assert reorder_calls == []  # le chemin de réordonnancement interne n'est pas déclenché


def test_dropping_multiple_files_on_tree_processes_all_not_just_the_first(qapp, tmp_path, monkeypatch):
    """Régression : dropEvent s'arrêtait au premier fichier (break après un seul appel à
    on_external_file_dropped), donc glisser plusieurs fichiers d'un coup sur l'arbre de
    Structure n'en traitait qu'un seul."""
    from unittest.mock import MagicMock

    from PySide6.QtCore import QUrl

    controller, editor = _make_editor(qapp)

    image_paths = [tmp_path / f"illustration{i}.jpg" for i in range(3)]
    for p in image_paths:
        p.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")

    fake_event = MagicMock()
    fake_event.mimeData.return_value.hasUrls.return_value = True
    fake_event.mimeData.return_value.urls.return_value = [QUrl.fromLocalFile(str(p)) for p in image_paths]

    editor.tree.dropEvent(fake_event)

    chapters = list(controller.project.document.chapters.values())
    assert len(chapters) == 3
    assert {c.title for c in chapters} == {"illustration0", "illustration1", "illustration2"}


def test_dropping_odt_on_tree_routes_to_import_not_image(qapp, tmp_path, monkeypatch):
    """Régression : un .odt déposé sur l'arbre de Structure tombait dans le même chemin qu'une
    image (add_image_as_chapter), qui refuse désormais tout format hors PNG/JPEG — un .odt y
    déclenchait donc une alerte absurde au lieu d'être importé. Doit router vers le même import
    que l'onglet Import (dispatch_odt_import)."""
    from unittest.mock import MagicMock

    from PySide6.QtCore import QUrl

    controller, editor = _make_editor(qapp)

    calls: list[Path] = []
    monkeypatch.setattr(controller, "import_odt", lambda p: calls.append(p))

    odt_path = tmp_path / "livre.odt"
    odt_path.write_bytes(b"fake-odt")

    fake_event = MagicMock()
    fake_event.mimeData.return_value.hasUrls.return_value = True
    fake_event.mimeData.return_value.urls.return_value = [QUrl.fromLocalFile(str(odt_path))]

    editor.tree.dropEvent(fake_event)

    assert calls == [odt_path]
    assert controller.project.document.chapters == {}


def test_dropping_epub_on_tree_routes_to_import_epub_file(qapp, tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from PySide6.QtCore import QUrl

    controller, editor = _make_editor(qapp)

    calls: list[Path] = []
    monkeypatch.setattr(controller, "import_epub_file", lambda p: calls.append(p))

    epub_path = tmp_path / "livre.epub"
    epub_path.write_bytes(b"fake-epub")

    fake_event = MagicMock()
    fake_event.mimeData.return_value.hasUrls.return_value = True
    fake_event.mimeData.return_value.urls.return_value = [QUrl.fromLocalFile(str(epub_path))]

    editor.tree.dropEvent(fake_event)

    assert calls == [epub_path]


def test_dropping_epbz_on_tree_emits_project_dropped(qapp, tmp_path):
    from unittest.mock import MagicMock

    from PySide6.QtCore import QUrl

    controller, editor = _make_editor(qapp)

    received: list[Path] = []
    editor.project_dropped.connect(received.append)

    epbz_path = tmp_path / "projet.epbz"
    epbz_path.write_bytes(b"fake-epbz")

    fake_event = MagicMock()
    fake_event.mimeData.return_value.hasUrls.return_value = True
    fake_event.mimeData.return_value.urls.return_value = [QUrl.fromLocalFile(str(epbz_path))]

    editor.tree.dropEvent(fake_event)

    assert received == [epbz_path]


def test_tree_default_drop_action_is_move(qapp):
    """Régression : DragDropMode.InternalMove forçait implicitement Qt::MoveAction pour tout
    glisser-déposer interne — passer à DragDropMode.DragDrop (nécessaire pour accepter un drop
    externe) fait retomber defaultDropAction sur IgnoreAction si non fixé explicitement, ce qui
    laissait Qt choisir une copie au lieu d'un déplacement lors d'un vrai drag souris : l'item
    source restait affiché en plus du nouvel emplacement, dupliquant le même chapter_id dans
    structure.items (invisible dans l'onglet Images, qui liste des assets dédupliqués, pas des
    chapitres)."""
    from PySide6.QtCore import Qt

    controller, editor = _make_editor(qapp)

    assert editor.tree.defaultDropAction() == Qt.DropAction.MoveAction
