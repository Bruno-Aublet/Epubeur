import zipfile
from pathlib import Path

from lxml import etree

NSMAP = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "dc": "http://purl.org/dc/elements/1.1/",
    "meta": "urn:oasis:names:tc:opendocument:xmlns:meta:1.0",
}


def qn(prefixed: str) -> str:
    prefix, local = prefixed.split(":", 1)
    return f"{{{NSMAP[prefix]}}}{local}"


class OdtSource:
    """Ouvre un fichier .odt (zip) et expose son contenu XML et ses images."""

    def __init__(self, path: Path):
        self.path = Path(path)
        with zipfile.ZipFile(self.path) as zf:
            self._content_bytes = zf.read("content.xml")
            self._styles_bytes = zf.read("styles.xml")
            # meta.xml est absent de certains .odt générés par des outils tiers (pas seulement
            # LibreOffice/OpenOffice) : jamais garanti par le format, donc lu de façon tolérante.
            self._meta_bytes = zf.read("meta.xml") if "meta.xml" in zf.namelist() else None
            self._picture_names = [n for n in zf.namelist() if n.startswith("Pictures/")]
            self._pictures = {name: zf.read(name) for name in self._picture_names}

        self.content_tree = etree.fromstring(self._content_bytes)
        self.styles_tree = etree.fromstring(self._styles_bytes)
        self.meta_tree = etree.fromstring(self._meta_bytes) if self._meta_bytes is not None else None

    def document_metadata(self):
        """Racine <office:meta> (dc:title, dc:creator, dc:description, meta:keyword...), ou None
        si le fichier n'a pas de meta.xml."""
        if self.meta_tree is None:
            return None
        return self.meta_tree.find(qn("office:meta"))

    def automatic_styles(self):
        """Styles automatiques déclarés dans content.xml (formatage direct)."""
        nodes = self.content_tree.find(qn("office:automatic-styles"))
        return nodes if nodes is not None else []

    def document_styles(self):
        """Styles nommés déclarés dans styles.xml (ex: Titre 1, Citation)."""
        nodes = self.styles_tree.find(qn("office:styles"))
        return nodes if nodes is not None else []

    def document_automatic_styles(self):
        """Certains ODT déclarent aussi des styles automatiques dans styles.xml."""
        nodes = self.styles_tree.find(qn("office:automatic-styles"))
        return nodes if nodes is not None else []

    def body_text_root(self):
        office_body = self.content_tree.find(qn("office:body"))
        return office_body.find(qn("office:text"))

    def iter_pictures(self):
        """Itère (href_dans_odt, bytes) pour chaque image embarquée."""
        for name, data in self._pictures.items():
            yield name, data
