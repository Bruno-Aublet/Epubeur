from controller import ProjectController
from model.assets import AssetRole
from model.document import Chapter, ImageAnchor, Paragraph


def test_load_project_backfills_alt_text_from_legacy_paragraphs(tmp_path, qapp):
    """Un projet sauvegardé avant l'introduction de Document.image_alt_texts peut contenir des
    ImageAnchor.alt_text jamais reportés — le chargement doit les reporter rétrospectivement,
    pour qu'une description déjà saisie dans Writer ne reste pas invisible dans l'onglet Images."""
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"fake-image", "perso.png", AssetRole.CHAPTER_POV)
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Un gobelin"))]
    controller.project.document.add_chapter(chapter)
    # Simule un projet "ancien" : sauvegardé sans jamais avoir appelé le backfill (donc sans
    # image_alt_texts peuplé), comme un projet créé avant ce chantier.
    assert asset.id not in controller.project.document.image_alt_texts

    epbz_path = tmp_path / "Project.epbz"
    assert controller.save_project_as(epbz_path)

    new_controller = ProjectController()
    new_controller.load_project_from(epbz_path)

    assert new_controller.project.document.image_alt_texts[asset.id] == "Un gobelin"


def test_backfill_keeps_first_description_when_multiple_paragraphs_share_asset(qapp):
    """Même image (même asset_id, déduplication par contenu) utilisée dans plusieurs fichiers
    ODT fondus dans un même projet : la première description rencontrée est conservée."""
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"fake-image", "perso.png", AssetRole.CHAPTER_POV)
    chapter_a = Chapter.create(title="Chapitre A")
    chapter_a.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Description A"))]
    chapter_b = Chapter.create(title="Chapitre B")
    chapter_b.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text=""))]
    controller.project.document.chapters[chapter_a.id] = chapter_a
    controller.project.document.chapters[chapter_b.id] = chapter_b

    controller._backfill_image_alt_texts_from_paragraphs()

    assert controller.project.document.image_alt_texts[asset.id] == "Description A"


def test_backfill_warns_on_conflicting_descriptions_for_same_asset(qapp):
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"fake-image", "perso.png", AssetRole.CHAPTER_POV)
    chapter_a = Chapter.create(title="Chapitre A")
    chapter_a.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Description A"))]
    chapter_b = Chapter.create(title="Chapitre B")
    chapter_b.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Description B"))]
    controller.project.document.chapters[chapter_a.id] = chapter_a
    controller.project.document.chapters[chapter_b.id] = chapter_b

    warnings = []
    controller.warning_occurred.connect(warnings.append)
    controller._backfill_image_alt_texts_from_paragraphs()

    assert len(warnings) == 1
    assert "Description A" in warnings[0]
    assert "Description B" in warnings[0]
    assert controller.project.document.image_alt_texts[asset.id] == "Description A"


def test_backfill_warns_only_once_per_asset_with_multiple_conflicts(qapp):
    """Trois occurrences en désaccord ne doivent produire qu'un seul avertissement, pas un par
    occurrence conflictuelle en trop."""
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"fake-image", "perso.png", AssetRole.CHAPTER_POV)
    chapter_a = Chapter.create(title="A")
    chapter_a.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Description A"))]
    chapter_b = Chapter.create(title="B")
    chapter_b.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Description B"))]
    chapter_c = Chapter.create(title="C")
    chapter_c.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Description C"))]
    controller.project.document.chapters[chapter_a.id] = chapter_a
    controller.project.document.chapters[chapter_b.id] = chapter_b
    controller.project.document.chapters[chapter_c.id] = chapter_c

    warnings = []
    controller.warning_occurred.connect(warnings.append)
    controller._backfill_image_alt_texts_from_paragraphs()

    assert len(warnings) == 1


def test_backfill_no_warning_when_descriptions_match(qapp):
    controller = ProjectController()
    asset = controller.asset_store.ingest_bytes(b"fake-image", "perso.png", AssetRole.CHAPTER_POV)
    chapter_a = Chapter.create(title="A")
    chapter_a.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Même description"))]
    chapter_b = Chapter.create(title="B")
    chapter_b.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id, alt_text="Même description"))]
    controller.project.document.chapters[chapter_a.id] = chapter_a
    controller.project.document.chapters[chapter_b.id] = chapter_b

    warnings = []
    controller.warning_occurred.connect(warnings.append)
    controller._backfill_image_alt_texts_from_paragraphs()

    assert warnings == []
