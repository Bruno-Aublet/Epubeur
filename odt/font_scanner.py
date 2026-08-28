from collections import Counter

from model.styles import CharFormat
from odt.chapter_detector import HEADING_TAG, PARAGRAPH_TAG, STYLE_NAME_ATTR, _iter_runs
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver


def scan_fonts(source: OdtSource, resolver: StyleResolver) -> Counter:
    """Compte les occurrences de chaque nom de police détecté dans les runs d'un ODT.
    Réutilise _iter_runs (même mécanisme d'héritage paragraphe -> span que l'import réel) pour
    que le comptage reflète la police effectivement appliquée à chaque run, y compris un span
    sans font-name propre dont le paragraphe englobant a une police figée."""
    counts: Counter = Counter()
    body = source.body_text_root()
    # elem.iter() descend aussi dans les text:note-body (text:note est un enfant comme un autre
    # dans l'arbre lxml) : les runs du corps d'une note sont donc déjà comptés une fois via ce
    # parcours global, sans traitement séparé — document_footnotes jetable, cette fonction ne
    # s'intéresse qu'aux polices utilisées, jamais au contenu structuré des notes lui-même.
    document_footnotes: dict = {}
    image_wraps: dict = {}

    def visit(elem):
        for child in elem.iter():
            if child.tag in (PARAGRAPH_TAG, HEADING_TAG):
                style_name = child.get(STYLE_NAME_ATTR)
                paragraph_fmt = resolver.resolve_text_style(style_name, inherited=CharFormat())
                for run in _iter_runs(child, resolver, paragraph_fmt, source, None, document_footnotes,
                                       image_wraps):
                    if run.fmt.font_name:
                        counts[run.fmt.font_name] += 1

    visit(body)
    return counts


def scan_fonts_multi(sources_and_resolvers: list[tuple[OdtSource, StyleResolver]]) -> Counter:
    total: Counter = Counter()
    for source, resolver in sources_and_resolvers:
        total.update(scan_fonts(source, resolver))
    return total
