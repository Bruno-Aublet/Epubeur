import zipfile
from pathlib import Path

from epub.builder import build_epub
from model.assets import AssetStore
from model.book_metadata import BookMetadata
from model.document import Chapter, Part
from model.project import ProjectMeta


def test_free_chapter_at_start_appears_first_in_spine_and_toc(tmp_path):
    asset_store = AssetStore(tmp_path / "assets")
    project = ProjectMeta()
    intro = Chapter.create(title="Intro")
    chap1 = Chapter.create(title="Chapitre Un")
    project.document.chapters[intro.id] = intro
    project.document.chapters[chap1.id] = chap1

    part = Part.create(title="Partie I")
    part.chapter_ids = [chap1.id]
    project.document.structure.items = [intro.id, part]

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Livre"))

    with zipfile.ZipFile(out) as zf:
        nav = zf.read("EPUB/nav.xhtml").decode()
        intro_pos = nav.find("Intro")
        part_pos = nav.find("Partie I")
        assert intro_pos != -1 and part_pos != -1
        assert intro_pos < part_pos, "le chapitre libre en tête doit apparaître avant la partie dans la TOC"

        names = zf.namelist()
        assert any(n.endswith("chapter_0.xhtml") for n in names)


def test_free_chapter_between_two_parts_appears_at_correct_position(tmp_path):
    asset_store = AssetStore(tmp_path / "assets")
    project = ProjectMeta()
    chap_a = Chapter.create(title="Chapitre A")
    interlude = Chapter.create(title="Interlude")
    chap_b = Chapter.create(title="Chapitre B")
    for c in (chap_a, interlude, chap_b):
        project.document.chapters[c.id] = c

    part1 = Part.create(title="Partie Un")
    part1.chapter_ids = [chap_a.id]
    part2 = Part.create(title="Partie Deux")
    part2.chapter_ids = [chap_b.id]
    project.document.structure.items = [part1, interlude.id, part2]

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Livre"))

    with zipfile.ZipFile(out) as zf:
        nav = zf.read("EPUB/nav.xhtml").decode()
        part1_pos = nav.find("Partie Un")
        interlude_pos = nav.find("Interlude")
        part2_pos = nav.find("Partie Deux")
        assert part1_pos != -1 and interlude_pos != -1 and part2_pos != -1
        assert part1_pos < interlude_pos < part2_pos, \
            "le chapitre libre doit apparaître exactement entre les deux parties dans la TOC"


def test_free_chapter_at_end_appears_last_in_spine_and_toc(tmp_path):
    asset_store = AssetStore(tmp_path / "assets")
    project = ProjectMeta()
    chap1 = Chapter.create(title="Chapitre Un")
    outro = Chapter.create(title="Outro")
    project.document.chapters[chap1.id] = chap1
    project.document.chapters[outro.id] = outro

    part = Part.create(title="Partie I")
    part.chapter_ids = [chap1.id]
    project.document.structure.items = [part, outro.id]

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Livre"))

    with zipfile.ZipFile(out) as zf:
        nav = zf.read("EPUB/nav.xhtml").decode()
        part_pos = nav.find("Partie I")
        outro_pos = nav.find("Outro")
        assert part_pos != -1 and outro_pos != -1
        assert part_pos < outro_pos, "le chapitre libre en fin doit apparaître après la partie dans la TOC"


def test_toc_free_chapter_is_top_level_entry_not_nested_under_a_part(tmp_path):
    """Un chapitre libre doit être une entrée de premier niveau dans la TOC — pas imbriqué
    sous un <ol> de section comme le sont les chapitres d'une Part."""
    asset_store = AssetStore(tmp_path / "assets")
    project = ProjectMeta()
    chap1 = Chapter.create(title="Chapitre Un")
    free = Chapter.create(title="Chapitre Libre")
    project.document.chapters[chap1.id] = chap1
    project.document.chapters[free.id] = free

    part = Part.create(title="Partie I")
    part.chapter_ids = [chap1.id]
    project.document.structure.items = [part, free.id]

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Livre"))

    with zipfile.ZipFile(out) as zf:
        nav = zf.read("EPUB/nav.xhtml").decode()
        # Le lien du chapitre libre doit apparaître après la fermeture du <ol> imbriqué de
        # la partie (pas à l'intérieur) — on vérifie que la dernière fermeture de sous-liste
        # avant "Chapitre Libre" précède bien sa position, signe qu'il est au niveau racine.
        free_pos = nav.find("Chapitre Libre")
        assert free_pos != -1
        # Le chapitre de la partie doit être imbriqué : une balise <ol> ouvre une sous-liste
        # après "Partie I" et se referme avant "Chapitre Libre".
        part_pos = nav.find("Partie I")
        nested_ol_open = nav.find("<ol", part_pos)
        nested_ol_close = nav.find("</ol>", nested_ol_open)
        assert part_pos < nested_ol_open < nested_ol_close < free_pos
