import zipfile
from pathlib import Path

import pytest

from controller import ProjectController
from model.assets import AssetRole, AssetStore
from model.document import Chapter, ImageAnchor, LockedFont, LockedFontFile, Paragraph, Part
from model.epbz import load_project_epbz, save_project_epbz
from model.project import ProjectMeta, SourceOdtFile


def _make_project_with_image_and_font(tmp_path) -> tuple[ProjectMeta, AssetStore]:
    asset_store = AssetStore(tmp_path / "assets")
    asset = asset_store.ingest_bytes(b"fake-image-bytes", "cover.png", AssetRole.CHAPTER_POV)

    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Un gobelin"))]

    project = ProjectMeta()
    project.document.add_chapter(chapter)

    font_file = tmp_path / "MaPolice.ttf"
    font_file.write_bytes(b"fake ttf bytes for the round-trip test")
    project.document.locked_fonts = [
        LockedFont(family="MaPolice", files=[LockedFontFile(file_path=str(font_file))])
    ]

    return project, asset_store


def test_roundtrip_preserves_document_image_and_font_bytes(tmp_path):
    project, asset_store = _make_project_with_image_and_font(tmp_path)
    epbz_path = tmp_path / "MonRoman.epbz"

    save_project_epbz(project, asset_store, epbz_path)
    loaded, extract_dir, warnings = load_project_epbz(epbz_path)

    assert warnings == []
    chapter_id = next(iter(project.document.chapters))
    loaded_chapter = loaded.document.chapters[chapter_id]
    assert loaded_chapter.title == "Chapitre Un"
    assert loaded_chapter.paragraphs[0].image.alt_text == "Un gobelin"

    original_asset_id = project.document.chapters[chapter_id].paragraphs[0].image.asset_id
    loaded_image_bytes = (extract_dir / "assets" / "images").glob("*")
    assert any(f.read_bytes() == b"fake-image-bytes" for f in loaded_image_bytes)
    assert loaded_chapter.paragraphs[0].image.asset_id == original_asset_id

    lf = loaded.document.locked_fonts[0]
    assert lf.family == "MaPolice"
    assert Path(lf.files[0].file_path).read_bytes() == b"fake ttf bytes for the round-trip test"
    assert loaded.epbz_path == epbz_path


def test_roundtrip_preserves_extra_images_on_same_paragraph(tmp_path):
    """Régression : Paragraph.extra_images (deuxième image et suivantes ancrées au même
    paragraphe, cf. odt/chapter_detector.py) doit survivre au cycle complet
    save_project_epbz -> écriture .epbz sur disque -> load_project_epbz, pas seulement à
    document_to_dict/document_from_dict pris isolément."""
    asset_store = AssetStore(tmp_path / "assets")
    asset_a = asset_store.ingest_bytes(b"premiere-image-bytes", "premiere.png", AssetRole.CHAPTER_POV)
    asset_b = asset_store.ingest_bytes(b"seconde-image-bytes", "seconde.png", AssetRole.CHAPTER_POV)

    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(
        image=ImageAnchor(asset_id=asset_a.id, alt_text="Première"),
        extra_images=[ImageAnchor(asset_id=asset_b.id, alt_text="Seconde")],
    )]
    project = ProjectMeta()
    project.document.add_chapter(chapter)

    epbz_path = tmp_path / "MonRoman.epbz"
    save_project_epbz(project, asset_store, epbz_path)
    loaded, _extract_dir, warnings = load_project_epbz(epbz_path)

    assert warnings == []
    chapter_id = next(iter(project.document.chapters))
    loaded_para = loaded.document.chapters[chapter_id].paragraphs[0]
    assert loaded_para.image.asset_id == asset_a.id
    assert loaded_para.image.alt_text == "Première"
    assert len(loaded_para.extra_images) == 1
    assert loaded_para.extra_images[0].asset_id == asset_b.id
    assert loaded_para.extra_images[0].alt_text == "Seconde"


def test_save_deduplicates_identical_locked_font_files(tmp_path):
    """Régression : deux LockedFontFile différents mais au contenu binaire IDENTIQUE (ex.
    l'utilisateur pointe volontairement Bold vers une copie du même fichier que Regular)
    produisaient le même arcname "fonts/<sha256>.<ext>" — save_project_epbz écrivait alors deux
    fois la même entrée dans le zip (UserWarning: Duplicate name, gaspillage d'espace)."""
    import warnings as warnings_module

    asset_store = AssetStore(tmp_path / "assets")
    project = ProjectMeta()

    font_file_a = tmp_path / "Police-Regular.ttf"
    font_file_b = tmp_path / "Police-Copie.ttf"
    identical_bytes = b"fake ttf bytes, identiques dans les deux fichiers"
    font_file_a.write_bytes(identical_bytes)
    font_file_b.write_bytes(identical_bytes)

    project.document.locked_fonts = [
        LockedFont(family="Police", files=[
            LockedFontFile(file_path=str(font_file_a)),
            LockedFontFile(file_path=str(font_file_b)),
        ])
    ]

    epbz_path = tmp_path / "MonRoman.epbz"
    with warnings_module.catch_warnings():
        warnings_module.simplefilter("error")  # une UserWarning ici doit faire échouer le test
        save_project_epbz(project, asset_store, epbz_path)

    with zipfile.ZipFile(epbz_path) as zf:
        font_entries = [n for n in zf.namelist() if n.startswith("fonts/")]
    assert len(font_entries) == len(set(font_entries)) == 1


def test_locked_font_survives_original_external_file_being_deleted(tmp_path):
    """Cœur de la promesse .epbz : la police est embarquée dans l'archive, donc supprimer le
    fichier externe d'origine APRÈS la sauvegarde ne doit plus jamais casser le rechargement —
    contrairement à l'ancien format dossier qui référençait toujours un chemin absolu externe."""
    project, asset_store = _make_project_with_image_and_font(tmp_path)
    epbz_path = tmp_path / "MonRoman.epbz"
    save_project_epbz(project, asset_store, epbz_path)

    original_font_path = Path(project.document.locked_fonts[0].files[0].file_path)
    original_font_path.unlink()

    loaded, _extract_dir, warnings = load_project_epbz(epbz_path)

    assert not any("introuvable" in w for w in warnings)
    assert Path(loaded.document.locked_fonts[0].files[0].file_path).exists()


def test_load_project_epbz_missing_project_json_entry_raises(tmp_path):
    epbz_path = tmp_path / "corrompu.epbz"
    with zipfile.ZipFile(epbz_path, "w") as zf:
        zf.writestr("assets/images/foo.png", b"not a real project")

    with pytest.raises(Exception):
        load_project_epbz(epbz_path)


def test_load_project_epbz_not_a_zip_raises(tmp_path):
    fake_path = tmp_path / "pas_un_zip.epbz"
    fake_path.write_bytes(b"this is definitely not a zip file")

    with pytest.raises(Exception):
        load_project_epbz(fake_path)


def test_warns_on_missing_source_odt_path(tmp_path):
    project, asset_store = _make_project_with_image_and_font(tmp_path)
    entry = SourceOdtFile.create(Path("C:/nonexistent/missing.odt"), 0)
    project.source_odt_files.append(entry)
    epbz_path = tmp_path / "MonRoman.epbz"

    save_project_epbz(project, asset_store, epbz_path)
    _loaded, _extract_dir, warnings = load_project_epbz(epbz_path)

    assert any("introuvable" in w for w in warnings)


def test_save_overwrites_atomically_leaving_no_tmp_file(tmp_path):
    project, asset_store = _make_project_with_image_and_font(tmp_path)
    epbz_path = tmp_path / "MonRoman.epbz"

    save_project_epbz(project, asset_store, epbz_path)
    save_project_epbz(project, asset_store, epbz_path)  # deuxième écriture, doit remplacer proprement

    assert epbz_path.exists()
    assert not epbz_path.with_suffix(".epbz.tmp").exists()


# --- Persistance de BookMetadata (titre, auteur, ISBN...) ---
# Régression : le formulaire de l'onglet Métadonnées était purement transitoire (reconstruit à la
# demande au clic sur « Générer » ou lors d'un import), jamais sauvegardé dans le projet — rouvrir
# un .epbz faisait perdre silencieusement tout ce formulaire.

def test_roundtrip_preserves_full_book_metadata(tmp_path):
    from model.book_metadata import BookMetadata, Contributor

    project, asset_store = _make_project_with_image_and_font(tmp_path)
    project.book_metadata = BookMetadata(
        title="Le Guide d'Eauprofonde", author="Volothamp Geddarm",
        author_file_as="Geddarm, Volothamp", language="fr", isbn="9782123456803",
        description="Un guide complet de la cité.", publication_date="2026-08-25",
        publisher="Éditions Waterdeep", subjects=["fantasy", "aventure"],
        thema_codes=["AMB", "A"], bisac_code="FIC009000",
        rights="© 2026 Volothamp Geddarm", source="Volo's Guide to Waterdeep",
        relation="Fait partie du coffret Chroniques d'Eauprofonde",
        coverage="Eauprofonde, période contemporaine",
        accessibility_summary="Texte seul, compatible lecteur d'écran.",
        collection_title="Chroniques d'Eauprofonde", collection_position="1",
        reading_direction="ltr",
        contributors=[Contributor(name="Elminster", role_code="ill", file_as="Elminster"),
                      Contributor(name="Mystra", role_code="trl", file_as="Mystra")],
    )
    epbz_path = tmp_path / "MonRoman.epbz"

    save_project_epbz(project, asset_store, epbz_path)
    loaded, _extract_dir, _warnings = load_project_epbz(epbz_path)

    assert loaded.book_metadata == project.book_metadata


def test_old_epbz_without_book_metadata_key_loads_with_defaults(tmp_path):
    """Un .epbz sauvegardé AVANT ce chantier n'a aucune clé "book_metadata" dans son JSON — doit
    charger proprement en BookMetadata() par défaut plutôt que de planter."""
    from model.book_metadata import BookMetadata

    project, asset_store = _make_project_with_image_and_font(tmp_path)
    epbz_path = tmp_path / "MonRoman.epbz"
    save_project_epbz(project, asset_store, epbz_path)

    # Simule un ancien .epbz : réécrit le zip sans la clé "book_metadata".
    import json
    with zipfile.ZipFile(epbz_path, "r") as zf:
        data = json.loads(zf.read("project.epubeur.json"))
    del data["book_metadata"]
    with zipfile.ZipFile(epbz_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.epubeur.json", json.dumps(data))

    loaded, _extract_dir, _warnings = load_project_epbz(epbz_path)

    assert loaded.book_metadata == BookMetadata()


# --- Intégration controller.py ---

def test_controller_save_and_load_roundtrip(tmp_path, qapp):
    controller = ProjectController()
    chapter = Chapter.create(title="Un chapitre")
    controller.project.document.add_chapter(chapter)

    epbz_path = tmp_path / "Projet.epbz"
    assert controller.save_project_as(epbz_path)
    assert controller.project.epbz_path == epbz_path

    new_controller = ProjectController()
    warnings = new_controller.load_project_from(epbz_path)

    assert warnings == []
    assert chapter.id in new_controller.project.document.chapters
    assert new_controller.project.epbz_path == epbz_path


def test_load_project_from_removes_previous_temp_dir(tmp_path, qapp):
    """Régression : load_project_from() écrasait _temp_assets_dir par le nouveau dossier extrait
    sans jamais supprimer le précédent — plusieurs ouvertures de projet dans la même session
    accumulaient des dossiers orphelins (potentiellement avec toutes les images) dans %TEMP%."""
    controller = ProjectController()
    chapter = Chapter.create(title="Un chapitre")
    controller.project.document.add_chapter(chapter)
    epbz_path = tmp_path / "Projet.epbz"
    assert controller.save_project_as(epbz_path)

    new_controller = ProjectController()
    first_temp_dir = new_controller._temp_assets_dir
    assert first_temp_dir.exists()

    new_controller.load_project_from(epbz_path)

    assert not first_temp_dir.exists()
    assert new_controller._temp_assets_dir.exists()


def test_roundtrip_preserves_image_added_via_add_image_as_chapter(tmp_path, qapp):
    controller = ProjectController()
    image_path = tmp_path / "personnage.jpg"
    image_bytes = b"\xff\xd8\xff\xe0fakejpeg"
    image_path.write_bytes(image_bytes)
    chapter_id = controller.add_image_as_chapter(image_path)

    epbz_path = tmp_path / "Projet.epbz"
    assert controller.save_project_as(epbz_path)

    new_controller = ProjectController()
    new_controller.load_project_from(epbz_path)

    assert chapter_id in new_controller.project.document.chapters
    reloaded_chapter = new_controller.project.document.chapters[chapter_id]
    assert reloaded_chapter.title == "personnage"
    asset_id = reloaded_chapter.paragraphs[0].image.asset_id
    assert new_controller.asset_store.path_for(asset_id).read_bytes() == image_bytes


def test_undo_after_everywhere_removal_fully_restores_image(qapp):
    """L'asset n'est jamais supprimé physiquement par remove_image_everywhere (cf.
    controller._drop_asset_if_orphaned) : _snapshot_structure() ne clone que project.document,
    jamais asset_store — une suppression physique immédiate aurait cassé Ctrl+Z (la référence
    revenait, pas le fichier, laissant une image cassée dans l'aperçu après un undo). Un undo
    doit donc restaurer l'image intégralement, fichier compris."""
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", "perso.jpg", AssetRole.CHAPTER_POV)
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id)), Paragraph(runs=[])]
    controller.project.document.add_chapter(chapter)

    controller.remove_image_everywhere(asset.id)
    assert controller.asset_store.get(asset.id) is not None  # jamais supprimé physiquement

    controller.undo()
    restored_chapter = controller.project.document.chapters[chapter.id]
    assert restored_chapter.paragraphs[0].image.asset_id == asset.id
    assert controller.asset_store.get(asset.id) is not None


def test_load_project_from_migrates_legacy_hash_named_image_and_resaves_epbz(tmp_path, qapp):
    """Régression : un .epbz créé avant que rename() ne renomme le fichier physique contient
    l'image encore nommée "<hash>.<ext>" dans assets/images/ alors que original_filename porte
    déjà le nom renommé (cf. model/assets.py::AssetStore._load_index). La migration à l'ouverture
    doit se refléter dans le .epbz sur disque SANS attendre un Enregistrer explicite de
    l'utilisateur — sinon rouvrir le même fichier sans le modifier ne change jamais rien."""
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", "old_name.jpg", AssetRole.CHAPTER_POV)
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id))]
    controller.project.document.add_chapter(chapter)
    epbz_path = tmp_path / "Projet.epbz"
    assert controller.save_project_as(epbz_path)

    # Simule l'état "legacy" : le fichier a été renommé après coup dans le .epbz déjà sauvegardé,
    # comme l'aurait laissé une version antérieure au correctif (rename() qui ne touchait jamais
    # au fichier physique).
    controller.asset_store.rename(asset.id, "Nouveau Nom")
    legacy_path = controller.asset_store.images_dir / f"{asset.id}.jpg"
    controller.asset_store.path_for(asset.id).replace(legacy_path)
    assert controller.save_project_as(epbz_path)
    with zipfile.ZipFile(epbz_path) as zf:
        names = zf.namelist()
    assert f"assets/images/{asset.id}.jpg" in names
    assert not any(n.endswith("Nouveau Nom.jpg") for n in names)

    new_controller = ProjectController()
    new_controller.load_project_from(epbz_path)

    reloaded_chapter = next(iter(new_controller.project.document.chapters.values()))
    reloaded_asset_id = reloaded_chapter.paragraphs[0].image.asset_id
    assert new_controller.asset_store.path_for(reloaded_asset_id).name == "Nouveau Nom.jpg"

    with zipfile.ZipFile(epbz_path) as zf:
        names_after = zf.namelist()
    assert any(n.endswith("Nouveau Nom.jpg") for n in names_after)
    assert f"assets/images/{asset.id}.jpg" not in names_after


def test_controller_save_without_epbz_path_errors(qapp):
    controller = ProjectController()
    errors: list[str] = []
    controller.error_occurred.connect(errors.append)

    assert controller.save_project() is False
    assert len(errors) == 1


def test_controller_save_reuses_epbz_path_on_plain_save(tmp_path, qapp):
    controller = ProjectController()
    controller.project.document.add_chapter(Chapter.create(title="Un chapitre"))
    epbz_path = tmp_path / "Projet.epbz"
    controller.save_project_as(epbz_path)

    controller.project.document.add_chapter(Chapter.create(title="Un deuxième chapitre"))
    assert controller.save_project()

    reloaded, _extract_dir, _warnings = load_project_epbz(epbz_path)
    assert len(reloaded.document.chapters) == 2


def test_controller_load_corrupt_epbz_emits_error_and_keeps_project_untouched(tmp_path, qapp):
    controller = ProjectController()
    original_chapter = Chapter.create(title="Chapitre existant")
    controller.project.document.add_chapter(original_chapter)

    corrupt_path = tmp_path / "corrompu.epbz"
    corrupt_path.write_bytes(b"not a zip")

    errors: list[str] = []
    controller.error_occurred.connect(errors.append)

    result = controller.load_project_from(corrupt_path)

    assert result == []
    assert len(errors) == 1
    assert original_chapter.id in controller.project.document.chapters
