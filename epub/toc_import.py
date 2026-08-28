from ebooklib import epub

from model.document import Part


def _flatten_toc_links(toc_entries) -> list[tuple[str, str]]:
    """Aplati une entrée de book.toc (Link ou (Section, [enfants])) en liste (titre, href)."""
    flat: list[tuple[str, str]] = []
    for entry in toc_entries:
        if isinstance(entry, tuple):
            _section, children = entry
            flat.extend(_flatten_toc_links(children))
        elif isinstance(entry, epub.Link):
            flat.append((entry.title, entry.href.split("#")[0]))
        elif isinstance(entry, list):
            flat.extend(_flatten_toc_links(entry))
    return flat


def import_toc_structure(book: epub.EpubBook, href_to_chapter_id: dict[str, str],
                          part_title_page_hrefs: set[str] | None = None) -> tuple[list["Part | str"], list[str]]:
    """Construit la séquence structure.items depuis book.toc — mélange de Part (groupes avec
    titre) et de chapter_id isolés (chapitres libres, sans partie), dans l'ordre exact de la
    TOC. Si la TOC n'a réellement qu'un niveau (liste plate de Link, pas de Section), tous les
    chapitres deviennent des éléments libres : le standard EPUB n'a pas de notion de "Partie",
    donc rien ne justifie de les regrouper artificiellement dans une partie anonyme.
    Une Section dont le href pointe vers une page de garde de partie (cf.
    epub/html_render.part_title_page_to_xhtml, détectée par importer.py) redonne
    Part.has_title_page = True, plutôt que d'être traitée comme un chapitre.
    Retourne (items, warnings)."""
    part_title_page_hrefs = part_title_page_hrefs or set()
    warnings: list[str] = []
    toc = book.toc

    def is_title_page_href(href: str) -> bool:
        return href.split("#")[0] in part_title_page_hrefs

    has_hierarchy = any(isinstance(entry, tuple) for entry in toc)

    if not has_hierarchy:
        flat_links = _flatten_toc_links(toc)
        chapter_ids = [href_to_chapter_id[href] for _, href in flat_links
                        if href in href_to_chapter_id and not is_title_page_href(href)]
        if not chapter_ids:
            warnings.append("Aucune entrée de TOC n'a pu être associée à un chapitre importé.")
        return list(chapter_ids), warnings

    items: list["Part | str"] = []
    for entry in toc:
        if isinstance(entry, tuple):
            section, children = entry
            title = getattr(section, "title", None) or str(section)
            section_href = getattr(section, "href", "") or ""
            links = _flatten_toc_links(children)
            part = Part.create(title=title)
            part.chapter_ids = [href_to_chapter_id[href] for _, href in links
                                 if href in href_to_chapter_id and not is_title_page_href(href)]
            part.has_title_page = bool(section_href) and is_title_page_href(section_href)
            items.append(part)
        elif isinstance(entry, epub.Link):
            href = entry.href.split("#")[0]
            if is_title_page_href(href):
                continue
            if href in href_to_chapter_id:
                items.append(href_to_chapter_id[href])

    return items, warnings
