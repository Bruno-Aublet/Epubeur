from PySide6.QtGui import QFont, QTextBlock, QTextBlockFormat, QTextCharFormat, QTextDocument

from model.document import Paragraph, Run, Table
from model.styles import CharFormat, ParagraphAlign, ParagraphKind, VerticalAlign

# ID de propriété custom posé sur QTextBlockFormat par ChapterFormatToolbar pour porter le style
# de paragraphe (Normal/Citation/Titre) — Qt n'a pas d'équivalent natif fidèle à ParagraphKind.QUOTE,
# donc jamais déduit de l'apparence visuelle du bloc (italique, retrait…), toujours de cette
# propriété. QTextFormat.UserProperty + 1 : le premier ID libre après les propriétés réservées Qt.
EPUBEUR_PARAGRAPH_KIND_PROPERTY = QTextBlockFormat.UserProperty + 1

# QTextBrowser (moteur Rich Text de Qt) ignore silencieusement border-top sur <p>/<div> et ne
# préserve pas la couleur d'un <hr> — seule une couleur de texte est fiablement rendue, d'où ce
# marqueur textuel plutôt qu'une pure ligne graphique. Défini ici (pas dans chapter_preview.py,
# qui importe ce module) pour que extract_paragraphs_from_document puisse reconnaître et
# exclure ce bloc de la détection d'insertion de paragraphe, sans import circulaire.
PAGE_BREAK_MARKER_TEXT = "――― Saut de page manuel ―――"
PAGE_BREAK_MARKER_HTML = f'<p align="center" style="color:#2a6fdb;">{PAGE_BREAK_MARKER_TEXT}</p>'

_ALIGN_FROM_QT = {
    0x0001: ParagraphAlign.LEFT,  # Qt.AlignLeft
    0x0002: ParagraphAlign.RIGHT,  # Qt.AlignRight
    0x0004: ParagraphAlign.CENTER,  # Qt.AlignHCenter
    0x0008: ParagraphAlign.JUSTIFY,  # Qt.AlignJustify
}

KIND_TO_INT = {
    ParagraphKind.BODY: 0,
    ParagraphKind.QUOTE: 1,
    ParagraphKind.HEADING: 2,
}
_KIND_FROM_INT = {v: k for k, v in KIND_TO_INT.items()}


def _align_from_block_format(block_format: QTextBlockFormat, fallback: ParagraphAlign) -> ParagraphAlign:
    # QTextBlockFormat.alignment() peut renvoyer un flag combiné (ex. AlignAbsolute en plus
    # d'AlignLeft) — on ne teste que le bit horizontal pertinent, dans un ordre qui privilégie
    # une correspondance exacte avant de retomber sur fallback (jamais None : un bloc dont
    # l'alignement Qt ne matche aucune valeur connue garde l'alignement précédent du Paragraph).
    raw = int(block_format.alignment())
    for mask, align in _ALIGN_FROM_QT.items():
        if raw & mask:
            return align
    return fallback


def _kind_from_block_style(block_format: QTextBlockFormat, fallback: ParagraphKind) -> ParagraphKind:
    value = block_format.property(EPUBEUR_PARAGRAPH_KIND_PROPERTY)
    if value is None:
        return fallback
    return _KIND_FROM_INT.get(int(value), fallback)


def _char_format_to_charformat(fmt: QTextCharFormat, fallback_font: str | None, in_quote: bool) -> CharFormat:
    vertical_align = VerticalAlign.NORMAL
    if fmt.verticalAlignment() == QTextCharFormat.VerticalAlignment.AlignSuperScript:
        vertical_align = VerticalAlign.SUPERSCRIPT
    elif fmt.verticalAlignment() == QTextCharFormat.VerticalAlignment.AlignSubScript:
        vertical_align = VerticalAlign.SUBSCRIPT

    font_name = fallback_font
    if fmt.hasProperty(QTextCharFormat.Property.FontFamilies):
        families = fmt.fontFamilies()
        if families:
            font_name = families[0]
    elif fmt.hasProperty(QTextCharFormat.Property.FontFamily):
        family = fmt.fontFamily()
        if family:
            font_name = family

    # ParagraphKind.QUOTE est rendu en <blockquote>, dont le CSS (font-style: italic, cf.
    # _show_chapter_impl) applique l'italique à TOUT le texte du paragraphe indépendamment de
    # tout <em> explicite -- QTextCharFormat.fontItalic() ne fait aucune différence entre
    # l'italique hérité de ce style de bloc et un <em> réellement tapé par l'utilisateur (vérifié
    # empiriquement : hasProperty(FontItalic) vaut True dans les deux cas). Sans ce garde,
    # CHAQUE run d'un paragraphe QUOTE ressortait italic=True après un simple aller-retour
    # setHtml()/extraction, même sans aucune frappe -- Paragraph.__eq__ voyait alors le
    # paragraphe entier comme "modifié", ce qui déclenchait une réécriture parasite du modèle
    # pivot à chaque undo/redo (cf. _merge_adjacent_runs, même famille de bug). Le style de
    # citation restant entièrement porté par Paragraph.kind (jamais par Run.fmt.italic), on
    # ignore donc fontItalic() pour tout run à l'intérieur d'un paragraphe QUOTE.
    italic = False if in_quote else fmt.fontItalic()

    return CharFormat(
        bold=fmt.fontWeight() >= QFont.Weight.Bold,
        italic=italic,
        underline=fmt.fontUnderline(),
        strikethrough=fmt.fontStrikeOut(),
        vertical_align=vertical_align,
        font_name=font_name,
    )


def block_contains_image(block: QTextBlock) -> bool:
    """Vrai si ce bloc Qt porte au moins un fragment image — un paragraphe texte+image (sans
    habillage) est scindé par ChapterPreview._isolate_images en plusieurs blocs Qt distincts
    (un bloc par image, PUIS un bloc texte séparé) : cette fonction distingue les deux, utilisée
    à la fois par ChapterPreview._is_block_editable (savoir quel bloc bloquer/laisser éditable)
    et par extract_paragraphs_from_document (savoir quel bloc, parmi plusieurs pointant vers le
    même Paragraph d'origine, porte le texte à jour plutôt que l'image)."""
    it = block.begin()
    while not it.atEnd():
        fragment = it.fragment()
        it += 1
        if fragment.isValid() and fragment.charFormat().isImageFormat():
            return True
    return False


def normalize_paragraphs_for_comparison(paragraphs: "list[Paragraph | Table]") -> "list[Paragraph | Table]":
    """Applique _merge_adjacent_runs à chaque Paragraph, pour comparer avec le résultat d'
    extract_paragraphs_from_document (qui produit toujours des runs déjà fusionnés) sans jamais
    considérer comme "différents" deux Paragraph dont le SEUL écart est un découpage de runs
    plus fin côté modèle pivot (ex. import ODT produisant deux Run consécutifs de même format,
    cf. _merge_adjacent_runs) — jamais utilisé pour écrire dans chapter.paragraphs, uniquement
    pour cette comparaison."""
    normalized: "list[Paragraph | Table]" = []
    for item in paragraphs:
        if isinstance(item, Paragraph):
            normalized.append(Paragraph(
                kind=item.kind, align=item.align, runs=_merge_adjacent_runs(item.runs),
                list_level=item.list_level, list_group_id=item.list_group_id,
                image=item.image, extra_images=item.extra_images,
                page_break_before=item.page_break_before,
            ))
        else:
            normalized.append(item)
    return normalized


def _merge_adjacent_runs(runs: list[Run]) -> list[Run]:
    """Fusionne les runs consécutifs de même format (fmt/link_url/note_id) en un seul.

    Qt fragmente un bloc en plusieurs QTextFragment selon des critères internes qui ne
    correspondent pas forcément à une frontière de Run côté modèle pivot — en particulier, un
    bloc reconstruit par setHtml() à partir de deux Run consécutifs de MÊME format (aucune
    balise <em>/<strong>/... ne les sépare dans le HTML généré, cf. run_to_html) redevient un
    UNIQUE fragment Qt à la lecture. Sans cette fusion, extract_paragraphs_from_document()
    produit un texte identique mais une liste de Run plus courte que l'originale : chaque
    Paragraph concerné comparait alors comme "différent" (Paragraph.__eq__ structurel, pas par
    plain_text()) à la moindre reconstruction complète (undo/redo, changement de chapitre...),
    même sans aucune frappe utilisateur — déclenchant une réécriture parasite du modèle qui
    videmait silencieusement redo_stack juste avant que controller.redo() ne soit appelé."""
    merged: list[Run] = []
    for run in runs:
        if merged:
            previous = merged[-1]
            if previous.fmt == run.fmt and previous.link_url == run.link_url and previous.note_id == run.note_id:
                merged[-1] = Run(text=previous.text + run.text, fmt=previous.fmt,
                                  link_url=previous.link_url, note_id=previous.note_id)
                continue
        merged.append(run)
    return merged


def _runs_from_block(block: QTextBlock, fallback_font: str | None, in_quote: bool = False) -> list[Run]:
    runs: list[Run] = []
    it = block.begin()
    while not it.atEnd():
        fragment = it.fragment()
        it += 1
        if not fragment.isValid():
            continue
        text = fragment.text()
        if not text:
            continue
        # U+2028 (line separator) est l'équivalent Qt d'un saut de ligne manuel (Maj+Entrée) à
        # l'intérieur d'un même bloc — reconverti en '\n', symétrique de run_to_html/
        # html_normalize.py qui utilisent tous deux '\n' comme représentation pivot.
        text = text.replace(" ", "\n")
        fmt = fragment.charFormat()
        char_format = _char_format_to_charformat(fmt, fallback_font, in_quote)
        link_url = fmt.anchorHref() or None
        runs.append(Run(text=text, fmt=char_format, link_url=link_url))
    return _merge_adjacent_runs(runs)


def _paragraph_from_block(block: QTextBlock, previous: Paragraph) -> Paragraph:
    block_format = block.blockFormat()
    fallback_font = previous.runs[0].fmt.font_name if previous.runs else None
    kind = _kind_from_block_style(block_format, previous.kind)
    return Paragraph(
        kind=kind,
        align=_align_from_block_format(block_format, previous.align),
        runs=_runs_from_block(block, fallback_font, in_quote=kind == ParagraphKind.QUOTE),
        list_level=previous.list_level,
        list_group_id=previous.list_group_id,
        image=previous.image,
        extra_images=previous.extra_images,
        page_break_before=previous.page_break_before,
    )


def _new_paragraph_from_block(block: QTextBlock) -> Paragraph:
    """Un bloc top-level nouvellement inséré (aucun Paragraph d'origine correspondant, ex.
    Entrée tapée en milieu de texte) — toujours BODY/LEFT, sans image ni saut de page : ce
    sont des propriétés qu'aucune frappe clavier normale ne peut poser, seules des actions
    dédiées (menu contextuel image, bouton saut de page) le font, sur des paragraphes déjà
    existants."""
    block_format = block.blockFormat()
    kind = _kind_from_block_style(block_format, ParagraphKind.BODY)
    return Paragraph(
        kind=kind,
        align=_align_from_block_format(block_format, ParagraphAlign.LEFT),
        runs=_runs_from_block(block, None, in_quote=kind == ParagraphKind.QUOTE),
    )


def extract_paragraphs_from_document(
    document: QTextDocument,
    original_paragraphs: "list[Paragraph | Table]",
    eligible_block_ranks: dict[int, int],
) -> "list[Paragraph | Table]":
    """Reconstruit une séquence de blocs top-level (Paragraph/Table) en parcourant `document`
    dans l'ordre et en le recalant en continu sur `original_paragraphs` via
    `eligible_block_ranks` (cf. ChapterPreview._eligible_paragraph_block_ranks : rang de bloc
    Qt -> index dans original_paragraphs). Table et paragraphes de liste (list_level > 0) ne
    sont jamais réinterprétés depuis Qt : recopiés tels quels, dans l'ordre où ils apparaissent
    entre deux paragraphes top-level édités.

    Un rang de bloc Qt sans entrée dans `eligible_block_ranks` (Entrée tapée en milieu de
    paragraphe) devient un nouveau Paragraph inséré à cette place. Un index de
    `original_paragraphs` dont plus AUCUN rang de bloc ne pointe vers lui (Suppr à cheval sur
    deux paragraphes, fusionnés par Qt en un seul bloc) disparaît du résultat — son texte a
    déjà été absorbé par le paragraphe voisin restant."""
    referenced_indexes = set(eligible_block_ranks.values())
    seen_indexes: set[int] = set()
    next_unmapped_index = 0  # curseur dans original_paragraphs pour recopier Table/listes intercalées
    result: "list[Paragraph | Table]" = []
    # Tant qu'aucun rang mappé n'a encore été rencontré, un bloc non mappé n'est jamais un
    # ajout de l'utilisateur : c'est le titre du chapitre (rang 0, jamais dans
    # eligible_block_ranks, cf. ChapterPreview.show_chapter) — jamais réinterprété comme un
    # nouveau Paragraph, sous peine de le dupliquer en tête de chapter.paragraphs à chaque sync.
    seen_any_mapped_block = False

    def flush_unmapped_up_to(index: int) -> None:
        """Recopie tel quel tout élément pas encore émis dans `result`, rencontré dans
        original_paragraphs avant `index` : une Table/un paragraphe de liste (jamais référencé
        dans eligible_block_ranks : absent de referenced_indexes), ou un Paragraph composé
        UNIQUEMENT d'image(s) donc sans aucun bloc texte séparé (référencé dans
        referenced_indexes, mais jamais ajouté à seen_indexes faute de bloc texte — cf.
        ChapterPreview._isolate_images, qui ne produit aucun bloc texte pour un tel paragraphe).
        Un index référencé mais purement fusionné dans un voisin (Suppr à cheval sur deux
        paragraphes) n'est PAS recopié ici : il est dans referenced_indexes ET absent de
        seen_indexes tout comme le cas image pur, mais son texte a déjà été absorbé ailleurs —
        distingué du cas image pur par le paragraphe lui-même (all_images() vide ou non)."""
        nonlocal next_unmapped_index
        while next_unmapped_index < index:
            item = original_paragraphs[next_unmapped_index]
            image_only_paragraph = (
                isinstance(item, Paragraph) and item.all_images() and not item.runs
            )
            never_referenced = next_unmapped_index not in referenced_indexes
            if next_unmapped_index not in seen_indexes and (never_referenced or image_only_paragraph):
                result.append(item)
            next_unmapped_index += 1

    block = document.begin()
    block_rank = 0
    while block.isValid():
        original_index = eligible_block_ranks.get(block_rank)
        if original_index is None:
            if seen_any_mapped_block and block.text() != PAGE_BREAK_MARKER_TEXT and _is_top_level_text_block(block):
                result.append(_new_paragraph_from_block(block))
        else:
            seen_any_mapped_block = True
            flush_unmapped_up_to(original_index)
            item = original_paragraphs[original_index]
            assert isinstance(item, Paragraph)
            if original_index not in seen_indexes:
                # Un Paragraph avec image(s) sans habillage est scindé par _isolate_images en
                # plusieurs blocs Qt pointant vers le MÊME original_index : un bloc par image
                # (rencontré en premier), puis un bloc texte séparé en dernier (cf.
                # block_contains_image). Seul CE bloc texte porte le texte/formatage à jour —
                # un bloc-image n'a aucun run textuel exploitable (juste un fragment image) et
                # ne doit jamais être passé à _paragraph_from_block, sous peine de perdre le
                # texte du paragraphe à la prochaine synchro. On diffère donc l'extraction tant
                # qu'on ne rencontre pas explicitement un bloc qui n'est pas lui-même une image.
                if not block_contains_image(block):
                    seen_indexes.add(original_index)
                    result.append(_paragraph_from_block(block, item))
                    next_unmapped_index = max(next_unmapped_index, original_index + 1)
                else:
                    # Bloc-image : ne PAS avancer next_unmapped_index au-delà de original_index
                    # tant que le bloc texte (qui, lui, déclenchera l'avance ci-dessus) n'a pas
                    # été rencontré — sinon le filet de sécurité final (flush_unmapped_up_to en
                    # fin de fonction) ne reverrait jamais cet index si AUCUN bloc texte séparé
                    # n'existe pour lui (paragraphe composé uniquement d'image(s), cf. sa
                    # docstring), le perdant silencieusement de original_paragraphs.
                    next_unmapped_index = max(next_unmapped_index, original_index)
            else:
                next_unmapped_index = max(next_unmapped_index, original_index + 1)
        block_rank += 1
        block = block.next()

    flush_unmapped_up_to(len(original_paragraphs))
    return result


def _is_top_level_text_block(block: QTextBlock) -> bool:
    """Un bloc Qt top-level ordinaire (pas dans une liste, pas dans une table) — les seuls
    blocs que l'utilisateur peut créer en tapant Entrée dans une zone éditable, cf. section 3
    du plan : l'édition est déjà restreinte aux paragraphes top-level simples, donc un nouveau
    bloc ne peut être créé que dans ce contexte."""
    return block.textList() is None
