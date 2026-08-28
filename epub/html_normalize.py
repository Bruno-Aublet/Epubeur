from bs4 import BeautifulSoup, NavigableString, Tag

from epub.css_resolve import CssResolver
from model.document import ImageAnchor, ImageWrap, Paragraph, Run, Table, TableCell, TableRow, new_id
from model.styles import CharFormat, ParagraphAlign, ParagraphKind

SEMANTIC_BOLD_TAGS = {"b", "strong"}
SEMANTIC_ITALIC_TAGS = {"i", "em"}
SEMANTIC_UNDERLINE_TAGS = {"u", "ins"}
SEMANTIC_STRIKE_TAGS = {"s", "strike", "del"}
SEMANTIC_SUP_TAGS = {"sup"}
SEMANTIC_SUB_TAGS = {"sub"}

ALIGN_VALUES = {
    "left": ParagraphAlign.LEFT,
    "right": ParagraphAlign.RIGHT,
    "center": ParagraphAlign.CENTER,
    "justify": ParagraphAlign.JUSTIFY,
}

BLOCK_TAGS = {"p", "div", "li", "blockquote"}


def _apply_semantic_tag(fmt: CharFormat, tag_name: str, classes: list[str]) -> CharFormat:
    bold = fmt.bold or tag_name in SEMANTIC_BOLD_TAGS
    italic = fmt.italic or tag_name in SEMANTIC_ITALIC_TAGS
    underline = fmt.underline or tag_name in SEMANTIC_UNDERLINE_TAGS
    strikethrough = fmt.strikethrough or tag_name in SEMANTIC_STRIKE_TAGS
    vertical_align = fmt.vertical_align
    if tag_name in SEMANTIC_SUP_TAGS:
        from model.styles import VerticalAlign
        vertical_align = VerticalAlign.SUPERSCRIPT
    elif tag_name in SEMANTIC_SUB_TAGS:
        from model.styles import VerticalAlign
        vertical_align = VerticalAlign.SUBSCRIPT

    # La résolution du nom de police (y compris pour une police figée, via les classes
    # .epubeur-locked-font-<slug>) est déjà entièrement prise en charge par
    # css_resolver.resolve_element_format() en amont — celui-ci lit font-family depuis
    # n'importe quelle classe CSS présente, générique, pas besoin de la redéfinir ici.
    return CharFormat(
        bold=bold,
        italic=italic,
        underline=underline,
        strikethrough=strikethrough,
        vertical_align=vertical_align,
        font_name=fmt.font_name,
    )


def _collect_note_ref_runs(anchor_el, css_resolver: CssResolver, inherited: CharFormat) -> list[Run]:
    """Reconstruit les Run d'un appel de note (<a epub:type="noteref" href="#note-...">) —
    l'id HTML brut extrait ici (après le préfixe "note-") sera régénéré via new_id() par la passe
    de fusion de html_to_paragraphs/import_epub, jamais réutilisé tel quel, pour éviter toute
    collision entre deux segments/chapitres réimportés séparément qui auraient par hasard le même
    suffixe."""
    href = anchor_el.get("href")
    html_note_id = (href or "").lstrip("#")
    if html_note_id.startswith("note-"):
        html_note_id = html_note_id[len("note-"):]
    inner_runs = _collect_runs(anchor_el, css_resolver, inherited)
    return [Run(text=r.text, fmt=r.fmt, note_id=html_note_id) for r in inner_runs]


def _collect_runs(node, css_resolver: CssResolver, inherited: CharFormat) -> list[Run]:
    runs: list[Run] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            text = str(child)
            if text:
                runs.append(Run(text=text, fmt=inherited))
        elif isinstance(child, Tag):
            tag_name = child.name.lower()
            if tag_name in ("img", "ul", "ol", "table"):
                # une sous-liste imbriquée dans un <li> est traitée séparément par visit()
                # (récursion dédiée), de même qu'un <table> imbriqué par erreur — jamais
                # avalés ici comme texte brut.
                continue
            if tag_name == "br":
                # symétrique de html_render.run_to_html : un <br/> à l'intérieur d'un
                # paragraphe redevient '\n', pour préserver un saut de ligne manuel au round-trip.
                runs.append(Run(text="\n", fmt=inherited))
                continue
            if tag_name == "sup":
                only_child = child.contents[0] if len(child.contents) == 1 else None
                if (isinstance(only_child, Tag) and only_child.name.lower() == "a"
                        and "noteref" in (only_child.get("epub:type") or "").split()):
                    # <sup><a epub:type="noteref">...</a></sup> : artefact de présentation ajouté
                    # par run_to_html pour un appel de note, jamais un vrai style "exposant" du
                    # modèle d'origine — on descend directement dans le <a> sans appliquer
                    # SUPERSCRIPT, pour ne pas corrompre le round-trip d'un run de note.
                    runs.extend(_collect_note_ref_runs(only_child, css_resolver, inherited))
                    continue
                # sinon : laisser tomber dans la branche générique de fin de boucle
            if tag_name == "a":
                epub_type = child.get("epub:type") or ""
                if "noteref" in epub_type.split():
                    runs.extend(_collect_note_ref_runs(child, css_resolver, inherited))
                    continue
                href = child.get("href")
                inner_runs = _collect_runs(child, css_resolver, inherited)
                if href:
                    inner_runs = [Run(text=r.text, fmt=r.fmt, link_url=href) for r in inner_runs]
                runs.extend(inner_runs)
                continue
            classes = _classes_of(child)
            inline_style = child.get("style")
            fmt = css_resolver.resolve_element_format(tag_name, classes, inline_style, inherited)
            fmt = _apply_semantic_tag(fmt, tag_name, classes)
            runs.extend(_collect_runs(child, css_resolver, fmt))
    return runs


def _classes_of(el) -> list[str]:
    """BeautifulSoup renvoie 'class' comme liste avec le parser HTML, mais comme
    chaîne unique avec le parser XML (lxml-xml) — on normalise toujours en liste."""
    raw = el.get("class")
    if raw is None:
        return []
    if isinstance(raw, str):
        return raw.split()
    return list(raw)


def _find_image_anchor(node) -> str | None:
    img = node.find("img")
    if img is None:
        return None
    return img.get("data-epubeur-image") or img.get("src")


def _find_image_wrap(node) -> ImageWrap:
    img = node.find("img")
    if img is None:
        return ImageWrap.NONE
    raw = img.get("data-epubeur-image-wrap")
    return {"left": ImageWrap.LEFT, "right": ImageWrap.RIGHT}.get(raw, ImageWrap.NONE)


def _int_attr(el, name: str, default: int) -> int:
    raw = el.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _table_from_html(table_el, css_resolver: CssResolver) -> Table:
    """Reconstruit une Table pivot depuis un <table> HTML. Cherche les <tr> directement, que le
    HTML source les regroupe ou non sous <thead>/<tbody> (find_all sur les <tr>, pas de
    dépendance à la présence de ces conteneurs intermédiaires — un <table> généré par Epubeur
    lui-même n'en a jamais, cf. epub.html_render.table_to_html, mais un EPUB EXTERNE réimporté
    peut légitimement en avoir)."""
    rows: list[TableRow] = []
    for tr in table_el.find_all("tr"):
        cells: list[TableCell] = []
        for cell_el in tr.find_all(["td", "th"], recursive=False):
            is_header = cell_el.name.lower() == "th"
            colspan = _int_attr(cell_el, "colspan", 1)
            rowspan = _int_attr(cell_el, "rowspan", 1)
            inner_paragraphs: list[Paragraph] = []
            child_blocks = cell_el.find_all(["p", "blockquote"], recursive=False)
            if child_blocks:
                for child in child_blocks:
                    if child.name.lower() == "blockquote":
                        inner_p = child.find("p") or child
                        base_fmt = css_resolver.resolve_element_format("p", _classes_of(inner_p),
                                                                        inner_p.get("style"), CharFormat())
                        runs = _collect_runs(inner_p, css_resolver, base_fmt)
                        inner_paragraphs.append(Paragraph(kind=ParagraphKind.QUOTE, runs=runs))
                    else:
                        base_fmt = css_resolver.resolve_element_format("p", _classes_of(child),
                                                                        child.get("style"), CharFormat())
                        runs = _collect_runs(child, css_resolver, base_fmt)
                        image_href = _find_image_anchor(child)
                        image_anchor = ImageAnchor(asset_id=image_href) if image_href else None
                        inner_paragraphs.append(Paragraph(kind=ParagraphKind.BODY, runs=runs, image=image_anchor))
            else:
                # Cellule sans <p> interne (texte nu direct dans <td>, cas EPUB externe généré
                # par un autre outil) : un seul Paragraph de secours reconstruit à partir de
                # tout le texte/inline direct de la cellule.
                base_fmt = css_resolver.resolve_element_format(cell_el.name.lower(), _classes_of(cell_el),
                                                                 cell_el.get("style"), CharFormat())
                runs = _collect_runs(cell_el, css_resolver, base_fmt)
                inner_paragraphs.append(Paragraph(kind=ParagraphKind.BODY, runs=runs))
            cells.append(TableCell(paragraphs=inner_paragraphs, colspan=colspan, rowspan=rowspan,
                                    is_header=is_header))
        rows.append(TableRow(cells=cells))
    return Table(rows=rows)


def _visit_container(container, css_resolver: CssResolver, paragraphs: "list[Paragraph | Table]",
                      local_image_wraps: dict[str, ImageWrap], list_level: int = 0) -> None:
    """Parcourt les enfants directs de `container` et accumule le résultat dans `paragraphs`/
    `local_image_wraps` (paramètres de sortie mutables, remplis par effet de bord) — logique
    commune au corps principal d'un chapitre ET au corps de chaque note (<aside>), pour qu'une
    note bénéficie exactement du même traitement (listes, tableaux, images) qu'un chapitre :
    avant ce correctif, le corps d'une note n'était reconstruit qu'à partir de <p>/<blockquote>
    (cf. historique), perdant silencieusement toute liste/tableau/image qu'une note peut
    pourtant légitimement contenir (le rendu, lui, les autorise sans restriction)."""
    for el in container.find_all(recursive=False):
        tag_name = el.name.lower()
        if tag_name == "aside":
            epub_type = el.get("epub:type") or ""
            if "footnote" in epub_type.split():
                continue  # note de bas de page : traitée séparément par _footnotes_from_html
            # <aside> générique (encart, remarque en marge — pas une note) : un EPUB EXTERNE
            # peut légitimement en produire un, distinct du epub:type="footnote" qu'Epubeur
            # génère elle-même. Avant ce correctif, TOUT <aside> était sauté inconditionnellement
            # ici, et _footnotes_from_html ne traite que ceux avec epub:type="footnote" — un
            # <aside> générique n'était donc traité NULLE PART, perte silencieuse totale de son
            # contenu. Traité ici comme un conteneur transparent, comme <section>.
            _visit_container(el, css_resolver, paragraphs, local_image_wraps, list_level)
            continue
        if tag_name in ("h1", "h2", "h3"):
            continue  # titre de chapitre géré séparément
        if tag_name in ("section", "article"):
            # Conteneurs structurels HTML5 sans équivalent dans le modèle pivot (pas de notion de
            # "section"/"article" — juste une séquence de blocs) : traversés comme un conteneur
            # transparent, symétrique de text:section côté lecture ODT (odt/chapter_detector.py).
            # Un EPUB EXTERNE (produit par un autre logiciel : Calibre, Sigil...) en contient
            # fréquemment pour découper un chapitre en sous-parties — sans cette branche, tout
            # leur contenu disparaissait silencieusement (aucune autre branche ne les reconnaît).
            _visit_container(el, css_resolver, paragraphs, local_image_wraps, list_level)
            continue
        if tag_name == "figure":
            # <figure> (image + légende sémantique HTML5) : pas de notion de légende dans le
            # modèle pivot — traversé comme un conteneur transparent ; son <img> est capté par la
            # branche "p" si la légende est un <figcaption>/<p>, ou par la récursion générique.
            # Avant ce correctif, <figure> n'était reconnu nulle part : perte totale (image ET
            # légende), pas de fallback générique en mode "bloc" contrairement au mode inline.
            _visit_container(el, css_resolver, paragraphs, local_image_wraps, list_level)
            continue
        if tag_name == "figcaption":
            base_fmt = css_resolver.resolve_element_format("p", _classes_of(el), el.get("style"), CharFormat())
            runs = _collect_runs(el, css_resolver, base_fmt)
            paragraphs.append(Paragraph(kind=ParagraphKind.BODY, align=ParagraphAlign.LEFT, runs=runs))
            continue
        if tag_name in ("ul", "ol"):
            kind = ParagraphKind.LIST_ITEM_BULLET if tag_name == "ul" else ParagraphKind.LIST_ITEM_NUMBER
            group_id = new_id()
            for li in el.find_all("li", recursive=False):
                base_fmt = css_resolver.resolve_element_format("li", _classes_of(li),
                                                                 li.get("style"), CharFormat())
                runs = _collect_runs(li, css_resolver, base_fmt)
                paragraphs.append(Paragraph(kind=kind, align=ParagraphAlign.LEFT, runs=runs,
                                             list_level=list_level + 1, list_group_id=group_id))
                # Sous-liste(s) imbriquée(s) directement dans ce <li> : récursion, produit les
                # paragraphes de niveau list_level+2 (ou plus) juste après celui du <li> parent,
                # dans l'ordre du document.
                _visit_container(li, css_resolver, paragraphs, local_image_wraps, list_level + 1)
        elif tag_name == "blockquote":
            inner_p = el.find("p") or el
            classes = _classes_of(inner_p)
            base_fmt = css_resolver.resolve_element_format("p", classes, inner_p.get("style"), CharFormat())
            runs = _collect_runs(inner_p, css_resolver, base_fmt)
            paragraphs.append(Paragraph(kind=ParagraphKind.QUOTE, align=ParagraphAlign.LEFT, runs=runs))
        elif tag_name == "p":
            classes = _classes_of(el)
            align = ParagraphAlign.LEFT
            for cls in classes:
                if cls == "align-center":
                    align = ParagraphAlign.CENTER
                elif cls == "align-right":
                    align = ParagraphAlign.RIGHT
                elif cls == "align-justify":
                    align = ParagraphAlign.JUSTIFY
            style_attr = el.get("style") or ""
            if "text-align" in style_attr:
                for value, enum_val in ALIGN_VALUES.items():
                    if value in style_attr:
                        align = enum_val
                        break

            base_fmt = css_resolver.resolve_element_format("p", classes, el.get("style"), CharFormat())
            runs = _collect_runs(el, css_resolver, base_fmt)

            image_href = _find_image_anchor(el)
            image_anchor = ImageAnchor(asset_id=image_href) if image_href else None
            if image_href:
                wrap = _find_image_wrap(el)
                if wrap != ImageWrap.NONE:
                    local_image_wraps[image_href] = wrap

            paragraphs.append(Paragraph(kind=ParagraphKind.BODY, align=align, runs=runs, image=image_anchor))
        elif tag_name == "table":
            paragraphs.append(_table_from_html(el, css_resolver))


def _footnotes_from_html(container_root, css_resolver: CssResolver,
                          local_image_wraps: dict[str, ImageWrap]) -> dict[str, list[Paragraph]]:
    """Collecte tous les <aside epub:type="footnote" id="..."> du segment (peu importe leur
    position dans le DOM, en pratique toujours en fin de <div class="epubeur-chapter">) — chaque
    corps est reconstitué via _visit_container, EXACTEMENT la même logique que le corps d'un
    chapitre (listes, tableaux, images compris, pas seulement <p>/<blockquote>). Clés = id HTML
    brut extrait du href, PAS encore régénéré en note_id final stable (cf.
    epub/importer.py::import_epub). local_image_wraps est partagé avec le corps principal
    (paramètre de sortie mutable) : un asset_id peut légitimement apparaître à la fois dans le
    corps et dans une note, la clé href/asset_id brut restant la même dans les deux cas."""
    local_footnotes: dict[str, list[Paragraph]] = {}
    for aside in container_root.find_all("aside", recursive=False):
        epub_type = aside.get("epub:type") or ""
        if "footnote" not in epub_type.split():
            continue
        aside_id = aside.get("id") or ""
        html_note_id = aside_id[len("note-"):] if aside_id.startswith("note-") else aside_id
        if not html_note_id:
            continue
        note_paragraphs: "list[Paragraph | Table]" = []
        _visit_container(aside, css_resolver, note_paragraphs, local_image_wraps)
        # Le corps d'une note reste list[Paragraph] pur dans le modèle pivot (jamais de Table
        # imbriquée, cf. Document.footnotes) : un <table> dans une note (cas exotique, symétrique
        # du hors-scope déjà accepté côté lecture ODT) est ici filtré plutôt que de faire planter
        # tout le réimport — silencieusement ignoré, pas de perte du RESTE du corps de la note.
        local_footnotes[html_note_id] = [p for p in note_paragraphs if isinstance(p, Paragraph)]
    return local_footnotes


def html_to_paragraphs(xhtml: str, css_resolver: CssResolver) -> "tuple[list[Paragraph | Table], dict[str, list[Paragraph]], dict[str, ImageWrap]]":
    """Convertit le corps d'un chapitre XHTML en liste de Paragraph, en reconnaissant
    balises sémantiques + classes CSS + style inline (résolution complète, pas de fallback brut).
    Retourne aussi le dict des notes locales à CE fichier XHTML (cf. _footnotes_from_html) et le
    dict des habillages d'image locaux (clé = href/asset_id brut tel qu'il apparaît dans le HTML,
    PAS encore remappé) — la régénération en note_id final stable et le remappage href->asset_id
    ont lieu au niveau appelant (epub/importer.py::import_epub), pour garantir l'unicité entre
    plusieurs fichiers/segments réimportés séparément."""
    soup = BeautifulSoup(xhtml, "lxml-xml" if "<?xml" in xhtml[:100] else "lxml")
    body = soup.find("body")
    if body is None:
        return [], {}, {}
    # Un EPUB généré par Epubeur place le contenu dans un <div class="epubeur-chapter"> enfant
    # de <body> (jamais directement sur <body>, qu'ebooklib régénère en ne gardant que ses
    # enfants à l'écriture du zip) — viser ce conteneur si présent. Un EPUB externe n'a pas ce
    # <div> : body reste le conteneur direct, comportement inchangé.
    container_root = body.find("div", class_="epubeur-chapter", recursive=False) or body

    local_image_wraps: dict[str, ImageWrap] = {}
    local_footnotes = _footnotes_from_html(container_root, css_resolver, local_image_wraps)

    paragraphs: "list[Paragraph | Table]" = []
    _visit_container(container_root, css_resolver, paragraphs, local_image_wraps)
    return paragraphs, local_footnotes, local_image_wraps
