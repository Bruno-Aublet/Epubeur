import copy
import tempfile
from pathlib import Path

from PySide6.QtCore import QMimeData, QObject, QUrl, Signal
from PySide6.QtGui import QFontDatabase, QGuiApplication

from epub.importer import import_epub
from model.assets import SUPPORTED_IMAGE_EXTENSIONS, AssetRole, AssetStore
from model.error_messages import (
    describe_epub_open_error,
    describe_odt_open_error,
    describe_project_load_error,
    describe_project_save_error,
)
from model.document import (
    Chapter,
    ImageAnchor,
    ImageDisplaySize,
    ImageWrap,
    LockedFont,
    LockedFontFile,
    Paragraph,
    Part,
    iter_all_paragraphs,
)
from model.epbz import load_project_epbz, save_project_epbz
from model.font_scan import scan_fonts_in_document
from model.font_variant_detection import detect_font_variant
from model.project import ProjectMeta, SourceOdtFile
from model.recent_files import add_recent_file, add_recent_project
from model.text_utils import natural_sort_key
from odt.chapter_detector import split_into_chapters
from odt.font_scanner import scan_fonts
from odt.metadata import extract_book_metadata
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver


MAX_UNDO_HISTORY = 50


class ProjectController(QObject):
    chapters_changed = Signal()
    structure_changed = Signal()
    assets_changed = Signal()
    fonts_changed = Signal()
    project_loaded = Signal()
    error_occurred = Signal(str)  # problème bloquant : l'action demandée a échoué
    warning_occurred = Signal(str)  # information non bloquante : l'action a réussi partiellement
    undo_availability_changed = Signal(bool, bool)  # (can_undo, can_redo)
    epub_imported = Signal(str)  # chemin du .epub importé avec succès (pour l'aperçu)
    metadata_imported = Signal(object)  # BookMetadata lue dans l'EPUB importé, pour pré-remplir l'onglet Générer
    odt_metadata_found = Signal(object, str)  # (BookMetadata, nom du fichier .odt importé) — ne doit
                                               # compléter que les champs encore vides, avec résolution
                                               # de conflit si une valeur différente existe déjà
                                               # (contrairement à metadata_imported qui écrase, cf.
                                               # GeneratePanel/MetadataConflictDialog)
    recent_files_changed = Signal()  # une entrée a été ajoutée/retirée des listes Projets/Fichiers
                                      # récents (model/recent_files.py) — MainWindow reconstruit
                                      # les deux sous-menus correspondants

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = ProjectMeta()
        self._temp_assets_dir = Path(tempfile.mkdtemp(prefix="epubeur_assets_"))
        self.asset_store = AssetStore(self._temp_assets_dir)
        self._font_counts: dict[str, int] = {}
        self._undo_stack: list = []
        self._redo_stack: list = []

        # asset_id copié/coupé (bouton "Copier l'image"/"Couper l'image", depuis l'aperçu
        # Structure OU l'onglet Images — un seul système partagé, ici plutôt que dans un widget
        # précis, pour que Copier d'un côté et Coller de l'autre fonctionnent ensemble). Écrire
        # aussi le fichier réel dans le presse-papier Windows (cf. copy_image_to_clipboard) rend
        # cette image disponible pour un collage dans un AUTRE logiciel, comme un vrai Copier de
        # fichier depuis l'Explorateur.
        self._copied_asset_id: str | None = None
        # dataChanged se déclenche pour CHAQUE écriture dans le presse-papier système, y compris
        # la nôtre (setMimeData dans copy_image_to_clipboard) : on doit l'ignorer une fois juste
        # après avoir nous-mêmes écrit, sinon _copied_asset_id serait effacé immédiatement après
        # un Copier. Un changement non causé par nous (copier un fichier dans l'Explorateur,
        # Ctrl+C ailleurs...) invalide en revanche l'ancien Copier/Couper interne : sans ça,
        # "Coller l'image ici" resservirait une image sans rapport avec le presse-papier actuel.
        self._suppress_next_clipboard_change = False
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.dataChanged.connect(self._on_clipboard_changed)

    def has_unsaved_content(self) -> bool:
        """Indique s'il y a des chapitres importés ou de l'historique non trivial, pour
        savoir s'il faut avertir avant de fermer/écraser le projet en cours."""
        return bool(self.project.document.chapters) or bool(self._undo_stack)

    def close_project(self) -> None:
        """Réinitialise entièrement l'état à un projet vide, comme au démarrage de l'app."""
        self.project = ProjectMeta()
        self._temp_assets_dir = Path(tempfile.mkdtemp(prefix="epubeur_assets_"))
        self.asset_store = AssetStore(self._temp_assets_dir)
        self._font_counts = {}
        self._undo_stack = []
        self._redo_stack = []
        self._emit_undo_availability()

        self.chapters_changed.emit()
        self.structure_changed.emit()
        self.assets_changed.emit()
        self.fonts_changed.emit()

    def _snapshot_structure(self) -> None:
        """Appelée par le contrôleur juste avant toute action modifiant la structure
        (chapitres, parties, organisation) pour permettre son annulation. Clone à la fois
        project.document ET project.source_odt_files (pas seulement le premier) : une opération
        comme replace_odt modifie entry.chapter_ids (sur SourceOdtFile) en plus des chapitres du
        document lui-même — sans cloner aussi cette liste, un undo/redo laisserait
        entry.chapter_ids désynchronisé de document.chapters après restauration."""
        self._undo_stack.append((copy.deepcopy(self.project.document), copy.deepcopy(self.project.source_odt_files)))
        if len(self._undo_stack) > MAX_UNDO_HISTORY:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._emit_undo_availability()

    def _emit_undo_availability(self) -> None:
        self.undo_availability_changed.emit(bool(self._undo_stack), bool(self._redo_stack))

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append((copy.deepcopy(self.project.document), copy.deepcopy(self.project.source_odt_files)))
        self.project.document, self.project.source_odt_files = self._undo_stack.pop()
        self._emit_undo_availability()
        self.chapters_changed.emit()
        self.structure_changed.emit()
        self.fonts_changed.emit()
        self.assets_changed.emit()

    def redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append((copy.deepcopy(self.project.document), copy.deepcopy(self.project.source_odt_files)))
        self.project.document, self.project.source_odt_files = self._redo_stack.pop()
        self._emit_undo_availability()
        self.chapters_changed.emit()
        self.structure_changed.emit()
        self.fonts_changed.emit()
        self.assets_changed.emit()

    def _backfill_image_alt_texts_from_paragraphs(self) -> None:
        """Reporte toute description ODF (svg:desc, lue dans ImageAnchor.alt_text) vers
        document.image_alt_texts (la description globale par asset_id, affichée dans l'onglet
        Images) si elle n'y est pas déjà — jamais perdue, jamais écrasée si une valeur globale
        existe déjà. Appelé à chaque import ODT ET au chargement d'un projet existant (un
        projet sauvegardé avant l'introduction de image_alt_texts peut contenir des ImageAnchor
        avec un alt_text jamais reporté).

        Une même image (déduplication par contenu, donc même asset_id) peut apparaître dans
        plusieurs fichiers ODT fondus dans un même projet, chacun avec sa propre description :
        la première rencontrée (ordre d'itération des chapitres/paragraphes) l'emporte
        silencieusement pour le report, mais si une autre occurrence porte une description
        DIFFÉRENTE et non vide, l'utilisateur en est prévenu (conflit à harmoniser à la main
        dans l'onglet Images) — averti une seule fois par asset_id, pas une fois par occurrence
        en conflit."""
        warned_asset_ids: set[str] = set()
        for chapter in self.project.document.chapters.values():
            for para in iter_all_paragraphs(chapter.paragraphs):
                if para.image is None or not para.image.alt_text.strip():
                    continue
                asset_id = para.image.asset_id
                existing = self.project.document.image_alt_texts.get(asset_id)
                if existing is None:
                    self.project.document.image_alt_texts[asset_id] = para.image.alt_text
                elif existing != para.image.alt_text and asset_id not in warned_asset_ids:
                    warned_asset_ids.add(asset_id)
                    self.warning_occurred.emit(
                        f"Une même image est décrite différemment selon les fichiers sources "
                        f"(« {existing} » vs « {para.image.alt_text} »). La première description "
                        "trouvée a été conservée — vérifiez/harmonisez dans l'onglet Images si besoin."
                    )

    def emit_unsupported_image_warnings(self) -> None:
        """Prévient l'utilisateur pour chaque image ingérée dans un format autre que PNG/JPEG
        (seuls formats testés/garantis pour la génération EPUB) lors d'un import ODT/EPUB —
        contexte où l'image fait partie du document source et doit être conservée telle quelle
        malgré le format non testé, contrairement à un ajout manuel (cf.
        warn_and_reject_if_unsupported) qui refuse purement et simplement ces formats."""
        for filename in self.asset_store.unsupported_format_warnings:
            self.warning_occurred.emit(
                f"Image « {filename} » dans un format non testé (seuls PNG et JPEG sont "
                "garantis) : elle pourrait ne pas s'afficher correctement dans l'EPUB généré."
            )
        self.asset_store.unsupported_format_warnings.clear()

    def warn_and_reject_if_unsupported(self, file_path: Path) -> bool:
        """Pour un ajout manuel d'image (drop/dialogue, jamais un import ODT/EPUB où le fichier
        source impose le format) : émet un avertissement et retourne False si l'extension n'est
        pas dans SUPPORTED_IMAGE_EXTENSIONS, sans rien ingérer — évite d'ajouter au projet un
        asset dans un format non garanti que l'utilisateur n'a pas choisi délibérément."""
        ext = file_path.suffix.lower().lstrip(".")
        if ext in SUPPORTED_IMAGE_EXTENSIONS:
            return True
        self.warning_occurred.emit(
            f"Image « {file_path.name} » dans un format non supporté (seuls PNG et JPEG sont "
            "acceptés) : elle n'a pas été ajoutée au projet."
        )
        return False

    def find_source_odt_by_path(self, path: Path) -> SourceOdtFile | None:
        path = Path(path)
        return next((f for f in self.project.source_odt_files if f.path == path), None)

    def _discard_chapter_footnotes(self, chapter: Chapter) -> None:
        """Retire du document les notes de bas de page qui n'appartenaient qu'à ce chapitre
        (avant qu'il ne soit remplacé/supprimé par replace_odt) — évite une accumulation
        d'entrées orphelines dans document.footnotes à chaque cycle correction->réimport du même
        fichier. Une note encore référencée par un AUTRE chapitre restant (cas exotique) n'est
        jamais retirée par erreur : on vérifie qu'aucun autre chapitre ne la référence encore
        avant de la retirer, plutôt que de supposer l'exclusivité (les note_id sont regénérés par
        new_id() à chaque parsing, donc en pratique jamais partagés entre deux fichiers — mais
        cette vérification reste peu coûteuse et évite un bug si cette hypothèse devait changer)."""
        note_ids = {run.note_id for para in iter_all_paragraphs(chapter.paragraphs)
                    for run in para.runs if run.note_id}
        if not note_ids:
            return
        still_referenced: set[str] = set()
        for other in self.project.document.chapters.values():
            if other is chapter:
                continue
            for para in iter_all_paragraphs(other.paragraphs):
                for run in para.runs:
                    if run.note_id:
                        still_referenced.add(run.note_id)
        for note_id in note_ids - still_referenced:
            self.project.document.footnotes.pop(note_id, None)

    def import_odt(self, path: Path) -> SourceOdtFile | None:
        path = Path(path)
        try:
            source = OdtSource(path)
            resolver = StyleResolver(source)
        except Exception as exc:
            self.error_occurred.emit(describe_odt_open_error(exc, path.name))
            return None

        entry = SourceOdtFile.create(path, self.project.next_import_order())
        new_footnotes: dict[str, list[Paragraph]] = {}
        new_orphan_image_asset_ids: list[str] = []
        new_image_wraps: dict = {}
        new_unresolved_image_hrefs: list[str] = []
        chapters = split_into_chapters(source, resolver, source_odt_id=entry.id, asset_store=self.asset_store,
                                        document_footnotes=new_footnotes,
                                        orphan_image_asset_ids=new_orphan_image_asset_ids,
                                        image_wraps=new_image_wraps,
                                        unresolved_image_hrefs=new_unresolved_image_hrefs)
        self.project.document.footnotes.update(new_footnotes)
        for asset_id, wrap in new_image_wraps.items():
            if asset_id not in self.project.document.image_wraps:
                self.project.document.image_wraps[asset_id] = wrap
        for chapter in chapters:
            self.project.document.chapters[chapter.id] = chapter
            entry.chapter_ids.append(chapter.id)
        self.project.source_odt_files.append(entry)
        self._insert_free_chapters_in_alphanumeric_order(entry, [c.id for c in chapters])
        self._backfill_image_alt_texts_from_paragraphs()

        font_counts = scan_fonts(source, resolver)
        for name, count in font_counts.items():
            self._font_counts[name] = self._font_counts.get(name, 0) + count
            self.project.document.known_font_counts[name] = (
                self.project.document.known_font_counts.get(name, 0) + count
            )

        self.chapters_changed.emit()
        self.assets_changed.emit()
        self.fonts_changed.emit()
        self.emit_unsupported_image_warnings()

        if new_orphan_image_asset_ids:
            count = len(new_orphan_image_asset_ids)
            self.warning_occurred.emit(
                f"{count} image(s) ancrée(s) à la page (hors de tout paragraphe dans le fichier "
                "Writer) ont été rattachées automatiquement à l'endroit où elles apparaissent dans "
                "le document. Leur position exacte dans le livre peut différer légèrement de "
                "l'intention d'origine : vérifiez leur emplacement après import."
            )

        if new_unresolved_image_hrefs:
            count = len(new_unresolved_image_hrefs)
            self.warning_occurred.emit(
                f"{count} image(s) du fichier Writer n'ont pas pu être localisées avec certitude "
                "et ne sont peut-être pas incluses dans l'EPUB généré : vérifiez le contenu du "
                "livre après génération."
            )

        odt_metadata = extract_book_metadata(source)
        if odt_metadata is not None:
            self.odt_metadata_found.emit(odt_metadata, path.name)

        add_recent_file(path, "imported")
        self.recent_files_changed.emit()

        return entry

    def replace_odt(self, path: Path) -> SourceOdtFile | None:
        """Réimporte un .odt DÉJÀ présent dans le projet (même chemin qu'un SourceOdtFile
        existant) en remplaçant ses chapitres par une nouvelle lecture du fichier, plutôt que de
        les dupliquer (comportement d'import_odt). Cas d'usage : l'utilisateur corrige une erreur
        dans le fichier Writer d'origine, puis le redépose dans l'appli.

        Contrairement à import_odt, préserve autant que possible les réglages déjà en place :
        - Position exacte de chaque chapitre (libre ou dans une Part), y compris après un
          réordonnancement manuel — via BookStructure.replace_chapter_id, jamais un nouvel ajout
          en fin de liste.
        - Titre personnalisé (title/title_visible) de chaque chapitre, appariement par POSITION
          entre l'ancienne et la nouvelle liste de chapitres (le n-ième nouveau chapitre hérite du
          titre du n-ième ancien).
        - Polices figées (document.locked_fonts) : jamais affectées, réglage global par famille de
          police, jamais lié à un chapitre précis.
        - Réglages d'image (image_display_sizes/image_wraps/image_alt_texts) : survivent
          automatiquement pour toute image dont les octets n'ont pas changé, car asset_id est
          dérivé d'un hash du contenu (AssetStore.ingest_bytes) — seules les images réellement
          modifiées perdent leurs réglages, inévitable.

        Si le nombre de chapitres détectés diffère entre l'ancienne et la nouvelle version, le
        surplus (dans un sens ou l'autre) n'a pas de position/titre ancien à hériter : les
        nouveaux chapitres en trop sont ajoutés libres en fin de séquence, les anciens chapitres
        en trop sont supprimés — un avertissement agrégé signale ce cas pour relecture manuelle,
        jamais une perte silencieuse."""
        path = Path(path)
        entry = self.find_source_odt_by_path(path)
        if entry is None:
            return self.import_odt(path)  # filet de sécurité, ne devrait pas arriver vu le câblage UI

        try:
            source = OdtSource(path)
            resolver = StyleResolver(source)
        except Exception as exc:
            self.error_occurred.emit(describe_odt_open_error(exc, path.name))
            return None

        self._snapshot_structure()

        new_footnotes: dict[str, list[Paragraph]] = {}
        new_orphan_image_asset_ids: list[str] = []
        new_image_wraps: dict = {}
        new_unresolved_image_hrefs: list[str] = []
        new_chapters = split_into_chapters(source, resolver, source_odt_id=entry.id,
                                            asset_store=self.asset_store,
                                            document_footnotes=new_footnotes,
                                            orphan_image_asset_ids=new_orphan_image_asset_ids,
                                            image_wraps=new_image_wraps,
                                            unresolved_image_hrefs=new_unresolved_image_hrefs)

        old_ids = list(entry.chapter_ids)
        paired = min(len(old_ids), len(new_chapters))

        # Appariement par position : le nouveau chapitre i hérite du titre/visibilité de l'ancien
        # chapitre i, puis prend sa place exacte dans structure.items (libre ou dans une Part).
        for i in range(paired):
            old_chapter = self.project.document.chapters[old_ids[i]]
            new_chapters[i].title = old_chapter.title
            new_chapters[i].title_visible = old_chapter.title_visible
            self.project.document.chapters[new_chapters[i].id] = new_chapters[i]
            self.project.document.structure.replace_chapter_id(old_ids[i], [new_chapters[i].id])
            self._discard_chapter_footnotes(old_chapter)
            del self.project.document.chapters[old_ids[i]]

        # Chapitres en trop côté NOUVEAU fichier : ajoutés libres en fin de séquence (pas de
        # position ancienne à hériter) — signalé par l'avertissement d'écart plus bas.
        for new_chapter in new_chapters[paired:]:
            self.project.document.add_chapter(new_chapter)

        # Chapitres en trop côté ANCIEN fichier : supprimés (delete_chapter nettoie aussi
        # structure.items/Part.chapter_ids).
        for old_id in old_ids[paired:]:
            old_chapter = self.project.document.chapters.get(old_id)
            if old_chapter is not None:
                self._discard_chapter_footnotes(old_chapter)
            self.project.document.delete_chapter(old_id)

        self.project.document.footnotes.update(new_footnotes)
        for asset_id, wrap in new_image_wraps.items():
            self.project.document.image_wraps.setdefault(asset_id, wrap)

        entry.chapter_ids = [c.id for c in new_chapters]
        self._backfill_image_alt_texts_from_paragraphs()

        font_counts = scan_fonts(source, resolver)
        for name, count in font_counts.items():
            self._font_counts[name] = self._font_counts.get(name, 0) + count
            self.project.document.known_font_counts[name] = (
                self.project.document.known_font_counts.get(name, 0) + count
            )

        self.chapters_changed.emit()
        self.structure_changed.emit()  # replace_chapter_id modifie items/Part.chapter_ids en place
        self.assets_changed.emit()
        self.fonts_changed.emit()
        self.emit_unsupported_image_warnings()

        if len(new_chapters) != len(old_ids):
            self.warning_occurred.emit(
                f"« {path.name} » contient maintenant {len(new_chapters)} chapitre(s) au lieu de "
                f"{len(old_ids)} : les {paired} premiers chapitres ont conservé leur titre et leur "
                "position, mais vérifiez la fin du fichier — des chapitres ont pu être ajoutés ou "
                "supprimés et nécessitent une relecture manuelle."
            )

        if new_orphan_image_asset_ids:
            count = len(new_orphan_image_asset_ids)
            self.warning_occurred.emit(
                f"{count} image(s) ancrée(s) à la page (hors de tout paragraphe dans le fichier "
                "Writer) ont été rattachées automatiquement à l'endroit où elles apparaissent dans "
                "le document. Leur position exacte dans le livre peut différer légèrement de "
                "l'intention d'origine : vérifiez leur emplacement après import."
            )

        if new_unresolved_image_hrefs:
            count = len(new_unresolved_image_hrefs)
            self.warning_occurred.emit(
                f"{count} image(s) du fichier Writer n'ont pas pu être localisées avec certitude "
                "et ne sont peut-être pas incluses dans l'EPUB généré : vérifiez le contenu du "
                "livre après génération."
            )

        odt_metadata = extract_book_metadata(source)
        if odt_metadata is not None:
            self.odt_metadata_found.emit(odt_metadata, path.name)

        add_recent_file(path, "imported")
        self.recent_files_changed.emit()

        return entry

    def _insert_free_chapters_in_alphanumeric_order(self, entry: SourceOdtFile, new_chapter_ids: list[str]) -> None:
        """Insère le bloc de chapitres d'un fichier ODT tout juste importé à sa position
        alphanumérique correcte parmi les chapitres LIBRES existants (jamais dans une Part —
        l'utilisateur peut avoir déjà organisé une partie, on ne la réordonne jamais). Reproduit
        pour l'import automatique la même clé de tri que
        StructureEditor._file_and_position_sort_key (tri naturel du nom de fichier ODT, cf.
        model.text_utils.natural_sort_key — "Chapitre2" avant "Chapitre12", pas un tri texte brut
        qui les inverserait), déjà utilisée pour un tri manuel via « Assigner à une partie… » —
        mais ici appliquée à l'insertion elle-même, pas seulement à un tri ponctuel de sélection.

        Ne retrie JAMAIS l'existant : ne fait qu'insérer le nouveau bloc au bon endroit, pour
        qu'un réordonnancement manuel antérieur (drag & drop dans l'onglet Structure) reste
        intact — cohérent avec le principe déjà en place que structure.items est la source de
        vérité de l'ordre affiché, jamais retriée globalement après coup."""
        items = self.project.document.structure.items
        new_key = natural_sort_key(entry.path.name)

        insert_at = len(items)
        for idx, item in enumerate(items):
            if not isinstance(item, str):
                continue  # une Part n'est jamais déplacée ni utilisée comme repère de tri
            other_chapter = self.project.document.chapters.get(item)
            if other_chapter is None or other_chapter.source_odt_id is None:
                continue
            other_entry = next(
                (f for f in self.project.source_odt_files if f.id == other_chapter.source_odt_id), None)
            if other_entry is None:
                continue
            if natural_sort_key(other_entry.path.name) > new_key:
                insert_at = idx
                break

        items[insert_at:insert_at] = new_chapter_ids

    def import_epub_file(self, path: Path) -> list[str]:
        """Importe un .epub (Epubeur ou externe) : les chapitres et parties importés
        s'ajoutent au document courant. Retourne les avertissements éventuels."""
        path = Path(path)
        try:
            imported_document, imported_metadata, warnings = import_epub(path, self.asset_store)
        except Exception as exc:
            self.error_occurred.emit(describe_epub_open_error(exc, path.name))
            return []

        # Pas add_chapter() : son effet de bord (ajout en libre en fin de séquence) créerait un
        # doublon avec la vraie structure importée ajoutée juste après (chaque chapitre
        # apparaîtrait deux fois : une fois libre, une fois dans sa Part/position réelle).
        for chapter in imported_document.chapters.values():
            self.project.document.chapters[chapter.id] = chapter
        self.project.document.structure.items.extend(imported_document.structure.items)

        existing_families = {lf.family for lf in self.project.document.locked_fonts}
        for lf in imported_document.locked_fonts:
            if lf.family not in existing_families:
                self.project.document.locked_fonts.append(lf)
                for f in lf.files:
                    if f.file_path:
                        self._load_font_into_application(f.file_path)

        for name, count in scan_fonts_in_document(imported_document).items():
            self._font_counts[name] = self._font_counts.get(name, 0) + count
            self.project.document.known_font_counts[name] = (
                self.project.document.known_font_counts.get(name, 0) + count
            )

        self.chapters_changed.emit()
        self.structure_changed.emit()
        self.assets_changed.emit()
        self.fonts_changed.emit()
        self.epub_imported.emit(str(path))
        self.metadata_imported.emit(imported_metadata)

        for warning in warnings:
            self.warning_occurred.emit(warning)
        self.emit_unsupported_image_warnings()

        add_recent_file(path, "imported")
        self.recent_files_changed.emit()

        return warnings

    def font_counts(self) -> dict[str, int]:
        return dict(self._font_counts)

    def lock_font_files(self, family: str, file_paths: list[Path]) -> None:
        """Fige family en associant un ou plusieurs fichiers physiques (variantes weight/style
        distinctes, ex. Regular + Bold). Chaque fichier est analysé individuellement (Qt chargé
        et déchargé un par un — voir model.font_variant_detection.detect_font_variant, jamais
        plusieurs à la fois sous peine de fusion ambiguë des styles côté QFontDatabase). En cas
        de collision de (weight, italic) entre deux fichiers de cette sélection, seul le premier
        dans l'ordre choisi par l'utilisateur est conservé, les autres sont ignorés et signalés."""
        seen_variants: dict[tuple[int, bool], Path] = {}
        ignored: list[Path] = []
        new_files: list[LockedFontFile] = []
        for path in file_paths:
            weight, italic, style_name = detect_font_variant(path)
            key = (weight, italic)
            if key in seen_variants:
                ignored.append(path)
                continue
            seen_variants[key] = path
            new_files.append(LockedFontFile(file_path=str(path), weight=weight, italic=italic,
                                             style_name=style_name))

        existing = self.project.document.locked_font_for_family(family)
        if existing is not None:
            existing.files = new_files
        else:
            self.project.document.locked_fonts.append(LockedFont(family=family, files=new_files))

        for f in new_files:
            self._load_font_into_application(f.file_path)
        self.fonts_changed.emit()

        if ignored:
            names = ", ".join(p.name for p in ignored)
            self.warning_occurred.emit(
                f"Fichier(s) ignoré(s) pour « {family} » : même graisse/style qu'un fichier déjà "
                f"sélectionné — {names}"
            )

    def lock_font_without_file(self, family: str) -> None:
        """Fige une police sans fichier associé (case cochée mais sélecteur annulé) : garde
        l'intention de l'utilisateur plutôt que de décocher silencieusement — validate_document
        bloquera la génération EPUB avec un message clair tant qu'aucun fichier n'est fourni."""
        if self.project.document.locked_font_for_family(family) is None:
            self.project.document.locked_fonts.append(LockedFont(family=family, files=[]))
        self.fonts_changed.emit()

    def unlock_font(self, family: str) -> None:
        self.project.document.locked_fonts = [
            lf for lf in self.project.document.locked_fonts if lf.family != family
        ]
        self.fonts_changed.emit()

    def unlock_all_fonts(self) -> None:
        self.project.document.locked_fonts = []
        self.fonts_changed.emit()

    def is_font_locked(self, family: str) -> bool:
        return self.project.document.locked_font_for_family(family) is not None

    def _load_font_into_application(self, font_file: str) -> None:
        """Charge le fichier de police dans QFontDatabase pour qu'elle soit affichable
        dans les aperçus de l'app (QTextBrowser) — sans ça, seule la référence au nom de
        police est connue, mais Qt n'a pas les données de la police pour la dessiner."""
        if not Path(font_file).exists():
            return
        QFontDatabase.addApplicationFont(font_file)

    def merge_chapters(self, id_a: str, id_b: str) -> None:
        self._snapshot_structure()
        self.project.document.merge_chapters(id_a, id_b)
        self.chapters_changed.emit()
        self.structure_changed.emit()

    def split_chapter(self, chapter_id: str, split_at_paragraph_index: int) -> None:
        self._snapshot_structure()
        self.project.document.split_chapter(chapter_id, split_at_paragraph_index)
        self.chapters_changed.emit()
        self.structure_changed.emit()

    def create_part(self, title: str) -> None:
        self._snapshot_structure()
        part = Part.create(title=title)
        self.project.document.structure.items.append(part)
        self.structure_changed.emit()

    def rename_part(self, part_id: str, title: str) -> None:
        part = next((p for p in self.project.document.structure.parts() if p.id == part_id), None)
        if part is None:
            return
        self._snapshot_structure()
        part.title = title
        self.structure_changed.emit()

    def rename_chapter(self, chapter_id: str, title: str, title_visible: bool | None = None) -> None:
        """`title_visible` : None laisse le champ inchangé (renommage seul, ex. juste pour la
        table des matières) — n'est jamais déduit automatiquement de `title` ici, pour ne jamais
        faire apparaître un titre dans le texte du chapitre sans action explicite de
        l'utilisateur (cf. case à cocher du dialogue de renommage, ui/structure_editor.py)."""
        chapter = self.project.document.chapters.get(chapter_id)
        if chapter is None:
            return
        self._snapshot_structure()
        chapter.title = title
        if title_visible is not None:
            chapter.title_visible = title_visible
        self.chapters_changed.emit()

    def remove_page_break(self, chapter_id: str, paragraph_index: int) -> None:
        """Retire le saut de page manuel porté par le paragraphe à cet index — le paragraphe
        reste à sa place, seul le passage à un nouveau fichier XHTML à la génération EPUB
        disparaît (fusion visuelle avec le segment précédent)."""
        chapter = self.project.document.chapters.get(chapter_id)
        if chapter is None or not (0 <= paragraph_index < len(chapter.paragraphs)):
            return
        block = chapter.paragraphs[paragraph_index]
        if not isinstance(block, Paragraph):
            return  # une Table ne porte jamais de saut de page manuel dans ce modèle
        self._snapshot_structure()
        block.page_break_before = False
        self.chapters_changed.emit()

    def add_image_as_chapter(self, file_path: Path) -> str | None:
        """Ingère file_path comme asset CHAPTER_POV et crée un nouveau chapitre libre en fin de
        séquence, titre = nom de fichier sans extension (pour le retrouver dans l'arbre de
        Structure), contenant un unique Paragraph(image=...). Retourne l'id du chapitre créé, ou
        None si le format n'est pas supporté (rien n'est ajouté au projet dans ce cas, seul un
        avertissement est émis). N'affecte jamais le fichier source (lecture seule)."""
        file_path = Path(file_path)
        if not self.warn_and_reject_if_unsupported(file_path):
            return None
        self._snapshot_structure()
        asset = self.asset_store.ingest_bytes(file_path.read_bytes(), file_path.name, AssetRole.CHAPTER_POV)
        chapter = Chapter.create(title=file_path.stem)
        # Chapter.create dérive title_visible=True dès qu'un titre est fourni (cf. model/document.py)
        # — correct pour un vrai titre de chapitre, mais un nom de fichier n'est pas un titre
        # littéraire à afficher en <h1> dans le texte/EPUB : le titre ne doit servir ici qu'à
        # identifier le chapitre dans l'arbre de Structure (ui/structure_editor.py affiche
        # chapter.title indépendamment de title_visible).
        chapter.title_visible = False
        chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id=asset.id))]
        self.project.document.add_chapter(chapter)
        self.chapters_changed.emit()
        self.structure_changed.emit()
        self.assets_changed.emit()
        return chapter.id

    def insert_image_after_paragraph(self, chapter_id: str, paragraph_index: int, file_path: Path) -> None:
        """Insère un nouveau Paragraph(image=...) juste après le paragraphe donné, dans le même
        chapitre. Taille 100% et pas d'habillage par défaut (absence d'entrée dans
        image_display_sizes/image_wraps, cf. Document.image_display_size/image_wrap). Ne fait
        rien si le format n'est pas supporté (avertissement émis à la place)."""
        chapter = self.project.document.chapters.get(chapter_id)
        if chapter is None or not (0 <= paragraph_index < len(chapter.paragraphs)):
            return
        file_path = Path(file_path)
        if not self.warn_and_reject_if_unsupported(file_path):
            return
        self._snapshot_structure()
        asset = self.asset_store.ingest_bytes(file_path.read_bytes(), file_path.name, AssetRole.CHAPTER_POV)
        new_paragraph = Paragraph(image=ImageAnchor(asset_id=asset.id))
        chapter.paragraphs.insert(paragraph_index + 1, new_paragraph)
        self.chapters_changed.emit()
        self.assets_changed.emit()

    def insert_existing_asset_after_paragraph(self, chapter_id: str, paragraph_index: int, asset_id: str) -> None:
        """Comme insert_image_after_paragraph, mais pour "Coller l'image ici" (menu contextuel de
        la preview Structure) : réutilise un asset déjà présent dans AssetStore (image
        copiée/coupée ailleurs dans le projet) au lieu de ré-ingérer un fichier, pour ne jamais
        créer un doublon de l'asset d'origine."""
        chapter = self.project.document.chapters.get(chapter_id)
        if chapter is None or not (0 <= paragraph_index < len(chapter.paragraphs)):
            return
        if self.asset_store.get(asset_id) is None:
            return
        self._snapshot_structure()
        new_paragraph = Paragraph(image=ImageAnchor(asset_id=asset_id))
        chapter.paragraphs.insert(paragraph_index + 1, new_paragraph)
        self.chapters_changed.emit()
        self.assets_changed.emit()

    def _on_clipboard_changed(self) -> None:
        if self._suppress_next_clipboard_change:
            self._suppress_next_clipboard_change = False
            return
        self._copied_asset_id = None

    def copy_image_to_clipboard(self, asset_id: str) -> None:
        """Écrit le fichier réel de l'asset dans le presse-papier Windows, comme un Copier de
        fichier depuis l'Explorateur — utilisable tel quel dans un autre logiciel. En parallèle,
        mémorise asset_id en interne pour que paste_image_source()/un "Coller l'image ici"
        réutilise directement cet asset existant sans repasser par une ré-ingestion de fichier."""
        if self.asset_store.get(asset_id) is None:
            return
        path = self.asset_store.path_for(asset_id)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        self._copied_asset_id = asset_id
        self._suppress_next_clipboard_change = True
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setMimeData(mime)

    def paste_image_source(self) -> str | Path | None:
        """Retourne ce que "Coller l'image ici" doit utiliser : un asset_id (str) déjà connu
        d'AssetStore si Copier/Couper vient d'être fait quelque part dans l'appli, sinon un Path
        si le presse-papier Windows contient un fichier PNG/JPEG externe (copié depuis
        l'Explorateur), sinon None (pas d'action proposée). Une image bitmap brute (Ctrl+C dans
        un logiciel type Writer, sans fichier associé) n'est PAS acceptée : aucun moyen de
        vérifier son format d'origine avant de l'avoir déjà ré-encodée, contrairement à un vrai
        fichier."""
        if self._copied_asset_id is not None and self.asset_store.get(self._copied_asset_id) is not None:
            return self._copied_asset_id
        clipboard = QGuiApplication.clipboard()
        mime = clipboard.mimeData() if clipboard is not None else None
        if mime is None or not mime.hasUrls():
            return None
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.suffix.lower().lstrip(".") in SUPPORTED_IMAGE_EXTENSIONS:
                return path
        return None

    def _drop_asset_if_orphaned(self, asset_id: str) -> None:
        """Nettoyage final commun aux deux points d'entrée de suppression d'image : si asset_id
        n'est plus référencé nulle part, retire ses entrées des dicts annexes. Ne supprime
        JAMAIS le fichier physique dans AssetStore : la pile undo (_snapshot_structure) ne clone
        que project.document, jamais asset_store — une suppression physique immédiate cassait
        silencieusement Ctrl+Z (la référence revenait, pas le fichier, laissant une image cassée
        dans l'aperçu). Un asset orphelin n'est de toute façon jamais inclus dans l'EPUB généré
        (epub/builder.py n'embarque que les assets réellement référencés au moment de la
        génération) : le laisser sur le disque du projet n'a donc aucune conséquence sur le
        livre produit, juste un peu d'espace .epbz non nettoyé."""
        if self.project.document.is_asset_referenced(asset_id):
            return
        self.project.document.image_display_sizes.pop(asset_id, None)
        self.project.document.image_wraps.pop(asset_id, None)
        self.project.document.image_alt_texts.pop(asset_id, None)

    def delete_orphaned_asset(self, asset_id: str) -> None:
        """Suppression DÉFINITIVE et NON ANNULABLE du fichier physique d'un asset orphelin
        (bouton "Supprimer définitivement" de la section Images orphelines) — contrairement à
        remove_image_everywhere/remove_image_occurrence, qui ne retirent jamais le fichier
        (cf. _drop_asset_if_orphaned). No-op si l'asset est encore référencé quelque part : ne
        supprime jamais une image utilisée, même par erreur d'appel."""
        if self.project.document.is_asset_referenced(asset_id):
            return
        self.asset_store.remove(asset_id)
        self.assets_changed.emit()

    def _delete_chapter_if_emptied_image_chapter(self, chapter_id: str) -> bool:
        """Si le chapitre a EXACTEMENT 1 paragraphe restant, un Paragraph (jamais une Table) avec
        image=None ET runs=[], supprime le chapitre entier et retourne True. Appelé APRÈS avoir
        posé image=None sur le paragraphe concerné, jamais avant."""
        chapter = self.project.document.chapters.get(chapter_id)
        if chapter is None or len(chapter.paragraphs) != 1:
            return False
        only = chapter.paragraphs[0]
        if isinstance(only, Paragraph) and only.image is None and only.runs == []:
            self.project.document.delete_chapter(chapter_id)
            return True
        return False

    def remove_image_everywhere(self, asset_id: str) -> None:
        """Retire cette image de TOUTES ses occurrences dans le livre (bouton de l'onglet
        Images). Un chapitre devenu vide (n'était composé que de cette image) est supprimé
        entièrement. L'asset devenu orphelin (plus référencé nulle part) reste sur le disque du
        projet — voir _drop_asset_if_orphaned et delete_orphaned_asset pour la suppression
        physique définitive, séparée et non annulable."""
        self._snapshot_structure()
        any_chapter_deleted = False
        for chapter in list(self.project.document.chapters.values()):
            changed = False
            for para in iter_all_paragraphs(chapter.paragraphs):
                if para.image is not None and para.image.asset_id == asset_id:
                    para.image = None
                    changed = True
            if not changed:
                continue
            if chapter.pov_image_asset_id == asset_id:
                chapter.pov_image_asset_id = None
            if self._delete_chapter_if_emptied_image_chapter(chapter.id):
                any_chapter_deleted = True
        self._drop_asset_if_orphaned(asset_id)
        self.chapters_changed.emit()
        if any_chapter_deleted:
            self.structure_changed.emit()
        self.assets_changed.emit()

    def remove_image_occurrence(self, chapter_id: str, paragraph_index: int) -> None:
        """Retire SEULEMENT cette occurrence précise de l'image (clic droit dans la preview de
        Structure) — les autres occurrences éventuelles ailleurs restent intactes."""
        chapter = self.project.document.chapters.get(chapter_id)
        if chapter is None or not (0 <= paragraph_index < len(chapter.paragraphs)):
            return
        block = chapter.paragraphs[paragraph_index]
        if not isinstance(block, Paragraph) or block.image is None:
            return
        asset_id = block.image.asset_id
        self._snapshot_structure()
        block.image = None
        if chapter.pov_image_asset_id == asset_id:
            chapter.pov_image_asset_id = None
        chapter_deleted = self._delete_chapter_if_emptied_image_chapter(chapter_id)
        self._drop_asset_if_orphaned(asset_id)
        self.chapters_changed.emit()
        if chapter_deleted:
            self.structure_changed.emit()
        self.assets_changed.emit()

    def set_part_title_page(self, part_id: str, has_title_page: bool) -> None:
        part = next((p for p in self.project.document.structure.parts() if p.id == part_id), None)
        if part is None:
            return
        self._snapshot_structure()
        part.has_title_page = has_title_page
        self.structure_changed.emit()

    def assign_chapters_to_part(self, chapter_ids: list[str], part_id: str) -> None:
        part = next((p for p in self.project.document.structure.parts() if p.id == part_id), None)
        if part is None:
            return
        self._snapshot_structure()
        for chapter_id in chapter_ids:
            self.project.document.structure.replace_chapter_id(chapter_id, [])
            part.chapter_ids.append(chapter_id)
        self.structure_changed.emit()

    def unassign_chapters(self, chapter_ids: list[str]) -> None:
        """Retire les chapitres donnés de leur Part et les réinsère comme éléments libres,
        juste après la Part dont chacun vient d'être extrait (préserve la proximité de
        contexte ; un drag & drop manuel permet ensuite de les repositionner ailleurs)."""
        self._snapshot_structure()
        structure = self.project.document.structure
        for chapter_id in chapter_ids:
            insert_at = None
            for idx, item in enumerate(structure.items):
                if isinstance(item, Part) and chapter_id in item.chapter_ids:
                    insert_at = idx + 1
                    break
            if insert_at is None:
                continue  # déjà libre ou introuvable : rien à faire
            structure.replace_chapter_id(chapter_id, [])
            structure.items.insert(insert_at, chapter_id)
        self.structure_changed.emit()

    def delete_chapter(self, chapter_id: str) -> None:
        """Supprime définitivement le chapitre (texte compris) du projet Epubeur en cours —
        n'affecte jamais le fichier .odt source. Ctrl+Z permet de revenir en arrière tant que
        le projet n'est pas fermé/rouvert (comme toute autre action de structure)."""
        if chapter_id not in self.project.document.chapters:
            return
        self._snapshot_structure()
        self.project.document.delete_chapter(chapter_id)
        self.chapters_changed.emit()
        self.structure_changed.emit()

    def delete_part(self, part_id: str) -> None:
        """Supprime la partie (le groupement) ; ses chapitres redeviennent libres, aucun texte
        n'est perdu — voir Document.delete_part."""
        part = next((p for p in self.project.document.structure.parts() if p.id == part_id), None)
        if part is None:
            return
        self._snapshot_structure()
        self.project.document.delete_part(part_id)
        self.structure_changed.emit()

    def apply_reordered_structure(self, new_items: list) -> None:
        """Remplace document.structure.items par le résultat d'une réorganisation manuelle
        (drag & drop) déjà reconstruite à partir de l'état affiché dans l'UI — Part et
        chapitres libres mélangés, dans l'ordre exact laissé par Qt après le drop."""
        self._snapshot_structure()
        self.project.document.structure.items = new_items
        self.structure_changed.emit()

    def set_cover_asset(self, asset_id: str | None) -> None:
        self._snapshot_structure()
        self.project.document.cover_asset_id = asset_id
        self.assets_changed.emit()

    def set_back_cover_asset(self, asset_id: str | None) -> None:
        self._snapshot_structure()
        self.project.document.back_cover_asset_id = asset_id
        self.assets_changed.emit()

    def remove_cover_asset(self) -> None:
        self.set_cover_asset(None)

    def remove_back_cover_asset(self) -> None:
        self.set_back_cover_asset(None)

    def set_image_display_size(self, asset_id: str, size: ImageDisplaySize) -> None:
        self._snapshot_structure()
        self.project.document.image_display_sizes[asset_id] = size
        self.assets_changed.emit()

    def set_all_images_display_size(self, size: ImageDisplaySize) -> None:
        """Applique la même taille à toutes les images de chapitre du projet (rôle
        CHAPTER_POV), en une seule action annulable — pas une par image."""
        asset_ids = [a.id for a in self.asset_store.all_assets() if a.role == AssetRole.CHAPTER_POV]
        if not asset_ids:
            return
        self._snapshot_structure()
        for asset_id in asset_ids:
            self.project.document.image_display_sizes[asset_id] = size
        self.assets_changed.emit()

    def set_image_wrap(self, asset_id: str, wrap: ImageWrap) -> None:
        self._snapshot_structure()
        self.project.document.image_wraps[asset_id] = wrap
        self.assets_changed.emit()

    def set_all_images_wrap(self, wrap: ImageWrap) -> None:
        """Applique le même habillage à toutes les images de chapitre du projet (rôle
        CHAPTER_POV), en une seule action annulable — pas une par image."""
        asset_ids = [a.id for a in self.asset_store.all_assets() if a.role == AssetRole.CHAPTER_POV]
        if not asset_ids:
            return
        self._snapshot_structure()
        for asset_id in asset_ids:
            self.project.document.image_wraps[asset_id] = wrap
        self.assets_changed.emit()

    def set_image_alt_text(self, asset_id: str, alt_text: str) -> None:
        """Description unique par image (une par asset_id, pas par occurrence/chapitre), saisie
        dans l'onglet Images — prime sur ImageAnchor.alt_text (svg:desc lu à l'import ODT) au
        rendu, cf. epub/html_render.py."""
        self._snapshot_structure()
        self.project.document.image_alt_texts[asset_id] = alt_text
        self.assets_changed.emit()

    def rename_image(self, asset_id: str, new_stem: str) -> None:
        """Renomme le libellé affiché d'une image (ImageAsset.original_filename) — ce nom est
        désormais aussi celui écrit dans le zip EPUB généré (epub/builder.py), sauf pour la
        couverture/4e de couverture qui gardent toujours un nom fixe. Pas de _snapshot_structure
        : cette mutation touche asset_store, pas project.document, donc hors de la pile undo
        (même limitation déjà connue pour delete_orphaned_asset)."""
        self.asset_store.rename(asset_id, new_stem)
        self.assets_changed.emit()

    def save_project_as(self, epbz_path: Path) -> bool:
        """Enregistre le projet dans CE fichier .epbz (nouveau chemin, ou changement de nom).
        Retourne True si la sauvegarde a réussi. En cas d'échec, émet error_occurred avec un
        message compréhensible plutôt que de laisser remonter l'exception. Lit directement les
        assets depuis self.asset_store.root (jamais de copie préalable nécessaire, contrairement
        à l'ancien format dossier) : le .epbz est reconstruit en entier à chaque sauvegarde."""
        epbz_path = Path(epbz_path)
        try:
            save_project_epbz(self.project, self.asset_store, epbz_path)
            self.project.epbz_path = epbz_path
            add_recent_project(epbz_path)
            self.recent_files_changed.emit()
            return True
        except Exception as exc:
            self.error_occurred.emit(describe_project_save_error(exc))
            return False

    def save_project(self) -> bool:
        """« Enregistrer » simple : réécrit le .epbz déjà associé au projet."""
        if self.project.epbz_path is None:
            self.error_occurred.emit(
                "Ce projet n'a encore jamais été enregistré : utilisez « Enregistrer sous… » pour choisir un fichier .epbz."
            )
            return False
        return self.save_project_as(self.project.epbz_path)

    def load_project_from(self, epbz_path: Path) -> list[str]:
        epbz_path = Path(epbz_path)
        try:
            project, extract_dir, warnings = load_project_epbz(epbz_path)
        except Exception as exc:
            self.error_occurred.emit(describe_project_load_error(exc, epbz_path.name))
            return []

        self.project = project
        self._temp_assets_dir = extract_dir
        self.asset_store = AssetStore(extract_dir / "assets")
        self._font_counts = dict(project.document.known_font_counts)
        # Un projet sauvegardé avant l'introduction de image_alt_texts peut contenir des
        # ImageAnchor avec un alt_text (svg:desc) jamais reporté vers la description globale.
        self._backfill_image_alt_texts_from_paragraphs()

        for lf in project.document.locked_fonts:
            for f in lf.files:
                if f.file_path:
                    self._load_font_into_application(f.file_path)

        self.chapters_changed.emit()
        self.structure_changed.emit()
        self.assets_changed.emit()
        self.fonts_changed.emit()
        self.project_loaded.emit()

        add_recent_project(epbz_path)
        self.recent_files_changed.emit()

        for warning in warnings:
            self.warning_occurred.emit(warning)

        return warnings
