import hashlib
import json
import re
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
    """Répertoire d'assets du projet : <root>/images/<nom-lisible>.<ext>, dédup par hash de
    contenu (asset_id = sha256, clé d'index uniquement — n'apparaît plus dans le nom de fichier
    physique, cf. path_for)."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.images_dir = self.root / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self._assets: dict[str, ImageAsset] = {}
        # Nom de fichier physique courant par asset_id (juste le nom, pas le chemin complet).
        # Tenu à jour explicitement à chaque écriture disque (ingest/rename/remove) plutôt que
        # recalculé depuis original_filename à la volée : un nom demandé peut être en collision
        # avec un AUTRE asset et recevoir un suffixe (cf. _reserve_physical_path), donc le nom
        # réellement sur disque n'est pas toujours déductible de l'index seul.
        self._physical_names: dict[str, str] = {}
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
        # Le nom de fichier physique n'est pas stocké dans l'index JSON (dérivé de
        # original_filename à l'écriture) : reconstruit ici en associant chaque asset au fichier
        # qui porte son nom attendu, avec repli sur un scan si un rename() précédent a fini en
        # collision et pris un suffixe (cf. _reserve_physical_path).
        remaining = {f.name for f in self.images_dir.iterdir() if f.is_file()} if self.images_dir.exists() else set()
        unmatched: list[ImageAsset] = []
        for asset in self._assets.values():
            expected = f"{self._safe_stem(asset)}.{asset.extension}"
            if expected in remaining:
                self._physical_names[asset.id] = expected
                remaining.discard(expected)
            else:
                unmatched.append(asset)
        self.migrated_on_load = False
        for asset in unmatched:
            # Migration : projets créés/modifiés avant que rename() ne renomme le fichier
            # physique (celui-ci était alors resté nommé "<hash>.<ext>" indéfiniment malgré un
            # original_filename déjà changé, cf. historique). L'ancien nom de fichier est
            # exactement "<asset.id>.<ext>" (asset.id = sha256 du contenu, format d'avant cette
            # migration) : identifié par nom exact, jamais par simple extension partagée — deux
            # assets renommés de même extension ne doivent pas se faire échanger leur fichier.
            candidate = f"{asset.id}.{asset.extension}"
            if candidate in remaining:
                remaining.discard(candidate)
                migrated_path = self._reserve_physical_path(asset)
                old_path = self.images_dir / candidate
                if old_path != migrated_path:
                    old_path.replace(migrated_path)
                    self.migrated_on_load = True
                self._physical_names[asset.id] = migrated_path.name

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

        asset = ImageAsset(id=digest, original_filename=original_filename, extension=ext, role=role)
        target = self._reserve_physical_path(asset)
        target.write_bytes(data)
        self._physical_names[digest] = target.name

        self._assets[digest] = asset
        self._save_index()
        return asset

    def _safe_stem(self, asset: ImageAsset) -> str:
        """Nom de fichier lisible dérivé de original_filename, débarrassé de tout caractère
        interdit sur le système de fichiers — retombe sur asset_id si le nom nettoyé est vide
        (ex : original_filename composé uniquement de caractères interdits)."""
        stem = Path(asset.original_filename).stem
        stem = re.sub(r'[<>:"/\\|?*]', "_", stem).strip().strip(".")
        return stem or asset.id

    def _reserve_physical_path(self, asset: ImageAsset) -> Path:
        """Calcule le chemin physique disponible pour le nom actuel de cet asset : son propre
        fichier existant ne compte jamais comme collision (un rename() sans changement réel de
        nom, ou qui garde le même stem, doit retomber sur son propre fichier plutôt que de lui
        ajouter un suffixe)."""
        base_stem = self._safe_stem(asset)
        own_name = self._physical_names.get(asset.id)
        candidate = self.images_dir / f"{base_stem}.{asset.extension}"
        suffix = 2
        while candidate.exists() and candidate.name != own_name:
            candidate = self.images_dir / f"{base_stem}-{suffix}.{asset.extension}"
            suffix += 1
        return candidate

    def path_for(self, asset_id: str) -> Path:
        asset = self._assets[asset_id]
        name = self._physical_names.get(asset_id)
        if name:
            return self.images_dir / name
        return self.images_dir / f"{self._safe_stem(asset)}.{asset.extension}"

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
        self._physical_names.pop(asset_id, None)
        self._save_index()
        file_path.unlink(missing_ok=True)

    def rename(self, asset_id: str, new_stem: str) -> None:
        """Change le nom AFFICHÉ (ImageAsset.original_filename) d'un asset ET renomme le fichier
        physique sur disque en conséquence (le but du renommage est de renommer l'image partout,
        y compris dans le .epbz — l'asset_id/hash reste la seule clé d'identification interne,
        cf. AssetStore docstring). new_stem est le nom SANS extension : l'extension réelle de
        l'asset (déterminée à l'ingestion depuis le nom d'origine, cf. ingest_bytes) est toujours
        conservée, jamais modifiable par ce renommage. No-op si asset_id inconnu ou new_stem vide
        après strip."""
        new_stem = new_stem.strip()
        if asset_id not in self._assets or not new_stem:
            return
        asset = self._assets[asset_id]
        old_path = self.path_for(asset_id)
        asset.original_filename = f"{new_stem}.{asset.extension}"
        new_path = self._reserve_physical_path(asset)
        if old_path.exists() and old_path != new_path:
            old_path.replace(new_path)
        self._physical_names[asset_id] = new_path.name
        self._save_index()
