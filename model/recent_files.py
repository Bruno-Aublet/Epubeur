import json
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QStandardPaths

MAX_ENTRIES = 10


def _recent_files_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return Path(base) / "recent_files.json"


def _load() -> dict:
    try:
        data = json.loads(_recent_files_path().read_text(encoding="utf-8"))
        data.setdefault("recent_projects", [])
        data.setdefault("recent_files", [])
        data.setdefault("last_project_dir", None)
        return data
    except Exception:
        return {"recent_projects": [], "recent_files": [], "last_project_dir": None}


def _save(data: dict) -> None:
    try:
        path = _recent_files_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)
    except Exception:
        pass  # jamais bloquant — au pire, la liste ne persiste pas cette fois-ci


def _upsert(entries: list[dict], path: Path, extra: dict) -> list[dict]:
    key = str(path)
    entries = [e for e in entries if e["path"] != key]
    entries.insert(0, {"path": key, "timestamp": datetime.now().isoformat(), **extra})
    return entries[:MAX_ENTRIES]


def add_recent_project(path: Path) -> None:
    data = _load()
    data["recent_projects"] = _upsert(data["recent_projects"], path, {})
    _save(data)


def add_recent_file(path: Path, kind: str) -> None:
    """kind : "imported" (import initial, remplacement, ajout volontaire, réimport EPUB) ou
    "generated" (EPUB produit par le bouton Générer)."""
    data = _load()
    data["recent_files"] = _upsert(data["recent_files"], path, {"kind": kind})
    _save(data)


def list_recent_projects() -> list[dict]:
    return _load()["recent_projects"]


def list_recent_files() -> list[dict]:
    return _load()["recent_files"]


def remove_recent_project(path: Path) -> None:
    data = _load()
    data["recent_projects"] = [e for e in data["recent_projects"] if e["path"] != str(path)]
    _save(data)


def remove_recent_file(path: Path) -> None:
    data = _load()
    data["recent_files"] = [e for e in data["recent_files"] if e["path"] != str(path)]
    _save(data)


def get_last_project_dir() -> Path | None:
    """Dernier dossier utilisé pour Enregistrer/Ouvrir un projet .epbz — None si jamais
    enregistré ou si le dossier n'existe plus (fichier déplacé/disque externe débranché)."""
    raw = _load()["last_project_dir"]
    if raw is None:
        return None
    path = Path(raw)
    return path if path.is_dir() else None


def set_last_project_dir(directory: Path) -> None:
    data = _load()
    data["last_project_dir"] = str(directory)
    _save(data)


def prune_missing() -> None:
    """Retire silencieusement toute entrée dont le fichier n'existe plus — appelé une fois au
    démarrage de l'appli (ui/main_window.py), avant la construction des menus."""
    data = _load()
    data["recent_projects"] = [e for e in data["recent_projects"] if Path(e["path"]).exists()]
    data["recent_files"] = [e for e in data["recent_files"] if Path(e["path"]).exists()]
    _save(data)


def format_recent_timestamp(iso_str: str) -> str:
    dt = datetime.fromisoformat(iso_str)
    now = datetime.now()
    time_part = dt.strftime("%Hh%M")
    if dt.date() == now.date():
        return f"aujourd'hui à {time_part}"
    if dt.date() == (now - timedelta(days=1)).date():
        return f"hier à {time_part}"
    return f"le {dt.strftime('%d/%m/%Y')} à {time_part}"
