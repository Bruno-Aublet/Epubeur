from model.book_metadata import BookMetadata
from odt.reader import OdtSource, qn


def _text_of(elem) -> str:
    return (elem.text or "").strip() if elem is not None else ""


def extract_book_metadata(source: OdtSource) -> BookMetadata | None:
    """Lit office:meta (dc:title, dc:creator, dc:description, dc:subject, dc:language,
    dc:date/meta:creation-date, meta:keyword) d'un .odt, pour pré-remplir l'onglet Générer —
    symétrique de epub/importer.py::_extract_book_metadata pour un EPUB importé. Retourne None si
    le fichier n'a pas de meta.xml (jamais garanti par le format), pour que l'appelant distingue
    "rien à pré-remplir" d'un BookMetadata par défaut."""
    meta = source.document_metadata()
    if meta is None:
        return None

    title = _text_of(meta.find(qn("dc:title")))
    author = _text_of(meta.find(qn("dc:creator"))) or _text_of(meta.find(qn("meta:initial-creator")))
    language = _text_of(meta.find(qn("dc:language")))
    description = _text_of(meta.find(qn("dc:description")))
    publication_date = _text_of(meta.find(qn("dc:date"))) or _text_of(meta.find(qn("meta:creation-date")))
    # ODF n'a pas d'équivalent direct de dc:publisher/dc:rights/dc:source dans office:meta —
    # champs volontairement absents ici (rien à lire), contrairement à dc:title/dc:creator/etc.
    subjects = [_text_of(k) for k in meta.findall(qn("meta:keyword"))]
    subjects = [s for s in subjects if s]
    dc_subject = _text_of(meta.find(qn("dc:subject")))
    if dc_subject and dc_subject not in subjects:
        subjects.insert(0, dc_subject)

    return BookMetadata(
        title=title or "Sans titre",
        author=author,
        language=language or "fr",
        description=description,
        publication_date=publication_date[:10] if publication_date else "",
        subjects=subjects,
    )
