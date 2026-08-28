import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path


class AssetRole(Enum):
    CHAPTER_POV = "chapter_pov"
    COVER = "cover"
    BACK_COVER = "back_cover"
    OTHER = "other"


@dataclass
class ImageAsset:
    id: str
    original_filename: str
    extension: str
    role: AssetRole

    def to_dict(self) -> dict:
        d = asdict(self)
        d["role"] = self.role.value
        return d

    @staticmethod
    def from_dict(d: dict) -> "ImageAsset":
        return ImageAsset(
            id=d["id"],
            original_filename=d["original_filename"],
            extension=d["extension"],
            role=AssetRole(d["role"]),
        )


SUPPORTED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg"}


class AssetStore:
    """Répertoire d'assets du projet : <root>/images/<sha256>.<ext>, dédup par hash de contenu."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.images_dir = self.root / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self._assets: dict[str, ImageAsset] = {}
        # Formats hors PNG/JPEG rencontrés lors des ingestions récentes (nom de fichier
        # d'origine, pas asset_id) — seul PNG/JPEG est testé/garanti pour la génération EPUB ;
        # collecté ici plutôt que de lever une exception, pour ne jamais bloquer l'import (une
        # image dans un format non testé reste ingérée telle quelle, l'utilisateur est juste
        # prévenu). Consulté puis vidé par l'appelant (voir controller.py) après chaque import.
        self.unsupported_format_warnings: list[str] = []
        self._load_index()

    @property
    def _index_path(self) -> Path:
        return self.root / "images_index.json"

    def _load_index(self) -> None:
        if self._index_path.exists():
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
            for entry in data:
                asset = ImageAsset.from_dict(entry)
                self._assets[asset.id] = asset

    def _save_index(self) -> None:
        data = [asset.to_dict() for asset in self._assets.values()]
        self._index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def ingest_bytes(self, data: bytes, original_filename: str, role: AssetRole) -> ImageAsset:
        digest = hashlib.sha256(data).hexdigest()
        if digest in self._assets:
            return self._assets[digest]

        ext = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else "png"
        if ext not in SUPPORTED_IMAGE_EXTENSIONS:
            self.unsupported_format_warnings.append(original_filename)
        target = self.images_dir / f"{digest}.{ext}"
        if not target.exists():
            target.write_bytes(data)

        asset = ImageAsset(id=digest, original_filename=original_filename, extension=ext, role=role)
        self._assets[digest] = asset
        self._save_index()
        return asset

    def path_for(self, asset_id: str) -> Path:
        asset = self._assets[asset_id]
        return self.images_dir / f"{asset.id}.{asset.extension}"

    def get(self, asset_id: str) -> ImageAsset | None:
        return self._assets.get(asset_id)

    def all_assets(self) -> list[ImageAsset]:
        return list(self._assets.values())

    def remove(self, asset_id: str) -> None:
        """Supprime définitivement l'asset : entrée d'index ET fichier physique. No-op si
        asset_id déjà inconnu. L'ordre importe : le chemin doit être résolu AVANT de retirer
        l'entrée de self._assets (path_for() en dépend)."""
        if asset_id not in self._assets:
            return
        file_path = self.path_for(asset_id)
        del self._assets[asset_id]
        self._save_index()
        file_path.unlink(missing_ok=True)

    def rename(self, asset_id: str, new_stem: str) -> None:
        """Change le nom AFFICHÉ (ImageAsset.original_filename) d'un asset — n'affecte JAMAIS le
        fichier physique sur disque (toujours nommé par son hash, cf. path_for) ni l'asset_id
        lui-même. new_stem est le nom SANS extension : l'extension réelle de l'asset (déterminée
        à l'ingestion depuis le nom d'origine, cf. ingest_bytes) est toujours conservée, jamais
        modifiable par ce renommage. No-op si asset_id inconnu ou new_stem vide après strip."""
        new_stem = new_stem.strip()
        if asset_id not in self._assets or not new_stem:
            return
        asset = self._assets[asset_id]
        asset.original_filename = f"{new_stem}.{asset.extension}"
        self._save_index()
