import posixpath
import re
import zipfile
from pathlib import Path

import pytest

from epub.builder import EpubBuildError, build_epub, validate_document
from epub.font_obfuscation import deobfuscate_font
from model.assets import AssetRole, AssetStore
from model.book_metadata import BookMetadata, Contributor
from model.document import Chapter, ImageAnchor, ImageDisplaySize, LockedFont, LockedFontFile, Paragraph, Part
from model.project import ProjectMeta
from odt.chapter_detector import split_into_chapters
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver

FIXTURE = Path(__file__).parent / "fixtures" / "sample_simple.odt"
ARIAL = Path("C:/Windows/Fonts/arial.ttf")
TIMES = Path("C:/Windows/Fonts/times.ttf")


def _make_project(tmp_path, with_locked_font: bool = True) -> tuple[ProjectMeta, AssetStore]:
    asset_store = AssetStore(tmp_path / "assets")
    source = OdtSource(FIXTURE)
    resolver = StyleResolver(source)
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)

    project = ProjectMeta()
    for ch in chapters:
        project.document.chapters[ch.id] = ch  # pas add_chapter() : structure posée explicitement ensuite
    part = Part.create(title="Partie I")
    part.chapter_ids = [c.id for c in chapters]
    project.document.structure.items.append(part)

    if with_locked_font:
        project.document.locked_fonts = [
            LockedFont(family="SpecialNarrative", files=[LockedFontFile(file_path=str(ARIAL))])
        ]

    return project, asset_store


def test_validate_document_rejects_empty_title(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    errors = validate_document(project, BookMetadata(title="   "))
    assert any("Titre" in e for e in errors)


def test_validate_document_accepts_nonempty_title(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    errors = validate_document(project, BookMetadata(title="Mon Roman"))
    assert errors == []


def test_validate_document_reports_orphan_cover_asset(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    project.document.cover_asset_id = "id-inexistant"
    errors = validate_document(project, BookMetadata(title="Mon Roman"), asset_store)
    assert any("couverture" in e.lower() for e in errors)


def test_validate_document_reports_orphan_back_cover_asset(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    project.document.back_cover_asset_id = "id-inexistant"
    errors = validate_document(project, BookMetadata(title="Mon Roman"), asset_store)
    assert any("4e de couverture" in e for e in errors)


def test_validate_document_reports_orphan_chapter_image_asset(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    chapter = next(iter(project.document.chapters.values()))
    chapter.paragraphs.append(Paragraph(image=ImageAnchor(asset_id="id-inexistant")))
    errors = validate_document(project, BookMetadata(title="Mon Roman"), asset_store)
    assert any("Image du chapitre" in e for e in errors)


def test_validate_document_reports_missing_physical_file_for_known_asset(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    asset = asset_store.ingest_bytes(b"fake-png-bytes", "cover.png", AssetRole.COVER)
    project.document.cover_asset_id = asset.id
    asset_store.path_for(asset.id).unlink()  # supprime le fichier, garde l'entrée en mémoire
    errors = validate_document(project, BookMetadata(title="Mon Roman"), asset_store)
    assert any("introuvable sur le disque" in e for e in errors)


def test_validate_document_ignores_assets_when_asset_store_not_provided(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    project.document.cover_asset_id = "id-inexistant"
    errors = validate_document(project, BookMetadata(title="Mon Roman"))  # pas d'asset_store
    assert not any("couverture" in e.lower() for e in errors)


def test_validate_document_reports_orphan_chapter_reference_in_part(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    part = project.document.structure.parts()[0]
    part.chapter_ids.append("chapitre-supprime-id")
    errors = validate_document(project, BookMetadata(title="Mon Roman"))
    assert any("Partie I" in e for e in errors)


def test_validate_document_reports_orphan_free_chapter_reference(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    project.document.structure.items.append("chapitre-supprime-id")
    errors = validate_document(project, BookMetadata(title="Mon Roman"))
    assert any("chapitre(s) libre(s)" in e for e in errors)


def test_validate_document_rejects_empty_book(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    project.document.structure.items = []
    errors = validate_document(project, BookMetadata(title="Mon Roman"))
    assert any("Aucun chapitre valide" in e for e in errors)


def test_build_epub_raises_cleanly_on_orphan_cover_asset(tmp_path):
    """Non-régression : ce cas plantait avant avec un AttributeError brut."""
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    project.document.cover_asset_id = "id-inexistant"
    with pytest.raises(EpubBuildError):
        build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))


def test_find_unreferenced_chapters_warns_without_blocking_build(tmp_path):
    from epub.builder import find_unreferenced_chapters
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    phantom = Chapter.create(title="Chapitre Oublié")
    project.document.chapters[phantom.id] = phantom  # volontairement absent de structure.items

    errors = validate_document(project, BookMetadata(title="Mon Roman"))
    assert errors == []  # pas bloquant

    warnings = find_unreferenced_chapters(project)
    assert any("Chapitre Oublié" in w for w in warnings)

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))
    assert out.exists()


def test_build_succeeds_with_free_chapters_and_no_parts(tmp_path):
    """Un chapitre "libre" (sans partie) n'est plus une erreur de validation ni un blocage
    de génération — c'est un état normal et voulu."""
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    project.document.structure.items = [c for c in project.document.chapters]

    errors = validate_document(project)
    assert errors == []

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert any(n.endswith("chapter_0.xhtml") for n in names)
        assert any(n.endswith("chapter_1.xhtml") for n in names)


@pytest.mark.skipif(not ARIAL.exists(), reason="Police système de test introuvable")
def test_build_produces_valid_zip_with_single_font_entry(tmp_path):
    project, asset_store = _make_project(tmp_path)
    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        font_entries = [n for n in names if n.endswith("arial.ttf")]
        assert len(font_entries) == 1, f"expected exactly one font entry, got {font_entries}"

        assert "META-INF/encryption.xml" in names
        enc = zf.read("META-INF/encryption.xml").decode()
        assert font_entries[0] in enc

        stored = zf.read(font_entries[0])
        original = ARIAL.read_bytes()
        assert stored != original  # obfusqué

        assert "text/chapter_0.xhtml" in [n.split("/", 1)[-1] if n.startswith("EPUB/") else n for n in names] or \
               any(n.endswith("chapter_0.xhtml") for n in names)


@pytest.mark.skipif(not ARIAL.exists(), reason="Police système de test introuvable")
def test_toc_reflects_parts_and_chapters(tmp_path):
    project, asset_store = _make_project(tmp_path)
    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        nav = zf.read("EPUB/nav.xhtml").decode()
        assert "Partie I" in nav
        assert "Chapitre un" in nav
        assert "Chapitre deux" in nav


def test_toc_includes_image_only_chapter_by_its_filename(tmp_path):
    """Un chapitre "image seule" (créé via controller.add_image_as_chapter, title_visible=False
    pour ne pas afficher le nom de fichier en <h1> dans le texte) doit quand même apparaître
    dans le sommaire — title_visible ne concerne que l'affichage dans le corps du chapitre,
    jamais son entrée dans la table des matières (epub/toc.py::build_toc, branche else)."""
    asset_store = AssetStore(tmp_path / "assets")
    asset = asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", "illustration.jpg", AssetRole.CHAPTER_POV)
    project = ProjectMeta()
    chapter = Chapter.create(title="illustration")
    chapter.title_visible = False
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id))]
    project.document.add_chapter(chapter)

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        nav = zf.read("EPUB/nav.xhtml").decode()
        assert "illustration" in nav


def test_chapter_css_link_resolves_to_an_existing_zip_entry(tmp_path):
    """Régression : ebooklib.EpubHtml.add_item(css_item) régénère le <link> à partir du
    file_name brut du CSS, sans le recalculer relativement au dossier du chapitre (text/) —
    le lien produit pointait vers un chemin inexistant et le CSS (donc la police figée) ne se
    chargeait jamais, ni dans l'aperçu ni dans un vrai lecteur EPUB."""
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        xhtml = zf.read("EPUB/text/chapter_0.xhtml").decode()

        import re
        match = re.search(r'<link[^>]+href="([^"]+)"', xhtml)
        assert match is not None, "aucun <link> stylesheet trouvé dans le chapitre généré"

        css_href = match.group(1)
        resolved = posixpath.normpath(posixpath.join("EPUB/text", css_href))
        assert resolved in names, f"le <link> pointe vers {resolved!r}, absent du zip : {sorted(names)}"


def test_chapter_image_src_includes_extension_and_resolves(tmp_path):
    """Régression : la balise <img> référençait l'asset_id (hash) sans son extension,
    donc ne correspondait jamais au vrai fichier écrit dans le zip (images/<hash>.<ext>)."""
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        xhtml = zf.read("EPUB/text/chapter_0.xhtml").decode()

        import re
        match = re.search(r'<img[^>]+src="([^"]+)"', xhtml)
        assert match is not None, "aucune balise <img> trouvée alors qu'une image de chapitre était attendue"

        img_src = match.group(1)
        resolved = posixpath.normpath(posixpath.join("EPUB/text", img_src))
        assert resolved in names, f"l'<img src> pointe vers {resolved!r}, absent du zip : {sorted(names)}"


def test_part_title_page_appears_before_chapters_in_toc(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    project.document.structure.parts()[0].has_title_page = True
    project.document.structure.parts()[0].title = "Prologues"

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        title_page_files = [n for n in names if "part_title" in n]
        assert len(title_page_files) == 1

        nav = zf.read("EPUB/nav.xhtml").decode()
        title_page_pos = nav.find(title_page_files[0].split("/", 1)[-1])
        # la page de garde consomme le premier order_counter : le premier vrai chapitre
        # s'appelle donc chapter_1.xhtml (pas chapter_0.xhtml) dans ce scénario
        chapter_pos = nav.find("chapter_1.xhtml")
        assert title_page_pos != -1
        assert chapter_pos != -1
        assert title_page_pos < chapter_pos, "la page de garde doit précéder les chapitres dans la TOC"


def test_part_title_page_content_is_centered_and_titled(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    project.document.structure.parts()[0].has_title_page = True
    project.document.structure.parts()[0].title = "Prologues"

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        title_page_files = [n for n in zf.namelist() if "part_title" in n]
        xhtml = zf.read(title_page_files[0]).decode()
        assert "Prologues" in xhtml
        assert 'class="epubeur-part-title-page"' in xhtml

        css = zf.read("EPUB/style/epubeur.css").decode()
        assert "epubeur-part-title-page" in css
        assert "justify-content: center" in css


def test_no_title_page_when_has_title_page_false(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    project.document.structure.parts()[0].has_title_page = False

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        title_page_files = [n for n in zf.namelist() if "part_title" in n]
        assert title_page_files == []


@pytest.mark.skipif(not (ARIAL.exists() and TIMES.exists()), reason="Polices système de test introuvables")
def test_build_supports_two_simultaneous_locked_fonts(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    project.document.locked_fonts = [
        LockedFont(family="SpecialNarrative", files=[LockedFontFile(file_path=str(ARIAL))]),
        LockedFont(family="AutrePoliceFigee", files=[LockedFontFile(file_path=str(TIMES))]),
    ]

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        font_entries = [n for n in names if n.endswith((".ttf", ".otf")) and "fonts/" in n]
        assert len(font_entries) == 2, f"expected 2 font entries, got {font_entries}"

        enc = zf.read("META-INF/encryption.xml").decode()
        for entry in font_entries:
            assert entry in enc, f"{entry} absent de encryption.xml"

        css = zf.read("EPUB/style/epubeur.css").decode()
        assert css.count("@font-face") == 2
        assert "SpecialNarrative" in css
        assert "AutrePoliceFigee" in css

        # Les deux fichiers de police sont bien obfusqués, distincts l'un de l'autre.
        stored_arial = zf.read([n for n in font_entries if "arial" in n.lower()][0])
        stored_times = zf.read([n for n in font_entries if "times" in n.lower()][0])
        assert stored_arial != ARIAL.read_bytes()
        assert stored_times != TIMES.read_bytes()
        assert stored_arial != stored_times


def _add_image_paragraph(project: ProjectMeta, asset_store: AssetStore, image_bytes: bytes) -> str:
    """Ajoute un paragraphe-image au premier chapitre du projet, retourne l'asset_id créé."""
    from model.document import Paragraph

    asset = asset_store.ingest_bytes(image_bytes, original_filename="img.png", role=AssetRole.CHAPTER_POV)
    first_chapter = next(iter(project.document.chapters.values()))
    first_chapter.paragraphs.append(Paragraph(image=ImageAnchor(asset_id=asset.id)))
    return asset.id


def test_image_at_default_size_emits_no_dedicated_css_rule(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    asset_id = _add_image_paragraph(project, asset_store, b"fake-png-bytes-1")

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))
    with zipfile.ZipFile(out) as zf:
        css = zf.read("EPUB/style/epubeur.css").decode()
        assert f'img[data-epubeur-image="{asset_id}"]' not in css


def test_image_display_size_emits_targeted_css_rule(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    asset_id = _add_image_paragraph(project, asset_store, b"fake-png-bytes-2")
    project.document.image_display_sizes[asset_id] = ImageDisplaySize.SMALL

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))
    with zipfile.ZipFile(out) as zf:
        css = zf.read("EPUB/style/epubeur.css").decode()
        assert f'img[data-epubeur-image="{asset_id}"]' in css
        assert "max-width: 25%;" in css


def test_image_display_size_does_not_leak_to_other_asset(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    asset_id_a = _add_image_paragraph(project, asset_store, b"fake-png-bytes-a")
    asset_id_b = _add_image_paragraph(project, asset_store, b"fake-png-bytes-b")
    project.document.image_display_sizes[asset_id_a] = ImageDisplaySize.SMALL
    project.document.image_display_sizes[asset_id_b] = ImageDisplaySize.LARGE

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))
    with zipfile.ZipFile(out) as zf:
        css = zf.read("EPUB/style/epubeur.css").decode()
        rule_a = css[css.index(f'img[data-epubeur-image="{asset_id_a}"]'):]
        rule_a = rule_a[:rule_a.index("}")]
        assert "max-width: 25%;" in rule_a

        rule_b = css[css.index(f'img[data-epubeur-image="{asset_id_b}"]'):]
        rule_b = rule_b[:rule_b.index("}")]
        assert "max-width: 75%;" in rule_b


def test_unused_asset_size_setting_emits_no_css_rule(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    unused_asset = asset_store.ingest_bytes(b"never-referenced", original_filename="orphan.png",
                                             role=AssetRole.CHAPTER_POV)
    project.document.image_display_sizes[unused_asset.id] = ImageDisplaySize.SMALL

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))
    with zipfile.ZipFile(out) as zf:
        css = zf.read("EPUB/style/epubeur.css").decode()
        assert f'img[data-epubeur-image="{unused_asset.id}"]' not in css


@pytest.mark.skipif(not (ARIAL.exists() and TIMES.exists()), reason="Polices système de test introuvables")
def test_build_disambiguates_same_filename_from_different_directories(tmp_path):
    """Deux polices figées peuvent porter le même nom de fichier sur disque si elles viennent
    de dossiers différents (ex : deux polices personnalisées appelées toutes deux 'font.ttf') —
    le builder doit leur attribuer des hrefs zip distincts plutôt que d'écraser l'une par
    l'autre."""
    dir_a = tmp_path / "dir_a"
    dir_b = tmp_path / "dir_b"
    dir_a.mkdir()
    dir_b.mkdir()
    font_a_path = dir_a / "font.ttf"
    font_b_path = dir_b / "font.ttf"
    font_a_path.write_bytes(ARIAL.read_bytes())
    font_b_path.write_bytes(TIMES.read_bytes())

    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    project.document.locked_fonts = [
        LockedFont(family="SpecialNarrative", files=[LockedFontFile(file_path=str(font_a_path))]),
        LockedFont(family="AutrePoliceFigee", files=[LockedFontFile(file_path=str(font_b_path))]),
    ]

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        font_entries = [n for n in names if n.endswith(".ttf") and "fonts/" in n]
        assert len(font_entries) == 2, f"expected 2 distinct font entries, got {font_entries}"

        enc = zf.read("META-INF/encryption.xml").decode()
        for entry in font_entries:
            assert entry in enc, f"{entry} absent de encryption.xml"

        stored_values = [zf.read(n) for n in font_entries]
        assert stored_values[0] != stored_values[1]


def test_cover_image_appears_exactly_once_in_zip(tmp_path):
    """Régression : la couverture était écrite deux fois dans le zip — une fois via l'ajout
    d'image normal (images/<hash>.<ext>), une fois via ebooklib.set_cover avec un chemin cassé
    (juste le nom de fichier, sans le dossier images/) qui la plaçait en doublon à la racine
    du dossier EPUB/."""
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    cover_bytes = b"\xff\xd8\xff\xe0fake-jpeg-content-for-cover-test"
    cover_asset = asset_store.ingest_bytes(cover_bytes, original_filename="cover.jpg", role=AssetRole.COVER)
    project.document.cover_asset_id = cover_asset.id

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        cover_image_entries = [n for n in names if n == "EPUB/images/cover.jpg"]
        assert len(cover_image_entries) == 1, f"expected exactly one cover image entry, got {cover_image_entries}"
        assert cover_image_entries[0] == "EPUB/images/cover.jpg"

        cover_html = zf.read("EPUB/cover.xhtml").decode()
        import re
        match = re.search(r'<img[^>]+src="([^"]+)"', cover_html)
        assert match is not None, "aucune balise <img> trouvée dans cover.xhtml"
        resolved = posixpath.normpath(posixpath.join("EPUB", match.group(1)))
        assert resolved in names, f"cover.xhtml pointe vers {resolved!r}, absent du zip"
        assert resolved == cover_image_entries[0]


def test_back_cover_image_appears_as_a_page_in_the_spine(tmp_path):
    """Régression : back_cover_asset_id n'était ajouté qu'en tant qu'image générique
    (images/<hash>.<ext>), sans jamais être référencée par un document XHTML — orpheline dans
    le zip, invisible pour un vrai lecteur EPUB. Doit désormais apparaître comme une page dans
    le spine, avec une balise <img> qui pointe vers une entrée existante du zip."""
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    back_cover_bytes = b"\xff\xd8\xff\xe0fake-jpeg-content-for-back-cover-test"
    back_cover_asset = asset_store.ingest_bytes(back_cover_bytes, original_filename="back_cover.jpg",
                                                 role=AssetRole.BACK_COVER)
    project.document.back_cover_asset_id = back_cover_asset.id

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "EPUB/text/back_cover.xhtml" in names

        image_entries = [n for n in names if n == "EPUB/images/back_cover.jpg"]
        assert len(image_entries) == 1

        back_cover_html = zf.read("EPUB/text/back_cover.xhtml").decode()
        import re
        match = re.search(r'<img[^>]+src="([^"]+)"', back_cover_html)
        assert match is not None, "aucune balise <img> trouvée dans back_cover.xhtml"
        resolved = posixpath.normpath(posixpath.join("EPUB/text", match.group(1)))
        assert resolved in names, f"back_cover.xhtml pointe vers {resolved!r}, absent du zip"
        assert resolved == image_entries[0]

        opf_candidates = [n for n in names if n.endswith("content.opf")]
        opf = zf.read(opf_candidates[0]).decode()
        assert "back_cover.xhtml" in opf  # bien référencée dans le spine/manifest OPF


def test_chapter_image_uses_readable_filename_in_epub(tmp_path):
    project = ProjectMeta()
    asset_store = AssetStore(tmp_path / "assets")
    asset = asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", "Perso 1.jpg", AssetRole.CHAPTER_POV)
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id))]
    project.document.add_chapter(chapter)

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "EPUB/images/Perso 1.jpg" in names

        text_entries = [n for n in names if n.startswith("EPUB/text/") and n.endswith(".xhtml")]
        chapter_html = "".join(zf.read(n).decode() for n in text_entries)
        assert 'src="../images/Perso 1.jpg"' in chapter_html


def test_two_chapter_images_with_same_original_filename_get_suffixed(tmp_path):
    project = ProjectMeta()
    asset_store = AssetStore(tmp_path / "assets")
    asset1 = asset_store.ingest_bytes(b"\xff\xd8\xff\xe0aaaa", "image.png", AssetRole.CHAPTER_POV)
    asset2 = asset_store.ingest_bytes(b"\xff\xd8\xff\xe0bbbb", "image.png", AssetRole.CHAPTER_POV)
    chapter1 = Chapter.create(title="Chapitre un")
    chapter1.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset1.id))]
    chapter2 = Chapter.create(title="Chapitre deux")
    chapter2.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset2.id))]
    project.document.add_chapter(chapter1)
    project.document.add_chapter(chapter2)

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "EPUB/images/image.png" in names
        assert "EPUB/images/image-2.png" in names


def test_cover_always_named_cover_regardless_of_original_filename(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    cover_bytes = b"\xff\xd8\xff\xe0fake-jpeg-content"
    cover_asset = asset_store.ingest_bytes(cover_bytes, original_filename="Mon Illustration De Couv.jpg",
                                            role=AssetRole.COVER)
    project.document.cover_asset_id = cover_asset.id

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "EPUB/images/cover.jpg" in names
        assert not any("Illustration" in n for n in names)


def test_back_cover_always_named_back_cover_regardless_of_original_filename(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    back_cover_bytes = b"\xff\xd8\xff\xe0fake-jpeg-content"
    back_cover_asset = asset_store.ingest_bytes(back_cover_bytes, original_filename="Photo 4e de couv.jpg",
                                                 role=AssetRole.BACK_COVER)
    project.document.back_cover_asset_id = back_cover_asset.id

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "EPUB/images/back_cover.jpg" in names
        assert not any("Photo" in n for n in names)


def test_validate_document_reports_missing_file_per_locked_font(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    project.document.locked_fonts = [
        LockedFont(family="PoliceValide", files=[LockedFontFile(file_path=str(ARIAL))]),
        LockedFont(family="PoliceSansFichier", files=[]),
        LockedFont(family="PoliceFichierIntrouvable", files=[LockedFontFile(file_path="C:/nonexistent/font.ttf")]),
    ]
    errors = validate_document(project)
    assert any("PoliceSansFichier" in e for e in errors)
    assert any("PoliceFichierIntrouvable" in e for e in errors)
    assert not any("PoliceValide" in e for e in errors)


def test_validate_document_reports_invalid_isbn(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    errors = validate_document(project, BookMetadata(title="Mon Roman", isbn="978-2-1234-5680-4"))
    assert any("ISBN" in e for e in errors)


def test_validate_document_accepts_valid_isbn(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    errors = validate_document(project, BookMetadata(title="Mon Roman", isbn="978-2-1234-5680-3"))
    assert errors == []


def test_validate_document_accepts_empty_isbn(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    errors = validate_document(project, BookMetadata(title="Mon Roman", isbn=""))
    assert errors == []


def test_validate_document_reports_invalid_language_code(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    errors = validate_document(project, BookMetadata(title="Mon Roman", language="francais"))
    assert any("langue" in e.lower() for e in errors)


def test_validate_document_reports_unknown_two_letter_language_code(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    errors = validate_document(project, BookMetadata(title="Mon Roman", language="zz"))
    assert any("langue" in e.lower() for e in errors)


def test_validate_document_accepts_simple_language_code(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    errors = validate_document(project, BookMetadata(title="Mon Roman", language="fr"))
    assert errors == []


def test_validate_document_accepts_language_code_with_region(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    errors = validate_document(project, BookMetadata(title="Mon Roman", language="en-US"))
    assert errors == []


def test_validate_document_accepts_empty_language_falls_back_to_default(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    errors = validate_document(project, BookMetadata(title="Mon Roman", language=""))
    assert errors == []


def test_build_epub_raises_on_invalid_language_code(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    with pytest.raises(EpubBuildError):
        build_epub(project, asset_store, tmp_path / "out.epub",
                    metadata=BookMetadata(title="Mon Roman", language="francais"))


def test_build_epub_raises_on_invalid_isbn(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    with pytest.raises(EpubBuildError):
        build_epub(project, asset_store, tmp_path / "out.epub",
                    metadata=BookMetadata(title="Mon Roman", isbn="978-2-1234-5680-4"))


def test_build_epub_uses_isbn_as_identifier_when_provided(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    out = build_epub(project, asset_store, tmp_path / "out.epub",
                      metadata=BookMetadata(title="Mon Roman", isbn="978-2-1234-5680-3"))
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        opf_candidates = [n for n in names if n.endswith("content.opf")]
        opf = zf.read(opf_candidates[0]).decode()
        assert "urn:isbn:9782123456803" in opf
        assert "urn:uuid:" not in opf
        assert '<dc:identifier id="id" opf:scheme="ISBN">urn:isbn:9782123456803</dc:identifier>' in opf


def test_build_epub_falls_back_to_uuid_without_isbn(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        opf_candidates = [n for n in names if n.endswith("content.opf")]
        opf = zf.read(opf_candidates[0]).decode()
        assert "urn:uuid:" in opf
        assert "urn:isbn:" not in opf
        assert 'opf:scheme="ISBN"' not in opf  # jamais sur un identifiant UUID de secours


@pytest.mark.skipif(not (ARIAL.exists() and Path("C:/Windows/Fonts/arialbd.ttf").exists()),
                     reason="Polices système de test introuvables")
def test_build_emits_one_font_face_per_file_with_correct_weight_style(tmp_path):
    arial_bold = Path("C:/Windows/Fonts/arialbd.ttf")
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    project.document.locked_fonts = [
        LockedFont(family="JMHTypewriter", files=[
            LockedFontFile(file_path=str(ARIAL), weight=400, italic=False),
            LockedFontFile(file_path=str(arial_bold), weight=700, italic=False),
        ])
    ]

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        font_entries = [n for n in names if n.endswith((".ttf", ".otf")) and "fonts/" in n]
        assert len(font_entries) == 2, f"expected 2 font entries, got {font_entries}"

        css = zf.read("EPUB/style/epubeur.css").decode()
        assert css.count("@font-face") == 2
        assert css.count("JMHTypewriter") >= 2  # au moins une fois par @font-face + la règle .class
        assert "font-weight: 700" in css
        assert "font-weight: 400" in css
        # une seule règle .epubeur-locked-font-* pour cette famille, pas une par fichier
        assert css.count("!important") == 1


@pytest.mark.skipif(not (ARIAL.exists() and Path("C:/Windows/Fonts/arialbd.ttf").exists()),
                     reason="Polices système de test introuvables")
def test_build_disambiguates_uid_for_multiple_files_same_family(tmp_path):
    """Régression potentielle : deux EpubItem avec le même uid produiraient un manifest OPF
    invalide (deux <item id="..."> identiques) — vérifie que build_epub réussit sans exception
    et produit bien 2 entrées zip distinctes pour 2 fichiers d'une même famille."""
    arial_bold = Path("C:/Windows/Fonts/arialbd.ttf")
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    project.document.locked_fonts = [
        LockedFont(family="JMHTypewriter", files=[
            LockedFontFile(file_path=str(ARIAL), weight=400, italic=False),
            LockedFontFile(file_path=str(arial_bold), weight=700, italic=False),
        ])
    ]

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        font_entries = [n for n in names if n.startswith("EPUB/fonts/")]
        assert len(font_entries) == 2
        assert len(set(font_entries)) == 2


def test_css_prevents_empty_paragraph_margin_collapsing(tmp_path):
    """Plusieurs <p></p> vides consécutifs (Entrée simple répétée dans Writer) verraient leurs
    marges fusionner (margin collapsing CSS standard) sans cette règle, les rendant quasi
    invisibles dans la plupart des lecteurs (Calibre, Chromium) malgré leur présence réelle
    dans le fichier."""
    project, asset_store = _make_project(tmp_path, with_locked_font=False)

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))
    with zipfile.ZipFile(out) as zf:
        css = zf.read("EPUB/style/epubeur.css").decode()
        assert "p:empty" in css
        assert "min-height" in css


def test_nav_has_toc_and_bodymatter_landmarks_without_cover(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))
    with zipfile.ZipFile(out) as zf:
        nav = zf.read("EPUB/nav.xhtml").decode()
        assert 'epub:type="landmarks"' in nav
        assert 'epub:type="toc" href="nav.xhtml"' in nav
        assert 'epub:type="bodymatter"' in nav
        assert 'epub:type="cover"' not in nav


def test_nav_has_cover_landmark_when_cover_defined(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    cover_asset = asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fakejpeg", "cover.jpg", AssetRole.COVER)
    project.document.cover_asset_id = cover_asset.id

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))
    with zipfile.ZipFile(out) as zf:
        nav = zf.read("EPUB/nav.xhtml").decode()
        assert 'epub:type="cover" href="cover.xhtml"' in nav


def test_bodymatter_landmark_points_to_part_title_page_when_present(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    project.document.structure.parts()[0].has_title_page = True

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))
    with zipfile.ZipFile(out) as zf:
        nav = zf.read("EPUB/nav.xhtml").decode()
        landmarks_section = nav.split('epub:type="landmarks"')[1]
        assert 'epub:type="bodymatter" href="text/part_title_0.xhtml"' in landmarks_section


def test_opf_declares_accessibility_metadata(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))
    with zipfile.ZipFile(out) as zf:
        opf_name = [n for n in zf.namelist() if n.endswith("content.opf")][0]
        opf = zf.read(opf_name).decode()
        assert 'property="schema:accessMode">textual</meta>' in opf
        assert 'property="schema:accessModeSufficient">textual</meta>' in opf
        assert 'property="schema:accessibilityFeature">structuralNavigation</meta>' in opf
        assert 'property="schema:accessibilityHazard">none</meta>' in opf


def test_opf_declares_contributors_with_typed_roles(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    metadata = BookMetadata(
        title="Mon Roman",
        contributors=[
            Contributor(name="Jean Traducteur", role_code="trl"),
            Contributor(name="Marie Illustratrice", role_code="ill"),
        ],
    )

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=metadata)
    with zipfile.ZipFile(out) as zf:
        opf_name = [n for n in zf.namelist() if n.endswith("content.opf")][0]
        opf = zf.read(opf_name).decode()

    assert '<dc:contributor id="contributor-0">Jean Traducteur</dc:contributor>' in opf
    assert '<dc:contributor id="contributor-1">Marie Illustratrice</dc:contributor>' in opf
    assert 'refines="#contributor-0" property="role" scheme="marc:relators">trl</meta>' in opf
    assert 'refines="#contributor-1" property="role" scheme="marc:relators">ill</meta>' in opf


def test_opf_declares_contributor_file_as(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    metadata = BookMetadata(
        title="Mon Roman",
        contributors=[Contributor(name="Jean Traducteur", role_code="trl", file_as="Traducteur, Jean")],
    )

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=metadata)
    with zipfile.ZipFile(out) as zf:
        opf_name = [n for n in zf.namelist() if n.endswith("content.opf")][0]
        opf = zf.read(opf_name).decode()

    assert 'refines="#contributor-0" property="file-as">Traducteur, Jean</meta>' in opf


def test_opf_contributor_without_file_as_has_no_file_as_metadata(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    metadata = BookMetadata(title="Mon Roman", contributors=[Contributor(name="Sans nom de tri", role_code="trl")])

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=metadata)
    with zipfile.ZipFile(out) as zf:
        opf_name = [n for n in zf.namelist() if n.endswith("content.opf")][0]
        opf = zf.read(opf_name).decode()

    assert 'property="file-as"' not in opf


def test_opf_declares_relation(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    metadata = BookMetadata(title="Mon Roman", relation="Fait partie du coffret La Trilogie Complète")

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=metadata)
    with zipfile.ZipFile(out) as zf:
        opf_name = [n for n in zf.namelist() if n.endswith("content.opf")][0]
        opf = zf.read(opf_name).decode()

    assert "<dc:relation>Fait partie du coffret La Trilogie Complète</dc:relation>" in opf


def test_opf_omits_relation_when_absent(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    metadata = BookMetadata(title="Mon Roman")

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=metadata)
    with zipfile.ZipFile(out) as zf:
        opf_name = [n for n in zf.namelist() if n.endswith("content.opf")][0]
        opf = zf.read(opf_name).decode()

    assert "dc:relation" not in opf


def test_opf_declares_coverage(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    metadata = BookMetadata(title="Mon Roman", coverage="Paris, 1920-1940")

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=metadata)
    with zipfile.ZipFile(out) as zf:
        opf_name = [n for n in zf.namelist() if n.endswith("content.opf")][0]
        opf = zf.read(opf_name).decode()

    assert "<dc:coverage>Paris, 1920-1940</dc:coverage>" in opf


def test_opf_omits_coverage_when_absent(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    metadata = BookMetadata(title="Mon Roman")

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=metadata)
    with zipfile.ZipFile(out) as zf:
        opf_name = [n for n in zf.namelist() if n.endswith("content.opf")][0]
        opf = zf.read(opf_name).decode()

    assert "dc:coverage" not in opf


def test_opf_declares_accessibility_summary(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    metadata = BookMetadata(
        title="Mon Roman",
        accessibility_summary="Ce livre contient uniquement du texte structuré, compatible "
                               "avec les lecteurs d'écran.",
    )

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=metadata)
    with zipfile.ZipFile(out) as zf:
        opf_name = [n for n in zf.namelist() if n.endswith("content.opf")][0]
        opf = zf.read(opf_name).decode()

    assert ('<meta property="schema:accessibilitySummary">Ce livre contient uniquement du texte '
            'structuré, compatible avec les lecteurs d\'écran.</meta>') in opf


def test_opf_omits_accessibility_summary_when_absent(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    metadata = BookMetadata(title="Mon Roman")

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=metadata)
    with zipfile.ZipFile(out) as zf:
        opf_name = [n for n in zf.namelist() if n.endswith("content.opf")][0]
        opf = zf.read(opf_name).decode()

    assert "accessibilitySummary" not in opf


def test_opf_contributor_without_role_has_no_role_metadata(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    metadata = BookMetadata(title="Mon Roman", contributors=[Contributor(name="Sans rôle précisé", role_code="")])

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=metadata)
    with zipfile.ZipFile(out) as zf:
        opf_name = [n for n in zf.namelist() if n.endswith("content.opf")][0]
        opf = zf.read(opf_name).decode()

    assert '<dc:contributor id="contributor-0">Sans rôle précisé</dc:contributor>' in opf
    assert 'property="role"' not in opf


def test_opf_skips_contributor_with_empty_name(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    metadata = BookMetadata(title="Mon Roman", contributors=[Contributor(name="", role_code="trl")])

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=metadata)
    with zipfile.ZipFile(out) as zf:
        opf_name = [n for n in zf.namelist() if n.endswith("content.opf")][0]
        opf = zf.read(opf_name).decode()

    assert "dc:contributor" not in opf


def test_opf_spine_defaults_to_ltr(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))
    with zipfile.ZipFile(out) as zf:
        opf_name = [n for n in zf.namelist() if n.endswith("content.opf")][0]
        opf = zf.read(opf_name).decode()

    assert 'page-progression-direction="ltr"' in opf


def test_opf_spine_declares_rtl_when_requested(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    metadata = BookMetadata(title="Mon Roman", reading_direction="rtl")

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=metadata)
    with zipfile.ZipFile(out) as zf:
        opf_name = [n for n in zf.namelist() if n.endswith("content.opf")][0]
        opf = zf.read(opf_name).decode()
        chapter_name = [n for n in zf.namelist() if "chapter_0" in n][0]
        chapter_xhtml = zf.read(chapter_name).decode()

    assert 'page-progression-direction="rtl"' in opf
    assert 'dir="rtl"' in chapter_xhtml


def test_validate_document_rejects_invalid_reading_direction(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    metadata = BookMetadata(title="Mon Roman", reading_direction="sideways")

    errors = validate_document(project, metadata)

    assert any("Sens de lecture" in e for e in errors)


def test_build_epub_raises_on_invalid_reading_direction(tmp_path):
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    metadata = BookMetadata(title="Mon Roman", reading_direction="sideways")

    with pytest.raises(EpubBuildError):
        build_epub(project, asset_store, tmp_path / "out.epub", metadata=metadata)


def test_manifest_items_all_exist_as_zip_entries(tmp_path):
    """Non-régression : chaque <item href="..."> déclaré dans le manifest OPF doit correspondre
    à une entrée réellement présente dans le zip — garanti par construction tant que build_epub
    ajoute uniquement des items via book.add_item() avec leur contenu fourni au même moment,
    mais vérifié explicitement pour détecter toute régression future de ce invariant."""
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    cover = asset_store.ingest_bytes(b"\xff\xd8\xff\xe0fake-jpeg", "cover.jpg", AssetRole.COVER)
    project.document.cover_asset_id = cover.id

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        opf_name = [n for n in names if n.endswith("content.opf")][0]
        opf = zf.read(opf_name).decode()
        opf_dir = posixpath.dirname(opf_name)

        hrefs = re.findall(r'<item\b[^>]*\bhref="([^"]+)"', opf)
        assert hrefs, "aucun <item href=...> trouvé dans le manifest OPF"
        for href in hrefs:
            resolved = posixpath.normpath(posixpath.join(opf_dir, href))
            assert resolved in names, f"item manifeste « {href} » absent du zip (résolu: {resolved})"


def test_spine_itemrefs_all_declared_in_manifest(tmp_path):
    """Non-régression : chaque <itemref idref="..."> du spine OPF doit correspondre à un
    <item id="..."> effectivement déclaré dans le manifest — même invariant garanti par
    construction (spine alimenté uniquement à partir d'items déjà ajoutés au manifest),
    vérifié explicitement contre toute régression future."""
    project, asset_store = _make_project(tmp_path, with_locked_font=False)

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        opf_name = [n for n in zf.namelist() if n.endswith("content.opf")][0]
        opf = zf.read(opf_name).decode()

    manifest_ids = set(re.findall(r'<item\b[^>]*\bid="([^"]+)"', opf))
    spine_idrefs = re.findall(r'<itemref\b[^>]*\bidref="([^"]+)"', opf)
    assert spine_idrefs, "aucun <itemref idref=...> trouvé dans le spine OPF"
    for idref in spine_idrefs:
        assert idref in manifest_ids, f"itemref « {idref} » du spine absent du manifest"


def test_manifest_item_ids_are_unique(tmp_path):
    """Non-régression : deux <item id="..."> identiques dans le manifest OPF produiraient un
    EPUB invalide. Vérifie l'unicité des uid ebooklib sur un projet avec couverture, 4e de
    couverture, images de chapitre et polices figées combinées — le scénario le plus riche en
    items simultanés que build_epub puisse produire."""
    project, asset_store = _make_project(tmp_path, with_locked_font=False)
    cover = asset_store.ingest_bytes(b"\xff\xd8\xff\xe0cover", "cover.jpg", AssetRole.COVER)
    back_cover = asset_store.ingest_bytes(b"\xff\xd8\xff\xe0back", "back.jpg", AssetRole.BACK_COVER)
    project.document.cover_asset_id = cover.id
    project.document.back_cover_asset_id = back_cover.id

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Mon Roman"))

    with zipfile.ZipFile(out) as zf:
        opf_name = [n for n in zf.namelist() if n.endswith("content.opf")][0]
        opf = zf.read(opf_name).decode()

    manifest_ids = re.findall(r'<item\b[^>]*\bid="([^"]+)"', opf)
    assert len(manifest_ids) == len(set(manifest_ids)), (
        f"id de manifest dupliqués : {[i for i in manifest_ids if manifest_ids.count(i) > 1]}"
    )
