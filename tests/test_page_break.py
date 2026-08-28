import zipfile
from pathlib import Path

from epub.builder import split_chapter_into_segments, build_epub
from epub.importer import import_epub
from model.assets import AssetStore
from model.book_metadata import BookMetadata
from model.document import Part
from model.project import ProjectMeta
from odt.chapter_detector import split_into_chapters
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver

CONTENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0">
  <office:automatic-styles>
    <style:style style:name="PageBreak" style:family="paragraph">
      <style:paragraph-properties fo:break-before="page"/>
    </style:style>
  </office:automatic-styles>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre un</text:h>
      <text:p>Paragraphe A.</text:p>
      <text:p text:style-name="PageBreak">Paragraphe B, après saut de page.</text:p>
      <text:p>Paragraphe C.</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

CONTENT_XML_BREAK_RIGHT_AFTER_HEADING = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0">
  <office:automatic-styles>
    <style:style style:name="PageBreak" style:family="paragraph">
      <style:paragraph-properties fo:break-before="page"/>
    </style:style>
  </office:automatic-styles>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre un</text:h>
      <text:p text:style-name="PageBreak">Premier paragraphe du chapitre, avec un saut de page.</text:p>
      <text:p>Suite normale.</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

STYLES_XML = """<?xml version="1.0"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0">
  <office:styles>
    <style:style style:name="Heading_20_1" style:display-name="Heading 1" style:family="paragraph"/>
  </office:styles>
</office:document-styles>
"""

MANIFEST_XML = ('<?xml version="1.0"?>'
                 '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>')


def _make_fixture(tmp_path: Path, content_xml: str) -> Path:
    fixture_path = tmp_path / "page_break.odt"
    with zipfile.ZipFile(fixture_path, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        zf.writestr("content.xml", content_xml)
        zf.writestr("styles.xml", STYLES_XML)
        zf.writestr("META-INF/manifest.xml", MANIFEST_XML)
    return fixture_path


def _load(tmp_path, content_xml):
    fixture = _make_fixture(tmp_path, content_xml)
    asset_store = AssetStore(tmp_path / "assets")
    source = OdtSource(fixture)
    resolver = StyleResolver(source)
    return split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)


def test_page_break_before_detected_on_paragraph(tmp_path):
    chapters = _load(tmp_path, CONTENT_XML)
    paragraphs = chapters[0].paragraphs
    assert [p.page_break_before for p in paragraphs] == [False, True, False]


def test_page_break_right_after_heading_does_not_create_split(tmp_path):
    chapters = _load(tmp_path, CONTENT_XML_BREAK_RIGHT_AFTER_HEADING)
    segments = split_chapter_into_segments(chapters[0].paragraphs)
    assert len(segments) == 1


def _make_project(tmp_path, content_xml):
    asset_store = AssetStore(tmp_path / "assets")
    chapters = _load(tmp_path, content_xml)
    project = ProjectMeta()
    for ch in chapters:
        project.document.chapters[ch.id] = ch
    part = Part.create(title="Partie I")
    part.chapter_ids = [c.id for c in chapters]
    project.document.structure.items.append(part)
    return project, asset_store


def test_build_epub_splits_chapter_with_internal_page_break_into_two_xhtml_files(tmp_path):
    project, asset_store = _make_project(tmp_path, CONTENT_XML)
    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        # order_counter s'incrémente une fois PAR SEGMENT (pas par chapitre), pour rester un
        # identifiant global unique : le premier segment consomme chapter_0.xhtml, le second
        # segment (bien que du même chapitre) consomme le compteur suivant, chapter_1_seg2.xhtml.
        assert any(n.endswith("chapter_0.xhtml") for n in names)
        assert any(n.endswith("chapter_1_seg2.xhtml") for n in names)

        opf_candidates = [n for n in names if n.endswith("content.opf")]
        opf = zf.read(opf_candidates[0]).decode()
        pos1 = opf.find("chapter_0.xhtml")
        pos2 = opf.find("chapter_1_seg2.xhtml")
        assert pos1 != -1 and pos2 != -1 and pos1 < pos2

        first_seg = zf.read([n for n in names if n.endswith("chapter_0.xhtml")][0]).decode()
        second_seg = zf.read([n for n in names if n.endswith("chapter_1_seg2.xhtml")][0]).decode()
        assert "<h1" in first_seg
        assert "<h1" not in second_seg
        assert "Paragraphe A" in first_seg
        assert "Paragraphe B" in second_seg
        assert "Paragraphe C" in second_seg


def test_toc_has_single_entry_for_split_chapter(tmp_path):
    project, asset_store = _make_project(tmp_path, CONTENT_XML)
    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))

    with zipfile.ZipFile(out) as zf:
        nav = zf.read("EPUB/nav.xhtml").decode()
        # Isole la section table des matières (avant les landmarks epub:type="landmarks",
        # qui référencent légitimement aussi chapter_0.xhtml comme "début du texte" — ce n'est
        # pas un doublon de TOC, juste un second type de repère de navigation).
        toc_section = nav.split('epub:type="landmarks"')[0]
        assert toc_section.count("chapter_0") == 1  # une seule référence, pas de lien vers _seg2


def test_chapter_without_page_break_still_produces_one_file(tmp_path):
    asset_store = AssetStore(tmp_path / "assets")
    fixture = _make_fixture(tmp_path, CONTENT_XML)
    source = OdtSource(fixture)
    resolver = StyleResolver(source)
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)

    # Retire le saut de page pour ce test de non-régression.
    for p in chapters[0].paragraphs:
        p.page_break_before = False

    project = ProjectMeta()
    for ch in chapters:
        project.document.chapters[ch.id] = ch
    part = Part.create(title="Partie I")
    part.chapter_ids = [c.id for c in chapters]
    project.document.structure.items.append(part)

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert any(n.endswith("chapter_0.xhtml") for n in names)
        assert not any("_seg" in n for n in names)


def test_round_trip_merges_split_chapter_segments_and_restores_page_break(tmp_path):
    project, asset_store = _make_project(tmp_path, CONTENT_XML)
    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))

    asset_store2 = AssetStore(tmp_path / "assets_import")
    imported_doc, _imported_metadata, warnings = import_epub(out, asset_store2)

    assert len(imported_doc.chapters) == 1
    chapter = next(iter(imported_doc.chapters.values()))
    texts = [p.plain_text() for p in chapter.paragraphs]
    assert texts == ["Paragraphe A.", "Paragraphe B, après saut de page.", "Paragraphe C."]

    # Le paragraphe qui a déclenché la scission (début du 2e segment) doit retrouver son
    # page_break_before après fusion — pas juste le texte.
    breaks = [p.page_break_before for p in chapter.paragraphs]
    assert breaks == [False, True, False]


def test_round_trip_toc_still_has_single_entry_after_reimport(tmp_path):
    project, asset_store = _make_project(tmp_path, CONTENT_XML)
    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))

    asset_store2 = AssetStore(tmp_path / "assets_import")
    imported_doc, _imported_metadata, warnings = import_epub(out, asset_store2)

    all_chapter_ids_in_structure = []
    for item in imported_doc.structure.items:
        if isinstance(item, str):
            all_chapter_ids_in_structure.append(item)
        else:
            all_chapter_ids_in_structure.extend(item.chapter_ids)
    assert len(all_chapter_ids_in_structure) == 1  # une seule référence, pas une par segment
