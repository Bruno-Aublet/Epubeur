import json
import tempfile
import zipfile
from pathlib import Path

from model.project import ProjectMeta, SourceOdtFile
from model.serialization import _build_project_dict, book_metadata_from_dict, document_from_dict


def save_project_epbz(project: ProjectMeta, asset_store, epbz_path: Path) -> None:
    """Écrit le projet complet (métadonnées + structure + images + polices figées) dans un
    fichier .epbz — zip standard, sans structure spéciale. Réécriture atomique (écrit dans un
    .tmp puis remplace) : un échec en cours d'écriture ne corrompt jamais un .epbz déjà existant
    à ce chemin."""
    epbz_path = Path(epbz_path)
    tmp_path = epbz_path.with_suffix(epbz_path.suffix + ".tmp")
    data, font_copy_list = _build_project_dict(project)
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.epubeur.json", json.dumps(data, ensure_ascii=False, indent=2))
        for f in asset_store.root.rglob("*"):
            if f.is_file():
                zf.write(f, arcname=str(Path("assets") / f.relative_to(asset_store.root)))
        for sha256, source_path in font_copy_list:
            zf.write(source_path, arcname=f"fonts/{sha256}{source_path.suffix}")
    tmp_path.replace(epbz_path)


def load_project_epbz(epbz_path: Path) -> tuple[ProjectMeta, Path, list[str]]:
    """Charge un .epbz : extrait le zip dans un nouveau dossier de travail temporaire, puis
    reconstruit le projet depuis project.epubeur.json exactement comme l'ancien load_project
    (format dossier, désormais retiré) le faisait. Retourne (project, extract_dir, warnings) —
    extract_dir est le nouveau dossier où vit assets/ (et fonts/), à la charge de l'appelant
    (controller) de le retenir comme _temp_assets_dir tant que ce projet est ouvert."""
    epbz_path = Path(epbz_path)
    extract_dir = Path(tempfile.mkdtemp(prefix="epubeur_epbz_"))
    with zipfile.ZipFile(epbz_path) as zf:
        zf.extractall(extract_dir)

    data = json.loads((extract_dir / "project.epubeur.json").read_text(encoding="utf-8"))

    warnings: list[str] = []
    source_files = []
    for f in data["source_odt_files"]:
        path = Path(f["path"])
        if not path.exists():
            warnings.append(f"Fichier ODT source introuvable (traçabilité seulement) : {path}")
        source_files.append(SourceOdtFile(id=f["id"], path=path, import_order=f["import_order"],
                                           chapter_ids=f["chapter_ids"]))

    document = document_from_dict(data["document"])

    # Polices figées : file_path relatif ("fonts/<sha>.<ext>") produit par save_project_epbz,
    # résolu contre extract_dir. Un chemin déjà absolu (ne devrait plus jamais être écrit par
    # cette fonction, mais reste possible si le JSON a été édité à la main) est laissé tel quel.
    for lf in document.locked_fonts:
        for f in lf.files:
            if f.file_path and not Path(f.file_path).is_absolute():
                f.file_path = str(extract_dir / f.file_path)
            if f.file_path and not Path(f.file_path).exists():
                warnings.append(f"Fichier de police figée introuvable pour « {lf.family} » : {f.file_path}")

    book_metadata = book_metadata_from_dict(data.get("book_metadata", {}))

    project = ProjectMeta(epbz_path=epbz_path, source_odt_files=source_files, document=document,
                           book_metadata=book_metadata)
    return project, extract_dir, warnings
