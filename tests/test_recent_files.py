from pathlib import Path

import model.recent_files as recent_files_module
from model.recent_files import (
    add_recent_file,
    add_recent_project,
    format_recent_timestamp,
    list_recent_files,
    list_recent_projects,
    prune_missing,
    remove_recent_file,
    remove_recent_project,
)

# Note : la fixture autouse isolate_recent_files (tests/conftest.py) redirige déjà
# _recent_files_path() vers un dossier temporaire par test — pas besoin de le refaire ici, mais
# certains tests ci-dessous veulent un chemin connu/contrôlé, donc redirigent explicitement.


def _use_path(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "recent_files.json"
    monkeypatch.setattr(recent_files_module, "_recent_files_path", lambda: path)
    return path


def test_add_recent_project_then_list_returns_it(tmp_path, monkeypatch):
    _use_path(tmp_path, monkeypatch)
    project_path = tmp_path / "MonRoman.epbz"

    add_recent_project(project_path)

    entries = list_recent_projects()
    assert len(entries) == 1
    assert entries[0]["path"] == str(project_path)


def test_reaccessing_existing_path_moves_to_top_without_duplicate(tmp_path, monkeypatch):
    _use_path(tmp_path, monkeypatch)
    a = tmp_path / "A.epbz"
    b = tmp_path / "B.epbz"

    add_recent_project(a)
    add_recent_project(b)
    add_recent_project(a)  # ré-accès à A : doit remonter en tête, pas de doublon

    entries = list_recent_projects()
    assert len(entries) == 2
    assert entries[0]["path"] == str(a)
    assert entries[1]["path"] == str(b)


def test_cap_at_ten_evicts_oldest(tmp_path, monkeypatch):
    _use_path(tmp_path, monkeypatch)
    for i in range(11):
        add_recent_project(tmp_path / f"Projet{i}.epbz")

    entries = list_recent_projects()
    assert len(entries) == 10
    # Projet0 (le plus ancien) doit avoir été évincé ; Projet10 (le plus récent) en tête.
    assert all(e["path"] != str(tmp_path / "Projet0.epbz") for e in entries)
    assert entries[0]["path"] == str(tmp_path / "Projet10.epbz")


def test_atomic_write_failure_leaves_existing_file_intact(tmp_path, monkeypatch):
    path = _use_path(tmp_path, monkeypatch)
    add_recent_project(tmp_path / "Premier.epbz")
    original_content = path.read_text(encoding="utf-8")

    monkeypatch.setattr(Path, "replace", lambda self, target: (_ for _ in ()).throw(OSError("échec simulé")))
    add_recent_project(tmp_path / "Second.epbz")  # ne doit pas lever, juste échouer silencieusement

    assert path.read_text(encoding="utf-8") == original_content


def test_prune_missing_removes_only_deleted_paths(tmp_path, monkeypatch):
    _use_path(tmp_path, monkeypatch)
    existing = tmp_path / "existe.epbz"
    existing.write_bytes(b"fake zip")
    missing = tmp_path / "disparu.epbz"

    add_recent_project(missing)
    add_recent_project(existing)

    prune_missing()

    entries = list_recent_projects()
    assert len(entries) == 1
    assert entries[0]["path"] == str(existing)


def test_prune_missing_applies_to_both_lists(tmp_path, monkeypatch):
    _use_path(tmp_path, monkeypatch)
    existing_file = tmp_path / "chapitre.odt"
    existing_file.write_bytes(b"fake odt")
    missing_file = tmp_path / "disparu.odt"

    add_recent_file(missing_file, "imported")
    add_recent_file(existing_file, "imported")

    prune_missing()

    entries = list_recent_files()
    assert len(entries) == 1
    assert entries[0]["path"] == str(existing_file)


def test_corrupt_json_falls_back_to_empty_lists(tmp_path, monkeypatch):
    path = _use_path(tmp_path, monkeypatch)
    path.write_text("ceci n'est pas du JSON valide {{{", encoding="utf-8")

    assert list_recent_projects() == []
    assert list_recent_files() == []


def test_missing_file_falls_back_to_empty_lists(tmp_path, monkeypatch):
    _use_path(tmp_path, monkeypatch)  # fichier jamais créé
    assert list_recent_projects() == []
    assert list_recent_files() == []


def test_remove_recent_project(tmp_path, monkeypatch):
    _use_path(tmp_path, monkeypatch)
    project_path = tmp_path / "MonRoman.epbz"
    add_recent_project(project_path)

    remove_recent_project(project_path)

    assert list_recent_projects() == []


def test_remove_recent_file(tmp_path, monkeypatch):
    _use_path(tmp_path, monkeypatch)
    file_path = tmp_path / "Chapitre.odt"
    add_recent_file(file_path, "imported")

    remove_recent_file(file_path)

    assert list_recent_files() == []


def test_add_recent_file_stores_kind(tmp_path, monkeypatch):
    _use_path(tmp_path, monkeypatch)
    add_recent_file(tmp_path / "MonRoman.epub", "generated")

    entries = list_recent_files()
    assert entries[0]["kind"] == "generated"


def test_format_recent_timestamp_today():
    from datetime import datetime
    iso = datetime.now().replace(hour=14, minute=32).isoformat()
    assert format_recent_timestamp(iso) == "aujourd'hui à 14h32"


def test_format_recent_timestamp_yesterday():
    from datetime import datetime, timedelta
    yesterday = (datetime.now() - timedelta(days=1)).replace(hour=9, minute=5)
    assert format_recent_timestamp(yesterday.isoformat()) == "hier à 09h05"


def test_format_recent_timestamp_older_date():
    from datetime import datetime, timedelta
    older = (datetime.now() - timedelta(days=10)).replace(hour=18, minute=0)
    result = format_recent_timestamp(older.isoformat())
    assert result.startswith("le ")
    assert "à 18h00" in result
