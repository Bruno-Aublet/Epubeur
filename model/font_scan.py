from collections import Counter

from model.document import Document, iter_all_paragraphs


def scan_fonts_in_document(document: Document) -> Counter:
    """Compte les occurrences de chaque nom de police utilisée dans les runs du document
    (modèle pivot déjà construit) — indépendant de la provenance des données (import ODT,
    import EPUB, projet rechargé), contrairement à odt.font_scanner.scan_fonts qui opère
    directement sur le XML ODT source."""
    counts: Counter = Counter()
    for chapter in document.chapters.values():
        for paragraph in iter_all_paragraphs(chapter.paragraphs):
            for run in paragraph.runs:
                if run.fmt.font_name:
                    counts[run.fmt.font_name] += 1
    return counts
