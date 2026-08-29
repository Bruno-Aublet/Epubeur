import copy
import hashlib

from model.assets import AssetRole, AssetStore
from model.document import (
    Chapter,
    ImageAnchor,
    ImageWrap,
    Paragraph,
    Run,
    Table,
    TableCell,
    TableRow,
    iter_all_paragraphs,
    new_id,
)
from model.styles import CharFormat, ParagraphKind
from odt.reader import OdtSource, qn
from odt.styles_cascade import StyleResolver

LIST_ITEM_TAG = qn("text:list-item")
LIST_TAG = qn("text:list")
PARAGRAPH_TAG = qn("text:p")
HEADING_TAG = qn("text:h")
SPAN_TAG = qn("text:span")
LINK_TAG = qn("text:a")
FRAME_TAG = qn("draw:frame")
IMAGE_TAG = qn("draw:image")
LINE_BREAK_TAG = qn("text:line-break")
STYLE_NAME_ATTR = qn("text:style-name")
LIST_STYLE_NAME_ATTR = qn("text:style-name")
TABLE_TAG = qn("table:table")
TABLE_ROW_TAG = qn("table:table-row")
TABLE_CELL_TAG = qn("table:table-cell")
COVERED_TABLE_CELL_TAG = qn("table:covered-table-cell")
HEADER_ROWS_TAG = qn("table:table-header-rows")
COLUMNS_REPEATED_ATTR = qn("table:number-columns-repeated")
ROWS_REPEATED_ATTR = qn("table:number-rows-repeated")
COLUMNS_SPANNED_ATTR = qn("table:number-columns-spanned")
ROWS_SPANNED_ATTR = qn("table:number-rows-spanned")
NOTE_TAG = qn("text:note")
NOTE_CITATION_TAG = qn("text:note-citation")
NOTE_BODY_TAG = qn("text:note-body")
SECTION_TAG = qn("text:section")
TEXT_BOX_TAG = qn("draw:text-box")


def _iter_runs(elem, resolver: StyleResolver, inherited: CharFormat, source: OdtSource,
                asset_store: AssetStore | None, document_footnotes: dict[str, list[Paragraph]],
                image_wraps: dict[str, ImageWrap]) -> list[Run]:
    """Parcourt récursivement le contenu d'un <text:p>/<text:h>, produit des Run.
    `inherited` est le format déjà résolu du contexte englobant (paragraphe ou span parent) :
    un style de caractère (span) n'est jamais un remplacement complet, seulement une surcharge
    partielle — sans propager `inherited`, un span qui ne redéfinit QUE le gras (par exemple)
    perdait entièrement la police du paragraphe englobant, alors que Writer l'affiche avec.
    <text:line-break/> (saut de ligne manuel, Maj+Entrée dans Writer) est traduit en '\\n'
    dans le texte du run — sans ça, les deux fragments de texte de part et d'autre du saut
    de ligne se retrouvaient simplement concaténés sans aucun séparateur.

    Suivi des modifications (text:change-start/text:change-end/text:change) : ni reconnus ni
    traités spécifiquement, mais le comportement résultant est correct et voulu — vérifié
    empiriquement sur une fixture reproduisant la structure ODF réelle. Le texte INSÉRÉ en
    attente de relecture reste en clair dans le paragraphe (entouré des marqueurs start/end,
    jamais un enfant du paragraphe lui-même) : son `.tail` est récupéré comme n'importe quel
    autre texte, donc il apparaît normalement. Le texte SUPPRIMÉ en attente est stocké par ODF
    dans text:tracked-changes/text:changed-region/text:deletion (hors du flux du paragraphe,
    jamais lu ici) : il n'apparaît jamais. Net : un export EPUB traite implicitement toutes les
    modifications en attente comme déjà acceptées (insertions gardées, suppressions retirées) —
    c'est le comportement le plus sensé pour un export final, pas une perte accidentelle."""
    runs: list[Run] = []
    fmt = inherited
    if elem.text:
        runs.append(Run(text=elem.text, fmt=fmt))
    for child in elem:
        if child.tag == SPAN_TAG:
            style_name = child.get(STYLE_NAME_ATTR)
            span_fmt = resolver.resolve_text_style(style_name, inherited=fmt)
            runs.extend(_iter_runs(child, resolver, span_fmt, source, asset_store, document_footnotes,
                                    image_wraps))
        elif child.tag == LINK_TAG:
            href = child.get(qn("xlink:href"))
            inner_runs = _iter_runs(child, resolver, fmt, source, asset_store, document_footnotes, image_wraps)
            if href:
                inner_runs = [Run(text=r.text, fmt=r.fmt, link_url=href) for r in inner_runs]
            runs.extend(inner_runs)
        elif child.tag == LINE_BREAK_TAG:
            runs.append(Run(text="\n", fmt=fmt))
        elif child.tag == NOTE_TAG:
            # text:note-class ("footnote"/"endnote") n'est jamais lu : décision actée, les deux
            # types se rendent identiquement (<aside epub:type="footnote">) dans le modèle pivot.
            citation_elem = child.find(NOTE_CITATION_TAG)
            citation_text = citation_elem.text if citation_elem is not None and citation_elem.text else ""
            note_id = new_id()
            note_paragraphs: list[Paragraph] = []
            body_elem = child.find(NOTE_BODY_TAG)
            if body_elem is not None:
                _walk_body(body_elem, resolver, source, asset_store, note_paragraphs, document_footnotes,
                           image_wraps)
            document_footnotes[note_id] = note_paragraphs
            # Le symbole de citation ("1", "i"...) déjà calculé par Writer est conservé tel quel
            # comme texte du run d'appel — jamais recalculé : ODF le fournit déjà résolu.
            runs.append(Run(text=citation_text, fmt=fmt, note_id=note_id))
        elif child.tag == FRAME_TAG:
            # Images gérées séparément par le détecteur (_find_images, appelée depuis
            # _paragraph_from_element) — mais une zone de texte (draw:text-box) ancrée au
            # caractère/paragraphe n'a pas d'équivalent "bloc à part" possible ici : _iter_runs
            # produit un flux plat de Run, pas des Paragraph de niveau supérieur. Son texte est
            # donc aplati en un run de secours (paragraphes séparés par des sauts de ligne,
            # formatage interne perdu) plutôt que silencieusement disparu comme avant ce
            # correctif — imparfait (pas de mise en forme riche préservée pour ce cas précis),
            # mais un texte lisible vaut mieux qu'un texte absent.
            text_box_paragraphs = _text_box_paragraphs(child, resolver, source, asset_store,
                                                         document_footnotes, image_wraps)
            if text_box_paragraphs:
                text_box_text = "\n".join(p.plain_text() for p in text_box_paragraphs if p.plain_text())
                if text_box_text:
                    runs.append(Run(text=text_box_text, fmt=fmt))
        if child.tail:
            runs.append(Run(text=child.tail, fmt=fmt))
    return runs


def _find_images(elem):
    """Retourne la liste de TOUTES les (href, alt_text, frame_style_name) trouvées dans elem —
    un même <text:p> peut contenir plusieurs <draw:frame> porteurs d'image (ex : deux images
    côte à côte dans la même ligne, ancrées au caractère) ; sans ceci, seule la première était
    conservée et les suivantes disparaissaient silencieusement du paragraphe (rattrapées
    seulement partiellement par le filet de sécurité unresolved_image_hrefs en fin de
    split_into_chapters). alt_text vient de <svg:desc>, la description ODF standard saisie dans
    Writer via clic droit sur l'image > Description (distincte de <svg:title>, le titre court,
    non utilisée ici). Chaîne vide si non renseignée par l'auteur. frame_style_name
    (draw:style-name du <draw:frame>) sert à résoudre l'habillage de texte (style:wrap), cf.
    _resolve_image_wrap ci-dessous."""
    results = []
    for frame in elem.iter(FRAME_TAG):
        image = frame.find(IMAGE_TAG)
        if image is not None:
            href = image.get(qn("xlink:href"))
            desc_elem = frame.find(qn("svg:desc"))
            alt_text = desc_elem.text or "" if desc_elem is not None else ""
            frame_style_name = frame.get(qn("draw:style-name"))
            results.append((href, alt_text, frame_style_name))
    return results


def _text_box_paragraphs(frame_elem, resolver: StyleResolver, source: OdtSource, asset_store,
                          document_footnotes: dict[str, list[Paragraph]],
                          image_wraps: dict[str, ImageWrap]) -> list[Paragraph] | None:
    """Extrait le texte d'une zone de texte Writer (Insertion > Zone de texte), structurellement
    un <draw:frame><draw:text-box><text:p>...</text:p></draw:text-box></draw:frame> — donc un
    <draw:frame> SANS <draw:image> interne (contrairement à une image). Sans cette fonction, un
    tel frame ne matchait ni _find_images (pas de draw:image, retourne une liste vide) ni aucune
    autre branche : son contenu disparaissait silencieusement, même mécanisme que le bug déjà
    corrigé pour les text:section. Retourne None si `frame_elem` n'est pas un draw:frame contenant
    une draw:text-box (cas normal : une image), pour laisser l'appelant essayer _find_images à la place."""
    text_box = frame_elem.find(TEXT_BOX_TAG)
    if text_box is None:
        return None
    paragraphs: list[Paragraph] = []
    _walk_body(text_box, resolver, source, asset_store, paragraphs, document_footnotes, image_wraps)
    return paragraphs


_WRAP_MAP = {"left": ImageWrap.LEFT, "right": ImageWrap.RIGHT}


def _resolve_image_wrap(resolver: StyleResolver, frame_style_name: str | None) -> ImageWrap:
    """Traduit style:wrap (ODF) en ImageWrap (modèle pivot). Les valeurs ODF sans équivalent CSS
    float fidèle (parallel/dynamic/run-through/biggest) replient sur ImageWrap.NONE plutôt qu'un
    choix arbitraire gauche/droite — voir odt/styles_cascade.py::ResolvedGraphicStyle."""
    resolved = resolver.resolve_graphic_style(frame_style_name)
    return _WRAP_MAP.get(resolved.wrap, ImageWrap.NONE)


def _paragraph_from_element(elem, resolver: StyleResolver, list_level: int, list_ordered: bool,
                             source: OdtSource, asset_store: AssetStore | None,
                             document_footnotes: dict[str, list[Paragraph]],
                             image_wraps: dict[str, ImageWrap],
                             list_group_id: str | None = None) -> Paragraph:
    style_name = elem.get(STYLE_NAME_ATTR)
    resolved = resolver.resolve_paragraph_style(style_name)

    kind = resolved.kind
    if list_level > 0:
        kind = ParagraphKind.LIST_ITEM_NUMBER if list_ordered else ParagraphKind.LIST_ITEM_BULLET

    paragraph_fmt = resolver.resolve_text_style(style_name, inherited=CharFormat())
    runs = _iter_runs(elem, resolver, paragraph_fmt, source, asset_store, document_footnotes, image_wraps)

    image_anchors: list[ImageAnchor] = []
    if asset_store is not None:
        pictures = dict(source.iter_pictures())
        for href, alt_text, frame_style_name in _find_images(elem):
            if href is None:
                continue
            data = pictures.get(href)
            if data is None:
                continue
            asset = asset_store.ingest_bytes(data, original_filename=href, role=AssetRole.CHAPTER_POV)
            image_anchors.append(ImageAnchor(asset_id=asset.id, alt_text=alt_text))
            if asset.id not in image_wraps:
                image_wraps[asset.id] = _resolve_image_wrap(resolver, frame_style_name)

    return Paragraph(
        kind=kind,
        align=resolved.align,
        runs=runs,
        list_level=list_level,
        list_group_id=list_group_id if list_level > 0 else None,
        image=image_anchors[0] if image_anchors else None,
        extra_images=image_anchors[1:],
        page_break_before=resolved.page_break_before,
    )


def _cells_from_row_element(row_elem, resolver: StyleResolver, source: OdtSource,
                             asset_store, is_header: bool,
                             document_footnotes: dict[str, list[Paragraph]],
                             image_wraps: dict[str, ImageWrap]) -> list[TableCell]:
    """Construit les cellules réelles d'une seule ligne (avant dépliage de
    table:number-rows-repeated, géré par l'appelant). table:covered-table-cell (la cellule
    fantôme masquée par une fusion voisine) n'est JAMAIS traduite en TableCell : elle est
    purement sautée, exactement comme une fusion HTML ne génère qu'une seule <td colspan/
    rowspan> et aucune balise pour les positions couvertes. table:number-columns-repeated
    (répétition compacte de cellules identiques) est déplié en cellules réelles INDÉPENDANTES
    (copy.deepcopy à chaque répétition) — jamais une référence partagée à la même instance,
    sous peine qu'une future mutation affecte silencieusement toutes les répétitions à la fois."""
    cells: list[TableCell] = []
    for cell_elem in row_elem:
        if cell_elem.tag == COVERED_TABLE_CELL_TAG:
            continue
        if cell_elem.tag != TABLE_CELL_TAG:
            continue
        cell_repeat = int(cell_elem.get(COLUMNS_REPEATED_ATTR, "1"))
        colspan = int(cell_elem.get(COLUMNS_SPANNED_ATTR, "1")) or 1
        rowspan = int(cell_elem.get(ROWS_SPANNED_ATTR, "1")) or 1
        # cell_elem est lui-même le conteneur générique attendu par _walk_body (ses enfants directs
        # peuvent être <text:p>, <text:list> ou <text:section>, exactement comme <text:note-body>)
        # — lui passer cell_elem directement, jamais un LIST_TAG trouvé dedans : _walk_body itère
        # sur les ENFANTS de l'argument reçu, donc lui passer la liste elle-même l'aurait fait
        # itérer sur les <text:list-item> (aucun ne matche PARAGRAPH_TAG/LIST_TAG/SECTION_TAG),
        # perdant silencieusement tout le contenu d'une liste directement dans une cellule.
        paragraphs: list[Paragraph] = []
        _walk_body(cell_elem, resolver, source, asset_store, paragraphs, document_footnotes, image_wraps)
        for _ in range(cell_repeat):
            cells.append(TableCell(paragraphs=[copy.deepcopy(p) for p in paragraphs],
                                    colspan=colspan, rowspan=rowspan, is_header=is_header))
    return cells


def _table_from_element(elem, resolver: StyleResolver, source: OdtSource, asset_store,
                         document_footnotes: dict[str, list[Paragraph]],
                         image_wraps: dict[str, ImageWrap]) -> Table:
    """Construit une Table pivot depuis un <table:table>. table:table-column est ignoré (pas
    de style de largeur de colonne dans cette version). Les lignes d'en-tête ODF sont
    regroupées sous un conteneur englobant table:table-header-rows (PAS un attribut sur
    chaque ligne) : détecté comme un cas particulier au même niveau que les table:table-row
    normales."""
    rows: list[TableRow] = []
    for child in elem:
        if child.tag == HEADER_ROWS_TAG:
            for row_elem in child.findall(TABLE_ROW_TAG):
                row_repeat = int(row_elem.get(ROWS_REPEATED_ATTR, "1"))
                cells = _cells_from_row_element(row_elem, resolver, source, asset_store, is_header=True,
                                                 document_footnotes=document_footnotes, image_wraps=image_wraps)
                for _ in range(row_repeat):
                    rows.append(TableRow(cells=[TableCell(paragraphs=[copy.deepcopy(p) for p in c.paragraphs],
                                                           colspan=c.colspan, rowspan=c.rowspan,
                                                           is_header=c.is_header) for c in cells]))
        elif child.tag == TABLE_ROW_TAG:
            row_repeat = int(child.get(ROWS_REPEATED_ATTR, "1"))
            cells = _cells_from_row_element(child, resolver, source, asset_store, is_header=False,
                                             document_footnotes=document_footnotes, image_wraps=image_wraps)
            for _ in range(row_repeat):
                rows.append(TableRow(cells=[TableCell(paragraphs=[copy.deepcopy(p) for p in c.paragraphs],
                                                       colspan=c.colspan, rowspan=c.rowspan,
                                                       is_header=c.is_header) for c in cells]))
    return Table(rows=rows)


def _walk_body(body_elem, resolver: StyleResolver, source: OdtSource, asset_store, out: list[Paragraph],
               document_footnotes: dict[str, list[Paragraph]], image_wraps: dict[str, ImageWrap],
               list_level: int = 0, list_ordered: bool = False):
    for child in body_elem:
        if child.tag in (PARAGRAPH_TAG, HEADING_TAG):
            out.append(_paragraph_from_element(child, resolver, list_level, list_ordered, source, asset_store,
                                                document_footnotes, image_wraps))
        elif child.tag == LIST_TAG:
            style_name = child.get(LIST_STYLE_NAME_ATTR)
            new_level = list_level + 1
            # level=new_level, pas le défaut (1) : sans ça, une sous-liste imbriquée (niveau >= 2)
            # dans une note/cellule/zone de texte résolvait toujours le type ODF du niveau 1 du
            # style, même quand celui-ci définit un type différent par niveau — même correctif
            # déjà appliqué dans collect() (flux principal du document) mais oublié ici.
            ordered = resolver.is_list_style_ordered(style_name, level=new_level)
            for item in child.findall(LIST_ITEM_TAG):
                _walk_body(item, resolver, source, asset_store, out, document_footnotes, image_wraps,
                           new_level, ordered)
        elif child.tag == SECTION_TAG:
            # Conteneur transparent (cf. collect() dans split_into_chapters, même raison) : une
            # section peut aussi apparaître dans une cellule de tableau ou un corps de note.
            _walk_body(child, resolver, source, asset_store, out, document_footnotes, image_wraps,
                       list_level, list_ordered)


def split_into_chapters(source: OdtSource, resolver: StyleResolver, source_odt_id: str,
                         asset_store: AssetStore | None = None,
                         document_footnotes: dict[str, list[Paragraph]] | None = None,
                         orphan_image_asset_ids: list[str] | None = None,
                         image_wraps: dict[str, ImageWrap] | None = None,
                         unresolved_image_hrefs: list[str] | None = None) -> list[Chapter]:
    """Parcourt content.xml séquentiellement, coupe à chaque Titre 1 détecté. Les notes ODT
    rencontrées sont accumulées dans document_footnotes (peuplé par effet de bord) si fourni par
    l'appelant — un appelant qui ne fournit rien perd silencieusement les notes de cet appel
    précis (comportement de repli, jamais un crash), ce qui conserve la compatibilité de tout
    appel existant qui n'a pas encore été mis à jour vers ce nouveau paramètre. Même principe pour
    orphan_image_asset_ids (images ancrées à la page, rattachées automatiquement à leur position
    réelle dans le flux — cf. la branche FRAME_TAG ci-dessous), image_wraps (habillage de texte
    gauche/droite lu depuis le style graphique de chaque image) et unresolved_image_hrefs (filet de
    sécurité : href d'images présentes dans le fichier mais dont aucun mécanisme de lecture n'a pu
    déterminer le rattachement — cas résiduel très rare, ex. une image de page perdue dans une
    cellule de tableau ou un corps de note sans rapport, cf. comparaison en fin de fonction)."""
    if document_footnotes is None:
        document_footnotes = {}
    if orphan_image_asset_ids is None:
        orphan_image_asset_ids = []
    if image_wraps is None:
        image_wraps = {}
    if unresolved_image_hrefs is None:
        unresolved_image_hrefs = []

    body = source.body_text_root()
    flat_paragraphs: list[Paragraph | Table] = []
    heading_flags: list[bool] = []
    heading_texts: list[str] = []
    break_after_flags: list[bool] = []

    def collect(elem, list_level=0, list_ordered=False, list_group_id=None):
        for child in elem:
            if child.tag in (PARAGRAPH_TAG, HEADING_TAG):
                style_name = child.get(STYLE_NAME_ATTR)
                resolved = resolver.resolve_paragraph_style(style_name)
                para = _paragraph_from_element(child, resolver, list_level, list_ordered, source,
                                                asset_store, document_footnotes, image_wraps, list_group_id)
                flat_paragraphs.append(para)
                heading_flags.append(resolved.is_heading1 or child.tag == HEADING_TAG and resolved.is_heading1)
                heading_texts.append(para.plain_text())
                break_after_flags.append(resolved.page_break_after)
            elif child.tag == LIST_TAG:
                style_name = child.get(LIST_STYLE_NAME_ATTR)
                new_level = list_level + 1
                ordered = resolver.is_list_style_ordered(style_name, level=new_level)
                group_id = new_id()
                for item in child.findall(LIST_ITEM_TAG):
                    collect(item, new_level, ordered, group_id)
            elif child.tag == SECTION_TAG:
                # text:section : conteneur de mise en page ODF (colonnes, zone de texte liée,
                # section protégée en écriture...) fréquemment utilisé par Writer pour des
                # encadrés/blocs indépendants — reste transparent pour la détection de chapitres :
                # traversé comme n'importe quel autre conteneur, jamais un bloc à part. Sans cette
                # branche, tout le texte à l'intérieur d'une section disparaissait silencieusement
                # (aucune des branches ci-dessus ne reconnaît text:section), le seul texte restant
                # visible étant celui resté hors section — bug réel constaté sur un document
                # utilisant des sections pour la quasi-totalité de son corps de texte.
                collect(child, list_level, list_ordered, list_group_id)
            elif child.tag == TABLE_TAG:
                table = _table_from_element(child, resolver, source, asset_store, document_footnotes,
                                             image_wraps)
                flat_paragraphs.append(table)
                heading_flags.append(False)
                heading_texts.append("")
                break_after_flags.append(False)
            elif child.tag == FRAME_TAG:
                # Image ancrée à la page (text:anchor-type="page") : ODF la place hors de tout
                # text:p, en enfant direct de office:text (ou, par récursivité de collect(), d'un
                # item de liste) — sans cette branche, elle disparaîtrait silencieusement (aucune
                # des branches ci-dessus ne la reconnaît). Traitée comme un mini-paragraphe
                # autonome (runs=[]) à sa position réelle dans le flux du document, plutôt que
                # perdue ou rattachée arbitrairement à un texte sans rapport.
                text_box_paragraphs = _text_box_paragraphs(child, resolver, source, asset_store,
                                                             document_footnotes, image_wraps)
                if text_box_paragraphs is not None:
                    # Zone de texte (draw:text-box) ancrée à la page : mêmes réserves qu'une
                    # image de page — position exacte dans le flux non garantie par rapport au
                    # texte environnant, mais le contenu n'est plus perdu.
                    for tb_para in text_box_paragraphs:
                        flat_paragraphs.append(tb_para)
                        heading_flags.append(False)
                        heading_texts.append("")
                        break_after_flags.append(False)
                    continue
                images_found = _find_images(child)
                href, alt_text, frame_style_name = images_found[0] if images_found else (None, "", None)
                if href is not None and asset_store is not None:
                    data = dict(source.iter_pictures()).get(href)
                    if data is not None:
                        asset = asset_store.ingest_bytes(data, original_filename=href, role=AssetRole.CHAPTER_POV)
                        image_anchor = ImageAnchor(asset_id=asset.id, alt_text=alt_text)
                        if asset.id not in image_wraps:
                            image_wraps[asset.id] = _resolve_image_wrap(resolver, frame_style_name)
                        flat_paragraphs.append(Paragraph(runs=[], image=image_anchor))
                        heading_flags.append(False)
                        heading_texts.append("")
                        break_after_flags.append(False)
                        orphan_image_asset_ids.append(asset.id)

    collect(body)

    # fo:break-after="page" est une propriété du paragraphe qui PRÉCÈDE le saut : on la
    # normalise en page_break_before=True sur le paragraphe suivant, seul endroit où le
    # modèle pivot représente un saut de page. Sans effet sur le tout dernier paragraphe du
    # document (rien à normaliser après lui).
    for i in range(1, len(flat_paragraphs)):
        if break_after_flags[i - 1]:
            flat_paragraphs[i].page_break_before = True

    chapters: list[Chapter] = []
    current: Chapter | None = None
    order_index = 0

    for para, is_heading, heading_text in zip(flat_paragraphs, heading_flags, heading_texts):
        if is_heading:
            current = Chapter.create(
                title=heading_text,
                source_odt_id=source_odt_id,
                source_order_index=order_index,
            )
            order_index += 1
            chapters.append(current)
            continue
        if current is None:
            current = Chapter.create(
                title="",
                source_odt_id=source_odt_id,
                source_order_index=order_index,
            )
            order_index += 1
            chapters.append(current)
        current.paragraphs.append(para)
        if isinstance(para, Paragraph) and para.image is not None and current.pov_image_asset_id is None:
            current.pov_image_asset_id = para.image.asset_id

    # Filet de sécurité : compare le nombre total de <draw:image> présents dans le fichier source
    # (peu importe où, y compris dans une cellule de tableau ou un corps de note) au nombre
    # effectivement rattaché à un Paragraph par les mécanismes ci-dessus (paragraphe normal,
    # cellule de tableau, corps de note, ou frame orphelin de la branche FRAME_TAG). Un écart
    # signale un cas résiduel non couvert (ex. une image de page perdue dans une cellule/note sans
    # rapport, cf. docstring) — jamais rattaché de force, seulement signalé pour que l'utilisateur
    # sache qu'une vérification manuelle dans Writer peut être nécessaire.
    #
    # Comparaison par ASSET_ID résolu (hash du contenu), jamais par nom de fichier d'origine :
    # AssetStore déduplique par contenu (cf. model/assets.py), donc deux hrefs distincts pointant
    # vers des octets identiques (image collée deux fois dans Writer) partagent le même asset_id
    # mais seul le nom du PREMIER href ingéré est conservé comme original_filename — comparer par
    # nom aurait fait considérer à tort le second href comme non résolu alors qu'il l'est bien
    # (même image, juste sous un autre nom de fichier dans le zip).
    if asset_store is not None:
        pictures_by_href = dict(source.iter_pictures())
        total_image_hrefs = {img.get(qn("xlink:href")) for img in body.iter(IMAGE_TAG)}
        total_image_hrefs.discard(None)

        resolved_asset_ids: set[str] = set()
        resolved_paragraphs = [para for chapter in chapters for para in iter_all_paragraphs(chapter.paragraphs)]
        resolved_paragraphs += [para for paras in document_footnotes.values()
                                 for para in iter_all_paragraphs(paras)]
        for para in resolved_paragraphs:
            for image in para.all_images():
                resolved_asset_ids.add(image.asset_id)

        for href in total_image_hrefs:
            data = pictures_by_href.get(href)
            if data is None:
                unresolved_image_hrefs.append(href)
                continue
            digest = hashlib.sha256(data).hexdigest()
            if digest not in resolved_asset_ids:
                unresolved_image_hrefs.append(href)
        unresolved_image_hrefs.sort()

    return chapters
