import zipfile
from pathlib import Path

from epub.builder import build_epub
from epub.importer import import_epub
from model.assets import AssetStore
from model.book_metadata import BookMetadata
from model.document import Paragraph, Part
from model.project import ProjectMeta
from odt.chapter_detector import split_into_chapters
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver

MANIFEST_XML = ('<?xml version="1.0"?>'
                 '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>')

NS_ATTRS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
)

STYLES_XML = """<?xml version="1.0"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0">
  <office:styles>
    <style:style style:name="Heading_20_1" style:display-name="Heading 1" style:family="paragraph"/>
  </office:styles>
</office:document-styles>
"""

ORPHAN_IMAGE_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>Paragraphe 1.</text:p>
      <draw:frame>
        <draw:image xlink:href="Pictures/orphan.png"/>
      </draw:frame>
      <text:p>Paragraphe 2.</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

NORMAL_IMAGE_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>Texte avec image
        <draw:frame>
          <draw:image xlink:href="Pictures/normal.png"/>
        </draw:frame>
      </text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

IMAGE_IN_UNRELATED_TABLE_CELL_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <table:table>
        <table:table-row>
          <table:table-cell>
            <text:p>Cellule
              <draw:frame>
                <draw:image xlink:href="Pictures/hidden.png"/>
              </draw:frame>
            </text:p>
          </table:table-cell>
        </table:table-row>
      </table:table>
    </office:text>
  </office:body>
</office:document-content>
"""

MISSING_PICTURE_FILE_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>Texte
        <draw:frame>
          <draw:image xlink:href="Pictures/introuvable.png"/>
        </draw:frame>
      </text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

DUPLICATE_CONTENT_IMAGES_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>Premier
        <draw:frame>
          <draw:image xlink:href="Pictures/copie1.png"/>
        </draw:frame>
      </text:p>
      <text:p>Second
        <draw:frame>
          <draw:image xlink:href="Pictures/copie2.png"/>
        </draw:frame>
      </text:p>
    </office:text>
  </office:body>
</office:document-content>
"""


TWO_IMAGES_SAME_PARAGRAPH_CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un</text:h>
      <text:p>Deux images côte à côte :
        <draw:frame>
          <draw:image xlink:href="Pictures/premiere.png"/>
        </draw:frame>
        <draw:frame>
          <draw:image xlink:href="Pictures/seconde.png"/>
        </draw:frame>
      </text:p>
    </office:text>
  </office:body>
</office:document-content>
"""


def _make_fixture(tmp_path: Path, content_xml: str, name: str = "fixture.odt",
                   include_pictures: bool = True) -> Path:
    fixture_path = tmp_path / name
    with zipfile.ZipFile(fixture_path, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        zf.writestr("content.xml", content_xml)
        zf.writestr("styles.xml", STYLES_XML)
        zf.writestr("META-INF/manifest.xml", MANIFEST_XML)
        if include_pictures:
            zf.writestr("Pictures/orphan.png", b"\x89PNG fake orphan bytes")
            zf.writestr("Pictures/normal.png", b"\x89PNG fake normal bytes")
            zf.writestr("Pictures/hidden.png", b"\x89PNG fake hidden bytes")
            zf.writestr("Pictures/premiere.png", b"\x89PNG fake premiere bytes")
            zf.writestr("Pictures/seconde.png", b"\x89PNG fake seconde bytes")
    return fixture_path


def _split(tmp_path: Path, content_xml: str, name: str = "fixture.odt", **kwargs):
    fixture = _make_fixture(tmp_path, content_xml, name)
    asset_store = AssetStore(tmp_path / f"assets_{name}")
    source = OdtSource(fixture)
    resolver = StyleResolver(source)
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store, **kwargs)
    return chapters, asset_store


# --- 1, 3. Position et structure du mini-paragraphe orphelin ---

def test_orphan_page_anchored_image_becomes_own_paragraph(tmp_path):
    chapters, _asset_store = _split(tmp_path, ORPHAN_IMAGE_CONTENT_XML)
    paragraphs = chapters[0].paragraphs

    assert len(paragraphs) == 3
    assert paragraphs[0].plain_text() == "Paragraphe 1."
    assert paragraphs[1].runs == []
    assert paragraphs[1].image is not None
    assert paragraphs[2].plain_text() == "Paragraphe 2."


# --- 2. orphan_image_asset_ids ---

def test_orphan_image_reports_asset_id_via_output_param(tmp_path):
    orphans: list[str] = []
    chapters, _asset_store = _split(tmp_path, ORPHAN_IMAGE_CONTENT_XML, orphan_image_asset_ids=orphans)

    assert len(orphans) == 1
    assert chapters[0].paragraphs[1].image.asset_id == orphans[0]


# --- 4. Non-régression : image normalement ancrée ---

def test_normal_anchor_type_paragraph_image_unaffected(tmp_path):
    orphans: list[str] = []
    chapters, _asset_store = _split(tmp_path, NORMAL_IMAGE_CONTENT_XML, orphan_image_asset_ids=orphans)
    paragraphs = chapters[0].paragraphs

    assert len(paragraphs) == 1
    assert paragraphs[0].image is not None
    assert orphans == []


# --- 5. Intégration controller.py::import_odt ---

def test_controller_import_odt_emits_orphan_warning(tmp_path):
    from controller import ProjectController

    fixture = _make_fixture(tmp_path, ORPHAN_IMAGE_CONTENT_XML)
    controller = ProjectController()
    controller.project = ProjectMeta()
    controller.asset_store = AssetStore(tmp_path / "project" / "assets")

    warnings: list[str] = []
    controller.warning_occurred.connect(warnings.append)

    controller.import_odt(fixture)

    assert any("ancrée(s) à la page" in w for w in warnings)


# --- 6. Round-trip ODT -> EPUB -> réimport ---

def test_orphan_image_roundtrip_through_epub(tmp_path):
    chapters, asset_store = _split(tmp_path, ORPHAN_IMAGE_CONTENT_XML)

    project = ProjectMeta()
    for ch in chapters:
        project.document.chapters[ch.id] = ch
    part = Part.create(title="Partie I")
    part.chapter_ids = [c.id for c in chapters]
    project.document.structure.items.append(part)

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))

    asset_store2 = AssetStore(tmp_path / "assets_import")
    imported_doc, _imported_metadata, _warnings = import_epub(out, asset_store2)

    imported_paragraphs = next(iter(imported_doc.chapters.values())).paragraphs
    assert len(imported_paragraphs) == 3
    image_para = imported_paragraphs[1]
    assert isinstance(image_para, Paragraph)
    assert image_para.image is not None
    assert image_para.runs == []


# --- 7. Filet de comptage global ---

def test_image_in_table_cell_does_not_trigger_false_positive(tmp_path):
    """Une image dans une cellule de tableau est déjà rattachée par le mécanisme normal des
    tableaux (_paragraph_from_element est appelée pour chaque <text:p> de cellule) — le filet de
    comptage global ne doit PAS la signaler comme non résolue."""
    unresolved: list[str] = []
    chapters, _asset_store = _split(tmp_path, IMAGE_IN_UNRELATED_TABLE_CELL_CONTENT_XML,
                                     unresolved_image_hrefs=unresolved)
    assert unresolved == []
    table = chapters[0].paragraphs[0]
    assert table.rows[0].cells[0].paragraphs[0].image is not None


def test_missing_picture_file_triggers_unresolved_warning(tmp_path):
    """Une image référencée dans le XML (<draw:image xlink:href=...>) mais dont le fichier n'existe
    pas réellement dans le zip (Pictures/*) échoue silencieusement à l'ingestion — le filet de
    comptage global doit le détecter et le signaler via unresolved_image_hrefs."""
    fixture = _make_fixture(tmp_path, MISSING_PICTURE_FILE_CONTENT_XML, include_pictures=False)
    asset_store = AssetStore(tmp_path / "assets_missing")
    source = OdtSource(fixture)
    resolver = StyleResolver(source)
    unresolved: list[str] = []

    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store,
                                    unresolved_image_hrefs=unresolved)

    assert chapters[0].paragraphs[0].image is None
    assert unresolved == ["Pictures/introuvable.png"]


def test_duplicate_content_images_do_not_trigger_false_positive(tmp_path):
    """Régression : deux <draw:image> avec des hrefs distincts mais un contenu binaire identique
    (image collée deux fois dans Writer) partagent le même asset_id après dédup par AssetStore —
    le filet de comptage global comparait par nom de fichier d'origine (qui ne garde que le nom du
    PREMIER href ingéré), signalant à tort le second comme non résolu alors qu'il l'est bien."""
    fixture_path = tmp_path / "dup.odt"
    with zipfile.ZipFile(fixture_path, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        zf.writestr("content.xml", DUPLICATE_CONTENT_IMAGES_CONTENT_XML)
        zf.writestr("styles.xml", STYLES_XML)
        zf.writestr("META-INF/manifest.xml", MANIFEST_XML)
        zf.writestr("Pictures/copie1.png", b"\x89PNG identical bytes")
        zf.writestr("Pictures/copie2.png", b"\x89PNG identical bytes")

    asset_store = AssetStore(tmp_path / "assets_dup")
    source = OdtSource(fixture_path)
    resolver = StyleResolver(source)
    unresolved: list[str] = []

    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store,
                                    unresolved_image_hrefs=unresolved)

    assert unresolved == []
    assert chapters[0].paragraphs[0].image is not None
    assert chapters[0].paragraphs[1].image is not None
    assert chapters[0].paragraphs[0].image.asset_id == chapters[0].paragraphs[1].image.asset_id


# --- Deux images ancrées au même paragraphe (régression : seule la première était conservée) ---

def test_two_images_in_same_paragraph_both_captured(tmp_path):
    """Régression : _find_image ne retournait que la PREMIÈRE image trouvée par .iter() dans un
    paragraphe — la seconde disparaissait silencieusement du modèle, seulement rattrapée
    partiellement par le filet unresolved_image_hrefs (listée "à vérifier manuellement" plutôt
    que réellement rattachée). Un paragraphe ODT peut pourtant contenir plusieurs draw:frame
    porteurs d'image (deux images côte à côte dans la même ligne, ancrées au caractère)."""
    unresolved: list[str] = []
    chapters, asset_store = _split(tmp_path, TWO_IMAGES_SAME_PARAGRAPH_CONTENT_XML,
                                    unresolved_image_hrefs=unresolved)

    para = chapters[0].paragraphs[0]
    assert unresolved == []
    assert para.image is not None
    assert len(para.extra_images) == 1
    assert para.all_images() == [para.image, para.extra_images[0]]
    assert para.image.asset_id != para.extra_images[0].asset_id


def test_two_images_in_same_paragraph_both_referenced_in_document(tmp_path):
    """Document.is_asset_referenced() et image_alt_text_candidates() doivent voir la seconde
    image (extra_images), pas seulement la première (.image) — sans quoi la seconde image
    resterait considérée comme orpheline/non décrite alors qu'elle est bien utilisée."""
    from model.document import Document

    chapters, _asset_store = _split(tmp_path, TWO_IMAGES_SAME_PARAGRAPH_CONTENT_XML)
    document = Document()
    for ch in chapters:
        document.chapters[ch.id] = ch

    para = chapters[0].paragraphs[0]
    assert document.is_asset_referenced(para.image.asset_id)
    assert document.is_asset_referenced(para.extra_images[0].asset_id)
    assert not document.is_asset_referenced("un-asset-id-inexistant")


def test_two_images_in_same_paragraph_both_rendered_to_html(tmp_path):
    """epub/html_render.py doit produire une balise <img> par image du paragraphe, pas
    seulement pour la première — sans quoi la seconde image disparaissait de l'EPUB généré
    alors qu'elle était bien détectée à l'import."""
    from epub.html_render import paragraph_to_html

    chapters, _asset_store = _split(tmp_path, TWO_IMAGES_SAME_PARAGRAPH_CONTENT_XML)
    para = chapters[0].paragraphs[0]

    html = paragraph_to_html(para)

    assert html.count("<img") == 2
    assert f'data-epubeur-image="{para.image.asset_id}"' in html
    assert f'data-epubeur-image="{para.extra_images[0].asset_id}"' in html


def test_two_images_in_same_paragraph_roundtrip_through_epub(tmp_path):
    """Les deux images doivent survivre au cycle complet ODT -> génération EPUB -> réimport,
    pas seulement à la détection ODT initiale."""
    chapters, asset_store = _split(tmp_path, TWO_IMAGES_SAME_PARAGRAPH_CONTENT_XML)

    project = ProjectMeta()
    for ch in chapters:
        project.document.chapters[ch.id] = ch
    part = Part.create(title="Partie I")
    part.chapter_ids = [c.id for c in chapters]
    project.document.structure.items.append(part)

    out = build_epub(project, asset_store, tmp_path / "out.epub", metadata=BookMetadata(title="Test"))

    asset_store2 = AssetStore(tmp_path / "assets_import")
    imported_doc, _imported_metadata, _warnings = import_epub(out, asset_store2)

    imported_para = next(iter(imported_doc.chapters.values())).paragraphs[0]
    assert imported_para.image is not None
    assert len(imported_para.extra_images) == 1
    assert imported_para.image.asset_id != imported_para.extra_images[0].asset_id


def test_two_images_in_same_paragraph_survives_epbz_serialization():
    """model/serialization.py doit persister extra_images, pas seulement .image — sans quoi la
    seconde image disparaîtrait à la sauvegarde/rechargement d'un projet .epbz."""
    from model.serialization import document_from_dict, document_to_dict

    document = _document_with_two_images_in_one_paragraph()

    reloaded = document_from_dict(document_to_dict(document))

    reloaded_para = next(iter(reloaded.chapters.values())).paragraphs[0]
    assert reloaded_para.image.asset_id == "asset-1"
    assert len(reloaded_para.extra_images) == 1
    assert reloaded_para.extra_images[0].asset_id == "asset-2"


def _document_with_two_images_in_one_paragraph():
    from model.document import Chapter, Document, ImageAnchor

    document = Document()
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [Paragraph(
        image=ImageAnchor(asset_id="asset-1", alt_text="Première"),
        extra_images=[ImageAnchor(asset_id="asset-2", alt_text="Seconde")],
    )]
    document.chapters[chapter.id] = chapter
    return document
