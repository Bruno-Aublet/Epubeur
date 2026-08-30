import re
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt, QUrl
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QFileDialog, QMenu, QTextBrowser

from controller import ProjectController
from epub.builder import split_chapter_into_segments
from epub.css import IMAGE_SIZE_RULE_TEMPLATE, IMAGE_WRAP_CSS
from epub.html_render import paragraphs_to_html, title_html_block
from model.document import ImageDisplaySize, ImageWrap, Paragraph, Table
from ui.image_gallery import SIZE_LABELS, WRAP_LABELS

# Matche <p></p> aussi bien que <p class="align-center"></p> — un paragraphe vide n'est pas
# toujours sans attribut (ex. il peut hériter d'un alignement centré/droit/justifié).
_EMPTY_P_RE = re.compile(r"<p[^>]*></p>")

# paragraph_to_html émet src="../images/{asset_id}.{ext}" — un chemin relatif valable UNIQUEMENT
# dans la structure de dossiers du zip EPUB final (text/ + images/ frères). QTextBrowser.setHtml()
# n'a aucune base URL correspondante : ce chemin ne résout jamais vers un fichier réel, d'où des
# images invisibles dans cet aperçu. On le remplace par le vrai chemin absolu sur disque
# (asset_store.path_for) juste avant affichage.
_IMAGE_SRC_RE = re.compile(r'src="\.\./images/([^".]+)\.[^"]+"')

# paragraph_to_html insère l'<img> en tête du <p> du paragraphe, dans le MÊME <p> que le texte
# éventuel qui l'accompagne (cf. epub/html_render.py::_paragraph_inner_html) — un <img> avec
# display:block/margin:auto (epub/css.py) se détache visuellement du texte dans un vrai moteur
# CSS (Chromium/liseuses) même techniquement imbriqué, mais Qt Rich Text ignore ces deux
# propriétés et rend l'image collée au texte, en ligne. On extrait donc l'<img> pour le placer
# dans son propre <p align="center"> séparé, uniquement pour cet aperçu.
# (?:\s*<img[^>]*/>)+ plutôt qu'une seule <img> : plusieurs images ancrées au même paragraphe
# ODT (cf. Paragraph.extra_images) sont toutes écrites en tête du <p> par
# epub/html_render.py::_paragraph_inner_html, chacune devant être isolée dans son propre <p>.
_IMG_IN_P_RE = re.compile(r"<p([^>]*)>((?:\s*<img[^>]*/>)+)(.*?)</p>", re.DOTALL)
_SINGLE_IMG_RE = re.compile(r"<img[^>]*/>")

# QTextBrowser (moteur Rich Text de Qt) ignore silencieusement border-top sur <p>/<div> et ne
# préserve pas la couleur d'un <hr> — seule une couleur de texte est fiablement rendue, d'où ce
# marqueur textuel plutôt qu'une pure ligne graphique.
PAGE_BREAK_MARKER_TEXT = "――― Saut de page manuel ―――"
PAGE_BREAK_MARKER_HTML = f'<p align="center" style="color:#2a6fdb;">{PAGE_BREAK_MARKER_TEXT}</p>'


class ChapterPreview(QTextBrowser):
    """Aperçu en lecture seule du texte formaté d'un chapitre (gras/italique/centré/listes/citations)."""

    def __init__(self, controller: ProjectController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._chapter_id: str | None = None
        self._page_break_paragraph_indexes: list[int] = []  # un par marqueur affiché, dans l'ordre
        self._eligible_paragraph_block_ranks: dict[int, int] = {}  # rang de bloc Qt -> index dans chapter.paragraphs
        self._highlighted_marker_rank: int | None = None  # marqueur de saut de page ceinturé d'un cadre pointillé
        self._highlighted_asset_id: str | None = None  # image ceinturée d'un cadre pointillé
        self._highlighted_asset_seed_doc_pos = None  # QPointF en coordonnées document, un point connu dans l'image
        self.setReadOnly(True)
        self.setOpenExternalLinks(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        # QTextBrowser en lecture seule (isReadOnly()==True) ne peint JAMAIS le curseur clignotant
        # dans son viewport, même avec setCursorWidth>0 et un QTextCursor positionné à jour :
        # Qt conditionne ce rendu en interne à !isReadOnly() (vérifié empiriquement — aucune
        # combinaison de flags publics ne le réactive). On simule donc le clignotement nous-mêmes :
        # un QTimer qui bascule _cursor_blink_visible et déclenche un repaint ciblé sur le seul
        # rectangle du curseur (viewport().update(rect), pas tout le viewport).
        self._cursor_blink_visible = True
        self._cursor_blink_timer = QTimer(self)
        self._cursor_blink_timer.setInterval(500)
        self._cursor_blink_timer.timeout.connect(self._toggle_cursor_blink)
        self._cursor_blink_timer.start()

    def _toggle_cursor_blink(self) -> None:
        self._cursor_blink_visible = not self._cursor_blink_visible
        self.viewport().update(self.cursorRect())

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            self.setTextCursor(self.cursorForPosition(pos))
            self._cursor_blink_visible = True
            # Un clic gauche sélectionne visuellement le marqueur de saut de page ou l'image sous
            # le curseur (cadre pointillé), comme le fait déjà un clic droit avant d'ouvrir son
            # menu — sans ça, rien ne matérialise "sur quoi on agit" pour un simple clic gauche.
            self._set_highlight_at(pos)
            self.viewport().update()

    def _set_highlight_at(self, pos) -> None:
        """Positionne le highlight (cadre pointillé) sur le marqueur de saut de page ou l'image
        sous `pos` (coordonnées viewport), ou l'efface si `pos` ne tombe sur aucun des deux."""
        self._highlighted_marker_rank = self._marker_index_at(pos)
        asset_id = self._asset_id_at(pos) if self._highlighted_marker_rank is None else None
        self._highlighted_asset_id = asset_id
        # Un point connu DANS l'image (coordonnées document = viewport + scroll courant), utilisé
        # par _image_rect() pour retrouver ses bords par expansion locale (cf. son docstring) —
        # doit survivre à un défilement pendant que le highlight reste actif, d'où des coordonnées
        # document plutôt que viewport (qui, elles, deviendraient fausses après un scroll).
        if asset_id is not None:
            offset_x = self.horizontalScrollBar().value()
            offset_y = self.verticalScrollBar().value()
            self._highlighted_asset_seed_doc_pos = QPointF(pos.x() + offset_x, pos.y() + offset_y)
        else:
            self._highlighted_asset_seed_doc_pos = None

    def _clear_highlight(self) -> None:
        self._highlighted_marker_rank = None
        self._highlighted_asset_id = None
        self._highlighted_asset_seed_doc_pos = None

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        highlight_rect = self._highlight_rect()
        show_cursor = self._cursor_blink_visible and self.hasFocus()
        if highlight_rect is None and not show_cursor:
            return
        # Un seul QPainter pour tout le paintEvent : deux QPainter successifs sur le même
        # viewport() (un pour le cadre, un pour le curseur) segfaultaient systématiquement sous
        # PySide6/Windows — le premier doit visiblement être détruit avant qu'un second ne
        # s'ouvre sur le même paint device, ce que la portée d'une variable locale ne garantit
        # pas de façon fiable ici.
        painter = QPainter(self.viewport())
        if highlight_rect is not None:
            pen = QPen(self.palette().text().color())
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawRect(highlight_rect.adjusted(1, 1, -2, -2))
        if show_cursor:
            painter.fillRect(self.cursorRect(), self.palette().text())

    def _highlight_rect(self):
        """Rectangle (coordonnées viewport) de l'élément actuellement ceinturé d'un cadre
        pointillé (marqueur de saut de page ou image), ou None si aucun n'est sélectionné ou si
        l'élément sélectionné n'existe plus (ex. document rechargé pendant qu'un menu était
        ouvert)."""
        if self._highlighted_marker_rank is not None:
            return self._marker_rect(self._highlighted_marker_rank)
        if self._highlighted_asset_id is not None:
            return self._image_rect(self._highlighted_asset_id)
        return None

    def _marker_rect(self, marker_rank: int):
        """Rectangle (coordonnées viewport) du bloc marqueur numéro `marker_rank` (0-indexé
        parmi ceux affichés), ou None s'il n'existe plus (ex. document rechargé sous le menu).
        cursorRect(QTextCursor) segfaultait de façon systématique lorsqu'appelée depuis
        paintEvent() (réentrance dans le layout du document pendant un paint en cours, constaté
        empiriquement sous PySide6/Windows) — on utilise donc blockBoundingRect(), une lecture
        pure du layout déjà calculé, puis on translate nous-mêmes par le scroll courant au lieu
        de passer par cursorRect()."""
        target_rank = 0
        block = self.document().begin()
        while block.isValid():
            if block.text() == PAGE_BREAK_MARKER_TEXT:
                if target_rank == marker_rank:
                    block_rect = self.document().documentLayout().blockBoundingRect(block)
                    offset_x = -self.horizontalScrollBar().value()
                    offset_y = -self.verticalScrollBar().value()
                    return block_rect.translated(offset_x, offset_y).toRect()
                target_rank += 1
            block = block.next()
        return None

    def _image_rect(self, asset_id: str):
        """Rectangle (coordonnées viewport) de l'image `asset_id`, ou None si elle n'apparaît
        plus dans le chapitre affiché (ou si _highlighted_asset_seed_doc_pos ne tombe plus
        dedans, ex. le paragraphe a changé de mise en page entre-temps).

        Une image avec habillage gauche/droite (style:wrap ODF -> float CSS, cf.
        epub/css.py::IMAGE_WRAP_CSS) est retirée du flux inline par le moteur Rich Text de Qt :
        QTextLine.cursorToX() sur son caractère objet (U+FFFC) renvoie alors une largeur nulle
        (constaté empiriquement), rendant impossible d'en déduire un rectangle par la position
        dans le texte comme pour un bloc normal (cf. _marker_rect). QAbstractTextDocumentLayout
        expose en revanche imageAt(QPointF) -> str (chemin/URL de l'image sous ce point, y
        compris pour un flottant, en COORDONNÉES DOCUMENT), donc indépendant du flux logique :
        on retrouve les 4 bords en étendant pixel par pixel depuis un point connu DANS l'image
        (_highlighted_asset_seed_doc_pos, posé au clic par _set_highlight_at) jusqu'à sortir de
        cette zone. Un balayage complet du viewport avec imageAt (sans seed) coûterait ~250ms
        par repaint (mesuré) — bien trop lent pour un curseur qui clignote 2x/seconde — alors que
        l'expansion locale depuis un point déjà connu ne coûte que quelques dizaines de µs."""
        if self._highlighted_asset_seed_doc_pos is None:
            return None
        layout = self.document().documentLayout()
        target_path = self.controller.asset_store.path_for(asset_id)

        def image_path_at(doc_x: float, doc_y: float) -> Path | None:
            image_url = layout.imageAt(QPointF(doc_x, doc_y))
            if not image_url:
                return None
            return Path(QUrl(image_url).toLocalFile())

        seed_x = self._highlighted_asset_seed_doc_pos.x()
        seed_y = self._highlighted_asset_seed_doc_pos.y()
        if image_path_at(seed_x, seed_y) != target_path:
            return None

        # Borne de sécurité : une image de couverture peut légitimement approcher la largeur du
        # document, mais jamais la dépasser — un garde-fou au cas où imageAt() se comporterait de
        # façon inattendue évite toute boucle d'expansion anormalement longue.
        doc_size = self.document().size()
        max_extent = int(doc_size.width() + doc_size.height()) + 10

        left = seed_x
        while left > seed_x - max_extent and image_path_at(left - 1, seed_y) == target_path:
            left -= 1
        right = seed_x
        while right < seed_x + max_extent and image_path_at(right + 1, seed_y) == target_path:
            right += 1
        top = seed_y
        while top > seed_y - max_extent and image_path_at(seed_x, top - 1) == target_path:
            top -= 1
        bottom = seed_y
        while bottom < seed_y + max_extent and image_path_at(seed_x, bottom + 1) == target_path:
            bottom += 1

        offset_x = -self.horizontalScrollBar().value()
        offset_y = -self.verticalScrollBar().value()
        return QRectF(left, top, right - left + 1, bottom - top + 1).translated(offset_x, offset_y).toRect()

    def show_chapter(self, chapter_id: str | None) -> None:
        # setHtml() reconstruit tout le QTextDocument et remet le scroll à zéro (comportement Qt,
        # pas de setter dédié) — sans ça, toute action déclenchant refresh() pendant qu'on regarde
        # un chapitre (ex. clic droit > "Insérer une image ici") fait remonter la vue tout en haut
        # au lieu de rester sur l'endroit édité. On ne restaure que si c'est le MÊME chapitre :
        # changer de sélection doit repartir en haut normalement.
        same_chapter = chapter_id is not None and chapter_id == self._chapter_id
        scroll_value = self.verticalScrollBar().value() if same_chapter else 0

        self._chapter_id = chapter_id
        self._page_break_paragraph_indexes = []
        self._eligible_paragraph_block_ranks = {}
        self._clear_highlight()
        if chapter_id is None:
            self.setHtml("")
            return
        chapter = self.controller.project.document.chapters.get(chapter_id)
        if chapter is None:
            self.setHtml("")
            return

        # Le nom des classes n'a ici aucune importance : QTextBrowser ignore les classes CSS
        # (seul le style inline compte, cf. inline_locked_font_style=True ci-dessous), donc
        # un mapping trivial suffit, indexé par position plutôt que par le slug déterministe
        # utilisé pour l'EPUB réel (qui n'a pas besoin d'être stable ici).
        family_to_css_class = {
            lf.family: f"epubeur-locked-font-preview-{i}"
            for i, lf in enumerate(self.controller.project.document.locked_fonts)
        }
        title = title_html_block(chapter.title) if chapter.title_visible else ""
        # inline_locked_font_style=True : QTextBrowser applique bien font-family en style
        # inline mais ignore les règles CSS basées sur une classe (vérifié) — la classe seule
        # (utilisée pour l'EPUB réel) ne suffirait pas à colorer la police dans cet aperçu.
        # Un saut de page manuel (Paragraph.page_break_before) ne produit aucun changement
        # visuel dans le texte lui-même — seul le découpage en fichiers XHTML distincts le
        # matérialise à la génération EPUB — donc invisible ici sans marqueur dédié. On réutilise
        # le même découpage en segments que la génération réelle (epub/builder.py) pour insérer
        # une ligne pointillée entre segments, propre à cet aperçu (jamais dans l'EPUB généré,
        # qui matérialise déjà le saut par un vrai changement de page).
        # QTextBrowser (moteur Rich Text de Qt) supprime purement et simplement tout bloc <p>
        # totalement vide au lieu de juste collapser sa marge (vérifié : absent de
        # QTextDocument.begin()/next(), pas seulement invisible) — contrairement à un vrai
        # moteur CSS où p:empty { min-height } suffirait (cf. epub/css.py, utilisé par l'EPUB
        # réel et l'aperçu Chromium). &nbsp; force Qt à conserver le bloc, sans changer le
        # rendu visuel d'un paragraphe qui contient déjà du texte.
        segments = split_chapter_into_segments(chapter.paragraphs)
        # Index (dans chapter.paragraphs) du paragraphe qui porte page_break_before=True pour
        # chaque marqueur affiché, dans l'ordre — c'est le premier paragraphe de chaque segment
        # sauf le tout premier (qui ne suit aucun saut). Reconstruit ici plutôt que lu depuis
        # Paragraph.page_break_before directement, pour rester en accord strict avec les
        # marqueurs réellement insérés ci-dessous (même source : split_chapter_into_segments).
        offset = 0
        for segment in segments[:-1]:
            offset += len(segment)
            self._page_break_paragraph_indexes.append(offset)

        # Mapping rang-de-bloc-Qt -> index dans chapter.paragraphs, pour retrouver depuis un clic
        # (cursorForPosition) sur quel Paragraph exact il tombe — utilisé pour "Insérer une image
        # ici" et "Supprimer cette image". Ne couvre que les Paragraph top-level non-liste
        # (list_level == 0) : un paragraphe de liste n'a aucun bloc top-level propre (imbriqué
        # dans un <li>), donc jamais mappé. Le comptage doit suivre EXACTEMENT ce que Qt produit
        # réellement comme blocs (vérifié empiriquement, comportement non documenté officiellement) :
        # - le h1 du titre occupe le rang 0 SEULEMENT s'il a un contenu (chapter.title_visible et
        #   chapter.title non vide) — <h1></h1> totalement vide disparaît purement et simplement
        #   du QTextDocument, comme n'importe quel bloc vide (même piège que les <p> vides déjà
        #   contourné plus bas avec &nbsp;, mais un <h1> n'a pas cette protection). Un chapitre-
        #   image (title_visible=False, cf. controller.add_image_as_chapter) tombe dans ce cas :
        #   sans cette correction, le mapping supposait à tort un rang 0 occupé par le titre,
        #   décalant tout le comptage d'un cran et faisant échouer la résolution du clic droit.
        # - un marqueur de saut de page entre segments consomme 1 rang.
        # - une Table consomme sum(max(1, len(cell.paragraphs)) pour chaque cellule) + 1 rangs
        #   (1 bloc par paragraphe de cellule, minimum 1 même vide, + 1 bloc "fantôme" après la
        #   table entière) — colspan/rowspan n'affectent pas ce compte, seul le nombre réel de
        #   <td>/<th> émis par table_to_html compte.
        # - un Paragraph(image=..., runs=[...]) SANS habillage est scindé par _isolate_images en
        #   plusieurs blocs Qt distincts (une image isolée par image du paragraphe + un bloc texte
        #   séparé si runs non vide) : tous les rangs doivent pointer vers le MÊME paragraph_index,
        #   sinon les paragraphes suivants seraient décalés. Si UNE SEULE image du paragraphe a un
        #   habillage, _isolate_images n'isole aucune image (tout reste dans le <p> d'origine) :
        #   un seul bloc Qt dans ce cas, quel que soit le nombre d'images.
        block_rank = 1 if title else 0
        paragraph_index = 0
        for seg_idx, segment in enumerate(segments):
            if seg_idx > 0:
                block_rank += 1  # bloc du marqueur de saut de page
            for block in segment:
                if isinstance(block, Table):
                    block_rank += sum(max(1, len(cell.paragraphs)) for row in block.rows for cell in row.cells) + 1
                elif isinstance(block, Paragraph) and block.list_level == 0:
                    images = block.all_images()
                    any_wrapped = any(
                        self.controller.project.document.image_wrap(img.asset_id) != ImageWrap.NONE
                        for img in images
                    )
                    self._eligible_paragraph_block_ranks[block_rank] = paragraph_index
                    block_rank += 1
                    if images and not any_wrapped:
                        extra_image_blocks = len(images) - 1  # 1 image déjà comptée ci-dessus
                        for _ in range(extra_image_blocks):
                            self._eligible_paragraph_block_ranks[block_rank] = paragraph_index
                            block_rank += 1
                        if block.runs:
                            self._eligible_paragraph_block_ranks[block_rank] = paragraph_index
                            block_rank += 1
                # paragraphe de liste : aucun bloc top-level propre, pas mappé
                paragraph_index += 1

        body = _EMPTY_P_RE.sub(
            lambda m: m.group()[:-4] + "&nbsp;</p>",
            PAGE_BREAK_MARKER_HTML.join(
                paragraphs_to_html(segment, family_to_css_class=family_to_css_class,
                                    asset_store=self.controller.asset_store, inline_locked_font_style=True,
                                    image_alt_texts=self.controller.project.document.image_alt_texts,
                                    image_wraps=self.controller.project.document.image_wraps)
                for segment in segments
            ),
        )
        body = self._resolve_image_paths(body)
        body = self._isolate_images(body)

        # Même mécanisme que la génération EPUB réelle (epub/css.py::build_css) : une règle CSS
        # ciblée par asset_id pour chaque image dont la taille a été réglée dans l'onglet Images
        # (aucune règle pour celles restées à 100%, cf. build_css). Vérifié : Qt Rich Text
        # supporte bien le sélecteur d'attribut img[data-epubeur-image="..."], contrairement à
        # d'autres règles CSS déjà rencontrées cette session (border-top, :empty sur <div>...).
        image_size_rules = "".join(
            IMAGE_SIZE_RULE_TEMPLATE.format(asset_id=asset_id, percent=size.value)
            for asset_id, size in self.controller.project.document.image_display_sizes.items()
            if size.value != 100
        )

        css = f"""
        <style>
        body {{ font-family: serif; font-size: 13pt; }}
        h1 {{ font-size: 17pt; }}
        .align-center {{ text-align: center; }}
        .align-right {{ text-align: right; }}
        .align-justify {{ text-align: justify; }}
        blockquote {{ margin-left: 2em; font-style: italic; color: #555; }}
        p:empty {{ min-height: 1em; }}
        {image_size_rules}
        {IMAGE_WRAP_CSS}
        </style>
        """
        html = f"{css}<h1>{title}</h1>{body}"
        self.setHtml(html)
        if same_chapter:
            self.verticalScrollBar().setValue(scroll_value)

    def _isolate_images(self, html: str) -> str:
        def replace(match: re.Match) -> str:
            p_attrs, img_tags_blob, rest = match.group(1), match.group(2), match.group(3)
            img_tags = _SINGLE_IMG_RE.findall(img_tags_blob)
            # Une image avec un habillage réglé (gauche/droite) doit rester dans le MÊME <p> que
            # le texte qui l'accompagne pour que le texte s'enroule autour d'elle (float, cf.
            # epub/css.py) — l'isoler dans son propre <p align="center"> séparé, comme pour une
            # image sans habillage, annulerait entièrement l'effet visuel voulu. Si UNE SEULE des
            # images du groupe a un habillage, aucune n'est isolée : les séparer casserait
            # l'ordre visuel image-habillée/texte que Writer/EPUB rendent côte à côte.
            if any('data-epubeur-image-wrap="left"' in tag or 'data-epubeur-image-wrap="right"' in tag
                   for tag in img_tags):
                return match.group()
            # Une image par <p align="center"> séparé (pas toutes regroupées dans un seul <p>) :
            # Qt Rich Text empile les blocs verticalement, donc plusieurs images resteraient
            # groupées en un seul bloc si elles partageaient le même <p>, alors que le mapping
            # de rangs (_eligible_paragraph_block_ranks ci-dessus) attend un bloc Qt par image.
            image_blocks = "".join(f'<p align="center">{tag}</p>' for tag in img_tags)
            if rest.strip():
                return f"{image_blocks}<p{p_attrs}>{rest}</p>"
            return image_blocks

        return _IMG_IN_P_RE.sub(replace, html)

    def _resolve_image_paths(self, html: str) -> str:
        def replace(match: re.Match) -> str:
            asset_id = match.group(1)
            asset = self.controller.asset_store.get(asset_id)
            if asset is None:
                return match.group()
            path = self.controller.asset_store.path_for(asset_id)
            if not path.exists():
                return match.group()
            return f'src="{QUrl.fromLocalFile(str(path)).toString()}"'

        return _IMAGE_SRC_RE.sub(replace, html)

    def _marker_index_at(self, pos) -> int | None:
        """Retourne l'index (dans _page_break_paragraph_indexes, donc aussi le rang du marqueur
        parmi ceux affichés) si `pos` (coordonnées viewport) tombe sur un bloc marqueur, sinon
        None. Identification par texte exact du bloc : le marqueur ne peut apparaître nulle
        part ailleurs dans un texte normal (tirets cadratins peu probables en contenu réel)."""
        cursor = self.cursorForPosition(pos)
        block_text = cursor.block().text()
        if block_text != PAGE_BREAK_MARKER_TEXT:
            return None
        marker_rank = 0
        block = self.document().begin()
        while block.isValid() and block != cursor.block():
            if block.text() == PAGE_BREAK_MARKER_TEXT:
                marker_rank += 1
            block = block.next()
        if marker_rank >= len(self._page_break_paragraph_indexes):
            return None
        return marker_rank

    def _asset_id_at(self, pos) -> str | None:
        """Retourne l'asset_id de l'image sous `pos` (coordonnées viewport), sinon None.
        QTextDocument (moteur Rich Text de Qt) ne conserve pas les attributs HTML custom
        (data-epubeur-image posé par epub/html_render.py) — seul le src résolu (chemin de
        fichier local posé par _resolve_image_paths) est accessible via QTextImageFormat.name().
        AssetStore nomme chaque fichier physique d'après son nom affiché, éventuellement renommé
        par l'utilisateur (model/assets.py::path_for) — le stem du chemin n'est donc PLUS
        l'asset_id ; on retrouve l'asset par correspondance de chemin (path_for) sur tous les
        assets du document."""
        cursor = self.cursorForPosition(pos)
        char_format = cursor.charFormat()
        if not char_format.isImageFormat():
            return None
        image_url = char_format.toImageFormat().name()
        local_path = Path(QUrl(image_url).toLocalFile())
        for asset in self.controller.asset_store.all_assets():
            if self.controller.asset_store.path_for(asset.id) == local_path:
                return asset.id
        return None

    def _paragraph_index_at(self, pos) -> int | None:
        """Retourne l'index dans chapter.paragraphs du paragraphe top-level (texte simple ou
        image) sous `pos`, si éligible pour insérer/supprimer une image, sinon None. S'appuie
        sur _eligible_paragraph_block_ranks, peuplé dans show_chapter()."""
        cursor = self.cursorForPosition(pos)
        block_rank = 0
        block = self.document().begin()
        while block.isValid() and block != cursor.block():
            block_rank += 1
            block = block.next()
        return self._eligible_paragraph_block_ranks.get(block_rank)

    def _show_context_menu(self, pos) -> None:
        marker_rank = self._marker_index_at(pos)
        if marker_rank is not None and self._chapter_id is not None:
            self._set_highlight_at(pos)
            self.viewport().update()
            menu = QMenu(self)
            menu.addAction("Supprimer ce saut de page manuel", lambda: self._remove_page_break(marker_rank))
            menu.exec(self.viewport().mapToGlobal(pos))
            self._clear_highlight()
            self.viewport().update()
            return

        asset_id = self._asset_id_at(pos)
        if asset_id is not None:
            self._set_highlight_at(pos)
            self.viewport().update()
            self._show_image_context_menu(asset_id, pos)
            self._clear_highlight()
            self.viewport().update()
            return

        paragraph_index = self._paragraph_index_at(pos)
        if paragraph_index is not None and self._chapter_id is not None:
            menu = QMenu(self)
            menu.addAction("Insérer une image ici", lambda: self._insert_image_after(paragraph_index))
            paste_source = self._paste_image_source()
            if paste_source is not None:
                menu.addAction("Coller l'image ici", lambda: self._paste_image_after(paragraph_index, paste_source))
            menu.exec(self.viewport().mapToGlobal(pos))

    def _show_image_context_menu(self, asset_id: str, pos) -> None:
        document = self.controller.project.document
        menu = QMenu(self)

        size_menu = menu.addMenu("Taille de l'image")
        current_size = document.image_display_size(asset_id)
        for size, label in SIZE_LABELS.items():
            action = size_menu.addAction(label, lambda s=size: self._set_image_display_size(asset_id, s))
            action.setCheckable(True)
            action.setChecked(size == current_size)

        wrap_menu = menu.addMenu("Positionnement / habillage")
        current_wrap = document.image_wrap(asset_id)
        for wrap, label in WRAP_LABELS.items():
            action = wrap_menu.addAction(label, lambda w=wrap: self._set_image_wrap(asset_id, w))
            action.setCheckable(True)
            action.setChecked(wrap == current_wrap)

        paragraph_index = self._paragraph_index_at(pos)
        if paragraph_index is not None and self._chapter_id is not None:
            menu.addSeparator()
            menu.addAction("Copier l'image", lambda: self._copy_image(asset_id))
            menu.addAction("Couper l'image", lambda: self._cut_image(asset_id, paragraph_index))
            menu.addSeparator()
            menu.addAction("Supprimer cette image",
                            lambda: self.controller.remove_image_occurrence(self._chapter_id, paragraph_index))

        menu.exec(self.viewport().mapToGlobal(pos))

    def _set_image_display_size(self, asset_id: str, size: ImageDisplaySize) -> None:
        # set_image_display_size émet assets_changed, écouté par StructureEditor.refresh() qui
        # rappelle show_chapter() sur la sélection courante — pas besoin de le refaire ici.
        self.controller.set_image_display_size(asset_id, size)

    def _set_image_wrap(self, asset_id: str, wrap: ImageWrap) -> None:
        self.controller.set_image_wrap(asset_id, wrap)

    def _remove_page_break(self, marker_rank: int) -> None:
        if self._chapter_id is None or marker_rank >= len(self._page_break_paragraph_indexes):
            return
        paragraph_index = self._page_break_paragraph_indexes[marker_rank]
        # remove_page_break émet chapters_changed, écouté par StructureEditor.refresh() qui
        # rappelle show_chapter() sur la sélection courante — pas besoin de le refaire ici.
        self.controller.remove_page_break(self._chapter_id, paragraph_index)

    def _insert_image_after(self, paragraph_index: int) -> None:
        if self._chapter_id is None:
            return
        path_str, _ = QFileDialog.getOpenFileName(self, "Insérer une image", "", "Images (*.png *.jpg *.jpeg)")
        if not path_str:
            return
        self.controller.insert_image_after_paragraph(self._chapter_id, paragraph_index, Path(path_str))

    def _copy_image(self, asset_id: str) -> None:
        self.controller.copy_image_to_clipboard(asset_id)

    def _cut_image(self, asset_id: str, paragraph_index: int) -> None:
        if self._chapter_id is None:
            return
        self.controller.copy_image_to_clipboard(asset_id)
        self.controller.remove_image_occurrence(self._chapter_id, paragraph_index)

    def _paste_image_source(self) -> str | Path | None:
        return self.controller.paste_image_source()

    def _paste_image_after(self, paragraph_index: int, source: str | Path) -> None:
        if self._chapter_id is None:
            return
        if isinstance(source, Path):
            self.controller.insert_image_after_paragraph(self._chapter_id, paragraph_index, source)
        else:
            self.controller.insert_existing_asset_after_paragraph(self._chapter_id, paragraph_index, source)
