import uuid
from pathlib import Path

from ebooklib import epub
from ebooklib.epub import NAMESPACES

from epub.accessibility import build_accessibility_metadata
from epub.css import LockedFontFaceSpec, build_css
from epub.font_obfuscation import postprocess_epub_zip
from epub.html_render import (
    back_cover_page_to_xhtml,
    build_family_to_css_class,
    chapter_to_xhtml,
    part_title_page_to_xhtml,
)
from epub.link_integrity import check_internal_link_integrity
from epub.toc import build_landmarks, build_toc
from model.assets import AssetStore
from model.book_metadata import BookMetadata, Contributor
from model.document import Paragraph, Part, Table, iter_all_paragraphs
from model.isbn import is_valid_isbn, normalize_isbn
from model.language import is_valid_language_code
from model.project import ProjectMeta
from model.thema import thema_label

CSS_HREF = "style/epubeur.css"


class EpubBuildError(Exception):
    pass


def split_chapter_into_segments(paragraphs: "list[Paragraph | Table]") -> "list[list[Paragraph | Table]]":
    """Découpe une liste de paragraphes en segments aux points où page_break_before=True,
    sauf au tout premier paragraphe (index 0) qui ne déclenche jamais de scission — il démarre
    déjà son propre fichier de toute façon. Un chapitre sans aucun saut de page interne
    retourne une liste à un seul segment (identité, non-régression). Une Table ne porte jamais
    ce champ dans ce modèle (isinstance requis avant l'accès)."""
    if not paragraphs:
        return [[]]
    segments: list[list] = [[]]
    for i, para in enumerate(paragraphs):
        if i > 0 and isinstance(para, Paragraph) and para.page_break_before:
            segments.append([])
        segments[-1].append(para)
    return segments


def validate_document(
    project: ProjectMeta,
    metadata: "BookMetadata | None" = None,
    asset_store: "AssetStore | None" = None,
) -> list[str]:
    errors = []
    document = project.document

    if metadata is not None and metadata.isbn.strip() and not is_valid_isbn(metadata.isbn):
        errors.append(f"ISBN invalide : « {metadata.isbn} » (format ou clé de contrôle incorrects).")

    if metadata is not None and metadata.reading_direction not in ("ltr", "rtl"):
        errors.append(f"Sens de lecture invalide : « {metadata.reading_direction} » (attendu ltr ou rtl).")

    if metadata is not None and not metadata.title.strip():
        errors.append("Titre du livre vide : un titre est obligatoire pour générer un EPUB valide.")

    if metadata is not None and metadata.language.strip() and not is_valid_language_code(metadata.language):
        errors.append(
            f"Code de langue invalide : « {metadata.language} » (attendu un code ISO 639, ex. « fr », « en-US »)."
        )

    seen_families: set[str] = set()
    for lf in document.locked_fonts:
        if not lf.family:
            errors.append("Police à figer sans nom de famille.")
        elif lf.family in seen_families:
            errors.append(f"Police à figer « {lf.family} » présente plusieurs fois.")
        seen_families.add(lf.family)

        if not lf.files:
            errors.append(f"Police à figer « {lf.family} » sans fichier de police fourni.")
        else:
            for lff in lf.files:
                if not lff.file_path:
                    errors.append(f"Police à figer « {lf.family} » contient une entrée sans fichier.")
                elif not Path(lff.file_path).exists():
                    errors.append(f"Fichier de police introuvable pour « {lf.family} » : {lff.file_path}")

    if asset_store is not None:
        def _check_asset(asset_id: str, context: str) -> None:
            asset = asset_store.get(asset_id)
            if asset is None:
                errors.append(f"{context} référence une image absente du projet (id « {asset_id} »).")
                return
            if not asset_store.path_for(asset_id).exists():
                errors.append(
                    f"{context} : fichier image introuvable sur le disque pour "
                    f"« {asset.original_filename} » (id « {asset_id} »)."
                )

        if document.cover_asset_id:
            _check_asset(document.cover_asset_id, "Image de couverture")

        if document.back_cover_asset_id:
            _check_asset(document.back_cover_asset_id, "Image de 4e de couverture")

        for chapter in document.chapters.values():
            for para in iter_all_paragraphs(chapter.paragraphs):
                chapter_label = chapter.title or "(chapitre sans titre)"
                for image in para.all_images():
                    _check_asset(image.asset_id, f"Image du chapitre « {chapter_label} »")

    # Une note appelée (Run.note_id) sans corps correspondant dans document.footnotes produirait
    # un lien <a href="#note-..."> pointant vers une ancre absente — détecté trop tard et de façon
    # peu explicite par check_internal_link_integrity (générique, "lien interne cassé", sans dire
    # qu'il s'agit d'une note). Vérifié ici en amont, avec un message qui identifie explicitement
    # la cause : ne devrait normalement jamais arriver (aucun mécanisme actuel ne peut produire un
    # Run.note_id sans entrée document.footnotes), mais rien ne le garantit structurellement — une
    # future modification manuelle du modèle (script, futur éditeur) pourrait le désynchroniser.
    missing_note_ids: set[str] = set()
    for chapter in document.chapters.values():
        for para in iter_all_paragraphs(chapter.paragraphs):
            for run in para.runs:
                if run.note_id and run.note_id not in document.footnotes:
                    missing_note_ids.add(run.note_id)
    if missing_note_ids:
        errors.append(
            f"{len(missing_note_ids)} appel(s) de note de bas de page référence(nt) une note "
            "dont le contenu est manquant : le livre ne peut pas être généré avec un lien de "
            "note cassé."
        )

    referenced_ids = document.structure.all_referenced_chapter_ids()
    orphan_ids = referenced_ids - document.chapters.keys()
    if orphan_ids:
        for part in document.structure.parts():
            missing_in_part = [cid for cid in part.chapter_ids if cid in orphan_ids]
            if missing_in_part:
                errors.append(
                    f"La partie « {part.title or '(sans titre)'} » référence "
                    f"{len(missing_in_part)} chapitre(s) qui n'existe(nt) plus dans le document."
                )
        free_orphans = [cid for cid in document.structure.free_chapter_ids() if cid in orphan_ids]
        if free_orphans:
            errors.append(
                f"{len(free_orphans)} chapitre(s) libre(s) référencé(s) dans la séquence du livre "
                f"n'existe(nt) plus dans le document."
            )

    if not referenced_ids - orphan_ids:
        errors.append(
            "Aucun chapitre valide à inclure dans l'EPUB : le livre serait généré sans contenu de lecture."
        )

    return errors


def find_unreferenced_chapters(project: ProjectMeta) -> list[str]:
    """Avertissements non bloquants pour les chapitres présents dans document.chapters mais
    jamais référencés dans document.structure.items (ni via une Part, ni comme chapitre libre) —
    un « chapitre fantôme » qui n'apparaîtra jamais dans l'EPUB généré, sans que ce soit en soi
    une erreur : l'utilisateur a pu le retirer intentionnellement de la séquence sans le supprimer."""
    document = project.document
    referenced_ids = document.structure.all_referenced_chapter_ids()
    phantom_ids = document.chapters.keys() - referenced_ids
    return [
        f"Le chapitre « {document.chapters[cid].title or '(sans titre)'} » n'est inclus dans "
        f"aucune partie ni dans la séquence du livre : il n'apparaîtra pas dans l'EPUB généré."
        for cid in phantom_ids
    ]


def build_epub(project: ProjectMeta, asset_store: AssetStore, output_path: Path,
               metadata: BookMetadata | None = None) -> Path:
    if metadata is None:
        metadata = BookMetadata()

    errors = validate_document(project, metadata, asset_store)
    if errors:
        raise EpubBuildError("; ".join(errors))

    document = project.document
    output_path = Path(output_path)
    # L'ISBN, quand fourni, devient l'identifiant principal du livre (celui que les liseuses et
    # boutiques utilisent pour identifier l'édition) — un UUID généré ne sert de secours que
    # si aucun ISBN n'est fourni, cf. urn:isbn: (convention symétrique de urn:uuid:).
    if metadata.isbn.strip():
        book_uid = f"urn:isbn:{normalize_isbn(metadata.isbn)}"
    else:
        book_uid = f"urn:uuid:{uuid.uuid4()}"

    book = epub.EpubBook()
    book.set_identifier(book_uid)
    if metadata.isbn.strip():
        # opf:scheme="ISBN" sur l'identifiant principal : forme la plus idiomatique de la norme
        # pour typer explicitement un dc:identifier (absent d'un urn:isbn: seul, qui reste
        # fonctionnel mais moins explicite) — jamais ajouté sur l'UUID de secours, qui n'est pas
        # un ISBN. set_identifier() n'accepte pas d'attributs supplémentaires : on complète donc
        # l'entrée qu'il vient de créer via set_unique_metadata (même id="id", mêmes others plus
        # opf:scheme).
        book.set_unique_metadata(
            "DC", "identifier", book_uid,
            {"id": book.IDENTIFIER_ID, f"{{{NAMESPACES['OPF']}}}scheme": "ISBN"},
        )
    book.set_title(metadata.title)
    book.set_language(metadata.language or "fr")
    book.set_direction(metadata.reading_direction)  # attribut page-progression-direction du spine OPF
    if metadata.author:
        book.add_author(metadata.author, file_as=metadata.author_file_as or None, role="aut")
    if metadata.description:
        book.add_metadata("DC", "description", metadata.description)
    if metadata.publication_date:
        book.add_metadata("DC", "date", metadata.publication_date)
    if metadata.publisher:
        book.add_metadata("DC", "publisher", metadata.publisher)
    for subject in metadata.subjects:
        if subject.strip():
            book.add_metadata("DC", "subject", subject.strip())
    for i, code in enumerate(metadata.thema_codes):
        if not code.strip():
            continue
        uid = f"thema-{i}"
        book.add_metadata("DC", "subject", thema_label(code.strip()), {"id": uid})
        book.add_metadata(None, "meta", "Thema", {"refines": f"#{uid}", "property": "authority"})
        book.add_metadata(None, "meta", code.strip(), {"refines": f"#{uid}", "property": "term"})
    if metadata.bisac_code.strip():
        uid = "bisac"
        book.add_metadata("DC", "subject", metadata.bisac_code.strip(), {"id": uid})
        book.add_metadata(None, "meta", "BISAC", {"refines": f"#{uid}", "property": "authority"})
        book.add_metadata(None, "meta", metadata.bisac_code.strip(), {"refines": f"#{uid}", "property": "term"})
    if metadata.rights:
        book.add_metadata("DC", "rights", metadata.rights)
    for i, contributor in enumerate(metadata.contributors):
        if not contributor.name.strip():
            continue
        uid = f"contributor-{i}"
        book.add_metadata("DC", "contributor", contributor.name, {"id": uid})
        if contributor.role_code:
            book.add_metadata(None, "meta", contributor.role_code,
                               {"refines": f"#{uid}", "property": "role", "scheme": "marc:relators"})
        if contributor.file_as:
            book.add_metadata(None, "meta", contributor.file_as,
                               {"refines": f"#{uid}", "property": "file-as"})
    if metadata.source:
        book.add_metadata("DC", "source", metadata.source)
    if metadata.relation:
        book.add_metadata("DC", "relation", metadata.relation)
    if metadata.coverage:
        book.add_metadata("DC", "coverage", metadata.coverage)
    if metadata.collection_title:
        book.add_metadata(None, "meta", metadata.collection_title,
                           {"id": "collection", "property": "belongs-to-collection"})
        book.add_metadata(None, "meta", "series",
                           {"refines": "#collection", "property": "collection-type"})
        if metadata.collection_position:
            book.add_metadata(None, "meta", metadata.collection_position,
                               {"refines": "#collection", "property": "group-position"})

    for property_name, value in build_accessibility_metadata(document):
        book.add_metadata(None, "meta", value, {"property": property_name})
    if metadata.accessibility_summary.strip():
        book.add_metadata(None, "meta", metadata.accessibility_summary.strip(),
                           {"property": "schema:accessibilitySummary"})

    family_to_css_class = build_family_to_css_class([lf.family for lf in document.locked_fonts])
    locked_font_specs: list[LockedFontFaceSpec] = []
    fonts_to_obfuscate: list[tuple[bytes, str]] = []  # (bytes, href dans le zip final)
    used_font_hrefs: set[str] = set()

    for lf in document.locked_fonts:
        css_class = family_to_css_class[lf.family]
        for file_index, lff in enumerate(lf.files):
            font_path = Path(lff.file_path)
            font_bytes = font_path.read_bytes()

            # Nom de fichier unique dans le zip : deux polices différentes (ou deux variantes
            # d'une même police) peuvent porter le même nom de fichier sur disque si choisies
            # depuis des dossiers différents.
            base_name = font_path.name
            candidate = base_name
            suffix = 2
            while candidate in used_font_hrefs:
                candidate = f"{font_path.stem}-{suffix}{font_path.suffix}"
                suffix += 1
            used_font_hrefs.add(candidate)
            font_href = f"fonts/{candidate}"

            font_item = epub.EpubItem(
                uid=f"locked-font-{css_class}-{file_index}",  # unique par fichier, pas juste par famille
                file_name=font_href,
                media_type="application/font-sfnt",
                content=font_bytes,
            )
            book.add_item(font_item)

            locked_font_specs.append(LockedFontFaceSpec(
                family=lf.family, css_class=css_class, font_href=candidate,
                weight=lff.weight, italic=lff.italic,
            ))
            fonts_to_obfuscate.append((font_bytes, font_href))

    used_pov_asset_ids: set[str] = set()
    for chapter in document.chapters.values():
        for para in iter_all_paragraphs(chapter.paragraphs):
            for image in para.all_images():
                used_pov_asset_ids.add(image.asset_id)
    relevant_image_sizes = {
        aid: size for aid, size in document.image_display_sizes.items() if aid in used_pov_asset_ids
    }

    css_content = build_css(locked_font_specs, relevant_image_sizes)
    css_item = epub.EpubItem(uid="style", file_name=CSS_HREF, media_type="text/css", content=css_content)
    book.add_item(css_item)

    # Nom de fichier écrit dans le zip pour chaque image : lisible (ImageAsset.original_filename,
    # éventuellement renommé dans l'onglet Images), jamais le hash asset_id — le hash reste
    # utilisé uniquement en interne par AssetStore pour la déduplication de stockage sur disque.
    # Sûr : le réimport d'un EPUB généré par Epubeur ne dépend jamais du nom de fichier
    # (data-epubeur-image porte l'asset_id indépendamment de src=, cf.
    # epub/html_normalize.py::_find_all_image_anchors), et le CSS de taille/habillage cible aussi
    # data-epubeur-image, jamais src= (epub/css.py::IMAGE_SIZE_RULE_TEMPLATE, IMAGE_WRAP_CSS).
    used_image_hrefs: set[str] = set()
    image_hrefs: dict[str, str] = {}

    # La 4e de couverture a un nom FIXE ("back_cover"), jamais dérivé de son original_filename —
    # réservé AVANT la boucle sur used_pov_asset_ids pour qu'aucune image de chapitre ne puisse
    # entrer en collision avec lui (improbable en pratique, gratuit à garantir).
    if document.back_cover_asset_id:
        back_cover_asset = asset_store.get(document.back_cover_asset_id)
        image_hrefs[document.back_cover_asset_id] = f"back_cover.{back_cover_asset.extension}"
        used_image_hrefs.add(image_hrefs[document.back_cover_asset_id])

    for asset_id in sorted(used_pov_asset_ids):  # ordre déterministe, indépendant de l'itération d'un set
        asset = asset_store.get(asset_id)
        base_stem = Path(asset.original_filename).stem or asset_id
        candidate = f"{base_stem}.{asset.extension}"
        suffix = 2
        while candidate in used_image_hrefs:
            candidate = f"{base_stem}-{suffix}.{asset.extension}"
            suffix += 1
        used_image_hrefs.add(candidate)
        image_hrefs[asset_id] = candidate

    added_image_ids: set[str] = set()

    def ensure_image_item(asset_id: str) -> str:
        href = f"images/{image_hrefs.get(asset_id, f'{asset_id}.{asset_store.get(asset_id).extension}')}"
        if asset_id not in added_image_ids:
            data = asset_store.path_for(asset_id).read_bytes()
            ext = asset_store.get(asset_id).extension
            media_type = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}"
            item = epub.EpubItem(uid=f"img-{asset_id}", file_name=href, media_type=media_type, content=data)
            book.add_item(item)
            added_image_ids.add(asset_id)
        return href

    if document.cover_asset_id:
        cover_asset = asset_store.get(document.cover_asset_id)
        # Nom FIXE ("cover"), jamais dérivé d'original_filename — indépendant du mapping
        # image_hrefs ci-dessus, qui ne couvre que les images de chapitre et la 4e de couverture.
        cover_href = f"images/cover.{cover_asset.extension}"
        book.set_cover(cover_href, asset_store.path_for(document.cover_asset_id).read_bytes())
        added_image_ids.add(document.cover_asset_id)

    html_items: dict[str, epub.EpubHtml] = {}
    part_title_page_items: dict[str, epub.EpubHtml] = {}
    spine = ["nav"]

    order_counter = 0

    def _add_chapter_to_book(chapter_id: str, order_counter: int) -> int:
        chapter = document.chapters.get(chapter_id)
        if chapter is None:
            return order_counter
        for para in iter_all_paragraphs(chapter.paragraphs):
            for image in para.all_images():
                ensure_image_item(image.asset_id)

        chapter_title = chapter.title if (chapter.title_visible and chapter.title) else (chapter.title or "Chapitre")
        segments = split_chapter_into_segments(chapter.paragraphs)

        for seg_index, segment_paragraphs in enumerate(segments):
            is_first = seg_index == 0
            if is_first:
                file_name = f"text/chapter_{order_counter}.xhtml"
                uid = f"chapter-{chapter_id}"
            else:
                file_name = f"text/chapter_{order_counter}_seg{seg_index + 1}.xhtml"
                uid = f"chapter-{chapter_id}-seg{seg_index + 1}"

            # ebooklib.EpubHtml.add_item(css_item) régénère le <link> lui-même à partir du
            # file_name brut du CSS ("style/epubeur.css"), sans le recalculer relativement au
            # dossier du chapitre ("text/") : le lien produit pointe alors vers un chemin
            # inexistant (text/style/epubeur.css). On construit donc le <link> nous-mêmes,
            # avec le vrai chemin relatif, et on l'injecte via add_link() (pas add_item) pour
            # éviter qu'ebooklib ne l'écrase par le sien.
            xhtml = chapter_to_xhtml(chapter, css_href=f"../{CSS_HREF}", family_to_css_class=family_to_css_class,
                                      asset_store=asset_store, paragraphs=segment_paragraphs,
                                      include_title=is_first, segment_index=seg_index,
                                      image_alt_texts=document.image_alt_texts,
                                      document_footnotes=document.footnotes,
                                      image_wraps=document.image_wraps,
                                      image_hrefs=image_hrefs)
            html_item = epub.EpubHtml(uid=uid, file_name=file_name, content=xhtml, title=chapter_title,
                                       direction=metadata.reading_direction)
            html_item.add_link(href=f"../{CSS_HREF}", rel="stylesheet", type="text/css")
            book.add_item(html_item)
            spine.append(html_item)

            if is_first:
                html_items[chapter_id] = html_item  # la TOC pointe toujours vers le premier segment
            order_counter += 1

        return order_counter

    for item in document.structure.items:
        if isinstance(item, Part):
            part = item
            if part.has_title_page and part.title:
                file_name = f"text/part_title_{order_counter}.xhtml"
                xhtml = part_title_page_to_xhtml(part.title, css_href=f"../{CSS_HREF}")
                title_page_item = epub.EpubHtml(uid=f"part-title-{part.id}", file_name=file_name, content=xhtml,
                                                 title=part.title, direction=metadata.reading_direction)
                title_page_item.add_link(href=f"../{CSS_HREF}", rel="stylesheet", type="text/css")
                book.add_item(title_page_item)
                part_title_page_items[part.id] = title_page_item
                spine.append(title_page_item)
                order_counter += 1

            for chapter_id in part.chapter_ids:
                order_counter = _add_chapter_to_book(chapter_id, order_counter)
        else:
            chapter_id = item
            order_counter = _add_chapter_to_book(chapter_id, order_counter)

    if document.back_cover_asset_id:
        back_cover_href = ensure_image_item(document.back_cover_asset_id)
        back_cover_xhtml = back_cover_page_to_xhtml(f"../{back_cover_href}", css_href=f"../{CSS_HREF}")
        back_cover_item = epub.EpubHtml(uid="back-cover", file_name="text/back_cover.xhtml",
                                         content=back_cover_xhtml, title="4e de couverture",
                                         direction=metadata.reading_direction)
        back_cover_item.add_link(href=f"../{CSS_HREF}", rel="stylesheet", type="text/css")
        back_cover_item.is_linear = False  # accessible en tournant les pages, absente de la TOC
        book.add_item(back_cover_item)
        spine.append(back_cover_item)

    book.toc = build_toc(document.structure, document.chapters, html_items, part_title_page_items)
    book.add_item(epub.EpubNcx())
    nav_item = epub.EpubNav()
    book.add_item(nav_item)
    book.spine = spine

    cover_item = book.get_item_with_id("cover") if document.cover_asset_id else None
    # Premier élément de contenu réel du spine après "nav" (spine[0]) — une page de garde de
    # partie ou un chapitre, selon ce qui a été ajouté en premier.
    bodymatter_item = spine[1] if len(spine) > 1 else None
    book.guide = build_landmarks(cover_item, nav_item, bodymatter_item)

    link_errors = check_internal_link_integrity(book)
    if link_errors:
        raise EpubBuildError("; ".join(link_errors))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(output_path), book, {"landmark_title": "Repères"})

    if fonts_to_obfuscate:
        zip_fonts = [(data, f"{book.FOLDER_NAME}/{href}") for data, href in fonts_to_obfuscate]
        postprocess_epub_zip(output_path, zip_fonts, book_uid)

    return output_path
