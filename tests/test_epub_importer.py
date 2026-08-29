from pathlib import Path

import pytest

from epub.builder import build_epub
from epub.importer import import_epub
from model.assets import AssetStore
from model.book_metadata import BookMetadata, Contributor
from model.document import Part
from model.project import ProjectMeta
from model.styles import ParagraphAlign, ParagraphKind
from odt.chapter_detector import split_into_chapters
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver

FIXTURE = Path(__file__).parent / "fixtures" / "sample_simple.odt"
ARIAL = Path("C:/Windows/Fonts/arial.ttf")


def _generate_reference_epub(tmp_path) -> Path:
    asset_store = AssetStore(tmp_path / "assets_src")
    source = OdtSource(FIXTURE)
    resolver = StyleResolver(source)
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)

    project = ProjectMeta()
    for ch in chapters:
        project.document.chapters[ch.id] = ch  # pas add_chapter() : structure posée explicitement ensuite
    part = Part.create(title="Partie I")
    part.chapter_ids = [c.id for c in chapters]
    project.document.structure.items.append(part)

    return build_epub(project, asset_store, tmp_path / "roundtrip.epub", metadata=BookMetadata(title="Roman Roundtrip"))


def test_round_trip_chapter_id_survives_zip_write(tmp_path):
    """Régression : data-epubeur-chapter-id était posé directement sur <body>, qu'ebooklib
    régénère entièrement à l'écriture du zip en ne conservant que ses enfants — l'attribut
    disparaissait donc silencieusement du fichier réellement écrit, cassant tout round-trip
    d'identité de chapitre. Vérifie directement le contenu du zip, pas juste avant écriture."""
    import zipfile

    epub_path = _generate_reference_epub(tmp_path)
    with zipfile.ZipFile(epub_path) as zf:
        chapter_files = [n for n in zf.namelist() if n.endswith("chapter_0.xhtml")]
        assert chapter_files, "aucun fichier chapter_0.xhtml trouvé dans le zip"
        content = zf.read(chapter_files[0]).decode()
        assert 'data-epubeur-chapter-id="' in content, \
            "data-epubeur-chapter-id absent du XHTML réellement écrit dans le zip"


def test_round_trip_preserves_chapter_ids_and_titles(tmp_path):
    epub_path = _generate_reference_epub(tmp_path)
    asset_store = AssetStore(tmp_path / "assets_import")

    document, _imported_metadata, warnings = import_epub(epub_path, asset_store)

    assert len(document.chapters) == 2
    titles = {c.title for c in document.chapters.values()}
    assert titles == {"Chapitre un", "Chapitre deux"}


def test_round_trip_marker_in_body_text_of_external_epub_does_not_corrupt_id(tmp_path):
    """Régression : _extract_round_trip_chapter_id cherchait le marqueur data-epubeur-chapter-id
    par simple sous-chaîne, sans exiger le contexte <div class="epubeur-chapter" ...> réel dans
    lequel epub/html_render.py l'émet toujours. Pour un EPUB EXTERNE (jamais généré par Epubeur,
    donc sans vrai marqueur), un chapitre dont le TEXTE contient littéralement ce marqueur en
    HTML échappé (ex. un livre technique documentant ce format) le faisait extraire à tort comme
    un vrai marqueur de round-trip — si deux chapitres distincts du même livre externe
    contenaient chacun ce même exemple technique, ils fusionnaient silencieusement en un seul à
    l'import (même chapter_id extrait des deux), perdant la distinction entre eux."""
    import zipfile

    poisoned_snippet = '&lt;div class="epubeur-chapter" data-epubeur-chapter-id="peu-importe"&gt;'
    external_dir_content = {
        "mimetype": "application/epub+zip",
        "META-INF/container.xml": """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""",
        "OEBPS/content.opf": """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:external-test-2</dc:identifier>
    <dc:title>Livre externe technique</dc:title>
    <dc:language>fr</dc:language>
  </metadata>
  <manifest>
    <item id="c1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="chap2.xhtml" media-type="application/xhtml+xml"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
  </manifest>
  <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
</package>""",
        "OEBPS/nav.xhtml": """<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<body><nav epub:type="toc"><ol>
<li><a href="chap1.xhtml">Un</a></li><li><a href="chap2.xhtml">Deux</a></li>
</ol></nav></body></html>""",
        "OEBPS/chap1.xhtml": f"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<body><h1>Chapitre Un</h1><p>Exemple de code : {poisoned_snippet}</p></body></html>""",
        "OEBPS/chap2.xhtml": f"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<body><h1>Chapitre Deux</h1><p>Même exemple repris ici : {poisoned_snippet}</p></body></html>""",
    }

    epub_path = tmp_path / "external_technical_book.epub"
    with zipfile.ZipFile(epub_path, "w") as zf:
        for name, content in external_dir_content.items():
            zf.writestr(name, content)

    asset_store = AssetStore(tmp_path / "assets")
    document, _imported_metadata, warnings = import_epub(epub_path, asset_store)

    # Sans le correctif, les deux fichiers XHTML extrayaient le même chapter_id "peu-importe"
    # depuis leur texte respectif et fusionnaient en un seul Chapter : toujours 2 chapitres
    # distincts attendu ici.
    assert len(document.chapters) == 2
    assert "peu-importe" not in document.chapters


def test_round_trip_preserves_part_structure(tmp_path):
    epub_path = _generate_reference_epub(tmp_path)
    asset_store = AssetStore(tmp_path / "assets_import")

    document, _imported_metadata, warnings = import_epub(epub_path, asset_store)

    assert len(document.structure.parts()) == 1
    assert document.structure.parts()[0].title == "Partie I"
    assert len(document.structure.parts()[0].chapter_ids) == 2


def test_round_trip_preserves_bold_italic_formatting(tmp_path):
    epub_path = _generate_reference_epub(tmp_path)
    asset_store = AssetStore(tmp_path / "assets_import")

    document, _imported_metadata, warnings = import_epub(epub_path, asset_store)

    all_runs = [r for c in document.chapters.values() for p in c.paragraphs for r in p.runs]
    bold_runs = [r for r in all_runs if r.fmt.bold]
    italic_runs = [r for r in all_runs if r.fmt.italic]
    assert any("gras" in r.text for r in bold_runs)
    assert any("italique" in r.text for r in italic_runs)


def test_round_trip_preserves_alignment_and_quote(tmp_path):
    epub_path = _generate_reference_epub(tmp_path)
    asset_store = AssetStore(tmp_path / "assets_import")

    document, _imported_metadata, warnings = import_epub(epub_path, asset_store)
    all_paragraphs = [p for c in document.chapters.values() for p in c.paragraphs]

    centered = [p for p in all_paragraphs if p.align == ParagraphAlign.CENTER]
    assert any("centré" in p.plain_text() for p in centered)

    quotes = [p for p in all_paragraphs if p.kind == ParagraphKind.QUOTE]
    assert any("mémorable" in p.plain_text() for p in quotes)


def test_import_external_epub_recognizes_inline_style_bold():
    """Formatage encodé en style inline (typique d'un export Word), pas en balise sémantique."""
    import zipfile

    external_dir_content = {
        "mimetype": "application/epub+zip",
        "META-INF/container.xml": """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""",
        "OEBPS/content.opf": """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:external-test</dc:identifier>
    <dc:title>External Book</dc:title>
    <dc:language>fr</dc:language>
  </metadata>
  <manifest>
    <item id="c1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
</package>""",
        "OEBPS/nav.xhtml": """<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<body><nav epub:type="toc"><ol><li><a href="chap1.xhtml">Chapitre externe</a></li></ol></nav></body></html>""",
        "OEBPS/chap1.xhtml": """<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapitre externe</title></head>
<body>
<p>Texte avec un mot <span style="font-weight:bold">important en gras</span> via style inline.</p>
</body></html>""",
    }

    import tempfile
    tmp_dir = Path(tempfile.mkdtemp())
    epub_path = tmp_dir / "external.epub"
    with zipfile.ZipFile(epub_path, "w") as zf:
        for name, content in external_dir_content.items():
            if name == "mimetype":
                zf.writestr(name, content, compress_type=zipfile.ZIP_STORED)
            else:
                zf.writestr(name, content)

    asset_store = AssetStore(tmp_dir / "assets")
    document, _imported_metadata, warnings = import_epub(epub_path, asset_store)

    all_runs = [r for c in document.chapters.values() for p in c.paragraphs for r in p.runs]
    bold_runs = [r for r in all_runs if r.fmt.bold]
    assert any("important en gras" in r.text for r in bold_runs), \
        f"style inline font-weight:bold non reconnu ; runs={[(r.text, r.fmt.bold) for r in all_runs]}"


def test_round_trip_preserves_free_chapter_position_not_degraded_to_anonymous_part(tmp_path):
    """Un chapitre libre (sans partie) généré par Epubeur doit revenir libre au réimport,
    pas dégradé vers une partie anonyme comme c'était le cas avant ce changement."""
    asset_store = AssetStore(tmp_path / "assets_src")
    source = OdtSource(FIXTURE)
    resolver = StyleResolver(source)
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)

    project = ProjectMeta()
    for ch in chapters:
        project.document.chapters[ch.id] = ch

    part = Part.create(title="Partie I")
    part.chapter_ids = [chapters[1].id]
    project.document.structure.items = [chapters[0].id, part]

    out = build_epub(project, asset_store, tmp_path / "free_chapter.epub", metadata=BookMetadata(title="Test"))

    asset_store2 = AssetStore(tmp_path / "assets_import")
    imported_doc, _imported_metadata, warnings = import_epub(out, asset_store2)

    assert len(imported_doc.structure.items) == 2
    assert isinstance(imported_doc.structure.items[0], str)
    assert imported_doc.structure.items[0] == chapters[0].id
    assert isinstance(imported_doc.structure.items[1], Part)
    assert imported_doc.structure.items[1].title == "Partie I"


def test_spine_chapter_absent_from_toc_is_preserved_as_free_chapter(tmp_path):
    """Un EPUB externe dont le spine contient plus de chapitres que sa TOC n'en référence ne
    doit plus perdre silencieusement les chapitres absents de la TOC — ils redeviennent des
    chapitres libres plutôt que de disparaître."""
    import zipfile

    external_dir_content = {
        "mimetype": "application/epub+zip",
        "META-INF/container.xml": """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""",
        "OEBPS/content.opf": """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:external-test-2</dc:identifier>
    <dc:title>External Book</dc:title>
    <dc:language>fr</dc:language>
  </metadata>
  <manifest>
    <item id="c1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="chap2.xhtml" media-type="application/xhtml+xml"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
  </manifest>
  <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
</package>""",
        "OEBPS/nav.xhtml": """<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<body><nav epub:type="toc"><ol><li><a href="chap1.xhtml">Chapitre référencé</a></li></ol></nav></body></html>""",
        "OEBPS/chap1.xhtml": """<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapitre référencé</title></head>
<body><p>Premier chapitre, dans la TOC.</p></body></html>""",
        "OEBPS/chap2.xhtml": """<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapitre absent de la TOC</title></head>
<body><p>Second chapitre, présent dans le spine mais absent de nav.xhtml.</p></body></html>""",
    }

    import tempfile
    tmp_dir = Path(tempfile.mkdtemp())
    epub_path = tmp_dir / "external_spine_gap.epub"
    with zipfile.ZipFile(epub_path, "w") as zf:
        for name, content in external_dir_content.items():
            if name == "mimetype":
                zf.writestr(name, content, compress_type=zipfile.ZIP_STORED)
            else:
                zf.writestr(name, content)

    asset_store = AssetStore(tmp_dir / "assets")
    document, _imported_metadata, warnings = import_epub(epub_path, asset_store)

    # ebooklib régénère intégralement le XHTML à la lecture (via lxml) et perd la balise
    # <title> d'un document sans <!DOCTYPE html> complet — le titre n'est donc pas fiable ici ;
    # on identifie les deux chapitres par leur texte, préservé fidèlement.
    assert len(document.chapters) == 2
    texts = {c.plain_text() for ch in document.chapters.values() for c in ch.paragraphs}
    assert any("absent de nav.xhtml" in t for t in texts), \
        "le chapitre du spine absent de la TOC doit être préservé, pas perdu"

    # TOC plate (pas de hiérarchie) : les deux chapitres deviennent des éléments libres —
    # celui référencé par la TOC ET celui qui n'y était pas, tous deux sans partie.
    assert len(document.structure.free_chapter_ids()) == 2
    assert document.structure.parts() == []


def test_round_trip_does_not_create_phantom_chapters_for_part_title_pages(tmp_path):
    """Régression : une page de garde de partie (générée par part_title_page_to_xhtml)
    était réimportée comme un chapitre normal, orphelin de toute partie — deux parties
    avec page de garde produisaient deux "(chapitre sans titre)" fantômes après réimport."""
    asset_store = AssetStore(tmp_path / "assets_src")
    source = OdtSource(FIXTURE)
    resolver = StyleResolver(source)
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)

    project = ProjectMeta()
    for ch in chapters:
        project.document.chapters[ch.id] = ch  # pas add_chapter() : structure posée explicitement ensuite

    part1 = Part.create(title="Prologues")
    part1.chapter_ids = [chapters[0].id]
    part1.has_title_page = True

    part2 = Part.create(title="Début !")
    part2.chapter_ids = [chapters[1].id]
    part2.has_title_page = True

    project.document.structure.items = [part1, part2]

    out = build_epub(project, asset_store, tmp_path / "two_title_pages.epub", metadata=BookMetadata(title="Test"))

    asset_store2 = AssetStore(tmp_path / "assets_import")
    imported_doc, _imported_metadata, warnings = import_epub(out, asset_store2)

    assert len(imported_doc.chapters) == 2
    assert imported_doc.structure.free_chapter_ids() == []

    imported_titles = {p.title: p.has_title_page for p in imported_doc.structure.parts()}
    assert imported_titles.get("Prologues") is True
    assert imported_titles.get("Début !") is True


def _make_project_with_parts(tmp_path) -> tuple[ProjectMeta, AssetStore]:
    asset_store = AssetStore(tmp_path / "assets_src")
    source = OdtSource(FIXTURE)
    resolver = StyleResolver(source)
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)

    project = ProjectMeta()
    for ch in chapters:
        project.document.chapters[ch.id] = ch
    part = Part.create(title="Partie I")
    part.chapter_ids = [c.id for c in chapters]
    project.document.structure.items.append(part)
    return project, asset_store


def test_import_epub_reads_full_metadata_round_trip(tmp_path):
    """Un EPUB généré par Epubeur avec toutes les métadonnées renseignées doit les reporter
    fidèlement à l'import, pour pré-remplir l'onglet Générer plutôt que de le laisser vide."""
    project, asset_store = _make_project_with_parts(tmp_path)
    metadata = BookMetadata(
        title="Mon Roman", author="Un Auteur", language="fr", isbn="978-2-1234-5680-3",
        description="Un résumé", publication_date="2026-01-01", publisher="Editions X",
        subjects=["fantasy", "aventure"], rights="© 2026", source="Oeuvre source",
        relation="Fait partie du coffret La Trilogie Complète",
        coverage="Paris, 1920-1940",
        accessibility_summary="Texte seul, compatible lecteur d'écran.",
        collection_title="Ma Collection", collection_position="2", reading_direction="rtl",
        contributors=[Contributor(name="Jean Traducteur", role_code="trl", file_as="Traducteur, Jean")],
    )
    out = build_epub(project, asset_store, tmp_path / "full_metadata.epub", metadata=metadata)

    asset_store2 = AssetStore(tmp_path / "assets_import")
    _document, imported_metadata, _warnings = import_epub(out, asset_store2)

    assert imported_metadata.title == "Mon Roman"
    assert imported_metadata.author == "Un Auteur"
    assert imported_metadata.language == "fr"
    assert imported_metadata.isbn == "9782123456803"
    assert imported_metadata.description == "Un résumé"
    assert imported_metadata.publication_date == "2026-01-01"
    assert imported_metadata.publisher == "Editions X"
    assert imported_metadata.subjects == ["fantasy", "aventure"]
    assert imported_metadata.rights == "© 2026"
    assert imported_metadata.source == "Oeuvre source"
    assert imported_metadata.relation == "Fait partie du coffret La Trilogie Complète"
    assert imported_metadata.coverage == "Paris, 1920-1940"
    assert imported_metadata.accessibility_summary == "Texte seul, compatible lecteur d'écran."
    assert imported_metadata.collection_title == "Ma Collection"
    assert imported_metadata.collection_position == "2"
    assert imported_metadata.reading_direction == "rtl"
    assert len(imported_metadata.contributors) == 1
    assert imported_metadata.contributors[0].name == "Jean Traducteur"
    assert imported_metadata.contributors[0].role_code == "trl"
    assert imported_metadata.contributors[0].file_as == "Traducteur, Jean"


def test_import_epub_defaults_metadata_when_absent(tmp_path):
    project, asset_store = _make_project_with_parts(tmp_path)
    out = build_epub(project, asset_store, tmp_path / "minimal.epub", metadata=BookMetadata(title="Titre Minimal"))

    asset_store2 = AssetStore(tmp_path / "assets_import")
    _document, imported_metadata, _warnings = import_epub(out, asset_store2)

    assert imported_metadata.title == "Titre Minimal"
    assert imported_metadata.author == ""
    assert imported_metadata.isbn == ""
    assert imported_metadata.contributors == []
    assert imported_metadata.reading_direction == "ltr"
