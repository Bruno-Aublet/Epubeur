from pathlib import Path

from model.book_metadata import BookMetadata, Contributor
from model.document import (
    BookStructure,
    Chapter,
    Document,
    ImageAnchor,
    ImageDisplaySize,
    ImageWrap,
    LockedFont,
    LockedFontFile,
    Paragraph,
    Part,
    Run,
    Table,
    TableCell,
    TableRow,
)
from model.project import ProjectMeta, SourceOdtFile
from model.styles import CharFormat, ParagraphAlign, ParagraphKind, VerticalAlign

FORMAT_VERSION = 5


def _char_format_to_dict(fmt: CharFormat) -> dict:
    return {
        "bold": fmt.bold,
        "italic": fmt.italic,
        "underline": fmt.underline,
        "strikethrough": fmt.strikethrough,
        "vertical_align": fmt.vertical_align.name,
        "font_name": fmt.font_name,
    }


def _char_format_from_dict(d: dict) -> CharFormat:
    return CharFormat(
        bold=d["bold"],
        italic=d["italic"],
        underline=d["underline"],
        strikethrough=d["strikethrough"],
        vertical_align=VerticalAlign[d["vertical_align"]],
        font_name=d.get("font_name"),
    )


def _paragraph_to_dict(p: Paragraph) -> dict:
    return {
        "kind": p.kind.name,
        "align": p.align.name,
        "list_level": p.list_level,
        "list_group_id": p.list_group_id,
        "runs": [{"text": r.text, "fmt": _char_format_to_dict(r.fmt), "link_url": r.link_url,
                  "note_id": r.note_id} for r in p.runs],
        "image": {"asset_id": p.image.asset_id, "alt_text": p.image.alt_text} if p.image else None,
        # Deuxième image (et suivantes) ancrée(s) au même paragraphe, cf. Paragraph.extra_images —
        # absent des projets sauvegardés avant ce champ, d.get() ci-dessous replie sur [] pour eux.
        "extra_images": [{"asset_id": img.asset_id, "alt_text": img.alt_text} for img in p.extra_images],
        "page_break_before": p.page_break_before,
    }


def _paragraph_from_dict(d: dict) -> Paragraph:
    return Paragraph(
        kind=ParagraphKind[d["kind"]],
        align=ParagraphAlign[d["align"]],
        list_level=d.get("list_level", 0),
        list_group_id=d.get("list_group_id"),
        runs=[Run(text=r["text"], fmt=_char_format_from_dict(r["fmt"]), link_url=r.get("link_url"),
                  note_id=r.get("note_id"))
              for r in d["runs"]],
        image=ImageAnchor(**d["image"]) if d.get("image") else None,
        extra_images=[ImageAnchor(**img) for img in d.get("extra_images", [])],
        page_break_before=d.get("page_break_before", False),
    )


def _table_cell_to_dict(cell: TableCell) -> dict:
    return {
        "paragraphs": [_paragraph_to_dict(p) for p in cell.paragraphs],
        "colspan": cell.colspan,
        "rowspan": cell.rowspan,
        "is_header": cell.is_header,
    }


def _table_cell_from_dict(d: dict) -> TableCell:
    return TableCell(
        paragraphs=[_paragraph_from_dict(p) for p in d["paragraphs"]],
        colspan=d.get("colspan", 1),
        rowspan=d.get("rowspan", 1),
        is_header=d.get("is_header", False),
    )


def _table_to_dict(t: Table) -> dict:
    return {"rows": [{"cells": [_table_cell_to_dict(c) for c in row.cells]} for row in t.rows]}


def _table_from_dict(d: dict) -> Table:
    return Table(rows=[TableRow(cells=[_table_cell_from_dict(c) for c in row["cells"]])
                        for row in d["rows"]])


def _block_to_dict(block: "Paragraph | Table") -> dict:
    if isinstance(block, Table):
        return {"type": "table", **_table_to_dict(block)}
    return {"type": "paragraph", **_paragraph_to_dict(block)}


def _block_from_dict(d: dict) -> "Paragraph | Table":
    if d.get("type", "paragraph") == "table":
        return _table_from_dict(d)
    return _paragraph_from_dict(d)


def _chapter_to_dict(c: Chapter) -> dict:
    return {
        "id": c.id,
        "source_odt_id": c.source_odt_id,
        "source_order_index": c.source_order_index,
        "title": c.title,
        "title_visible": c.title_visible,
        "pov_image_asset_id": c.pov_image_asset_id,
        "paragraphs": [_block_to_dict(p) for p in c.paragraphs],
    }


def _chapter_from_dict(d: dict) -> Chapter:
    return Chapter(
        id=d["id"],
        source_odt_id=d.get("source_odt_id"),
        source_order_index=d.get("source_order_index", 0),
        title=d.get("title", ""),
        title_visible=d.get("title_visible", True),
        pov_image_asset_id=d.get("pov_image_asset_id"),
        paragraphs=[_block_from_dict(p) for p in d["paragraphs"]],
    )


def _locked_font_file_to_dict(f: LockedFontFile) -> dict:
    return {"file_path": f.file_path, "weight": f.weight, "italic": f.italic, "style_name": f.style_name}


def _locked_font_file_from_dict(d: dict) -> LockedFontFile:
    return LockedFontFile(
        file_path=d["file_path"],
        weight=d.get("weight", 400),
        italic=d.get("italic", False),
        style_name=d.get("style_name", ""),
    )


def document_to_dict(document: Document) -> dict:
    return {
        "chapters": {cid: _chapter_to_dict(c) for cid, c in document.chapters.items()},
        "structure": {
            "items": [
                {"type": "part", "id": it.id, "title": it.title, "chapter_ids": it.chapter_ids,
                 "has_title_page": it.has_title_page}
                if isinstance(it, Part) else
                {"type": "chapter", "chapter_id": it}
                for it in document.structure.items
            ]
        },
        "locked_fonts": [
            {"family": lf.family, "files": [_locked_font_file_to_dict(f) for f in lf.files]}
            for lf in document.locked_fonts
        ],
        "cover_asset_id": document.cover_asset_id,
        "back_cover_asset_id": document.back_cover_asset_id,
        "image_display_sizes": {aid: size.name for aid, size in document.image_display_sizes.items()},
        "image_wraps": {aid: wrap.name for aid, wrap in document.image_wraps.items()},
        "image_alt_texts": dict(document.image_alt_texts),
        "footnotes": {note_id: [_paragraph_to_dict(p) for p in paras]
                      for note_id, paras in document.footnotes.items()},
        "known_font_counts": dict(document.known_font_counts),
    }


def document_from_dict(d: dict) -> Document:
    chapters = {cid: _chapter_from_dict(cd) for cid, cd in d["chapters"].items()}

    structure_dict = d["structure"]
    if "items" in structure_dict:
        items: list[Part | str] = []
        for entry in structure_dict["items"]:
            if entry["type"] == "part":
                items.append(Part(id=entry["id"], title=entry["title"], chapter_ids=entry["chapter_ids"],
                                   has_title_page=entry.get("has_title_page", False)))
            else:
                items.append(entry["chapter_id"])
    else:
        # v3 et antérieur : "parts" seul, tous les chapitres non référencés étaient orphelins
        # et invisibles dans la structure. Migration : les Parts deviennent des items dans
        # l'ordre où elles apparaissaient ; les chapitres jamais référencés par aucune
        # Part.chapter_ids deviennent des éléments libres, ajoutés à la fin de la séquence
        # (aucune information d'ordre "prévu" n'existait pour eux dans l'ancien format).
        parts = [
            Part(id=pd["id"], title=pd["title"], chapter_ids=pd["chapter_ids"],
                 has_title_page=pd.get("has_title_page", False))
            for pd in structure_dict["parts"]
        ]
        referenced = {cid for p in parts for cid in p.chapter_ids}
        free_ids = [cid for cid in chapters if cid not in referenced]
        items = list(parts) + free_ids

    if "locked_fonts" in d:
        locked_fonts = []
        for lf in d["locked_fonts"]:
            if "files" in lf:
                # v3 : liste de fichiers par famille (weight/style par fichier).
                locked_fonts.append(LockedFont(
                    family=lf["family"],
                    files=[_locked_font_file_from_dict(f) for f in lf["files"]],
                ))
            else:
                # v2 : un seul file_path singulier -> liste à un élément, weight/style
                # inconnus (projet sauvegardé avant le support multi-fichiers) : Regular
                # non-italique par défaut, cohérent avec le comportement précédent où un
                # seul fichier représentait toute la famille.
                file_path = lf.get("file_path", "")
                files = [LockedFontFile(file_path=file_path)] if file_path else []
                locked_fonts.append(LockedFont(family=lf["family"], files=files))
    else:
        # Rétrocompatibilité : ancien schéma singulier plat (format_version 1), migré vers une
        # liste à un élément. Branché sur la présence de la clé, pas sur format_version,
        # plus robuste si un fichier a été édité à la main ou provient d'une version
        # intermédiaire.
        legacy_family = d.get("locked_font_family")
        legacy_file = d.get("locked_font_file")
        if legacy_family and legacy_file:
            locked_fonts = [LockedFont(family=legacy_family, files=[LockedFontFile(file_path=legacy_file)])]
        else:
            locked_fonts = []

    image_display_sizes = {
        aid: ImageDisplaySize[name] for aid, name in d.get("image_display_sizes", {}).items()
    }
    image_wraps = {aid: ImageWrap[name] for aid, name in d.get("image_wraps", {}).items()}
    image_alt_texts = dict(d.get("image_alt_texts", {}))
    footnotes = {note_id: [_paragraph_from_dict(p) for p in paras]
                 for note_id, paras in d.get("footnotes", {}).items()}

    document = Document(
        chapters=chapters,
        structure=BookStructure(items=items),
        locked_fonts=locked_fonts,
        cover_asset_id=d.get("cover_asset_id"),
        back_cover_asset_id=d.get("back_cover_asset_id"),
        image_display_sizes=image_display_sizes,
        image_wraps=image_wraps,
        image_alt_texts=image_alt_texts,
        footnotes=footnotes,
    )

    if "known_font_counts" in d:
        document.known_font_counts = dict(d["known_font_counts"])
    else:
        # Projet sauvegardé avant l'introduction de known_font_counts : repli sur un rescan du
        # modèle pivot (chapters + footnotes) — récupère les polices des runs, mais pas celles
        # utilisées uniquement dans un titre de chapitre (Chapter.title est une simple chaîne,
        # jamais scannée). Mieux que rien pour un ancien projet, mais pas parfaitement fidèle
        # à ce que l'import ODT original avait détecté.
        from model.font_scan import scan_fonts_in_document
        document.known_font_counts = dict(scan_fonts_in_document(document))

    return document


def _contributor_to_dict(c: Contributor) -> dict:
    return {"name": c.name, "role_code": c.role_code, "file_as": c.file_as}


def _contributor_from_dict(d: dict) -> Contributor:
    return Contributor(name=d["name"], role_code=d.get("role_code", ""), file_as=d.get("file_as", ""))


def book_metadata_to_dict(m: BookMetadata) -> dict:
    return {
        "title": m.title,
        "author": m.author,
        "author_file_as": m.author_file_as,
        "language": m.language,
        "isbn": m.isbn,
        "description": m.description,
        "publication_date": m.publication_date,
        "publisher": m.publisher,
        "subjects": list(m.subjects),
        "thema_codes": list(m.thema_codes),
        "bisac_code": m.bisac_code,
        "rights": m.rights,
        "contributors": [_contributor_to_dict(c) for c in m.contributors],
        "source": m.source,
        "relation": m.relation,
        "coverage": m.coverage,
        "collection_title": m.collection_title,
        "collection_position": m.collection_position,
        "reading_direction": m.reading_direction,
        "accessibility_summary": m.accessibility_summary,
    }


def book_metadata_from_dict(d: dict) -> BookMetadata:
    """Un .epbz sauvegardé avant l'introduction de la persistance des métadonnées (aucune clé
    "book_metadata" dans son JSON) doit charger proprement en BookMetadata() par défaut plutôt
    que de planter — .get(clé, défaut) systématique sur chaque champ, même convention que le
    reste de ce fichier (cf. locked_fonts, image_display_sizes...)."""
    return BookMetadata(
        title=d.get("title", "Sans titre"),
        author=d.get("author", ""),
        author_file_as=d.get("author_file_as", ""),
        language=d.get("language", "fr"),
        isbn=d.get("isbn", ""),
        description=d.get("description", ""),
        publication_date=d.get("publication_date", ""),
        publisher=d.get("publisher", ""),
        subjects=list(d.get("subjects", [])),
        thema_codes=list(d.get("thema_codes", [])),
        bisac_code=d.get("bisac_code", ""),
        rights=d.get("rights", ""),
        contributors=[_contributor_from_dict(c) for c in d.get("contributors", [])],
        source=d.get("source", ""),
        relation=d.get("relation", ""),
        coverage=d.get("coverage", ""),
        collection_title=d.get("collection_title", ""),
        collection_position=d.get("collection_position", ""),
        reading_direction=d.get("reading_direction", "ltr"),
        accessibility_summary=d.get("accessibility_summary", ""),
    )


def _build_project_dict(project: ProjectMeta) -> tuple[dict, list[tuple[str, Path]]]:
    """Construit le dict JSON du projet, prêt à être écrit par model/epbz.py (le seul format de
    sauvegarde restant — cf. model.epbz.save_project_epbz). Retourne aussi la liste des polices
    figées à copier dans le .epbz (sha256, chemin_absolu_source) : chaque LockedFontFile dont
    file_path est un chemin ABSOLU existant sur disque est réécrit dans le dict en
    "fonts/<sha256>.<ext>" (même convention de nommage par hash de contenu que
    AssetStore.ingest_bytes, pour la même raison de dédup/stabilité) — la copie physique des
    octets est à la charge de l'appelant, cette fonction reste pure (aucune I/O de police ici, à
    part le hash lui-même qui doit lire le fichier)."""
    import hashlib

    font_copy_list: list[tuple[str, Path]] = []
    # Dédoublonne par arcname (sha256 + extension) : deux LockedFontFile distincts peuvent
    # pointer vers des fichiers au contenu identique (ex. l'utilisateur pointe volontairement
    # Bold vers une copie du même fichier que Regular) — sans ceci, save_project_epbz écrivait
    # deux fois la même entrée dans le zip (UserWarning: Duplicate name), gaspillant de l'espace
    # sans perte fonctionnelle (les deux LockedFontFile retrouvent un chemin valide au rechargement).
    seen_arcnames: set[str] = set()
    document_dict = document_to_dict(project.document)
    for lf in document_dict["locked_fonts"]:
        for f in lf["files"]:
            raw_path = f["file_path"]
            if not raw_path:
                continue
            source_path = Path(raw_path)
            if not source_path.is_absolute() or not source_path.exists():
                continue
            sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
            f["file_path"] = f"fonts/{sha256}{source_path.suffix}"
            if f["file_path"] not in seen_arcnames:
                seen_arcnames.add(f["file_path"])
                font_copy_list.append((sha256, source_path))

    data = {
        "format_version": FORMAT_VERSION,
        "source_odt_files": [
            {
                "id": f.id,
                "path": str(f.path),
                "import_order": f.import_order,
                "chapter_ids": f.chapter_ids,
            }
            for f in project.source_odt_files
        ],
        "document": document_dict,
        "book_metadata": book_metadata_to_dict(project.book_metadata),
    }
    return data, font_copy_list
