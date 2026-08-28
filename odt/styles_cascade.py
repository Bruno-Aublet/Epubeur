from dataclasses import dataclass

from model.styles import CharFormat, ParagraphAlign, ParagraphKind, VerticalAlign
from odt.reader import OdtSource, qn

HEADING1_STYLE_NAMES = {
    "Heading_20_1",
    "Titre_20_1",
}

QUOTE_STYLE_NAMES = {
    "Quotations",
    "Citation",
}


@dataclass
class ResolvedParagraphStyle:
    is_heading1: bool = False
    kind: ParagraphKind = ParagraphKind.BODY
    align: ParagraphAlign = ParagraphAlign.LEFT
    list_level: int = 0
    page_break_before: bool = False
    page_break_after: bool = False  # transitoire : normalisé par chapter_detector.py sur le
                                     # paragraphe suivant, jamais exposé sur le modèle pivot


@dataclass
class ResolvedGraphicStyle:
    wrap: str = "none"  # valeur ODF brute (style:wrap) — traduite en ImageWrap dans
                         # odt/chapter_detector.py uniquement (qui importe déjà model.document) ;
                         # ce module ne connaît que model.styles, jamais model.document, même
                         # séparation de responsabilités que resolve_paragraph_style.


class StyleResolver:
    """Résout la cascade de styles ODT (style:parent-style-name) pour un OdtSource donné."""

    def __init__(self, source: OdtSource):
        self.source = source
        self._style_nodes: dict[str, object] = {}
        self._index_styles(source.document_styles())
        self._index_styles(source.document_automatic_styles())
        self._index_styles(source.automatic_styles())
        self._paragraph_cache: dict[str, ResolvedParagraphStyle] = {}
        self._graphic_cache: dict[str, ResolvedGraphicStyle] = {}

    def _index_styles(self, container) -> None:
        if container is None:
            return
        for node in container:
            name = node.get(qn("style:name"))
            if name:
                self._style_nodes[name] = node

    def _style_chain(self, style_name: str | None) -> list:
        chain = []
        seen: set[str] = set()
        current = style_name
        while current and current not in seen:
            seen.add(current)
            node = self._style_nodes.get(current)
            if node is None:
                break
            chain.append(node)
            current = node.get(qn("style:parent-style-name"))
        chain.reverse()
        return chain

    def resolve_paragraph_style(self, style_name: str | None) -> ResolvedParagraphStyle:
        if style_name is None:
            return ResolvedParagraphStyle()
        if style_name in self._paragraph_cache:
            return self._paragraph_cache[style_name]

        result = ResolvedParagraphStyle()
        chain = self._style_chain(style_name)

        family_name = style_name
        for node in chain:
            display_name = node.get(qn("style:display-name")) or node.get(qn("style:name")) or ""
            underlying_name = node.get(qn("style:name")) or ""
            if underlying_name in HEADING1_STYLE_NAMES or display_name in HEADING1_STYLE_NAMES:
                result.is_heading1 = True
                result.kind = ParagraphKind.HEADING
            if underlying_name in QUOTE_STYLE_NAMES or display_name in QUOTE_STYLE_NAMES:
                result.kind = ParagraphKind.QUOTE

            parent = node.get(qn("style:parent-style-name"))
            if parent in QUOTE_STYLE_NAMES:
                result.kind = ParagraphKind.QUOTE

            props = node.find(qn("style:paragraph-properties"))
            if props is not None:
                align = props.get(qn("fo:text-align"))
                if align == "center":
                    result.align = ParagraphAlign.CENTER
                elif align == "end" or align == "right":
                    result.align = ParagraphAlign.RIGHT
                elif align == "justify":
                    result.align = ParagraphAlign.JUSTIFY
                elif align == "start" or align == "left":
                    result.align = ParagraphAlign.LEFT

                break_before = props.get(qn("fo:break-before"))
                if break_before == "page":
                    result.page_break_before = True
                elif break_before is not None:
                    result.page_break_before = False

                break_after = props.get(qn("fo:break-after"))
                if break_after == "page":
                    result.page_break_after = True
                elif break_after is not None:
                    result.page_break_after = False

        self._paragraph_cache[style_name] = result
        return result

    def resolve_graphic_style(self, style_name: str | None) -> ResolvedGraphicStyle:
        if style_name is None:
            return ResolvedGraphicStyle()
        if style_name in self._graphic_cache:
            return self._graphic_cache[style_name]

        result = ResolvedGraphicStyle()
        for node in self._style_chain(style_name):
            props = node.find(qn("style:graphic-properties"))
            if props is None:
                continue
            wrap = props.get(qn("style:wrap"))
            if wrap is not None:
                result.wrap = wrap

        self._graphic_cache[style_name] = result
        return result

    def resolve_text_style(self, style_name: str | None, inherited: CharFormat | None = None) -> CharFormat:
        """Résout un style de caractère en partant de `inherited` (le format déjà résolu du
        contexte englobant — paragraphe ou span parent) : chaque propriété n'est réécrite que
        si CE style la redéfinit explicitement, exactement comme LibreOffice Writer traite un
        style de caractère comme une surcharge partielle, jamais un remplacement complet."""
        base = inherited if inherited is not None else CharFormat()
        if style_name is None:
            return base

        bold = base.bold
        italic = base.italic
        underline = base.underline
        strikethrough = base.strikethrough
        vertical_align = base.vertical_align
        font_name = base.font_name

        for node in self._style_chain(style_name):
            props = node.find(qn("style:text-properties"))
            if props is None:
                continue
            weight = props.get(qn("fo:font-weight"))
            if weight is not None:
                bold = weight == "bold"
            style = props.get(qn("fo:font-style"))
            if style is not None:
                italic = style == "italic"
            underline_style = props.get(qn("style:text-underline-style"))
            if underline_style is not None:
                underline = underline_style != "none"
            strike_style = props.get(qn("style:text-line-through-style"))
            if strike_style is not None:
                strikethrough = strike_style != "none"
            pos = props.get(qn("style:text-position"))
            if pos is not None:
                token = pos.split(" ")[0]
                try:
                    percent = float(token.rstrip("%"))
                    if percent > 0:
                        vertical_align = VerticalAlign.SUPERSCRIPT
                    elif percent < 0:
                        vertical_align = VerticalAlign.SUBSCRIPT
                except ValueError:
                    pass
            name = props.get(qn("style:font-name")) or props.get(qn("fo:font-family"))
            if name:
                font_name = name.strip('"')

        return CharFormat(
            bold=bold,
            italic=italic,
            underline=underline,
            strikethrough=strikethrough,
            vertical_align=vertical_align,
            font_name=font_name,
        )

    def is_list_style_ordered(self, list_style_name: str | None, level: int = 1) -> bool:
        """Résout le type (numéroté/puce) du niveau ODF `level` (1-indexed, cf. text:level) d'un
        <text:list-style>. Un style de liste peut ne définir explicitement que certains niveaux
        (ODF l'autorise) : si `level` n'a pas de définition explicite, on retombe sur le plus grand
        niveau défini <= level (comportement d'affichage de Writer) ; si aucun niveau <= level n'est
        défini, False (puce) par défaut, comme avant ce correctif."""
        if list_style_name is None:
            return False
        node = self._style_nodes.get(list_style_name)
        if node is None:
            return False

        by_level: dict[int, bool] = {}
        for child in node:
            level_attr = child.get(qn("text:level"))
            if level_attr is None:
                continue
            try:
                child_level = int(level_attr)
            except ValueError:
                continue
            if child.tag == qn("text:list-level-style-number"):
                by_level[child_level] = True
            elif child.tag == qn("text:list-level-style-bullet"):
                by_level[child_level] = False

        if level in by_level:
            return by_level[level]
        fallback_levels = [lv for lv in by_level if lv <= level]
        if fallback_levels:
            return by_level[max(fallback_levels)]
        return False
