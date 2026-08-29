import posixpath
import re
import zipfile
from pathlib import Path

from ebooklib import epub, ITEM_DOCUMENT, ITEM_STYLE, ITEM_IMAGE

from epub.css_resolve import CssResolver, extract_font_face_rules
from epub.font_obfuscation import deobfuscate_font, parse_encryption_xml
from epub.html_normalize import html_to_paragraphs
from epub.toc_import import import_toc_structure
from model.assets import AssetRole, AssetStore
from model.book_metadata import BookMetadata, Contributor
from model.document import Chapter, Document, LockedFont, LockedFontFile, Paragraph, Part, iter_all_paragraphs, new_id
from model.styles import ParagraphKind

# Ancré sur le contexte exact émis par epub/html_render.py (<h1 data-epubeur-part-title="1">),
# jamais une simple sous-chaîne — même raison que _ROUND_TRIP_DIV_RE ci-dessous (un chapitre dont
# le texte contient littéralement ce marqueur en HTML échappé le ferait classer à tort comme
# page de garde de partie plutôt qu'un vrai chapitre).
_PART_TITLE_PAGE_RE = re.compile(r'<h1\s+data-epubeur-part-title="1">')
# Ancré sur le contexte exact émis par epub/html_render.py (<div class="epubeur-chapter"
# data-epubeur-chapter-id="..."[ data-epubeur-segment-index="..."]>) plutôt qu'une simple
# recherche de sous-chaîne — sans cet ancrage, un chapitre dont le TEXTE contient littéralement
# ce marqueur en HTML échappé (ex. un livre technique documentant ce format) le ferait extraire à
# tort comme un vrai marqueur de round-trip, avec un risque concret de fusion silencieuse de deux
# chapitres distincts partageant le même texte technique en exemple. Un seul regex pour les deux
# attributs (plutôt que deux recherches indépendantes) : ils sont toujours émis ensemble sur le
# même <div>, capturer les deux d'un coup garantit qu'ils restent cohérents entre eux.
_ROUND_TRIP_DIV_RE = re.compile(
    r'<div\s+class="epubeur-chapter"\s+data-epubeur-chapter-id="([^"]*)"'
    r'(?:\s+data-epubeur-segment-index="(\d+)")?'
)
LOCKED_FONT_CLASS_PREFIX = "epubeur-locked-font-"


def _extract_locked_fonts(epub_path: Path, css_texts: list[str], css_resolver: CssResolver,
                           asset_store: AssetStore) -> tuple[list[LockedFont], list[str]]:
    """Retrouve les polices figées (nom + fichier réel désobfusqué) depuis un EPUB généré par
    Epubeur. Le nom de chaque famille vient des règles CSS .epubeur-locked-font-*, le fichier
    associé vient des blocs @font-face (correspondance family -> url), croisés avec
    META-INF/encryption.xml (obfuscation IDPF, cf. epub/font_obfuscation.py) pour retrouver
    puis désobfusquer les bytes réels. Retourne (locked_fonts, warnings)."""
    warnings: list[str] = []

    # Le slug de classe n'est jamais reparsé pour en tirer un nom : on relit font-family
    # directement dans chaque règle .epubeur-locked-font-* correspondante.
    families: list[str] = []
    for selector in css_resolver.rules:
        if not selector.startswith(f".{LOCKED_FONT_CLASS_PREFIX}"):
            continue
        family_raw = css_resolver.rules[selector].get("font-family")
        if family_raw:
            families.append(family_raw.split(",")[0].strip().strip('"').strip("'"))

    if not families:
        return [], warnings

    def _warn_unresolved(family: str) -> None:
        warnings.append(
            f"La police figée « {family} » a été détectée mais son fichier n'a pas pu être "
            f"extrait de l'EPUB — il faudra la re-choisir manuellement dans l'onglet Police de caractères."
        )

    family_to_variants: dict[str, list[tuple[str, int, bool]]] = {}
    for css_text in css_texts:
        for family, variants in extract_font_face_rules(css_text).items():
            family_to_variants.setdefault(family, []).extend(variants)

    try:
        with zipfile.ZipFile(epub_path) as zf:
            names = set(zf.namelist())
            if "META-INF/encryption.xml" not in names:
                for family in families:
                    _warn_unresolved(family)
                return [], warnings
            encryption_xml = zf.read("META-INF/encryption.xml").decode("utf-8")
            obfuscated_hrefs = set(parse_encryption_xml(encryption_xml))

            opf_candidates = [n for n in names if n.endswith("content.opf")]
            book_uid = None
            if opf_candidates:
                opf_text = zf.read(opf_candidates[0]).decode("utf-8", errors="replace")
                match = re.search(
                    r"<dc:identifier[^>]*>(urn:(?:uuid|isbn):[^<]+)</dc:identifier>", opf_text
                )
                if match:
                    book_uid = match.group(1)

            fonts_dir = asset_store.root / "fonts"
            fonts_dir.mkdir(parents=True, exist_ok=True)
            used_names: set[str] = set()

            locked_fonts: list[LockedFont] = []
            for family in families:
                variants = family_to_variants.get(family)
                if not variants or book_uid is None:
                    _warn_unresolved(family)
                    continue

                files: list[LockedFontFile] = []
                for url, weight, italic in variants:
                    # url est relative au dossier du CSS (EPUB/style/), pas au dossier text/ —
                    # même logique de résolution que pour les <link> CSS ailleurs dans le projet.
                    resolved_href = posixpath.normpath(posixpath.join("EPUB/style", url))
                    if resolved_href not in obfuscated_hrefs or resolved_href not in names:
                        continue  # cette variante précise est illisible, les autres peuvent l'être

                    obfuscated = zf.read(resolved_href)
                    font_bytes = deobfuscate_font(obfuscated, book_uid)

                    base_name = Path(resolved_href).name
                    candidate = base_name
                    suffix = 2
                    while candidate in used_names:
                        stem, ext = Path(base_name).stem, Path(base_name).suffix
                        candidate = f"{stem}-{suffix}{ext}"
                        suffix += 1
                    used_names.add(candidate)

                    font_file_path = fonts_dir / candidate
                    font_file_path.write_bytes(font_bytes)
                    files.append(LockedFontFile(file_path=str(font_file_path), weight=weight, italic=italic))

                if not files:
                    _warn_unresolved(family)
                    continue
                locked_fonts.append(LockedFont(family=family, files=files))
    except (KeyError, zipfile.BadZipFile, OSError):
        for family in families:
            _warn_unresolved(family)
        return [], warnings

    return locked_fonts, warnings


def _first_value(values: list[tuple]) -> str:
    return values[0][0].strip() if values and values[0][0] else ""


def _extract_book_metadata(book: "epub.EpubBook") -> BookMetadata:
    """Reporte les métadonnées Dublin Core/EPUB3 déjà lues par ebooklib (book.get_metadata,
    book.direction) vers un BookMetadata prêt à pré-remplir l'onglet Générer — aussi bien pour
    un EPUB produit par Epubeur que pour un EPUB commercial externe (le vocabulaire lu ici est
    le standard EPUB3, pas un format propriétaire à l'app)."""
    title = _first_value(book.get_metadata("DC", "title")) or "Sans titre"
    author = _first_value(book.get_metadata("DC", "creator"))
    language = _first_value(book.get_metadata("DC", "language")) or "fr"
    description = _first_value(book.get_metadata("DC", "description"))
    publication_date = _first_value(book.get_metadata("DC", "date"))
    publisher = _first_value(book.get_metadata("DC", "publisher"))
    rights = _first_value(book.get_metadata("DC", "rights"))
    source = _first_value(book.get_metadata("DC", "source"))
    relation = _first_value(book.get_metadata("DC", "relation"))
    coverage = _first_value(book.get_metadata("DC", "coverage"))

    isbn = ""
    for identifier, _ in book.get_metadata("DC", "identifier"):
        if not identifier:
            continue
        match = re.match(r"urn:isbn:(.+)", identifier, re.IGNORECASE)
        if match:
            isbn = match.group(1).strip()
            break

    contributors: list[Contributor] = []
    role_by_refined_id: dict[str, str] = {}
    authority_by_refined_id: dict[str, str] = {}
    term_by_refined_id: dict[str, str] = {}
    file_as_by_refined_id: dict[str, str] = {}
    author_file_as = ""
    collection_title = ""
    collection_position = ""
    accessibility_summary = ""
    for value, others in book.get_metadata("OPF", "meta"):
        others = others or {}
        property_name = others.get("property")
        refines = (others.get("refines") or "").lstrip("#")
        if property_name == "role" and refines:
            role_by_refined_id[refines] = value or ""
        elif property_name == "authority" and refines:
            authority_by_refined_id[refines] = value or ""
        elif property_name == "term" and refines:
            term_by_refined_id[refines] = value or ""
        elif property_name == "file-as" and refines == "creator":
            author_file_as = value or ""
        elif property_name == "file-as" and refines:
            file_as_by_refined_id[refines] = value or ""
        elif property_name == "belongs-to-collection":
            collection_title = value or ""
        elif property_name == "group-position":
            collection_position = value or ""
        elif property_name == "schema:accessibilitySummary":
            accessibility_summary = value or ""

    for value, others in book.get_metadata("DC", "contributor"):
        if not value or not value.strip():
            continue
        contributor_id = (others or {}).get("id", "")
        contributors.append(Contributor(
            name=value.strip(),
            role_code=role_by_refined_id.get(contributor_id, ""),
            file_as=file_as_by_refined_id.get(contributor_id, ""),
        ))

    # Un dc:subject raffiné en authority="Thema"/"BISAC" (écrit par epub/builder.py) ne doit
    # jamais réapparaître comme mot-clé libre dans `subjects` — sinon un aller-retour EPUB
    # dupliquerait l'information (le code Thema/BISAC serait à la fois dans thema_codes/
    # bisac_code ET comme "mot-clé" dans subjects).
    subjects: list[str] = []
    thema_codes: list[str] = []
    bisac_code = ""
    for value, others in book.get_metadata("DC", "subject"):
        if not value or not value.strip():
            continue
        subj_id = (others or {}).get("id", "")
        authority = authority_by_refined_id.get(subj_id, "") if subj_id else ""
        term = term_by_refined_id.get(subj_id, "") if subj_id else ""
        if authority == "Thema" and term:
            thema_codes.append(term)
        elif authority == "BISAC" and term:
            bisac_code = term
        else:
            subjects.append(value.strip())

    reading_direction = book.direction if book.direction in ("ltr", "rtl") else "ltr"

    return BookMetadata(
        title=title, author=author, author_file_as=author_file_as, language=language, isbn=isbn,
        description=description, publication_date=publication_date, publisher=publisher,
        subjects=subjects, thema_codes=thema_codes, bisac_code=bisac_code, rights=rights,
        contributors=contributors, source=source, relation=relation, coverage=coverage,
        collection_title=collection_title,
        collection_position=collection_position, reading_direction=reading_direction,
        accessibility_summary=accessibility_summary,
    )


def _extract_round_trip_chapter_id(xhtml: str) -> str | None:
    match = _ROUND_TRIP_DIV_RE.search(xhtml)
    return match.group(1) if match else None


def _extract_round_trip_segment_index(xhtml: str) -> int:
    """Absence du marqueur = segment 0 (premier/unique segment) — cf. html_render.chapter_to_xhtml
    qui n'émet ce marqueur que pour segment_index > 0."""
    match = _ROUND_TRIP_DIV_RE.search(xhtml)
    if match is None or match.group(2) is None:
        return 0
    return int(match.group(2))


def _extract_title_text(xhtml: str) -> str:
    import re
    from html import unescape

    # <h1 littéral exigé avant l'attribut (pas seulement une recherche de sous-chaîne) : même
    # raison que _ROUND_TRIP_DIV_RE/_PART_TITLE_PAGE_RE ci-dessus.
    match = re.search(r'<h1\s+data-epubeur-chapter-title="1">(.*?)</h1>', xhtml, re.DOTALL)
    if match:
        # symétrique de html_render.title_html_block : les <br/> insérés pour un saut de
        # ligne manuel redeviennent '\n' au réimport, plutôt que du texte littéral "<br/>".
        raw = re.sub(r"<br\s*/?>", "\n", match.group(1))
        return unescape(raw).strip()
    match = re.search(r"<title>(.*?)</title>", xhtml, re.IGNORECASE | re.DOTALL)
    return unescape(match.group(1)).strip() if match else ""


def import_epub(path: Path, asset_store: AssetStore) -> tuple[Document, BookMetadata, list[str]]:
    """Importe un .epub (généré par Epubeur ou externe) vers le modèle pivot Document.
    Priorité au marqueur data-epubeur-chapter-id pour un round-trip fidèle ; sinon
    résolution CSS générique complète (balises sémantiques + classes + inline).
    Retourne (Document, BookMetadata, warnings)."""
    path = Path(path)
    book = epub.read_epub(str(path))
    warnings: list[str] = []
    metadata = _extract_book_metadata(book)

    css_texts = [item.get_content().decode("utf-8", errors="replace") for item in book.get_items_of_type(ITEM_STYLE)]
    css_resolver = CssResolver(css_texts)

    href_to_asset_id: dict[str, str] = {}
    for item in book.get_items_of_type(ITEM_IMAGE):
        data = item.get_content()
        asset = asset_store.ingest_bytes(data, Path(item.file_name).name, AssetRole.CHAPTER_POV)
        href_to_asset_id[item.file_name] = asset.id
        href_to_asset_id[Path(item.file_name).name] = asset.id
        href_to_asset_id[Path(item.file_name).stem] = asset.id
        # data-epubeur-image (posé par html_render._paragraph_inner_html) contient l'asset_id
        # d'ORIGINE, c'est-à-dire le hash SHA256 du contenu — indépendant du nom de fichier
        # physique dans le zip (qui est désormais un nom lisible, cf. epub/builder.py). Comme le
        # contenu binaire n'a pas changé, asset.id (hash recalculé par ingest_bytes ci-dessus) lui
        # est forcément identique : l'indexer directement est donc la clé de résolution fiable et
        # prioritaire (cf. html_normalize._find_all_image_anchors), indépendante du nom de fichier.
        href_to_asset_id[asset.id] = asset.id

    document = Document()
    href_to_chapter_id: dict[str, str] = {}
    part_title_page_hrefs: set[str] = set()

    # Passe 1 : un chapitre peut être scindé en plusieurs fichiers XHTML (un par saut de page
    # manuel interne, cf. epub/builder.py::split_chapter_into_segments) — chaque item est
    # d'abord parsé isolément, sans fusionner, round_trip_id étant évalué UNE FOIS PAR ITEM
    # (jamais réévalué en passe 2) : c'est ce qui garantit qu'un EPUB externe sans marqueur ne
    # fusionne jamais rien (chaque item externe génère un new_id() distinct, donc forme un
    # groupe singleton en passe 2).
    parsed_segments: list[tuple[str, int, str, list, str]] = []  # (chapter_id, seg_idx, title, paragraphs, href)

    for item in book.get_items_of_type(ITEM_DOCUMENT):
        if item.file_name == "nav.xhtml":
            continue
        xhtml = item.get_content().decode("utf-8", errors="replace")

        if _PART_TITLE_PAGE_RE.search(xhtml):
            # Page de garde de partie (cf. epub/html_render.part_title_page_to_xhtml) : ce
            # n'est pas un chapitre, elle ne doit pas apparaître dans document.chapters —
            # import_toc_structure la retrouvera via ce même href pour positionner
            # Part.has_title_page, plutôt que d'en faire un chapitre orphelin.
            part_title_page_hrefs.add(item.file_name)
            part_title_page_hrefs.add(Path(item.file_name).name)
            continue

        round_trip_id = _extract_round_trip_chapter_id(xhtml)
        chapter_id = round_trip_id or new_id()
        segment_index = _extract_round_trip_segment_index(xhtml)
        title = _extract_title_text(xhtml)

        paragraphs, local_footnotes, local_image_wraps = html_to_paragraphs(xhtml, css_resolver)

        for para in iter_all_paragraphs(paragraphs):
            resolved_images = []
            for image in para.all_images():
                resolved = href_to_asset_id.get(image.asset_id) or href_to_asset_id.get(
                    Path(image.asset_id).name)
                if resolved:
                    image.asset_id = resolved
                    resolved_images.append(image)
            para.image = resolved_images[0] if resolved_images else None
            para.extra_images = resolved_images[1:]

        # "premier gagne" à travers tous les segments réimportés, cohérent avec la lecture ODT
        # (cf. odt/chapter_detector.py) — un habillage déjà connu pour cet asset_id n'est jamais
        # écrasé par une occurrence ultérieure divergente.
        for raw_key, wrap in local_image_wraps.items():
            resolved = href_to_asset_id.get(raw_key) or href_to_asset_id.get(Path(raw_key).name)
            if resolved and resolved not in document.image_wraps:
                document.image_wraps[resolved] = wrap

        # Régénération systématique des note_id : jamais l'id HTML brut réutilisé tel quel (deux
        # segments distincts pourraient accidentellement partager un suffixe) — même précaution
        # que list_group_id, régénéré à chaque réimport plutôt que de faire confiance à un id
        # externe. Le remap a lieu segment par segment (chaque item XHTML est un fichier distinct).
        note_id_remap = {html_note_id: new_id() for html_note_id in local_footnotes}
        for para in iter_all_paragraphs(paragraphs):
            for run in para.runs:
                if run.note_id and run.note_id in note_id_remap:
                    run.note_id = note_id_remap[run.note_id]
        document.footnotes.update({
            note_id_remap[html_note_id]: note_paragraphs
            for html_note_id, note_paragraphs in local_footnotes.items()
        })

        parsed_segments.append((chapter_id, segment_index, title, paragraphs, item.file_name))

    # Passe 2 : regroupe les segments par chapter_id, en préservant l'ordre de première
    # apparition (dict Python normal, insertion-ordered), puis fusionne chaque groupe en un
    # seul Chapter — le saut de page manuel revient (page_break_before=True sur le premier
    # paragraphe de chaque segment non-initial), pas seulement le texte.
    grouped: dict[str, list[tuple[str, int, str, list, str]]] = {}
    for seg in parsed_segments:
        grouped.setdefault(seg[0], []).append(seg)

    order_index = 0
    for chapter_id, segs in grouped.items():
        segs.sort(key=lambda s: s[1])  # tri défensif par segment_index
        title = segs[0][2]  # titre = celui du segment 0 uniquement ; les segments suivants n'ont pas de h1
        merged_paragraphs = []
        for seg_idx, seg in enumerate(segs):
            paras = seg[3]
            if seg_idx > 0 and paras and isinstance(paras[0], Paragraph):
                paras[0].page_break_before = True
            merged_paragraphs.extend(paras)

        chapter = Chapter(
            id=chapter_id,
            source_odt_id=None,
            source_order_index=order_index,
            title=title,
            title_visible=bool(title),
            paragraphs=merged_paragraphs,
        )
        pov_images = [image.asset_id for p in iter_all_paragraphs(merged_paragraphs) for image in p.all_images()]
        if pov_images:
            chapter.pov_image_asset_id = pov_images[0]

        document.add_chapter(chapter)
        for seg in segs:
            href = seg[4]
            href_to_chapter_id[href] = chapter_id
            href_to_chapter_id[Path(href).name] = chapter_id
        order_index += 1

    items, toc_warnings = import_toc_structure(book, href_to_chapter_id, part_title_page_hrefs)
    warnings.extend(toc_warnings)

    # add_chapter() (appelé plus haut pour chaque chapitre) a déjà pré-rempli
    # document.structure.items avec tous les chapitres en libre, dans l'ordre du spine — avant
    # d'écraser avec la vraie structure importée (items, ci-dessus), on récupère l'ordre du
    # spine pour les chapitres absents de toute entrée de TOC, afin de ne jamais les perdre
    # (plutôt que de les laisser disparaître silencieusement en écrasant naïvement).
    spine_order = [cid for cid in document.structure.items if isinstance(cid, str)]
    referenced = {cid for cid in items if isinstance(cid, str)}
    referenced |= {cid for it in items if isinstance(it, Part) for cid in it.chapter_ids}
    for chapter_id in spine_order:
        if chapter_id not in referenced:
            items.append(chapter_id)
    document.structure.items = items

    locked_fonts, locked_font_warnings = _extract_locked_fonts(path, css_texts, css_resolver, asset_store)
    document.locked_fonts = locked_fonts
    warnings.extend(locked_font_warnings)

    parts = document.structure.parts()
    if not parts and document.structure.free_chapter_ids():
        warnings.append(
            "La table des matières importée n'avait qu'un seul niveau : tous les chapitres ont été "
            "importés comme chapitres libres, sans partie (le format EPUB ne porte pas de notion "
            "de « Partie »)."
        )

    return document, metadata, warnings
