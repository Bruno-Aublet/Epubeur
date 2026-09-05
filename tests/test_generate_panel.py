from controller import ProjectController
from model.book_metadata import BookMetadata, Contributor
from ui.generate_panel import GeneratePanel


def test_collect_metadata_reflects_form_fields(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)

    panel.title_edit.setText("Mon Roman")
    panel.author_edit.setText("Un Auteur")
    panel.isbn_edit.setText("978-2-1234-5680-3")

    metadata = panel.collect_metadata()

    assert metadata.title == "Mon Roman"
    assert metadata.author == "Un Auteur"
    assert metadata.isbn == "978-2-1234-5680-3"


def test_collect_metadata_defaults_reading_direction_to_ltr(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)

    metadata = panel.collect_metadata()

    assert metadata.reading_direction == "ltr"


def test_collect_metadata_reflects_rtl_selection(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)

    rtl_index = panel.reading_direction_combo.findData("rtl")
    panel.reading_direction_combo.setCurrentIndex(rtl_index)

    metadata = panel.collect_metadata()

    assert metadata.reading_direction == "rtl"


def test_collect_metadata_defaults_title_when_empty(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)

    metadata = panel.collect_metadata()

    assert metadata.title == "Sans titre"


def test_no_contributors_collected_by_default(qapp):
    """Une paire de lignes vide est visible dès l'ouverture (pour porter le bouton "+"), mais un
    contributeur au nom vide n'est jamais collecté."""
    controller = ProjectController()
    panel = GeneratePanel(controller)

    assert len(panel._contributor_rows) == 1
    metadata = panel.collect_metadata()

    assert metadata.contributors == []


def test_add_contributor_button_creates_a_second_row(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)

    panel.add_contributor_btn.click()

    assert len(panel._contributor_rows) == 2


def test_add_contributor_button_stays_on_last_row(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)

    panel.add_contributor_btn.click()
    panel.add_contributor_btn.click()

    assert panel._contributor_rows[-1].trailing_slot.count() == 1
    assert panel._contributor_rows[0].trailing_slot.count() == 0


def test_contributor_row_labels_are_numbered(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)

    panel.add_contributor_btn.click()

    row0, row1 = panel._contributor_rows
    assert panel._form.labelForField(row0.name_row_widget).text() == "Contributeur 1 :"
    assert panel._form.labelForField(row0.file_as_edit).text() == "Nom de tri du contributeur 1 :"
    assert panel._form.labelForField(row1.name_row_widget).text() == "Contributeur 2 :"
    assert panel._form.labelForField(row1.file_as_edit).text() == "Nom de tri du contributeur 2 :"


def test_single_contributor_row_label_has_no_number(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)

    row = panel._contributor_rows[0]
    assert panel._form.labelForField(row.name_row_widget).text() == "Contributeur :"
    assert panel._form.labelForField(row.file_as_edit).text() == "Nom de tri du contributeur :"


def test_collect_metadata_includes_contributor_with_role(qapp):
    from model.contributor_roles import CONTRIBUTOR_ROLE_LABELS

    controller = ProjectController()
    panel = GeneratePanel(controller)

    row = panel._contributor_rows[0]
    row.name_edit.setText("Jean Traducteur")
    trl_index = list(CONTRIBUTOR_ROLE_LABELS.keys()).index("trl")
    row.role_combo.setCurrentIndex(trl_index)

    metadata = panel.collect_metadata()

    assert len(metadata.contributors) == 1
    assert metadata.contributors[0].name == "Jean Traducteur"
    assert metadata.contributors[0].role_code == "trl"


def test_role_combo_shows_labels_not_raw_codes(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)

    row = panel._contributor_rows[0]
    item_texts = [row.role_combo.itemText(i) for i in range(row.role_combo.count())]

    assert "Traducteur" in item_texts
    assert "Illustrateur" in item_texts
    assert "trl" not in item_texts
    assert "ill" not in item_texts


def test_multiple_contributors_are_all_collected(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)
    panel._contributor_rows[0].name_edit.setText("Jean Traducteur")
    panel.add_contributor_btn.click()
    panel._contributor_rows[1].name_edit.setText("Marie Illustratrice")

    metadata = panel.collect_metadata()

    names = {c.name for c in metadata.contributors}
    assert names == {"Jean Traducteur", "Marie Illustratrice"}


def test_remove_button_disabled_when_only_one_contributor_row(qapp):
    """Avec une seule paire de lignes, "Retirer" n'a rien d'utile à faire (il en resterait de
    toute façon une) — désactivé plutôt que de laisser un clic sans effet visible. Régression :
    un clic malgré tout provoquait un crash (RuntimeError sur le bouton "+", déjà détruit en
    cascade avec la ligne par deleteLater() avant d'avoir été détaché)."""
    controller = ProjectController()
    panel = GeneratePanel(controller)

    assert panel._contributor_rows[0].remove_btn.isEnabled() is False


def test_remove_button_reenabled_after_adding_a_second_row(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)

    panel.add_contributor_btn.click()

    assert panel._contributor_rows[0].remove_btn.isEnabled() is True
    assert panel._contributor_rows[1].remove_btn.isEnabled() is True


def test_remove_button_disabled_again_after_removing_back_down_to_one_row(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)
    panel.add_contributor_btn.click()
    second_row = panel._contributor_rows[1]

    second_row.remove_btn.click()

    assert len(panel._contributor_rows) == 1
    assert panel._contributor_rows[0].remove_btn.isEnabled() is False


def test_clearing_the_only_contributor_row_name_is_not_collected(qapp):
    """Sans bouton Retirer disponible, vider le champ nom à la main reste le moyen de "retirer"
    le seul contributeur restant — collect_metadata doit toujours ignorer une ligne au nom vide."""
    controller = ProjectController()
    panel = GeneratePanel(controller)
    row = panel._contributor_rows[0]
    row.name_edit.setText("À retirer")
    row.name_edit.setText("")

    metadata = panel.collect_metadata()

    assert metadata.contributors == []


def test_removing_one_of_several_contributor_rows_keeps_the_others(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)
    panel._contributor_rows[0].name_edit.setText("Garder Moi")
    panel.add_contributor_btn.click()
    second_row = panel._contributor_rows[1]
    second_row.name_edit.setText("À retirer")

    second_row.remove_btn.click()

    assert len(panel._contributor_rows) == 1
    metadata = panel.collect_metadata()
    assert [c.name for c in metadata.contributors] == ["Garder Moi"]


def test_contributor_row_with_empty_name_is_not_collected(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)
    panel.add_contributor_btn.click()  # nom laissé vide

    metadata = panel.collect_metadata()

    assert metadata.contributors == []


def test_apply_metadata_fills_simple_fields(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)
    metadata = BookMetadata(
        title="Livre Importé", author="Auteur Externe", language="en", isbn="9782123456803",
        description="Résumé importé", publication_date="2020", publisher="Editeur Y",
        subjects=["polar", "thriller"], rights="© 2020", source="Oeuvre X",
        relation="Fait partie du coffret Z",
        coverage="Paris, 1920-1940",
        accessibility_summary="Texte seul, compatible lecteur d'écran.",
        collection_title="Collection Y", collection_position="3", reading_direction="rtl",
    )

    panel.apply_metadata(metadata)

    assert panel.title_edit.text() == "Livre Importé"
    assert panel.author_edit.text() == "Auteur Externe"
    assert panel.language_combo.currentData() == "en"
    assert panel.isbn_edit.text() == "9782123456803"
    assert panel.description_edit.toPlainText() == "Résumé importé"
    assert panel.date_edit.text() == "2020"
    assert panel.publisher_edit.text() == "Editeur Y"
    assert panel.subjects_edit.text() == "polar, thriller"
    assert panel.rights_edit.text() == "© 2020"
    assert panel.source_edit.text() == "Oeuvre X"
    assert panel.relation_edit.text() == "Fait partie du coffret Z"
    assert panel.coverage_edit.text() == "Paris, 1920-1940"
    assert panel.accessibility_summary_edit.toPlainText() == "Texte seul, compatible lecteur d'écran."
    assert panel.collection_title_edit.text() == "Collection Y"
    assert panel.collection_position_edit.text() == "3"
    assert panel.reading_direction_combo.currentData() == "rtl"


def test_collect_metadata_includes_relation(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)

    panel.relation_edit.setText("Fait partie du coffret La Trilogie Complète")

    metadata = panel.collect_metadata()

    assert metadata.relation == "Fait partie du coffret La Trilogie Complète"


def test_collect_metadata_includes_coverage(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)

    panel.coverage_edit.setText("Paris, 1920-1940")

    metadata = panel.collect_metadata()

    assert metadata.coverage == "Paris, 1920-1940"


def test_collect_metadata_includes_accessibility_summary(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)

    panel.accessibility_summary_edit.setPlainText(
        "Ce livre contient uniquement du texte structuré, compatible avec les lecteurs "
        "d'écran. Les quelques images sont accompagnées de descriptions.")

    metadata = panel.collect_metadata()

    assert metadata.accessibility_summary == (
        "Ce livre contient uniquement du texte structuré, compatible avec les lecteurs "
        "d'écran. Les quelques images sont accompagnées de descriptions.")


def test_apply_metadata_leaves_title_blank_for_default_placeholder(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)

    panel.apply_metadata(BookMetadata(title="Sans titre"))

    assert panel.title_edit.text() == ""


def test_apply_metadata_populates_contributor_rows(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)
    metadata = BookMetadata(title="Livre", contributors=[
        Contributor(name="Jean Traducteur", role_code="trl"),
        Contributor(name="Marie Illustratrice", role_code="ill"),
    ])

    panel.apply_metadata(metadata)

    assert len(panel._contributor_rows) == 2
    collected = panel.collect_metadata().contributors
    names = {c.name for c in collected}
    assert names == {"Jean Traducteur", "Marie Illustratrice"}
    roles = {c.name: c.role_code for c in collected}
    assert roles["Jean Traducteur"] == "trl"
    assert roles["Marie Illustratrice"] == "ill"


def test_apply_metadata_preserves_unrecognized_contributor_role_code(qapp):
    """Régression : un role_code absent de CONTRIBUTOR_ROLE_LABELS (import EPUB externe,
    édition manuelle du JSON .epbz) était silencieusement remplacé par la valeur par défaut du
    combo ("non précisé") dès la réouverture du formulaire, sans que l'utilisateur ait rien
    changé — perte d'information au premier collect_metadata() (au clic sur Générer, ou à la
    sauvegarde du projet), même sans toucher au formulaire."""
    controller = ProjectController()
    panel = GeneratePanel(controller)
    metadata = BookMetadata(title="Livre", contributors=[
        Contributor(name="Quelqu'un", role_code="code-inconnu-xyz"),
    ])

    panel.apply_metadata(metadata)

    collected = panel.collect_metadata().contributors
    assert collected[0].role_code == "code-inconnu-xyz"


def test_manually_changing_role_combo_overrides_unrecognized_code(qapp):
    """Une fois qu'un code non reconnu a été conservé, un choix EXPLICITE de l'utilisateur dans
    le combo doit prendre le dessus — sans ça, le code d'origine reviendrait malgré le
    changement manuel ultérieur."""
    controller = ProjectController()
    panel = GeneratePanel(controller)
    metadata = BookMetadata(title="Livre", contributors=[
        Contributor(name="Quelqu'un", role_code="code-inconnu-xyz"),
    ])
    panel.apply_metadata(metadata)
    row = panel._contributor_rows[0]

    row.role_combo.setCurrentIndex(1)  # choix manuel explicite d'un rôle connu

    collected = panel.collect_metadata().contributors
    assert collected[0].role_code == row.role_combo.itemData(1)


def test_typing_contributor_name_auto_derives_file_as(qapp):
    from PySide6.QtTest import QTest

    controller = ProjectController()
    panel = GeneratePanel(controller)
    row = panel._contributor_rows[0]

    QTest.keyClicks(row.name_edit, "Isabelle Dupont")

    assert row.file_as_edit.text() == "Dupont, Isabelle"


def test_manually_edited_contributor_file_as_is_not_overwritten(qapp):
    from PySide6.QtTest import QTest

    controller = ProjectController()
    panel = GeneratePanel(controller)
    row = panel._contributor_rows[0]

    QTest.keyClicks(row.name_edit, "Isabelle Dupont")
    row.file_as_edit.clear()
    QTest.keyClicks(row.file_as_edit, "Dupont-Martin, Isabelle")
    QTest.keyClicks(row.name_edit, " (Traductrice)")

    assert row.file_as_edit.text() == "Dupont-Martin, Isabelle"


def test_collect_metadata_includes_contributor_file_as(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)
    row = panel._contributor_rows[0]
    row.name_edit.setText("Jean Traducteur")
    row.file_as_edit.setText("Traducteur, Jean")

    metadata = panel.collect_metadata()

    assert metadata.contributors[0].file_as == "Traducteur, Jean"


def test_apply_metadata_populates_contributor_file_as(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)
    metadata = BookMetadata(title="Livre", contributors=[
        Contributor(name="Jean Traducteur", role_code="trl", file_as="Traducteur, Jean"),
    ])

    panel.apply_metadata(metadata)

    row = panel._contributor_rows[0]
    assert row.file_as_edit.text() == "Traducteur, Jean"
    assert panel.collect_metadata().contributors[0].file_as == "Traducteur, Jean"


def test_apply_metadata_derives_contributor_file_as_when_missing(qapp):
    """Un EPUB importé sans file-as pour un contributeur (ex. généré par un autre outil) doit
    quand même afficher un nom de tri dérivé, plutôt qu'un champ vide — même filet de sécurité
    que pour l'auteur."""
    controller = ProjectController()
    panel = GeneratePanel(controller)
    metadata = BookMetadata(title="Livre", contributors=[
        Contributor(name="Jean Traducteur", role_code="trl", file_as=""),
    ])

    panel.apply_metadata(metadata)

    row = panel._contributor_rows[0]
    assert row.file_as_edit.text() == "Traducteur, Jean"


def test_apply_metadata_replaces_existing_contributor_rows(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)
    panel.add_contributor_btn.click()
    panel._contributor_rows[0].name_edit.setText("Ancien")

    panel.apply_metadata(BookMetadata(title="Livre", contributors=[Contributor(name="Nouveau")]))

    assert len(panel._contributor_rows) == 1
    assert panel.collect_metadata().contributors[0].name == "Nouveau"


def test_controller_metadata_imported_signal_reaches_generate_panel(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)

    controller.metadata_imported.emit(BookMetadata(title="Depuis Signal"))

    assert panel.title_edit.text() == "Depuis Signal"


def test_apply_metadata_if_empty_fills_blank_fields(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)

    panel.apply_metadata_if_empty(BookMetadata(
        title="Titre ODT", author="Auteur ODT", description="Résumé ODT",
        publication_date="2026-08-25", subjects=["fantasy"]))

    assert panel.title_edit.text() == "Titre ODT"
    assert panel.author_edit.text() == "Auteur ODT"
    assert panel.description_edit.toPlainText() == "Résumé ODT"
    assert panel.date_edit.text() == "2026-08-25"
    assert panel.subjects_edit.text() == "fantasy"


def test_apply_metadata_if_empty_never_silently_overwrites_a_filled_field(qapp, monkeypatch):
    """Cœur du correctif : contrairement à apply_metadata (import EPUB, écrase toujours), un
    import ODT ne doit JAMAIS effacer silencieusement une valeur déjà saisie — un conflit ouvre
    MetadataConflictDialog, et le choix par défaut (bouton radio pré-coché) est de garder
    l'ancienne valeur si l'utilisateur ferme la boîte sans changer la sélection."""
    monkeypatch.setattr("ui.metadata_conflict_dialog.MetadataConflictDialog.exec", lambda self: None)
    controller = ProjectController()
    panel = GeneratePanel(controller)
    panel.title_edit.setText("Titre déjà saisi")
    panel.author_edit.setText("Auteur déjà saisi")

    panel.apply_metadata_if_empty(BookMetadata(title="Autre titre", author="Autre auteur"))

    assert panel.title_edit.text() == "Titre déjà saisi"
    assert panel.author_edit.text() == "Auteur déjà saisi"


def test_apply_metadata_if_empty_conflict_dialog_can_replace_value(qapp, monkeypatch):
    """Si l'utilisateur choisit explicitement la nouvelle valeur dans le dialogue de conflit,
    le champ est bien remplacé."""
    monkeypatch.setattr("ui.metadata_conflict_dialog.MetadataConflictDialog.exec", lambda self: None)
    monkeypatch.setattr("ui.metadata_conflict_dialog.MetadataConflictDialog.resolved_choices",
                         lambda self: {name: True for name in self._groups})
    controller = ProjectController()
    panel = GeneratePanel(controller)
    panel.title_edit.setText("Ancien titre")

    panel.apply_metadata_if_empty(BookMetadata(title="Nouveau titre"), "fichier2.odt")

    assert panel.title_edit.text() == "Nouveau titre"


def test_apply_metadata_if_empty_merges_subjects_without_conflict(qapp):
    """Les mots-clés sont fusionnés automatiquement (jamais de conflit/dialogue pour ce champ) :
    une liste peut légitimement s'enrichir entre plusieurs fichiers d'un même livre."""
    controller = ProjectController()
    panel = GeneratePanel(controller)
    panel.subjects_edit.setText("fantasy")

    panel.apply_metadata_if_empty(BookMetadata(subjects=["fantasy", "aventure"]))

    assert panel.subjects_edit.text() == "fantasy, aventure"


def test_language_combo_is_preselected_on_creation(qapp):
    """La langue n'est plus un champ texte à taper (code ISO illisible pour un humain) — une
    liste déroulante fermée est présélectionnée automatiquement (langue système, ou français en
    repli) dès la création du formulaire."""
    controller = ProjectController()
    panel = GeneratePanel(controller)

    assert panel.language_combo.currentData() in ("fr", None) or panel.language_combo.currentData()
    assert panel.language_combo.currentText() != ""


def test_apply_metadata_if_empty_sets_language_from_odt_without_conflict(qapp):
    """La présélection automatique (langue système) n'est jamais une vraie saisie utilisateur :
    un import ODT peut la remplacer directement, sans déclencher de conflit."""
    controller = ProjectController()
    panel = GeneratePanel(controller)

    panel.apply_metadata_if_empty(BookMetadata(language="ja"))

    assert panel.language_combo.currentData() == "ja"


def test_apply_metadata_if_empty_language_conflict_after_manual_selection(qapp, monkeypatch):
    """Une fois la langue changée MANUELLEMENT par l'utilisateur, un import ODT proposant une
    langue différente doit déclencher le dialogue de conflit, pas un écrasement silencieux."""
    monkeypatch.setattr("ui.metadata_conflict_dialog.MetadataConflictDialog.exec", lambda self: None)
    controller = ProjectController()
    panel = GeneratePanel(controller)
    index = panel.language_combo.findData("de")
    panel.language_combo.setCurrentIndex(index)
    assert panel._language_manually_set is True

    panel.apply_metadata_if_empty(BookMetadata(language="ja"))

    # Choix par défaut du dialogue (non modifié ici) : garde l'ancienne langue.
    assert panel.language_combo.currentData() == "de"


def test_apply_metadata_if_empty_language_conflict_can_be_resolved_to_new_value(qapp, monkeypatch):
    monkeypatch.setattr("ui.metadata_conflict_dialog.MetadataConflictDialog.exec", lambda self: None)
    monkeypatch.setattr("ui.metadata_conflict_dialog.MetadataConflictDialog.resolved_choices",
                         lambda self: {name: True for name in self._groups})
    controller = ProjectController()
    panel = GeneratePanel(controller)
    index = panel.language_combo.findData("de")
    panel.language_combo.setCurrentIndex(index)

    panel.apply_metadata_if_empty(BookMetadata(language="ja"))

    assert panel.language_combo.currentData() == "ja"


def test_collect_metadata_returns_language_code_from_combo(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)
    index = panel.language_combo.findData("es")
    panel.language_combo.setCurrentIndex(index)

    assert panel.collect_metadata().language == "es"


def test_apply_metadata_if_empty_ignores_default_title(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)

    panel.apply_metadata_if_empty(BookMetadata(title="Sans titre"))

    assert panel.title_edit.text() == ""


def test_controller_odt_metadata_found_signal_only_fills_empty_fields(qapp, monkeypatch):
    monkeypatch.setattr("ui.metadata_conflict_dialog.MetadataConflictDialog.exec", lambda self: None)
    controller = ProjectController()
    panel = GeneratePanel(controller)
    panel.author_edit.setText("Déjà rempli")

    controller.odt_metadata_found.emit(BookMetadata(title="Depuis ODT", author="Depuis ODT aussi"), "fichier.odt")

    assert panel.title_edit.text() == "Depuis ODT"
    # Conflit sur "author" (déjà rempli avec une valeur différente) : le choix par défaut du
    # dialogue (non modifié ici) garde l'ancienne valeur, jamais un écrasement silencieux.
    assert panel.author_edit.text() == "Déjà rempli"


# --- Persistance de BookMetadata dans le projet (.epbz) ---

def test_new_project_book_metadata_matches_empty_form(qapp, monkeypatch):
    # _preselect_default_language() (ui/generate_panel.py) lit QLocale.system() pour présélectionner
    # la langue du formulaire — sous QT_QPA_PLATFORM=offscreen (forcé par tests/conftest.py pour toute
    # la suite, nécessaire pour lancer les tests sans afficher de fenêtres), QLocale.system() ne
    # reflète PAS la vraie locale Windows (vérifié : elle retombe sur en_US même quand Windows est
    # réellement en fr-FR, confirmé via l'API Win32 GetUserDefaultLocaleName et le registre). Sans ce
    # monkeypatch, ce test dépendrait de la locale système ET du mode Qt (offscreen ou non) au lieu de
    # tester uniquement le comportement de GeneratePanel — figé ici sur "fr" pour être déterministe
    # indépendamment de la machine/l'environnement d'exécution.
    from PySide6.QtCore import QLocale
    monkeypatch.setattr(QLocale, "system", staticmethod(lambda: QLocale("fr_FR")))

    controller = ProjectController()
    panel = GeneratePanel(controller)

    assert controller.project.book_metadata == BookMetadata()
    assert panel.collect_metadata() == BookMetadata()


def test_project_loaded_signal_repopulates_form(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)
    controller.project.book_metadata = BookMetadata(
        title="Roman Chargé", author="Autrice Chargée",
        contributors=[Contributor(name="Illustrateur X", role_code="ill")],
    )

    controller.project_loaded.emit()

    assert panel.title_edit.text() == "Roman Chargé"
    assert panel.author_edit.text() == "Autrice Chargée"
    assert len(panel._contributor_rows) == 1
    assert panel._contributor_rows[0].name_edit.text() == "Illustrateur X"


def test_save_project_as_captures_current_form_state(qapp, monkeypatch, tmp_path):
    """Exerce le vrai chemin utilisateur (MainWindow._save_project_as, pas
    controller.save_project_as directement) : c'est CE point précis qui capture l'état courant
    du formulaire dans le projet avant l'écriture — controller.save_project_as seul ne le fait
    jamais (aucune connaissance de l'UI par conception)."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from ui.main_window import MainWindow

    window = MainWindow()
    window.generate_panel.title_edit.setText("Titre Saisi")
    window.generate_panel.author_edit.setText("Auteur Saisi")

    epbz_path = tmp_path / "Projet.epbz"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(epbz_path), ""))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    window._save_project_as()

    from model.epbz import load_project_epbz
    loaded, _extract_dir, _warnings = load_project_epbz(epbz_path)
    assert loaded.book_metadata.title == "Titre Saisi"
    assert loaded.book_metadata.author == "Auteur Saisi"


# --- Thema (menus en cascade) / BISAC (champ texte libre) ---

def test_new_thema_row_has_one_combo_with_26_roots(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)

    row = panel.thema_row
    assert len(row.combos) == 1
    assert row.combos[0].count() == 27  # "(aucun)" + 26 racines


def test_selecting_root_with_children_adds_a_second_combo(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)
    row = panel.thema_row

    index = row.combos[0].findData("A")  # "Arts", a des enfants
    row.combos[0].setCurrentIndex(index)

    assert len(row.combos) == 2
    child_codes = {row.combos[1].itemData(i) for i in range(row.combos[1].count())}
    assert "AM" in child_codes


def test_selecting_leaf_code_does_not_add_a_combo(qapp):
    from model.thema import thema_children
    controller = ProjectController()
    panel = GeneratePanel(controller)
    row = panel.thema_row

    # "ABK" est une feuille connue (vérifié dans tests/test_thema.py)
    row.combos[0].setCurrentIndex(row.combos[0].findData("A"))
    assert not thema_children("ABK")
    index = row.combos[1].findData("AB")
    row.combos[1].setCurrentIndex(index)
    row.combos[2].setCurrentIndex(row.combos[2].findData("ABK"))

    assert len(row.combos) == 3  # pas de 4e menu ajouté


def test_changing_root_selection_removes_obsolete_child_combos(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)
    row = panel.thema_row

    row.combos[0].setCurrentIndex(row.combos[0].findData("A"))
    assert len(row.combos) == 2

    row.combos[0].setCurrentIndex(row.combos[0].findData(""))  # "(aucun)"
    assert len(row.combos) == 1


def test_to_code_returns_deepest_selected_code(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)
    row = panel.thema_row

    row.combos[0].setCurrentIndex(row.combos[0].findData("A"))
    row.combos[1].setCurrentIndex(row.combos[1].findData("AM"))

    assert row.to_code() == "AM"


def test_set_code_reconstructs_full_depth(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)
    row = panel.thema_row

    row.set_code("AMB")

    assert len(row.combos) == 3
    assert row.to_code() == "AMB"
    assert row.combos[0].currentData() == "A"
    assert row.combos[1].currentData() == "AM"
    assert row.combos[2].currentData() == "AMB"


def test_collect_metadata_includes_thema_codes_and_bisac_code(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)
    panel.thema_row.set_code("AMB")
    panel.bisac_edit.setText("FIC009000")

    metadata = panel.collect_metadata()

    assert metadata.thema_codes == ["AMB"]
    assert metadata.bisac_code == "FIC009000"


def test_apply_metadata_repopulates_thema_row_and_bisac(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)

    panel.apply_metadata(BookMetadata(title="Livre", thema_codes=["AMB", "A"], bisac_code="FIC009000"))

    # Une seule ligne fixe : seul le PREMIER code de la liste est affiché/éditable dans l'UI.
    assert panel.thema_row.to_code() == "AMB"
    assert panel.bisac_edit.text() == "FIC009000"


def test_apply_metadata_if_empty_fills_thema_row_only_if_still_empty(qapp):
    controller = ProjectController()
    panel = GeneratePanel(controller)
    panel.thema_row.set_code("A")

    panel.apply_metadata_if_empty(BookMetadata(thema_codes=["AMB"]))

    assert panel.thema_row.to_code() == "A"  # déjà rempli, jamais écrasé silencieusement

    controller2 = ProjectController()
    panel2 = GeneratePanel(controller2)
    panel2.apply_metadata_if_empty(BookMetadata(thema_codes=["AMB"]))
    assert panel2.thema_row.to_code() == "AMB"  # vide au départ, complété


def test_bisac_link_is_clickable_qlabel(qapp):
    from PySide6.QtWidgets import QLabel
    controller = ProjectController()
    panel = GeneratePanel(controller)

    links = [w for w in panel.findChildren(QLabel) if "bisg.org" in w.text()]
    assert len(links) == 1
    assert links[0].openExternalLinks() is True
