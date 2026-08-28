import uuid
from dataclasses import dataclass, field
from enum import Enum

from model.styles import CharFormat, ParagraphAlign, ParagraphKind


def new_id() -> str:
    return uuid.uuid4().hex


class ImageDisplaySize(Enum):
    SMALL = 25
    MEDIUM = 50
    LARGE = 75
    FULL = 100


class ImageWrap(Enum):
    NONE = "none"
    LEFT = "left"
    RIGHT = "right"


@dataclass
class Run:
    text: str
    fmt: CharFormat
    link_url: str | None = None
    # Identifie l'appel de note (text:note ODF) que ce run représente : le texte du run est le
    # symbole de citation déjà calculé par Writer (ex. "1"), rendu en exposant + lien vers l'ancre
    # du corps de note (cf. epub/html_render.py::run_to_html). None si ce run n'est pas un appel de
    # note. Relie le point d'appel au contenu (Document.footnotes, dict séparé) — même pattern
    # d'indirection que Paragraph.image -> Document.image_alt_texts, jamais le corps de la note
    # recopié inline dans le run lui-même.
    note_id: str | None = None


@dataclass
class ImageAnchor:
    asset_id: str
    alt_text: str = ""


@dataclass
class Paragraph:
    kind: ParagraphKind = ParagraphKind.BODY
    align: ParagraphAlign = ParagraphAlign.LEFT
    runs: list[Run] = field(default_factory=list)
    list_level: int = 0
    # Identifie l'instance de liste ODF (<text:list>) ou HTML (<ul>/<ol>) à laquelle ce paragraphe
    # appartient à ce niveau précis. None si list_level == 0, ou si issu d'un projet sauvegardé avant
    # ce champ (repli : fusion par contiguïté de level/kind, ancien comportement). Non déterministe,
    # régénéré à chaque lecture ODT/réimport EPUB (new_id()), jamais stable entre deux imports.
    list_group_id: str | None = None
    image: ImageAnchor | None = None
    page_break_before: bool = False

    def plain_text(self) -> str:
        return "".join(run.text for run in self.runs)


@dataclass
class TableCell:
    """Une cellule de tableau. Contient une séquence de Paragraph (jamais de Table imbriquée :
    l'ODF autorise techniquement un tableau dans une cellule, mais Writer ne le produit qu'à la
    main dans des cas très rares — hors scope de cette première version, une telle cellule est
    simplement lue comme si son contenu de tableau imbriqué n'existait pas, cf.
    odt/chapter_detector.py). colspan/rowspan valent 1 par défaut (cellule normale, pas de
    fusion) — jamais 0 : une fusion ODF non standard indiquant 0 colonne/ligne couverte n'a pas
    de sens visuel, elle est normalisée à 1 dès la lecture (cf. odt/chapter_detector.py)."""
    paragraphs: list[Paragraph] = field(default_factory=list)
    colspan: int = 1
    rowspan: int = 1
    is_header: bool = False  # cellule d'en-tête (table:table-header-rows) -> <th> au rendu


@dataclass
class TableRow:
    cells: list[TableCell] = field(default_factory=list)


@dataclass
class Table:
    """Un tableau Writer, tel qu'un bloc de plus haut niveau dans Chapter.paragraphs (union
    polymorphe avec Paragraph, même pattern que BookStructure.items: list["Part | str"]).
    N'a pas de .kind/.align/.runs propres : sa présentation reste celle du CSS de base généré
    par l'app (epub/css.py), jamais lue depuis les styles ODF de cellule/colonne (hors scope
    de cette première version)."""
    rows: list[TableRow] = field(default_factory=list)


def iter_all_paragraphs(blocks: "list[Paragraph | Table]"):
    """Aplatit une séquence Chapter.paragraphs (mélange Paragraph/Table) en un flux de tous
    les Paragraph qu'elle contient, y compris ceux imbriqués dans les cellules d'une Table —
    pour tout traitement qui doit voir chaque paragraphe indépendamment de sa position
    structurelle (scan de polices, recherche d'images, candidats alt-text). Ne préserve
    aucune information de position (index de bloc, ligne/colonne) : uniquement pour les
    traitements qui n'en ont pas besoin."""
    for block in blocks:
        if isinstance(block, Table):
            for row in block.rows:
                for cell in row.cells:
                    yield from cell.paragraphs
        else:
            yield block


@dataclass
class Chapter:
    id: str
    source_odt_id: str | None = None
    source_order_index: int = 0
    title: str = ""
    title_visible: bool = True
    paragraphs: "list[Paragraph | Table]" = field(default_factory=list)
    pov_image_asset_id: str | None = None

    @staticmethod
    def create(title: str = "", source_odt_id: str | None = None, source_order_index: int = 0) -> "Chapter":
        # title_visible dérivé de bool(title) : un chapitre créé sans titre n'a rien à afficher
        # dans le texte tant que l'utilisateur ne l'a pas explicitement demandé (cf. rename_chapter,
        # qui ne bascule plus title_visible automatiquement — voir controller.py).
        return Chapter(id=new_id(), title=title, title_visible=bool(title),
                        source_odt_id=source_odt_id, source_order_index=source_order_index)


@dataclass
class Part:
    id: str
    title: str = ""
    chapter_ids: list[str] = field(default_factory=list)
    has_title_page: bool = False  # insère une page de garde (titre seul, centré) avant les chapitres

    @staticmethod
    def create(title: str = "") -> "Part":
        return Part(id=new_id(), title=title)


@dataclass
class BookStructure:
    """Séquence unique ordonnée du livre : chaque élément de `items` est soit une Part
    (groupe de chapitres avec titre), soit un `str` (un chapter_id directement — un chapitre
    "libre", sans partie, positionné à cet endroit précis de la séquence). Ce mélange permet
    de placer un chapitre n'importe où (début, milieu, fin, entre deux parties) sans avoir à
    créer une partie juste pour lui."""

    items: list["Part | str"] = field(default_factory=list)

    def parts(self) -> list[Part]:
        """Vue filtrée en lecture seule des seules Part de la séquence — pour l'UI/les tests
        qui veulent juste itérer les parties existantes. Méthode (pas propriété) pour signaler
        que c'est une vue recalculée, pas un champ mutable : `structure.parts().append(...)`
        ne persisterait rien, contrairement à `structure.items.append(...)`."""
        return [it for it in self.items if isinstance(it, Part)]

    def free_chapter_ids(self) -> list[str]:
        return [it for it in self.items if isinstance(it, str)]

    def all_referenced_chapter_ids(self) -> set[str]:
        ids: set[str] = set()
        for it in self.items:
            if isinstance(it, Part):
                ids.update(it.chapter_ids)
            else:
                ids.add(it)
        return ids

    def replace_chapter_id(self, old_id: str, new_ids: list[str]) -> None:
        """Substitue old_id par new_ids (1 id -> plusieurs pour une scission,
        plusieurs -> 1 pour une fusion en appelant plusieurs fois) partout où il apparaît,
        que old_id soit dans une Part.chapter_ids ou libre directement dans items — préserve
        la position dans les deux cas."""
        new_idx = 0
        while new_idx < len(self.items):
            it = self.items[new_idx]
            if isinstance(it, Part):
                idx = 0
                while idx < len(it.chapter_ids):
                    if it.chapter_ids[idx] == old_id:
                        it.chapter_ids[idx:idx + 1] = new_ids
                        idx += len(new_ids)
                    else:
                        idx += 1
                new_idx += 1
            else:
                if it == old_id:
                    self.items[new_idx:new_idx + 1] = new_ids
                    new_idx += len(new_ids)
                else:
                    new_idx += 1

    def append_free_chapter(self, chapter_id: str) -> None:
        self.items.append(chapter_id)


@dataclass
class LockedFontFile:
    file_path: str
    weight: int = 400          # valeur CSS numérique (100..900), source: QFontDatabase.weight()
    italic: bool = False       # source: QFontDatabase.italic()
    style_name: str = ""       # nom de style brut Qt (ex. "Bold", "Black", "Thin Italic"),
                                # affichage/debug uniquement, jamais reparsé comme source de vérité


@dataclass
class LockedFont:
    family: str
    files: list[LockedFontFile] = field(default_factory=list)

    def primary_file_path(self) -> str | None:
        """Premier fichier (Regular si présent, sinon le premier de la liste) — utilisé
        partout où l'ancien code ne voulait qu'un fichier représentatif."""
        for f in self.files:
            if f.weight == 400 and not f.italic:
                return f.file_path
        return self.files[0].file_path if self.files else None


@dataclass
class Document:
    chapters: dict[str, Chapter] = field(default_factory=dict)
    structure: BookStructure = field(default_factory=BookStructure)
    locked_fonts: list[LockedFont] = field(default_factory=list)
    cover_asset_id: str | None = None
    back_cover_asset_id: str | None = None
    image_display_sizes: dict[str, ImageDisplaySize] = field(default_factory=dict)
    # asset_id -> taille choisie ; absent du dict = ImageDisplaySize.FULL (défaut)
    image_wraps: dict[str, ImageWrap] = field(default_factory=dict)
    # asset_id -> habillage choisi ; absent du dict = ImageWrap.NONE (défaut, pas de flottement —
    # comportement d'avant ce chantier, préservé pour tout projet existant/image non concernée)
    image_alt_texts: dict[str, str] = field(default_factory=dict)
    # asset_id -> description unique par image (une par asset_id, pas par occurrence/chapitre) —
    # saisie dans l'onglet Images, prime sur ImageAnchor.alt_text (le svg:desc brut lu à l'import
    # ODT) quand elle est renseignée. Absent du dict = pas encore de description globale saisie.
    footnotes: dict[str, list[Paragraph]] = field(default_factory=dict)
    # note_id (généré par new_id() à la lecture ODT ou au réimport EPUB, jamais l'id ODF/HTML brut
    # réutilisé tel quel) -> corps complet de la note, une séquence de Paragraph pure (jamais de
    # Table imbriquée : cas exotique ignoré silencieusement, comme pour TableCell). Une entrée non
    # référencée par aucun Run.note_id n'est jamais nettoyée automatiquement ni ne casse le rendu :
    # elle est simplement ignorée (cf. epub/html_render.py, qui ne rend que les notes réellement
    # appelées dans le segment courant).

    def image_display_size(self, asset_id: str) -> ImageDisplaySize:
        return self.image_display_sizes.get(asset_id, ImageDisplaySize.FULL)

    def image_wrap(self, asset_id: str) -> ImageWrap:
        return self.image_wraps.get(asset_id, ImageWrap.NONE)

    def image_alt_text(self, asset_id: str) -> str:
        return self.image_alt_texts.get(asset_id, "")

    def image_alt_text_candidates(self, asset_id: str) -> list[str]:
        """Toutes les descriptions ODF distinctes et non vides (ImageAnchor.alt_text) trouvées
        pour cet asset_id à travers tous les chapitres, dans l'ordre de première apparition —
        pour proposer un cycle de navigation entre elles dans l'onglet Images quand plusieurs
        fichiers sources décrivent la même image différemment (une seule reste retenue dans
        image_alt_texts, cf. controller._backfill_image_alt_texts_from_paragraphs)."""
        candidates: list[str] = []
        for chapter in self.chapters.values():
            for para in iter_all_paragraphs(chapter.paragraphs):
                if para.image is None or para.image.asset_id != asset_id:
                    continue
                text = para.image.alt_text.strip()
                if text and text not in candidates:
                    candidates.append(text)
        return candidates

    def is_asset_referenced(self, asset_id: str) -> bool:
        """True si asset_id est utilisé quelque part : au moins un Paragraph.image.asset_id (y
        compris dans une cellule de tableau, via iter_all_paragraphs) dans n'importe quel
        chapitre, OU cover_asset_id, OU back_cover_asset_id."""
        if asset_id in (self.cover_asset_id, self.back_cover_asset_id):
            return True
        for chapter in self.chapters.values():
            for para in iter_all_paragraphs(chapter.paragraphs):
                if para.image is not None and para.image.asset_id == asset_id:
                    return True
        return False

    def add_chapter(self, chapter: Chapter) -> None:
        """Ajoute le chapitre et le positionne immédiatement comme élément libre en fin de
        séquence — jamais invisible tant qu'il n'est pas explicitement assigné à une partie.
        Attention : un appelant qui pose ensuite `document.structure.items` explicitement
        (ex. import EPUB, reconstruction de fixture de test) doit écraser `items` entièrement
        plutôt que d'y ajouter, sous peine de dupliquer chaque chapitre (une fois libre via cet
        effet de bord, une fois dans sa vraie position) — voir controller.import_epub_file."""
        self.chapters[chapter.id] = chapter
        self.structure.append_free_chapter(chapter.id)

    def locked_font_for_family(self, family: str) -> LockedFont | None:
        return next((lf for lf in self.locked_fonts if lf.family == family), None)

    def delete_chapter(self, chapter_id: str) -> None:
        """Supprime définitivement le chapitre (et son texte) du projet Epubeur en cours —
        n'affecte jamais le fichier .odt source, qui n'est jamais réécrit par l'application."""
        self.chapters.pop(chapter_id, None)
        self.structure.replace_chapter_id(chapter_id, [])

    def delete_part(self, part_id: str) -> None:
        """Supprime la partie (le groupement), jamais son contenu : les chapitres qu'elle
        contenait redeviennent des éléments libres, insérés à la position de l'ancienne partie,
        dans leur ordre d'origine — aucun texte n'est perdu."""
        for idx, item in enumerate(self.structure.items):
            if isinstance(item, Part) and item.id == part_id:
                self.structure.items[idx:idx + 1] = item.chapter_ids
                return

    def merge_chapters(self, id_a: str, id_b: str) -> str:
        """Fusionne b dans a (concatène les paragraphes), retire b, remplace b par a dans structure."""
        chap_a = self.chapters[id_a]
        chap_b = self.chapters[id_b]
        chap_a.paragraphs.extend(chap_b.paragraphs)
        del self.chapters[id_b]
        self.structure.replace_chapter_id(id_b, [])
        return id_a

    def split_chapter(self, chapter_id: str, split_at_paragraph_index: int) -> tuple[str, str]:
        """Scinde un chapitre en deux au niveau du paragraphe donné (qui démarre le second)."""
        original = self.chapters[chapter_id]
        first = Chapter.create(
            title=original.title,
            source_odt_id=original.source_odt_id,
            source_order_index=original.source_order_index,
        )
        first.id = chapter_id
        first.title_visible = original.title_visible
        first.pov_image_asset_id = original.pov_image_asset_id
        first.paragraphs = original.paragraphs[:split_at_paragraph_index]

        second = Chapter.create(
            title="",
            source_odt_id=original.source_odt_id,
            source_order_index=original.source_order_index,
        )
        second.pov_image_asset_id = original.pov_image_asset_id
        second.paragraphs = original.paragraphs[split_at_paragraph_index:]

        self.chapters[first.id] = first
        self.chapters[second.id] = second
        self.structure.replace_chapter_id(chapter_id, [first.id, second.id])
        return first.id, second.id
