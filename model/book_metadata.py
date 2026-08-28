from dataclasses import dataclass, field


@dataclass
class Contributor:
    name: str
    role_code: str = ""  # code MARC Relator (ex. "trl", "ill") — voir CONTRIBUTOR_ROLE_LABELS ;
                          # vide = dc:contributor sans rôle typé (opf:role/property "role" omis)
    file_as: str = ""  # nom de tri du contributeur, ex. "Dupont, Isabelle" — même principe que
                        # BookMetadata.author_file_as ; vide = pas de opf:file-as écrit


@dataclass
class BookMetadata:
    """Métadonnées Dublin Core + EPUB3 du livre, toutes optionnelles sauf le titre."""

    title: str = "Sans titre"
    author: str = ""
    author_file_as: str = ""  # nom de tri de l'auteur, ex. "Sartre, Jean-Paul" — utilisé par les
                                # liseuses/bibliothèques pour classer par nom de famille, jamais
                                # affiché tel quel (dc:creator reste le nom affiché normalement,
                                # ex. "Jean-Paul Sartre") ; vide = pas de opf:file-as écrit
    language: str = "fr"
    isbn: str = ""  # ISBN-10 ou ISBN-13, tirets/espaces acceptés — devient l'identifiant
                     # principal du livre si fourni (sinon un UUID généré fait office d'identifiant)
    description: str = ""
    publication_date: str = ""  # format libre accepté par l'utilisateur, ex: "2026-08-25" ou "2026"
    publisher: str = ""
    subjects: list[str] = field(default_factory=list)  # mots-clés / genre (texte libre)
    thema_codes: list[str] = field(default_factory=list)  # codes Thema (classification
                                                             # thématique européenne, gratuite),
                                                             # ex. "FBA" — voir model/thema.py
    bisac_code: str = ""  # code BISAC (taxonomie américaine équivalente), saisi librement par
                           # l'utilisateur — jamais validé contre un référentiel embarqué : BISAC
                           # est payant pour un usage embarqué en logiciel (licence BISG), donc
                           # aucune liste BISAC n'est intégrée à Epubeur, contrairement à Thema
    rights: str = ""
    contributors: list[Contributor] = field(default_factory=list)
    source: str = ""  # dc:source — œuvre source, si adaptation
    relation: str = ""  # dc:relation — lien vers une ressource associée (coffret, suite étroitement
                         # liée, édition alternative...), texte libre
    coverage: str = ""  # dc:coverage — portée géographique/temporelle de l'œuvre (ex. "Paris,
                         # 1920-1940"), texte libre, surtout utile pour un ouvrage académique/de
                         # référence
    collection_title: str = ""  # nom de la série/collection (EPUB3 belongs-to-collection)
    collection_position: str = ""  # numéro dans la série (EPUB3 group-position)
    reading_direction: str = "ltr"  # "ltr" ou "rtl" — sens de lecture du livre (ex. manga,
                                     # langues s'écrivant de droite à gauche comme l'arabe/l'hébreu)
    accessibility_summary: str = ""  # schema:accessibilitySummary — résumé en langage humain de
                                       # l'accessibilité du livre, saisi par l'utilisateur (à ne
                                       # pas confondre avec epub/accessibility.py::
                                       # build_accessibility_metadata, qui déduit automatiquement
                                       # des faits techniques structurés du contenu réel)
