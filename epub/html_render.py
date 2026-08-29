import re
from html import escape

from model.assets import AssetStore
from model.document import Chapter, ImageAnchor, ImageWrap, Paragraph, Run, Table, iter_all_paragraphs
from model.styles import ParagraphAlign, ParagraphKind, VerticalAlign
from model.text_utils import flatten_to_single_line

LOCKED_FONT_CLASS_PREFIX = "epubeur-locked-font-"

_SLUG_INVALID_CHARS_RE = re.compile(r"[^a-z0-9]+")


def slugify_font_family(family: str) -> str:
    """Normalise un nom de famille en slug utilisable comme classe CSS : minuscules,
    non-alphanumériques -> '-', tronqué. N'est jamais reparsé pour retrouver le nom
    (la vérité reste dans la déclaration font-family du CSS) — sert uniquement de clé
    technique stable pour nommer une classe CSS par police figée."""
    slug = _SLUG_INVALID_CHARS_RE.sub("-", family.strip().lower()).strip("-")
    return (slug or "font")[:40]


def build_family_to_css_class(families: list[str]) -> dict[str, str]:
    """Calcule une classe CSS unique par famille, une seule fois pour toute une génération
    (pas à la volée par run) — déterministe entre deux builds identiques : les collisions de
    slug (deux familles différentes normalisées vers la même valeur) sont désambiguïsées par
    suffixe numérique calculé sur l'ordre de la liste passée en entrée."""
    family_to_css_class: dict[str, str] = {}
    used_classes: set[str] = set()
    for family in families:
        base_slug = slugify_font_family(family)
        css_class = f"{LOCKED_FONT_CLASS_PREFIX}{base_slug}"
        suffix = 2
        while css_class in used_classes:
            css_class = f"{LOCKED_FONT_CLASS_PREFIX}{base_slug}-{suffix}"
            suffix += 1
        used_classes.add(css_class)
        family_to_css_class[family] = css_class
    return family_to_css_class


def title_html_block(title: str) -> str:
    """Un titre peut contenir des '\\n' (saut de ligne manuel, Maj+Entrée dans Writer,
    voir odt/chapter_detector.py) : rendus en <br/> pour un vrai retour à la ligne visuel
    dans le corps de la page."""
    return "<br/>".join(escape(line) for line in title.split("\n"))


def title_single_line(title: str) -> str:
    """Version aplatie et échappée HTML d'un titre pour un contexte à ligne unique
    (balise <title> du head, infobulles, listes)."""
    return escape(flatten_to_single_line(title))


ALIGN_CLASS = {
    ParagraphAlign.LEFT: None,
    ParagraphAlign.RIGHT: "align-right",
    ParagraphAlign.CENTER: "align-center",
    ParagraphAlign.JUSTIFY: "align-justify",
}


def run_to_html(run: Run, family_to_css_class: dict[str, str] | None, inline_locked_font_style: bool = False) -> str:
    # Un saut de ligne manuel (Maj+Entrée dans Writer, text:line-break en ODT) est conservé
    # comme '\n' dans run.text — sans conversion, le HTML le collapse silencieusement
    # (aucun espace ni saut de ligne visible), exactement le même bug déjà corrigé sur les
    # titres de chapitre.
    text = "<br/>".join(escape(line) for line in run.text.split("\n"))
    if run.fmt.vertical_align == VerticalAlign.SUPERSCRIPT:
        text = f"<sup>{text}</sup>"
    elif run.fmt.vertical_align == VerticalAlign.SUBSCRIPT:
        text = f"<sub>{text}</sub>"
    if run.fmt.strikethrough:
        text = f"<s>{text}</s>"
    if run.fmt.underline:
        text = f"<u>{text}</u>"
    if run.fmt.italic:
        text = f"<em>{text}</em>"
    if run.fmt.bold:
        text = f"<strong>{text}</strong>"
    css_class = family_to_css_class.get(run.fmt.font_name) if family_to_css_class and run.fmt.font_name else None
    if css_class:
        # QTextBrowser (moteur Rich Text de Qt) applique bien font-family en style inline,
        # mais ignore les règles CSS basées sur une classe (vérifié) — un style inline est
        # ajouté en plus de la classe pour l'aperçu app, sans rien changer pour l'EPUB réel
        # (qui utilise le vrai @font-face + la classe .epubeur-locked-font-<slug>).
        style_attr = f' style="font-family: \'{escape(run.fmt.font_name)}\';"' if inline_locked_font_style else ""
        text = f'<span class="{css_class}"{style_attr} data-epubeur-locked-font="1">{text}</span>'
    if run.link_url:
        text = f'<a href="{escape(run.link_url)}">{text}</a>'
    if run.note_id:
        # <sup> : convention typographique standard pour un appel de note, numérique ou
        # alphabétique — appliquée ici plutôt que dans le CSS pour ne pas dépendre d'une classe.
        text = f'<sup><a epub:type="noteref" href="#note-{run.note_id}">{text}</a></sup>'
    return text


def _paragraph_inner_html(paragraph: Paragraph, family_to_css_class: dict[str, str] | None,
                           asset_store: AssetStore | None, inline_locked_font_style: bool,
                           image_alt_texts: dict[str, str] | None = None,
                           image_wraps: dict[str, ImageWrap] | None = None,
                           image_hrefs: dict[str, str] | None = None) -> str:
    """Contenu HTML interne d'un paragraphe (sans balise englobante p/li/blockquote) —
    factorisé pour être réutilisé à la fois par paragraph_to_html (cas simple, hors liste
    imbriquée) et par paragraphs_to_html (qui gère lui-même l'ouverture/fermeture de <li>
    pour permettre l'imbrication d'une sous-liste à l'intérieur)."""
    inner = "".join(run_to_html(r, family_to_css_class, inline_locked_font_style) for r in paragraph.runs)

    # Plusieurs images ancrées au même paragraphe (cas rare mais possible dans Writer : deux
    # images côte à côte dans la même ligne) rendent chacune leur propre <img>, dans l'ordre —
    # toutes préfixées au texte, comme le faisait déjà l'unique image historique.
    img_tags = "".join(
        _image_to_html_tag(image, asset_store, image_alt_texts, image_wraps, image_hrefs)
        for image in paragraph.all_images()
    )
    return img_tags + inner


def _image_to_html_tag(image: ImageAnchor, asset_store: AssetStore | None,
                        image_alt_texts: dict[str, str] | None,
                        image_wraps: dict[str, ImageWrap] | None,
                        image_hrefs: dict[str, str] | None) -> str:
    asset_id = image.asset_id
    extension = "png"
    if asset_store is not None:
        asset = asset_store.get(asset_id)
        if asset is not None:
            extension = asset.extension
    # image_alt_texts (Document.image_alt_texts, une description par asset_id, saisie dans
    # l'onglet Images) prime sur image.alt_text (le svg:desc brut lu à l'import ODT pour CETTE
    # occurrence précise) quand elle est renseignée — c'est la dernière intention explicite de
    # l'utilisateur dans l'app.
    alt_text = (image_alt_texts or {}).get(asset_id) or image.alt_text
    wrap = (image_wraps or {}).get(asset_id, ImageWrap.NONE)
    wrap_attr = f' data-epubeur-image-wrap="{wrap.value}"' if wrap != ImageWrap.NONE else ""
    # image_hrefs (calculé une fois pour tout le livre par epub/builder.py, avec gestion des
    # collisions de nom lisible) prime sur le repli "{asset_id}.{extension}" — le hash n'est
    # plus jamais le nom réellement écrit dans le zip EPUB une fois ce mapping fourni, seul
    # data-epubeur-image continue de porter l'asset_id (utilisé au réimport, cf.
    # epub/html_normalize.py::_find_all_image_anchors, indépendant du src=).
    href = (image_hrefs or {}).get(asset_id, f"{asset_id}.{extension}")
    return (f'<img src="../images/{href}" alt="{escape(alt_text)}" '
            f'data-epubeur-image="{asset_id}"{wrap_attr}/>')


def paragraph_to_html(paragraph: Paragraph, family_to_css_class: dict[str, str] | None = None,
                       asset_store: AssetStore | None = None, inline_locked_font_style: bool = False,
                       image_alt_texts: dict[str, str] | None = None,
                       image_wraps: dict[str, ImageWrap] | None = None,
                       image_hrefs: dict[str, str] | None = None) -> str:
    inner = _paragraph_inner_html(paragraph, family_to_css_class, asset_store, inline_locked_font_style,
                                   image_alt_texts, image_wraps, image_hrefs)

    align_class = ALIGN_CLASS.get(paragraph.align)
    classes = []
    if align_class:
        classes.append(align_class)

    if paragraph.kind == ParagraphKind.QUOTE:
        class_attr = f' class="{" ".join(classes)}"' if classes else ""
        return f"<blockquote{class_attr}><p>{inner}</p></blockquote>"

    if paragraph.kind in (ParagraphKind.LIST_ITEM_BULLET, ParagraphKind.LIST_ITEM_NUMBER):
        return f"<li>{inner}</li>"

    class_attr = f' class="{" ".join(classes)}"' if classes else ""
    return f"<p{class_attr}>{inner}</p>"


def table_to_html(table: Table, family_to_css_class: dict[str, str] | None = None,
                   asset_store: AssetStore | None = None, inline_locked_font_style: bool = False,
                   image_alt_texts: dict[str, str] | None = None,
                   image_wraps: dict[str, ImageWrap] | None = None,
                   image_hrefs: dict[str, str] | None = None) -> str:
    """Une cellule peut contenir plusieurs paragraphes (Writer autorise plusieurs lignes de
    texte dans une même cellule) : chacun est rendu via paragraph_to_html (même logique que le
    corps du chapitre), concaténés directement dans <td>/<th>. colspan/rowspan ne sont émis QUE
    s'ils dépassent 1 (comportement HTML par défaut identique à colspan=1/rowspan=1, pas besoin
    de les répéter partout et d'alourdir le HTML généré)."""
    rows_html = []
    for row in table.rows:
        cells_html = []
        for cell in row.cells:
            tag = "th" if cell.is_header else "td"
            attrs = ""
            if cell.colspan > 1:
                attrs += f' colspan="{cell.colspan}"'
            if cell.rowspan > 1:
                attrs += f' rowspan="{cell.rowspan}"'
            inner = "".join(
                paragraph_to_html(p, family_to_css_class, asset_store, inline_locked_font_style,
                                   image_alt_texts, image_wraps, image_hrefs)
                for p in cell.paragraphs
            )
            cells_html.append(f"<{tag}{attrs}>{inner}</{tag}>")
        rows_html.append(f"<tr>{''.join(cells_html)}</tr>")
    return f"<table>{''.join(rows_html)}</table>"


def paragraphs_to_html(paragraphs: "list[Paragraph | Table]", family_to_css_class: dict[str, str] | None = None,
                        asset_store: AssetStore | None = None, inline_locked_font_style: bool = False,
                        image_alt_texts: dict[str, str] | None = None,
                        image_wraps: dict[str, ImageWrap] | None = None,
                        image_hrefs: dict[str, str] | None = None) -> str:
    """Groupe les paragraphes de type liste en <ul>/<ol> imbriqués selon list_level (une sous-liste
    ODF produit une balise <ul>/<ol> réellement imbriquée dans le <li> parent, pas aplatie), et ouvre
    une nouvelle balise à chaque rupture de list_group_id à niveau égal (deux listes ODF adjacentes du
    même type ne sont jamais fusionnées en une seule liste continue). `stack` retient, du plus extérieur
    au plus profond, un triplet (level, kind, group_id) par niveau de liste actuellement ouvert — le
    <li> ouvert au niveau le plus profond de la pile n'est fermé (</li>) que juste avant qu'un nouvel
    élément de niveau égal ou inférieur ne s'écrive, jamais avant : c'est ce qui laisse une sous-liste
    s'insérer valablement à l'intérieur (<li>texte<ul>...</ul></li>, jamais des balises frères)."""
    parts: list[str] = []
    stack: list[tuple[int, ParagraphKind, str | None]] = []
    li_open = False  # un <li> est ouvert au niveau le plus profond de `stack`, pas encore fermé

    def same_list(entry: tuple[int, ParagraphKind, str | None], level: int, kind: ParagraphKind,
                  group_id: str | None) -> bool:
        """Deux paragraphes appartiennent à la même balise <ul>/<ol> ssi même level, même kind, et
        même list_group_id — sauf si les deux group_id sont None (paragraphes issus d'un projet
        sauvegardé avant l'introduction du champ) : on retombe alors sur l'ancien comportement,
        fusion par simple contiguïté de level/kind, jamais de rupture artificielle."""
        entry_level, entry_kind, entry_group = entry
        if entry_level != level or entry_kind != kind:
            return False
        if entry_group is None and group_id is None:
            return True
        return entry_group is not None and group_id is not None and entry_group == group_id

    def close_li_if_open() -> None:
        nonlocal li_open
        if li_open:
            parts.append("</li>")
            li_open = False

    def pop_to(level: int) -> None:
        """Ferme tout niveau de pile strictement plus profond que `level` (</li> puis </ul> ou
        </ol> pour chacun), et laisse `li_open` refléter l'état du niveau restant (son <li> était
        ouvert avant qu'on y insère la sous-liste qu'on vient de fermer : il l'est donc encore)."""
        nonlocal li_open
        while stack and stack[-1][0] > level:
            close_li_if_open()
            _, kind, _ = stack.pop()
            tag = "ul" if kind == ParagraphKind.LIST_ITEM_BULLET else "ol"
            parts.append(f"</{tag}>")
            li_open = bool(stack)

    def open_new_list(level: int, kind: ParagraphKind, group_id: str | None) -> None:
        tag = "ul" if kind == ParagraphKind.LIST_ITEM_BULLET else "ol"
        parts.append(f"<{tag}>")
        stack.append((level, kind, group_id))

    def close_all_lists() -> None:
        pop_to(0)

    for para in paragraphs:
        if isinstance(para, Table):
            close_all_lists()
            parts.append(table_to_html(para, family_to_css_class, asset_store, inline_locked_font_style,
                                        image_alt_texts, image_wraps, image_hrefs))
            continue

        is_list = para.kind in (ParagraphKind.LIST_ITEM_BULLET, ParagraphKind.LIST_ITEM_NUMBER)

        if not is_list:
            close_all_lists()
            parts.append(paragraph_to_html(para, family_to_css_class, asset_store, inline_locked_font_style,
                                            image_alt_texts, image_wraps, image_hrefs))
            continue

        level = para.list_level if para.list_level > 0 else 1
        kind = para.kind
        group_id = para.list_group_id

        if stack and stack[-1][0] > level:
            pop_to(level)

        if stack and stack[-1][0] == level:
            if same_list(stack[-1], level, kind, group_id):
                close_li_if_open()
            else:
                pop_to(level - 1)
                open_new_list(level, kind, group_id)
        else:
            open_new_list(level, kind, group_id)

        inner = _paragraph_inner_html(para, family_to_css_class, asset_store, inline_locked_font_style,
                                       image_alt_texts, image_wraps, image_hrefs)
        parts.append(f"<li>{inner}")
        li_open = True

    close_all_lists()
    return "".join(parts)


def part_title_page_to_xhtml(part_title: str, css_href: str) -> str:
    """Page de garde de partie : titre seul, centré horizontalement et verticalement.
    Le centrage est porté par le <div> (pas par <body>) : ebooklib régénère <body> à
    l'écriture du zip et ne conserve que ses enfants, en perdant tout attribut posé
    directement sur la balise <body> elle-même."""
    return f"""<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
<title>{escape(part_title)}</title>
<link rel="stylesheet" type="text/css" href="{css_href}"/>
</head>
<body>
<div class="epubeur-part-title-page">
<h1 data-epubeur-part-title="1">{escape(part_title)}</h1>
</div>
</body>
</html>"""


def back_cover_page_to_xhtml(image_href: str, css_href: str) -> str:
    """Page de 4e de couverture : image seule, centrée pleine page. Le centrage est porté par
    le <div> (pas par <body>), même contrainte qu'ailleurs — ebooklib régénère <body> à
    l'écriture du zip et ne conserve que ses enfants, en perdant tout attribut posé
    directement sur la balise <body> elle-même."""
    return f"""<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
<title>4e de couverture</title>
<link rel="stylesheet" type="text/css" href="{css_href}"/>
</head>
<body>
<div class="epubeur-back-cover-page">
<img src="{escape(image_href)}" alt="4e de couverture" data-epubeur-back-cover="1"/>
</div>
</body>
</html>"""


def footnotes_html(segment_paragraphs: "list[Paragraph | Table]", document_footnotes: dict[str, list[Paragraph]],
                    family_to_css_class: dict[str, str] | None = None, asset_store: AssetStore | None = None,
                    inline_locked_font_style: bool = False, image_alt_texts: dict[str, str] | None = None,
                    image_wraps: dict[str, ImageWrap] | None = None,
                    image_hrefs: dict[str, str] | None = None) -> str:
    """Rend les corps de note (<aside epub:type="footnote">) des SEULS Run.note_id rencontrés dans
    segment_paragraphs (jamais tout document_footnotes) — garantit que l'ancre #note-id reste
    toujours dans le même fichier XHTML que son appel, condition nécessaire pour que
    check_internal_link_integrity valide les liens sans modification. Ordre des <aside> = ordre de
    première apparition du run d'appel dans le segment (ordre de lecture)."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for para in iter_all_paragraphs(segment_paragraphs):
        for run in para.runs:
            if run.note_id and run.note_id not in seen_set:
                seen.append(run.note_id)
                seen_set.add(run.note_id)

    if not seen:
        return ""

    parts: list[str] = []
    for note_id in seen:
        note_paragraphs = document_footnotes.get(note_id)
        if note_paragraphs is None:
            continue  # incohérence de données : ne devrait jamais arriver en pratique
        inner = paragraphs_to_html(note_paragraphs, family_to_css_class, asset_store,
                                    inline_locked_font_style, image_alt_texts, image_wraps, image_hrefs)
        parts.append(f'<aside epub:type="footnote" id="note-{note_id}">{inner}</aside>')
    return "".join(parts)


def chapter_to_xhtml(chapter: Chapter, css_href: str, family_to_css_class: dict[str, str] | None = None,
                      asset_store: AssetStore | None = None, paragraphs: list[Paragraph] | None = None,
                      include_title: bool = True, segment_index: int = 0,
                      image_alt_texts: dict[str, str] | None = None,
                      document_footnotes: dict[str, list[Paragraph]] | None = None,
                      image_wraps: dict[str, ImageWrap] | None = None,
                      image_hrefs: dict[str, str] | None = None) -> str:
    """Un chapitre peut être scindé en plusieurs fichiers XHTML (un par saut de page manuel
    interne, cf. Paragraph.page_break_before) : `paragraphs` restreint le rendu à un segment
    donné (défaut : tout le chapitre), `include_title` n'inclut le <h1> que sur le premier
    segment, `segment_index` (0 = premier) est exposé au réimport pour reconstituer l'ordre."""
    title_html = ""
    if include_title and chapter.title_visible and chapter.title:
        title_html = f'<h1 data-epubeur-chapter-title="1">{title_html_block(chapter.title)}</h1>'

    segment_paragraphs = paragraphs if paragraphs is not None else chapter.paragraphs
    body_html = paragraphs_to_html(segment_paragraphs, family_to_css_class, asset_store,
                                    image_alt_texts=image_alt_texts, image_wraps=image_wraps,
                                    image_hrefs=image_hrefs)

    # Corps des notes appelées DANS ce segment précis, rendues en fin de fichier (jamais réparties
    # entre plusieurs fichiers) — c'est ce qui garantit que l'ancre #note-id reste toujours dans le
    # même document XHTML que le lien qui la référence, seule façon de satisfaire
    # check_internal_link_integrity sans ancre inter-fichiers.
    footnotes_block = footnotes_html(segment_paragraphs, document_footnotes or {}, family_to_css_class,
                                      asset_store, image_alt_texts=image_alt_texts, image_wraps=image_wraps,
                                      image_hrefs=image_hrefs)

    segment_attr = f' data-epubeur-segment-index="{segment_index}"' if segment_index > 0 else ""

    # data-epubeur-chapter-id (et segment_attr) sont posés sur un <div> enfant, jamais sur
    # <body> lui-même : ebooklib régénère entièrement <body> à l'écriture du zip et ne conserve
    # que ses enfants, perdant tout attribut posé directement dessus (même piège déjà résolu
    # pour data-epubeur-part-title et data-epubeur-back-cover, eux aussi sur un enfant).
    return f"""<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
<title>{title_single_line(chapter.title or "Chapitre")}</title>
<link rel="stylesheet" type="text/css" href="{css_href}"/>
</head>
<body>
<div class="epubeur-chapter" data-epubeur-chapter-id="{chapter.id}"{segment_attr}>
{title_html}
{body_html}
{footnotes_block}
</div>
</body>
</html>"""
