from dataclasses import dataclass, field
from pathlib import Path

from model.book_metadata import BookMetadata
from model.document import Document, new_id


@dataclass
class SourceOdtFile:
    id: str
    path: Path
    import_order: int
    chapter_ids: list[str] = field(default_factory=list)

    @staticmethod
    def create(path: Path, import_order: int) -> "SourceOdtFile":
        return SourceOdtFile(id=new_id(), path=Path(path), import_order=import_order)


@dataclass
class ProjectMeta:
    epbz_path: Path | None = None  # chemin du fichier .epbz cible pour un simple "Enregistrer" ;
                                     # None pour un projet jamais encore sauvegardé. Le dossier de
                                     # travail temporaire où vit AssetStore pendant l'édition (ex.
                                     # extraction d'un .epbz) est un détail interne du controller
                                     # (ProjectController._temp_assets_dir), jamais stocké ici.
    source_odt_files: list[SourceOdtFile] = field(default_factory=list)
    document: Document = field(default_factory=Document)
    book_metadata: BookMetadata = field(default_factory=BookMetadata)

    def next_import_order(self) -> int:
        if not self.source_odt_files:
            return 0
        return max(f.import_order for f in self.source_odt_files) + 1
