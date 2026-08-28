from ebooklib import epub

from model.document import BookStructure, Chapter, Part
from model.text_utils import flatten_to_single_line


def build_landmarks(cover_item: "epub.EpubHtml | None", nav_item: "epub.EpubHtml",
                     bodymatter_item: "epub.EpubHtml | None") -> list[dict]:
    """Repères de navigation EPUB3 (<nav epub:type="landmarks">, distincts de la table des
    matières) : "cover" (couverture, si définie), "toc" (le sommaire lui-même) et "bodymatter"
    (premier élément de contenu réel du spine — page de garde de partie ou chapitre). Consommé
    via book.guide, seul mécanisme qu'ebooklib expose pour générer cette section (les types
    EPUB2 "guide" ne couvrent pas tous les types EPUB3, mais "cover"/"text" suffisent ici et
    "text" est automatiquement traduit en "bodymatter" par ebooklib à l'écriture)."""
    landmarks: list[dict] = []
    if cover_item is not None:
        landmarks.append({"type": "cover", "href": cover_item.file_name, "title": "Couverture"})
    landmarks.append({"type": "toc", "href": nav_item.file_name, "title": "Sommaire"})
    if bodymatter_item is not None:
        landmarks.append({"type": "text", "href": bodymatter_item.file_name, "title": "Début du texte"})
    return landmarks


def build_toc(structure: BookStructure, chapters: dict[str, Chapter],
              html_items: dict[str, epub.EpubHtml],
              part_title_page_items: dict[str, epub.EpubHtml] | None = None) -> list:
    """Construit la structure attendue par ebooklib pour nav.xhtml + toc.ncx : une liste
    mêlant des tuples (Section(part.title), [Link, ...]) — Parties > Chapitres — et des
    Link isolés de premier niveau pour les chapitres libres (sans partie), exactement à leur
    position dans la séquence. Si la partie a une page de garde, le titre de la partie
    devient lui-même le lien cliquable vers cette page (ebooklib rend une Section avec href
    en <a>, sans href en <span>) — évite de répéter le même titre une fois comme
    regroupement et une fois comme premier lien enfant."""
    part_title_page_items = part_title_page_items or {}
    toc = []
    for item in structure.items:
        if isinstance(item, Part):
            part = item
            links = []
            for chapter_id in part.chapter_ids:
                chapter = chapters.get(chapter_id)
                html_item = html_items.get(chapter_id)
                if chapter is None or html_item is None:
                    continue
                title = chapter.title if (chapter.title_visible and chapter.title) else (chapter.title or "Chapitre")
                links.append(epub.Link(html_item.file_name, flatten_to_single_line(title), html_item.id))
            if not links:
                continue

            title_page_item = part_title_page_items.get(part.id)
            section_href = title_page_item.file_name if title_page_item is not None else ""
            section_title = flatten_to_single_line(part.title or "Partie")
            section = epub.Section(section_title, href=section_href)
            toc.append((section, links))
        else:
            chapter_id = item
            chapter = chapters.get(chapter_id)
            html_item = html_items.get(chapter_id)
            if chapter is None or html_item is None:
                continue
            title = chapter.title if (chapter.title_visible and chapter.title) else (chapter.title or "Chapitre")
            toc.append(epub.Link(html_item.file_name, flatten_to_single_line(title), html_item.id))
    return toc
