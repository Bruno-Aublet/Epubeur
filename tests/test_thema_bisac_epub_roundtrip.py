from pathlib import Path

from epub.builder import build_epub
from epub.importer import import_epub
from model.assets import AssetStore
from model.book_metadata import BookMetadata
from model.document import Chapter
from model.project import ProjectMeta

# Vérifie le point critique du chantier Thema/BISAC : un code Thema/BISAC est écrit comme un
# dc:subject raffiné (authority/term) — sans traitement particulier à la lecture, il réapparaîtrait
# EN DOUBLE comme un simple mot-clé libre dans `subjects` (epub/importer.py doit explicitement
# l'exclure).


def _build_and_reimport(tmp_path, metadata: BookMetadata) -> BookMetadata:
    project = ProjectMeta()
    project.document.add_chapter(Chapter.create(title="Un chapitre"))
    asset_store = AssetStore(tmp_path / "assets_src")

    epub_path = build_epub(project, asset_store, tmp_path / "out.epub", metadata=metadata)

    reimport_asset_store = AssetStore(tmp_path / "assets_reimport")
    _document, imported_metadata, _warnings = import_epub(epub_path, reimport_asset_store)
    return imported_metadata


def test_thema_and_bisac_codes_survive_roundtrip(tmp_path):
    metadata = BookMetadata(
        title="Roman Test",
        subjects=["fantasy"],
        thema_codes=["AMB", "A"],
        bisac_code="FIC009000",
    )

    imported = _build_and_reimport(tmp_path, metadata)

    assert imported.thema_codes == ["AMB", "A"]
    assert imported.bisac_code == "FIC009000"


def test_thema_and_bisac_codes_do_not_duplicate_into_subjects(tmp_path):
    """Le point critique : un code Thema/BISAC ne doit JAMAIS réapparaître comme mot-clé libre
    dans `subjects` après un aller-retour EPUB."""
    metadata = BookMetadata(
        title="Roman Test",
        subjects=["fantasy", "aventure"],
        thema_codes=["AMB"],
        bisac_code="FIC009000",
    )

    imported = _build_and_reimport(tmp_path, metadata)

    assert imported.subjects == ["fantasy", "aventure"]
    assert "AMB" not in imported.subjects
    assert "Architectes et cabinets d'architecture" not in imported.subjects  # libellé Thema de AMB
    assert "FIC009000" not in imported.subjects


def test_no_thema_or_bisac_produces_empty_defaults(tmp_path):
    metadata = BookMetadata(title="Roman Sans Classification", subjects=["polar"])

    imported = _build_and_reimport(tmp_path, metadata)

    assert imported.thema_codes == []
    assert imported.bisac_code == ""
    assert imported.subjects == ["polar"]
