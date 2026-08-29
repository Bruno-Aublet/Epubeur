from pathlib import Path

from controller import ProjectController
from model.assets import AssetRole


def test_add_image_as_chapter_rejects_unsupported_format(qapp, tmp_path):
    """Un ajout manuel (drop) d'image dans un format non supporté ne doit RIEN ajouter au
    projet — contrairement à un import ODT/EPUB où le fichier source impose le format,
    l'utilisateur choisit ici délibérément un fichier, il vaut mieux refuser que polluer le
    projet avec un asset dans un format non garanti."""
    controller = ProjectController()
    image_path = tmp_path / "personnage.gif"
    image_path.write_bytes(b"gif-bytes")

    emitted = []
    controller.warning_occurred.connect(emitted.append)
    chapter_id = controller.add_image_as_chapter(image_path)

    assert chapter_id is None
    assert controller.project.document.chapters == {}
    assert len(emitted) == 1
    assert "personnage.gif" in emitted[0]


def test_add_image_as_chapter_rejects_missing_file(qapp, tmp_path):
    """Régression : un chemin dont le fichier n'existe plus (déplacé/supprimé entre la
    sélection et l'ajout effectif) faisait lever une FileNotFoundError non gérée par
    file_path.read_bytes(), au lieu d'un avertissement propre comme pour un format non
    supporté."""
    controller = ProjectController()
    missing_path = tmp_path / "disparu.png"  # jamais créé

    emitted = []
    controller.warning_occurred.connect(emitted.append)
    chapter_id = controller.add_image_as_chapter(missing_path)  # ne doit pas lever

    assert chapter_id is None
    assert controller.project.document.chapters == {}
    assert len(emitted) == 1
    assert "disparu.png" in emitted[0]


def test_insert_image_after_paragraph_rejects_missing_file(qapp, tmp_path):
    """Même régression que add_image_as_chapter, pour "Coller l'image ici" — chemin le plus
    exposé au TOCTOU puisqu'il vient du presse-papier Windows (paste_image_source), dont le
    contenu peut dater d'un Ctrl+C ancien avec le fichier déjà déplacé/supprimé depuis."""
    from model.document import Chapter, Paragraph

    controller = ProjectController()
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph()]
    controller.project.document.chapters[chapter.id] = chapter
    missing_path = tmp_path / "disparu.png"  # jamais créé

    emitted = []
    controller.warning_occurred.connect(emitted.append)
    controller.insert_image_after_paragraph(chapter.id, 0, missing_path)  # ne doit pas lever

    assert len(chapter.paragraphs) == 1  # rien inséré
    assert len(emitted) == 1
    assert "disparu.png" in emitted[0]


def test_add_image_as_chapter_accepts_supported_format(qapp, tmp_path):
    controller = ProjectController()
    image_path = tmp_path / "personnage.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")

    emitted = []
    controller.warning_occurred.connect(emitted.append)
    chapter_id = controller.add_image_as_chapter(image_path)

    assert chapter_id is not None
    assert chapter_id in controller.project.document.chapters
    assert emitted == []


def test_emit_unsupported_image_warnings_emits_signal_per_format(qapp):
    controller = ProjectController()
    controller.asset_store.ingest_bytes(b"a", "image.gif", AssetRole.CHAPTER_POV)
    controller.asset_store.ingest_bytes(b"b", "image.webp", AssetRole.CHAPTER_POV)

    emitted = []
    controller.warning_occurred.connect(emitted.append)
    controller.emit_unsupported_image_warnings()

    assert len(emitted) == 2
    assert "image.gif" in emitted[0]
    assert "image.webp" in emitted[1]


def test_emit_unsupported_image_warnings_clears_after_emitting(qapp):
    controller = ProjectController()
    controller.asset_store.ingest_bytes(b"a", "image.gif", AssetRole.CHAPTER_POV)

    controller.emit_unsupported_image_warnings()
    emitted = []
    controller.warning_occurred.connect(emitted.append)
    controller.emit_unsupported_image_warnings()

    assert emitted == []


def test_emit_unsupported_image_warnings_silent_for_png_jpeg(qapp):
    controller = ProjectController()
    controller.asset_store.ingest_bytes(b"a", "image.png", AssetRole.CHAPTER_POV)
    controller.asset_store.ingest_bytes(b"b", "image.jpg", AssetRole.CHAPTER_POV)

    emitted = []
    controller.warning_occurred.connect(emitted.append)
    controller.emit_unsupported_image_warnings()

    assert emitted == []
