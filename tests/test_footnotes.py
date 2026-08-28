import zipfile
from pathlib import Path

from epub.builder import EpubBuildError, build_epub, validate_document
from epub.css_resolve import CssResolver
from epub.html_normalize import html_to_paragraphs
from epub.importer import import_epub
from epub.link_integrity import check_internal_link_integrity
from model.assets import AssetStore
from model.book_metadata import BookMetadata
from model.document import Document, ImageWrap, Part, Table, TableCell, TableRow
from model.project import ProjectMeta
from model.serialization import document_from_dict, document_to_dict
from odt.chapter_detector import split_into_chapters
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver

MANIFEST_XML = ('<?xml version="1.0"?>'
                 '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>')

NS_ATTRS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink"'
)

STYLES_XML = """<?xml version="1.0"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0">
  <office:styles>
    <style:style style:name="Heading_20_1" style:display-name="Heading 1" style:family="paragraph"/>
  </office:styles>
</office:document-styles>
"""

SIMPLE_NOTE_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>Avant<text:note text:id="ftn1" text:note-class="footnote">
        <text:note-citation>1</text:note-citation>
        <text:note-body><text:p>Corps de la note.</text:p></text:note-body>
      </text:note>Après</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

MULTI_PARAGRAPH_NOTE_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>Texte<text:note text:id="ftn1" text:note-class="endnote">
        <text:note-citation>1</text:note-citation>
        <text:note-body>
          <text:p>Premier paragraphe.</text:p>
          <text:p>Second paragraphe.</text:p>
        </text:note-body>
      </text:note></text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

FORMATTED_NOTE_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:automatic-styles>
    <style:style style:name="Bold" style:family="text">
      <style:text-properties fo:font-weight="bold"
          xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"/>
    </style:style>
  </office:automatic-styles>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>Texte<text:note text:id="ftn1" text:note-class="footnote">
        <text:note-citation>1</text:note-citation>
        <text:note-body><text:p><text:span text:style-name="Bold">Gras</text:span> et
          <text:a xlink:href="https://example.com">lien</text:a></text:p></text:note-body>
      </text:note></text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

TWO_NOTES_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>Un<text:note text:id="ftn1" text:note-class="footnote">
        <text:note-citation>1</text:note-citation>
        <text:note-body><text:p>Première note.</text:p></text:note-body>
      </text:note> deux<text:note text:id="ftn2" text:note-class="footnote">
        <text:note-citation>2</text:note-citation>
        <text:note-body><text:p>Seconde note.</text:p></text:note-body>
      </text:note></text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

NOTE_WITH_TABLE_INSIDE_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>Texte<text:note text:id="ftn1" text:note-class="footnote">
        <text:note-citation>1</text:note-citation>
        <text:note-body>
          <text:p>Avant tableau.</text:p>
          <table:table>
            <table:table-row><table:table-cell><text:p>Cellule</text:p></table:table-cell></table:table-row>
          </table:table>
        </text:note-body>
      </text:note></text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

PAGE_BREAK_WITH_NOTE_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}
    xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0">
  <office:automatic-styles>
    <style:style style:name="PageBreak" style:family="paragraph">
      <style:paragraph-properties fo:break-before="page"/>
    </style:style>
  </office:automatic-styles>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>Paragraphe A, sans note.</text:p>
      <text:p text:style-name="PageBreak">Paragraphe B, après saut de page<text:note text:id="ftn1"
          text:note-class="footnote">
        <text:note-citation>1</text:note-citation>
        <text:note-body><text:p>Note du second segment.</text:p></text:note-body>
      </text:note>.</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""


def _make_fixture(tmp_path: Path, content_xml: str, name: str = "fixture.odt") -> Path:
    fixture_path = tmp_path / name
    with zipfile.ZipFile(fixture_path, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        zf.writestr("content.xml", content_xml)
        zf.writestr("styles.xml", STYLES_XML)
        zf.writestr("META-INF/manifest.xml", MANIFEST_XML)
    return fixture_path


def _split(tmp_path: Path, content_xml: str, name: str = "fixture.odt", document_footnotes=None):
    fixture = _make_fixture(tmp_path, content_xml, name)
    asset_store = AssetStore(tmp_path / f"assets_{name}")
    source = OdtSource(fixture)
    resolver = StyleResolver(source)
    if document_footnotes is None:
        document_footnotes = {}
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store,
                                    document_footnotes=document_footnotes)
    return chapters, document_footnotes


# --- 1. Note simple ---

def test_simple_note_citation_and_body(tmp_path):
    chapters, footnotes = _split(tmp_path, SIMPLE_NOTE_CONTENT_XML)
    runs = chapters[0].paragraphs[0].runs

    assert [r.text for r in runs] == ["Avant", "1", "Après"]
    assert runs[0].note_id is None
    assert runs[2].note_id is None
    note_id = runs[1].note_id
    assert note_id is not None

    assert len(footnotes[note_id]) == 1
    assert footnotes[note_id][0].plain_text() == "Corps de la note."


# --- 2. Note avec corps multi-paragraphes ---

def test_note_with_multi_paragraph_body(tmp_path):
    chapters, footnotes = _split(tmp_path, MULTI_PARAGRAPH_NOTE_CONTENT_XML)
    note_id = next(r.note_id for r in chapters[0].paragraphs[0].runs if r.note_id)

    assert len(footnotes[note_id]) == 2
    assert footnotes[note_id][0].plain_text() == "Premier paragraphe."
    assert footnotes[note_id][1].plain_text() == "Second paragraphe."


# --- 3. Note avec texte formaté ---

def test_note_body_preserves_formatting_and_links(tmp_path):
    chapters, footnotes = _split(tmp_path, FORMATTED_NOTE_CONTENT_XML)
    note_id = next(r.note_id for r in chapters[0].paragraphs[0].runs if r.note_id)

    runs = footnotes[note_id][0].runs
    assert any(r.fmt.bold and r.text == "Gras" for r in runs)
    assert any(r.link_url == "https://example.com" for r in runs)


# --- 4. Plusieurs notes ---

def test_multiple_notes_have_distinct_ids(tmp_path):
    chapters, footnotes = _split(tmp_path, TWO_NOTES_CONTENT_XML)
    note_ids = [r.note_id for r in chapters[0].paragraphs[0].runs if r.note_id]

    assert len(note_ids) == 2
    assert note_ids[0] != note_ids[1]
    assert footnotes[note_ids[0]][0].plain_text() == "Première note."
    assert footnotes[note_ids[1]][0].plain_text() == "Seconde note."


# --- 8. Note contenant un tableau imbriqué (cas exotique, ignoré silencieusement) ---

def test_note_body_ignores_nested_table(tmp_path):
    chapters, footnotes = _split(tmp_path, NOTE_WITH_TABLE_INSIDE_CONTENT_XML)
    note_id = next(r.note_id for r in chapters[0].paragraphs[0].runs if r.note_id)

    body = footnotes[note_id]
    assert len(body) == 1
    assert body[0].plain_text() == "Avant tableau."
    assert not any(isinstance(b, Table) for b in body)


def _make_project(tmp_path: Path, content_xml: str) -> tuple[ProjectMeta, AssetStore]:
    document_footnotes: dict = {}
    chapters, footnotes = _split(tmp_path, content_xml, document_footnotes=document_footnotes)
    asset_store = AssetStore(tmp_path / "assets_src2")
    project = ProjectMeta()
    for ch in chapters:
        project.document.chapters[ch.id] = ch
    project.document.footnotes = footnotes
    part = Part.create(title="Partie I")
    part.chapter_ids = [c.id for c in chapters]
    project.document.structure.items.append(part)
    return project, asset_store


# --- 5. Interaction avec un saut de page manuel ---

def test_note_body_rendered_only_in_the_segment_where_it_is_called(tmp_path):
    project, asset_store = _make_project(tmp_path, PAGE_BREAK_WITH_NOTE_CONTENT_XML)
    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))

    with zipfile.ZipFile(out) as zf:
        seg1 = zf.read("EPUB/text/chapter_0.xhtml").decode()
        seg2_name = next(n for n in zf.namelist() if "_seg2" in n)
        seg2 = zf.read(seg2_name).decode()

    assert 'epub:type="footnote"' not in seg1
    assert 'epub:type="footnote"' in seg2
    assert "Note du second segment." in seg2


# --- 7. check_internal_link_integrity ne lève aucune erreur ---

def test_build_epub_with_notes_does_not_raise_link_errors(tmp_path):
    project, asset_store = _make_project(tmp_path, TWO_NOTES_CONTENT_XML)
    # build_epub appelle déjà check_internal_link_integrity en interne (EpubBuildError si erreurs) :
    # la génération réussissant sans exception suffit à prouver l'absence de lien cassé.
    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))
    assert out.exists()


# --- 6. Round-trip complet ODT -> EPUB -> réimport ---

def test_round_trip_odt_to_epub_to_reimport_preserves_footnote(tmp_path):
    project, asset_store = _make_project(tmp_path, SIMPLE_NOTE_CONTENT_XML)
    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))

    asset_store2 = AssetStore(tmp_path / "assets_import")
    imported_doc, _imported_metadata, _warnings = import_epub(out, asset_store2)

    chapter = next(iter(imported_doc.chapters.values()))
    runs = chapter.paragraphs[0].runs
    note_run = next((r for r in runs if r.note_id), None)
    assert note_run is not None
    assert note_run.text == "1"

    body = imported_doc.footnotes.get(note_run.note_id)
    assert body is not None
    assert body[0].plain_text() == "Corps de la note."


# --- 9. Sérialisation round-trip ---

def test_serialization_round_trip_preserves_footnotes():
    document = Document()
    from model.document import Chapter, Paragraph, Run
    from model.styles import CharFormat

    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="Texte", fmt=CharFormat()),
                        Run(text="1", fmt=CharFormat(), note_id="note-abc")])
    ]
    document.chapters[chapter.id] = chapter
    document.structure.append_free_chapter(chapter.id)
    document.footnotes["note-abc"] = [Paragraph(runs=[Run(text="Corps.", fmt=CharFormat())])]

    d = document_to_dict(document)
    reloaded = document_from_dict(d)

    reloaded_chapter = next(iter(reloaded.chapters.values()))
    note_run = next(r for r in reloaded_chapter.paragraphs[0].runs if r.note_id)
    assert note_run.note_id == "note-abc"
    assert reloaded.footnotes["note-abc"][0].plain_text() == "Corps."


def test_reimport_note_body_preserves_list_and_image(tmp_path):
    """Régression : le corps d'une note ne conservait au réimport que les <p>/<blockquote>,
    perdant silencieusement toute liste ou image qu'une note peut pourtant légitimement
    contenir (le rendu, lui, les autorise sans restriction — cf. footnotes_html/paragraphs_to_html
    dans epub/html_render.py, qui rendent le corps d'une note exactement comme un chapitre)."""
    xhtml = """<html><body><div class="epubeur-chapter">
<p>Texte<sup><a epub:type="noteref" href="#note-n1">1</a></sup></p>
<aside epub:type="footnote" id="note-n1">
<p>Avant liste.</p>
<ul><li>Item A</li><li>Item B</li></ul>
<p><img data-epubeur-image="imgX" data-epubeur-image-wrap="left"/>Une image dans la note.</p>
</aside>
</div></body></html>"""
    resolver = CssResolver([])
    _paragraphs, footnotes, wraps = html_to_paragraphs(xhtml, resolver)

    note_body = footnotes["n1"]
    assert [p.plain_text() for p in note_body] == ["Avant liste.", "Item A", "Item B",
                                                     "Une image dans la note."]
    assert note_body[1].list_level == 1
    assert note_body[2].list_level == 1
    assert note_body[3].image is not None
    assert note_body[3].image.asset_id == "imgX"
    assert wraps == {"imgX": ImageWrap.LEFT}


def test_validate_document_reports_note_ref_without_body(tmp_path):
    """Régression : un Run.note_id sans entrée correspondante dans document.footnotes produirait
    un lien <a href="#note-..."> cassé, détecté trop tard et de façon peu explicite par
    check_internal_link_integrity — validate_document doit l'identifier explicitement en amont."""
    from model.document import Chapter, Paragraph, Run
    from model.styles import CharFormat

    project = ProjectMeta()
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [
        Paragraph(runs=[Run(text="Texte", fmt=CharFormat()),
                        Run(text="1", fmt=CharFormat(), note_id="note-orpheline")])
    ]
    project.document.chapters[chapter.id] = chapter
    part = Part.create(title="Partie I")
    part.chapter_ids = [chapter.id]
    project.document.structure.items.append(part)
    # note-orpheline n'est jamais ajoutée à project.document.footnotes

    errors = validate_document(project, BookMetadata(title="Test"))
    assert any("note de bas de page" in e for e in errors)

    asset_store = AssetStore(tmp_path / "assets")
    try:
        build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))
        assert False, "build_epub aurait dû lever EpubBuildError"
    except EpubBuildError as exc:
        assert "note de bas de page" in str(exc)
