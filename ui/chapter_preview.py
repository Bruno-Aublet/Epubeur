import copy
import re
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import QKeySequence, QPainter, QPen, QTextCursor
from PySide6.QtWidgets import QFileDialog, QMenu, QTextBrowser

from controller import ProjectController
from epub.builder import split_chapter_into_segments
from epub.css import IMAGE_SIZE_RULE_TEMPLATE, IMAGE_WRAP_CSS
from epub.html_render import paragraphs_to_html, title_html_block
from model.document import ImageDisplaySize, ImageWrap, Paragraph, Table
from ui.chapter_editor_sync import (
    PAGE_BREAK_MARKER_HTML,
    PAGE_BREAK_MARKER_TEXT,
    block_contains_image,
    extract_paragraphs_from_document,
    normalize_paragraphs_for_comparison,
)
from ui.image_gallery import SIZE_LABELS, WRAP_LABELS

# Touches qui modifient le contenu du document si transmises à QTextBrowser.keyPressEvent /
# inputMethodEvent alors que le curseur est hors d'un bloc éditable (cf. _is_block_editable) —
# tout le reste (navigation, Ctrl+C, Ctrl+A...) doit rester transmis normalement.
_EDITING_KEYS = {
    Qt.Key.Key_Backspace, Qt.Key.Key_Delete, Qt.Key.Key_Return, Qt.Key.Key_Enter,
    Qt.Key.Key_Tab, Qt.Key.Key_Insert,
}

# Matche <p></p> aussi bien que <p class="align-center"></p> — un paragraphe vide n'est pas
# toujours sans attribut (ex. il peut hériter d'un alignement centré/droit/justifié).
_EMPTY_P_RE = re.compile(r"<p[^>]*></p>")

# epub/html_render.py::ALIGN_CLASS n'exprime l'alignement QUE via une classe CSS (align-justify),
# correct pour l'EPUB réel (vrai moteur CSS) mais silencieusement IGNORÉ par le moteur Rich Text
# de Qt pour la valeur "justify" précisément — vérifié empiriquement : `text-align: justify`
# posé par une règle de <style> (classe ou style inline, peu importe) ne modifie jamais
# QTextBlockFormat.alignment() (reste Qt.AlignLeft), alors que centré/droite fonctionnent très
# bien de la même façon. Seul l'attribut HTML natif align="justify" est honoré par Qt. Sans ce
# correctif, un paragraphe justifié affichait un alignement à gauche dans cet aperçu (bug
# cosmétique préexistant), ET après l'ajout de l'édition de texte, faisait considérer CHAQUE
# paragraphe justifié comme "modifié" par extract_paragraphs_from_document (LEFT extrait au lieu
# de JUSTIFY), déclenchant une réécriture parasite du modèle qui vidait silencieusement
# redo_stack juste avant que Ctrl+Y ne s'exécute.
_JUSTIFY_CLASS_RE = re.compile(r'(<(?:p|blockquote)\s+class="[^"]*\balign-justify\b[^"]*")')

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


class ChapterPreview(QTextBrowser):
    """Éditeur du texte formaté d'un chapitre (gras/italique/centré/listes/citations) — les
    paragraphes top-level simples (pas de liste, pas de table, pas d'image) sont librement
    éditables ; le reste (listes, tables, images) garde le comportement précédent : lecture
    seule + menu contextuel dédié."""

    def __init__(self, controller: ProjectController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._chapter_id: str | None = None
        self._page_break_paragraph_indexes: list[int] = []  # un par marqueur affiché, dans l'ordre
        self._eligible_paragraph_block_ranks: dict[int, int] = {}  # rang de bloc Qt -> index dans chapter.paragraphs
        # Capture de chapter.paragraphs (au sens ==, pas d'identité) telle qu'elle était au
        # dernier show_chapter() complet — permet à _sync_to_model() de détecter qu'une mutation
        # EXTERNE (menu contextuel image/saut de page, undo/redo...) a modifié le modèle sans
        # jamais passer par le buffer Qt affiché ici : dans ce cas, le buffer n'a par définition
        # rien de nouveau à écrire, et une synchro aveugle écraserait la mutation externe avec le
        # contenu périmé du buffer. None tant qu'aucun chapitre n'a encore été affiché.
        self._last_known_paragraphs: list | None = None
        self._highlighted_marker_rank: int | None = None  # marqueur de saut de page ceinturé d'un cadre pointillé
        self._highlighted_asset_id: str | None = None  # image ceinturée d'un cadre pointillé
        self._highlighted_asset_seed_doc_pos = None  # QPointF en coordonnées document, un point connu dans l'image
        # Réentrance (cf. _sync_to_model) : empêche show_chapter() de reconstruire le document
        # depuis un modèle qu'on vient tout juste d'écrire avec exactement ce qui est déjà
        # affiché — sans ce flag, la synchro émettrait chapters_changed, qui redéclencherait
        # show_chapter() en boucle.
        self._syncing_to_model = False
        # Debounce de la synchro texte -> modèle pivot : redémarré à chaque frappe modifiante
        # (cf. _on_text_possibly_changed), synchronise au bout de 500ms d'inactivité. Le modèle
        # pivot ne reste ainsi jamais désynchronisé du texte affiché de plus de 500ms, jamais
        # dépendant d'une perte de focus — contrairement à l'ancien mécanisme purement différé
        # (synchro seulement à la perte de focus/changement de chapitre/sauvegarde), qui causait
        # des bugs en cascade (menu contextuel invisible tant qu'on ne change pas de chapitre,
        # Ctrl+Z inopérant tant qu'on n'a pas perdu le focus).
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(500)
        self._sync_timer.timeout.connect(self._sync_to_model)
        # Posé juste avant controller.undo()/redo() (cf. MainWindow._undo/_redo) : bloque TOUT
        # appel à _sync_to_model() jusqu'à la prochaine reconstruction de l'affichage, peu
        # importe qui l'invoque (StructureEditor._on_selection_changed, ou show_chapter()
        # lui-même quand il autorise la reconstruction sous focus — cf. _show_chapter_impl).
        # Sans ce garde, le document Qt encore affiché (l'état d'AVANT l'undo, pas encore
        # reconstruit) serait comparé au modèle qui vient tout juste d'être restauré et
        # réécrirait dessus l'ancien texte, annulant silencieusement l'undo/redo.
        self._suppress_sync_once = False
        self.setReadOnly(False)
        # L'undo/redo de l'app est géré exclusivement par ProjectController (snapshots du modèle
        # pivot, cf. controller._snapshot_structure), jamais par le QTextDocument affiché ici —
        # laisser l'undo interne de Qt activé ferait que Ctrl+Z, tant que ce panneau a le focus,
        # annule un changement de caractère dans le buffer Qt local SANS jamais toucher au modèle
        # (aucun effet observable après la prochaine synchro, qui réécrirait le texte "annulé").
        # Désactivé pour empêcher toute modification via ce mécanisme interne — Ctrl+Z/Ctrl+Y
        # sont de toute façon interceptés explicitement dans keyPressEvent (cf. perform_undo/
        # perform_redo), qui appellent directement controller.undo()/redo() sans jamais compter
        # sur la remontée de l'événement clavier vers le raccourci de menu (elle n'a pas lieu :
        # un widget de texte Qt avec le focus consomme toujours ces combinaisons en interne,
        # avant même que setUndoRedoEnabled(False) n'entre en jeu — vérifié empiriquement).
        self.setUndoRedoEnabled(False)
        self.setOpenExternalLinks(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            # super().mousePressEvent() a déjà positionné le curseur normalement (mode éditable) ;
            # on ne le repositionne nous-mêmes que si la cible n'est pas éditable (marqueur/image),
            # pour ne pas perturber le placement natif d'une sélection en cours de glisser.
            if not self._is_position_editable(pos):
                self.setTextCursor(self.cursorForPosition(pos))
            # Un clic gauche sélectionne visuellement le marqueur de saut de page ou l'image sous
            # le curseur (cadre pointillé), comme le fait déjà un clic droit avant d'ouvrir son
            # menu — sans ça, rien ne matérialise "sur quoi on agit" pour un simple clic gauche.
            self._set_highlight_at(pos)
            self.viewport().update()

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        pos = event.position().toPoint()
        cursor_shape = Qt.CursorShape.IBeamCursor if self._is_position_editable(pos) else Qt.CursorShape.ArrowCursor
        self.viewport().setCursor(cursor_shape)

    def keyPressEvent(self, event) -> None:
        # Ctrl+Z/Ctrl+Y : QTextBrowser (comme n'importe quel widget de texte Qt) intercepte et
        # CONSOMME ces combinaisons dans son propre keyPressEvent interne dès qu'il a le focus —
        # y compris avec setUndoRedoEnabled(False) (qui désactive seulement la modification du
        # document, pas la consommation de l'événement clavier lui-même). Un widget avec focus
        # prime TOUJOURS sur les QAction de la fenêtre pour ces touches, quel que soit leur
        # ShortcutContext (vérifié empiriquement) — l'action de menu "Annuler" ne se déclenche
        # donc jamais tant que ce panneau a le focus, peu importe la logique de synchro derrière.
        # On appelle donc directement ici l'équivalent de MainWindow._undo()/_redo() (synchro
        # puis controller.undo()/redo(), avec le même garde anti-écrasement), sans jamais
        # transmettre l'événement à Qt.
        if event.matches(QKeySequence.StandardKey.Undo):
            self.perform_undo()
            return
        if event.matches(QKeySequence.StandardKey.Redo):
            self.perform_redo()
            return
        # Ctrl+Z/Ctrl+Y (et toute combinaison Ctrl/Meta+lettre, ex. Ctrl+B) ont un event.text()
        # NON VIDE et IMPRIMABLE sous Qt/Windows (ex. 'z' pour Ctrl+Z) — sans cette exclusion,
        # elles seraient classées à tort comme une frappe de texte normale par le test suivant.
        # Seules les touches SANS aucun modificateur de commande peuvent être une vraie frappe.
        has_command_modifier = bool(event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier))
        is_editing_key = not has_command_modifier and (
            event.key() in _EDITING_KEYS or (event.text() and event.text().isprintable())
        )
        if is_editing_key:
            if not self._is_selection_editable(self.textCursor()):
                return
            super().keyPressEvent(event)
            self._on_text_possibly_changed()
            return
        super().keyPressEvent(event)

    def perform_undo(self) -> None:
        """Point d'entrée public pour Ctrl+Z — appelé directement par keyPressEvent quand ce
        panneau a le focus (contournant l'interception native de Qt), et par
        MainWindow._undo() (menu Edit > Annuler) pour tout autre contexte. Synchronise la frappe
        en attente pour qu'elle devienne annulable, bloque toute resynchro pendant TOUTE la
        cascade de signaux que controller.undo() va émettre (cf. suppress_sync_until_next_
        reconstruction et son relâchement explicite ci-dessous), puis annule."""
        self.sync_pending_edits()
        self.suppress_sync_until_next_reconstruction()
        try:
            self.controller.undo()
        finally:
            # Relâché ici, explicitement, une seule fois — PAS par show_chapter() (cf. son
            # commentaire) : controller.undo() émet chapters_changed/structure_changed/
            # fonts_changed/assets_changed à la suite, chacun pouvant redéclencher
            # StructureEditor.refresh() -> show_chapter() plusieurs fois pour cette seule
            # opération. Relâcher trop tôt (dès le premier show_chapter() de la cascade)
            # laissait les suivants sans protection, permettant une resynchro qui écrasait le
            # undo qui venait de réussir.
            self._suppress_sync_once = False

    def perform_redo(self) -> None:
        """Symétrique de perform_undo pour Ctrl+Y/Ctrl+Maj+Z."""
        self.sync_pending_edits()
        self.suppress_sync_until_next_reconstruction()
        try:
            self.controller.redo()
        finally:
            self._suppress_sync_once = False

    def inputMethodEvent(self, event) -> None:
        # Saisie IME (accents composés, méthodes de saisie CJK...) ne passe pas par
        # keyPressEvent — même garde nécessaire ici pour empêcher toute modification hors d'un
        # bloc éditable.
        if not self._is_selection_editable(self.textCursor()):
            return
        super().inputMethodEvent(event)
        self._on_text_possibly_changed()

    def _on_text_possibly_changed(self) -> None:
        """Appelée après toute frappe/IME/glisser-déposer qui a pu modifier le texte affiché —
        marque le projet non enregistré immédiatement (pas seulement à la synchro différée, cf.
        controller.mark_dirty) et (re)démarre le debounce de synchro vers le modèle pivot."""
        self.controller.mark_dirty()
        self._sync_timer.start()

    def dragEnterEvent(self, event) -> None:
        if not self._is_selection_editable(self.textCursor()):
            event.ignore()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        # Qt propose par défaut un déplacement de texte sélectionné par glisser — bloqué si la
        # cible du dépôt tombe hors d'un bloc éditable (la source l'est nécessairement déjà,
        # cf. dragEnterEvent, mais la cible doit être vérifiée séparément).
        target_cursor = self.cursorForPosition(event.position().toPoint())
        if not self._is_block_editable(target_cursor.block()):
            event.ignore()
            return
        super().dropEvent(event)
        self._on_text_possibly_changed()

    def focusOutEvent(self, event) -> None:
        # Un menu contextuel (clic droit) ou un dialogue ouvert depuis la barre d'outils (lien...)
        # font perdre puis retrouver le focus sans intention réelle de l'utilisateur de "sortir"
        # du panneau — Qt distingue ce cas via event.reason(), pas de synchro/snapshot dans ce cas.
        if event.reason() != Qt.FocusReason.PopupFocusReason:
            self._sync_to_model()
        super().focusOutEvent(event)

    def sync_pending_edits(self) -> None:
        """Point d'entrée public : force la synchronisation vers le modèle de toute édition en
        attente, sans attendre le débounce ou une perte de focus — appelé avant un changement de
        chapitre sélectionné, avant une sauvegarde de projet, ou avant undo()/redo() (cf.
        StructureEditor, MainWindow)."""
        self._sync_to_model()

    def suppress_sync_until_next_reconstruction(self) -> None:
        """Point d'entrée public : bloque tout appel à _sync_to_model() jusqu'à la prochaine
        reconstruction de l'affichage (show_chapter, qui relâche le flag après coup) — à
        appeler juste APRÈS avoir synchronisé une édition en attente (sync_pending_edits) mais
        AVANT controller.undo()/redo() (cf. MainWindow._undo/_redo). Nécessaire car
        chapters_changed (émis par undo()/redo()) redéclenche show_chapter() sous focus, qui
        tente lui-même une resynchro (cf. _show_chapter_impl) : sans ce garde, elle comparerait
        le document Qt ENCORE affiché (l'état d'avant l'undo) au modèle qui vient d'être
        restauré, et réécrirait dessus le texte que l'undo était censé annuler."""
        self._suppress_sync_once = True

    def _sync_to_model(self) -> None:
        # Arrête le débounce en cours : _sync_to_model() peut désormais être appelée depuis deux
        # origines concurrentes (expiration du timer, ou appel direct via sync_pending_edits()
        # avant un focus perdu/changement de sélection/sauvegarde/undo-redo) — évite un tir en
        # double du timer juste après un appel direct (optimisation ; même sans stop(), un
        # second tir serait un no-op grâce à la comparaison new_paragraphs == chapter.paragraphs
        # ci-dessous).
        self._sync_timer.stop()
        if self._chapter_id is None or self._syncing_to_model or self._suppress_sync_once:
            return
        chapter = self.controller.project.document.chapters.get(self._chapter_id)
        if chapter is None:
            return
        # chapter.paragraphs a pu être modifié AILLEURS dans l'app (menu contextuel image/saut
        # de page, undo/redo, scission/fusion de chapitre...) depuis le dernier show_chapter()
        # complet, sans jamais passer par le buffer Qt affiché ici — dans ce cas, le buffer n'a
        # par construction rien de nouveau à écrire (l'utilisateur n'a rien tapé depuis), et le
        # comparer au nouveau chapter.paragraphs les trouverait à tort différents (le modèle a
        # changé, pas le buffer), écrasant la mutation externe avec le contenu périmé du buffer.
        # _last_known_paragraphs (capturé à la dernière reconstruction complète) permet de
        # distinguer les deux cas : si le modèle a bougé depuis sans notre concours, on abandonne
        # la synchro — le show_chapter() qui suit (déclenché par le même chapters_changed/
        # assets_changed externe, cf. StructureEditor.refresh) reconstruit et reflète l'état à
        # jour, sans jamais passer par cette synchro.
        if chapter.paragraphs != self._last_known_paragraphs:
            return
        new_paragraphs = extract_paragraphs_from_document(
            self.document(), chapter.paragraphs, self._eligible_paragraph_block_ranks,
        )
        if new_paragraphs == normalize_paragraphs_for_comparison(chapter.paragraphs):
            return
        self._syncing_to_model = True
        try:
            self.controller.apply_edited_paragraphs(self._chapter_id, new_paragraphs)
        finally:
            self._syncing_to_model = False
        # apply_edited_paragraphs() émet chapters_changed, absorbé par _syncing_to_model dans
        # show_chapter() (qui retourne donc sans reconstruire ni recapturer l'instantané) — mis
        # à jour ici explicitement pour que la prochaine synchro compare au bon état de
        # référence, pas à celui d'avant cette écriture.
        self._last_known_paragraphs = new_paragraphs

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
        # Le curseur clignotant est désormais peint nativement par Qt (mode éditable,
        # isReadOnly()==False) — seul le cadre pointillé (marqueur de saut de page / image
        # sélectionnée) reste à peindre manuellement ici.
        highlight_rect = self._highlight_rect()
        if highlight_rect is None:
            return
        painter = QPainter(self.viewport())
        pen = QPen(self.palette().text().color())
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawRect(highlight_rect.adjusted(1, 1, -2, -2))

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

    def show_chapter(self, chapter_id: str | None, force: bool = False) -> None:
        # Réentrance : ChapterPreview vient lui-même d'écrire ce contenu dans le modèle (cf.
        # _sync_to_model) — reconstruire depuis ce qu'on vient d'en extraire serait un travail
        # inutile, et surtout casserait la position du curseur en cours d'édition.
        if self._syncing_to_model:
            return
        # _suppress_sync_once N'EST PLUS relâché ici (contrairement à avant) : controller.undo()/
        # redo() émettent QUATRE signaux à la suite (chapters_changed, structure_changed,
        # fonts_changed, assets_changed), chacun connecté à StructureEditor.refresh() ->
        # show_chapter() — donc show_chapter() est appelée PLUSIEURS FOIS en cascade pour un seul
        # undo()/redo(). Relâcher le flag dès le premier appel laissait les suivants sans
        # protection : le 2e/3e appel de la cascade retombait sur une resynchro non bloquée, qui
        # écrasait le undo/redo qui venait tout juste de réussir avec le contenu périmé du buffer
        # Qt — undo_stack/redo_stack finissaient identiques à leur état d'AVANT l'opération,
        # rendant Ctrl+Z/Ctrl+Y invisibles en apparence. Le flag est maintenant relâché une seule
        # fois, explicitement, par perform_undo()/perform_redo() APRÈS que controller.undo()/
        # redo() ait fini d'émettre tous ses signaux.
        self._show_chapter_impl(chapter_id, force)

    def _show_chapter_impl(self, chapter_id: str | None, force: bool) -> None:
        # Arrête tout débounce en attente AVANT la éventuelle synchro/reconstruction ci-dessous :
        # _sync_timer a pu être démarré par une frappe (cf. _on_text_possibly_changed) et n'être
        # stoppé QUE par _sync_to_model() — jamais par une reconstruction complète (setHtml() un
        # peu plus bas). Sans cet arrêt explicite ici, un timer resté actif après un undo/redo
        # (ex. frappé juste avant le Ctrl+Z, jamais nettoyé par la restauration) pouvait se
        # déclencher tout seul PLUS TARD, hors de toute protection _suppress_sync_once (déjà
        # relâchée à ce moment) — sa synchro comparait alors un buffer Qt qui n'était plus
        # d'actualité, écrivait dessus un _snapshot_structure() parasite, et vidait
        # silencieusement redo_stack (ou undo_stack) entre deux opérations undo/redo qui
        # semblaient pourtant réussies individuellement.
        self._sync_timer.stop()
        if not force and chapter_id == self._chapter_id and self._chapter_id is not None:
            # Même chapitre déjà affiché, pas de reconstruction forcée explicitement demandée :
            # synchroniser d'abord une éventuelle frappe en attente (no-op silencieux sinon, ou
            # si une mutation externe a déjà rendu la synchro invalide — cf. _sync_to_model),
            # PUIS reconstruire dans tous les cas. Reconstruire n'est pas coûteux pour l'usage
            # (le scroll est déjà préservé par le code de reconstruction ci-dessous via
            # same_chapter) et c'est le seul moyen fiable de refléter toute mutation externe qui
            # ne touche pas chapter.paragraphs — ex. set_image_display_size()/set_image_wrap()
            # (onglet Images), qui changent le rendu HTML sans jamais passer par les paragraphes
            # eux-mêmes (comparer seulement chapter.paragraphs manquerait ce cas).
            self._sync_to_model()

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
            self._last_known_paragraphs = None
            self.setHtml("")
            return
        chapter = self.controller.project.document.chapters.get(chapter_id)
        if chapter is None:
            self._last_known_paragraphs = None
            self.setHtml("")
            return
        # Instantané de chapter.paragraphs tel qu'il est AU MOMENT de cette reconstruction — sert
        # de référence à _sync_to_model() pour détecter une mutation externe survenue depuis (cf.
        # son champ, définition ligne ~66). deepcopy() est nécessaire ici, pas juste list() : des
        # mutations comme controller.remove_page_break()/insert_page_break() modifient un
        # Paragraph EN PLACE (block.page_break_before = ...) sans jamais recréer d'objet — un
        # simple list(chapter.paragraphs) partagerait les mêmes instances de Paragraph, rendant
        # toute comparaison ultérieure aveugle à ce type de mutation externe (déjà pris en
        # défaut : une copie superficielle "voyait" la mutation en même temps que le modèle).
        self._last_known_paragraphs = copy.deepcopy(chapter.paragraphs)

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
        body = _JUSTIFY_CLASS_RE.sub(r'\1 align="justify"', body)
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
        return self._eligible_paragraph_index_for_block(self.cursorForPosition(pos).block())

    def _eligible_paragraph_index_for_block(self, block) -> int | None:
        block_rank = 0
        cursor_block = self.document().begin()
        while cursor_block.isValid() and cursor_block != block:
            block_rank += 1
            cursor_block = cursor_block.next()
        return self._eligible_paragraph_block_ranks.get(block_rank)

    def _is_block_editable(self, block) -> bool:
        """Vrai ssi ce bloc Qt correspond à un Paragraph top-level simple ET que ce bloc précis
        ne PORTE PAS lui-même une image — un paragraphe texte+image (sans habillage) est scindé
        par _isolate_images en plusieurs blocs Qt distincts (un bloc par image, un bloc texte
        séparé, cf. show_chapter) : seul le bloc-image reste non éditable (son interaction passe
        par le menu contextuel dédié, insérer/copier/couper/supprimer), le bloc-texte du MÊME
        paragraphe reste librement éditable, même si Paragraph.all_images() est non vide.
        Une image AVEC habillage (gauche/droite) reste dans le même <p> que le texte (jamais
        isolée, cf. _isolate_images) : le bloc entier est alors exclu, faute de pouvoir séparer
        proprement l'un de l'autre dans ce cas."""
        if self._chapter_id is None:
            return False
        index = self._eligible_paragraph_index_for_block(block)
        if index is None:
            return False
        chapter = self.controller.project.document.chapters.get(self._chapter_id)
        if chapter is None or not (0 <= index < len(chapter.paragraphs)):
            return False
        item = chapter.paragraphs[index]
        if not isinstance(item, Paragraph):
            return False
        images = item.all_images()
        if not images:
            return True
        any_wrapped = any(
            self.controller.project.document.image_wrap(img.asset_id) != ImageWrap.NONE for img in images
        )
        if any_wrapped:
            return False  # image non isolée, mêlée au texte dans le même bloc : tout le bloc exclu
        return not block_contains_image(block)

    def _is_position_editable(self, pos) -> bool:
        return self._is_block_editable(self.cursorForPosition(pos).block())

    def _is_selection_editable(self, cursor: QTextCursor) -> bool:
        """Vrai ssi toute la sélection (ou la position du curseur si pas de sélection) tombe à
        l'intérieur d'un seul bloc éditable — une sélection qui déborde sur un marqueur, une
        image, une liste ou une table n'est jamais éditable, même partiellement."""
        start_block = self.document().findBlock(cursor.selectionStart())
        end_block = self.document().findBlock(cursor.selectionEnd())
        if start_block != end_block:
            return False
        return self._is_block_editable(start_block)

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
