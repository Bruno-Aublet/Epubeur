import zipfile
from pathlib import Path

from controller import ProjectController
from model.book_metadata import BookMetadata

MANIFEST_XML = ('<?xml version="1.0"?>'
                 '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>')

NS_ATTRS = 'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'

CONTENT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS} xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
  <office:body>
    <office:text>
      <text:p>Un paragraphe.</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

STYLES_XML = f"""<?xml version="1.0"?>
<office:document-styles {NS_ATTRS}/>
"""

META_XML = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:dc="http://purl.org/dc/elements/1.1/">
  <office:meta>
    <dc:title>Mon Roman</dc:title>
    <dc:creator>Une Autrice</dc:creator>
  </office:meta>
</office:document-meta>
"""


def _make_fixture(tmp_path: Path, name: str = "fixture.odt") -> Path:
    fixture_path = tmp_path / name
    with zipfile.ZipFile(fixture_path, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        zf.writestr("content.xml", CONTENT_XML)
        zf.writestr("styles.xml", STYLES_XML)
        zf.writestr("META-INF/manifest.xml", MANIFEST_XML)
        zf.writestr("meta.xml", META_XML)
    return fixture_path


def test_import_odt_emits_odt_metadata_found_with_document_properties(tmp_path):
    controller = ProjectController()
    fixture = _make_fixture(tmp_path)

    received: list[tuple[BookMetadata, str]] = []
    controller.odt_metadata_found.connect(lambda metadata, name: received.append((metadata, name)))

    controller.import_odt(fixture)

    assert len(received) == 1
    metadata, source_file_name = received[0]
    assert metadata.title == "Mon Roman"
    assert metadata.author == "Une Autrice"
    assert source_file_name == fixture.name


def test_import_odt_without_meta_xml_does_not_emit_odt_metadata_found(tmp_path):
    """Non-régression : sample_simple.odt (fixture existante) n'a pas de meta.xml — l'import ne
    doit ni planter ni émettre un signal avec des métadonnées vides trompeuses."""
    controller = ProjectController()
    fixture = Path(__file__).parent / "fixtures" / "sample_simple.odt"

    received: list[tuple[BookMetadata, str]] = []
    controller.odt_metadata_found.connect(lambda metadata, name: received.append((metadata, name)))

    controller.import_odt(fixture)

    assert received == []
