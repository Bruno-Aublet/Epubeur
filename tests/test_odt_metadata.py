import zipfile
from pathlib import Path

from model.book_metadata import BookMetadata
from odt.metadata import extract_book_metadata
from odt.reader import OdtSource

# Aucune propriété de document ODT (titre, auteur, description, mots-clés...) n'était lue avant ce
# correctif : odt/reader.py n'ouvrait jamais meta.xml. L'utilisateur devait tout retaper à la main
# dans l'onglet Générer, même si le fichier Writer avait déjà des propriétés renseignées.

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

FULL_META_XML = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0">
  <office:meta>
    <dc:title>Le Guide d'Eauprofonde</dc:title>
    <dc:creator>Volothamp Geddarm</dc:creator>
    <dc:description>Un guide complet de la cité.</dc:description>
    <dc:language>fr-FR</dc:language>
    <dc:date>2026-08-25T10:00:00</dc:date>
    <meta:keyword>fantasy</meta:keyword>
    <meta:keyword>donjons et dragons</meta:keyword>
  </office:meta>
</office:document-meta>
"""

EMPTY_META_XML = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0">
  <office:meta/>
</office:document-meta>
"""


def _make_fixture(tmp_path: Path, meta_xml: str | None, name: str = "fixture.odt") -> Path:
    fixture_path = tmp_path / name
    with zipfile.ZipFile(fixture_path, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        zf.writestr("content.xml", CONTENT_XML)
        zf.writestr("styles.xml", STYLES_XML)
        zf.writestr("META-INF/manifest.xml", MANIFEST_XML)
        if meta_xml is not None:
            zf.writestr("meta.xml", meta_xml)
    return fixture_path


def test_metadata_is_extracted_from_meta_xml(tmp_path):
    fixture = _make_fixture(tmp_path, FULL_META_XML)
    source = OdtSource(fixture)

    metadata = extract_book_metadata(source)

    assert isinstance(metadata, BookMetadata)
    assert metadata.title == "Le Guide d'Eauprofonde"
    assert metadata.author == "Volothamp Geddarm"
    assert metadata.description == "Un guide complet de la cité."
    assert metadata.language == "fr-FR"
    assert metadata.publication_date == "2026-08-25"
    assert metadata.subjects == ["fantasy", "donjons et dragons"]


def test_missing_meta_xml_returns_none(tmp_path):
    """Non-régression : un .odt sans meta.xml (jamais garanti par le format) ne doit pas
    faire planter l'import — extract_book_metadata retourne None, pas un objet vide trompeur."""
    fixture = _make_fixture(tmp_path, None)
    source = OdtSource(fixture)

    assert extract_book_metadata(source) is None


def test_empty_office_meta_returns_defaults(tmp_path):
    fixture = _make_fixture(tmp_path, EMPTY_META_XML)
    source = OdtSource(fixture)

    metadata = extract_book_metadata(source)

    assert metadata is not None
    assert metadata.title == "Sans titre"
    assert metadata.author == ""
    assert metadata.subjects == []
