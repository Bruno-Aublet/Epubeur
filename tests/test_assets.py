import json

from model.assets import AssetRole, AssetStore


def test_ingest_same_bytes_deduplicates(tmp_path):
    store = AssetStore(tmp_path / "assets")
    data = b"fake-image-bytes-12345"

    asset1 = store.ingest_bytes(data, "perso1.png", AssetRole.CHAPTER_POV)
    asset2 = store.ingest_bytes(data, "perso1_copy.png", AssetRole.CHAPTER_POV)

    assert asset1.id == asset2.id
    assert len(store.all_assets()) == 1
    assert len(list((tmp_path / "assets" / "images").iterdir())) == 1


def test_ingest_different_bytes_creates_separate_assets(tmp_path):
    store = AssetStore(tmp_path / "assets")
    asset1 = store.ingest_bytes(b"aaa", "a.png", AssetRole.CHAPTER_POV)
    asset2 = store.ingest_bytes(b"bbb", "b.png", AssetRole.CHAPTER_POV)

    assert asset1.id != asset2.id
    assert len(store.all_assets()) == 2


def test_index_persists_across_reload(tmp_path):
    root = tmp_path / "assets"
    store1 = AssetStore(root)
    asset = store1.ingest_bytes(b"persisted", "x.png", AssetRole.COVER)

    store2 = AssetStore(root)
    reloaded = store2.get(asset.id)
    assert reloaded is not None
    assert reloaded.original_filename == "x.png"


def test_ingest_png_or_jpeg_does_not_warn(tmp_path):
    store = AssetStore(tmp_path / "assets")
    store.ingest_bytes(b"a", "image.png", AssetRole.CHAPTER_POV)
    store.ingest_bytes(b"b", "image.jpg", AssetRole.CHAPTER_POV)
    store.ingest_bytes(b"c", "image.JPEG", AssetRole.CHAPTER_POV)

    assert store.unsupported_format_warnings == []


def test_ingest_unsupported_format_records_warning(tmp_path):
    store = AssetStore(tmp_path / "assets")
    store.ingest_bytes(b"a", "image.gif", AssetRole.CHAPTER_POV)

    assert store.unsupported_format_warnings == ["image.gif"]


def test_ingest_unsupported_format_still_ingests_the_asset(tmp_path):
    store = AssetStore(tmp_path / "assets")
    asset = store.ingest_bytes(b"a", "image.bmp", AssetRole.CHAPTER_POV)

    assert asset.extension == "bmp"
    assert store.path_for(asset.id).exists()


def test_remove_deletes_index_entry_and_file(tmp_path):
    store = AssetStore(tmp_path / "assets")
    asset = store.ingest_bytes(b"a", "image.png", AssetRole.CHAPTER_POV)
    file_path = store.path_for(asset.id)
    assert file_path.exists()

    store.remove(asset.id)

    assert store.get(asset.id) is None
    assert not file_path.exists()


def test_remove_persists_across_reload(tmp_path):
    root = tmp_path / "assets"
    store1 = AssetStore(root)
    asset = store1.ingest_bytes(b"a", "image.png", AssetRole.CHAPTER_POV)
    store1.remove(asset.id)

    store2 = AssetStore(root)
    assert store2.get(asset.id) is None


def test_remove_unknown_asset_id_is_noop(tmp_path):
    store = AssetStore(tmp_path / "assets")
    store.remove("does-not-exist")  # ne lève pas


def test_rename_changes_original_filename_keeps_extension(tmp_path):
    store = AssetStore(tmp_path / "assets")
    asset = store.ingest_bytes(b"a", "old_name.png", AssetRole.CHAPTER_POV)

    store.rename(asset.id, "Nouveau Nom")

    assert store.get(asset.id).original_filename == "Nouveau Nom.png"


def test_rename_renames_physical_file(tmp_path):
    store = AssetStore(tmp_path / "assets")
    asset = store.ingest_bytes(b"a", "old_name.png", AssetRole.CHAPTER_POV)
    path_before = store.path_for(asset.id)

    store.rename(asset.id, "Nouveau Nom")

    path_after = store.path_for(asset.id)
    assert path_after != path_before
    assert path_after.name == "Nouveau Nom.png"
    assert path_after.exists()
    assert not path_before.exists()


def test_rename_persists_physical_file_across_reload(tmp_path):
    root = tmp_path / "assets"
    store1 = AssetStore(root)
    asset = store1.ingest_bytes(b"a", "old_name.png", AssetRole.CHAPTER_POV)
    store1.rename(asset.id, "Nouveau Nom")

    store2 = AssetStore(root)
    path = store2.path_for(asset.id)
    assert path.name == "Nouveau Nom.png"
    assert path.exists()


def test_rename_to_colliding_name_gets_suffix(tmp_path):
    store = AssetStore(tmp_path / "assets")
    asset1 = store.ingest_bytes(b"a", "one.png", AssetRole.CHAPTER_POV)
    asset2 = store.ingest_bytes(b"b", "two.png", AssetRole.CHAPTER_POV)

    store.rename(asset2.id, "one")

    path1 = store.path_for(asset1.id)
    path2 = store.path_for(asset2.id)
    assert path1.name == "one.png"
    assert path2.name == "one-2.png"
    assert path1.exists()
    assert path2.exists()


def test_rename_sanitizes_filesystem_forbidden_characters(tmp_path):
    store = AssetStore(tmp_path / "assets")
    asset = store.ingest_bytes(b"a", "old_name.png", AssetRole.CHAPTER_POV)

    store.rename(asset.id, "a/b:c")

    path = store.path_for(asset.id)
    assert path.exists()
    assert "/" not in path.name and ":" not in path.name


def test_rename_empty_stem_is_noop(tmp_path):
    store = AssetStore(tmp_path / "assets")
    asset = store.ingest_bytes(b"a", "old_name.png", AssetRole.CHAPTER_POV)

    store.rename(asset.id, "   ")

    assert store.get(asset.id).original_filename == "old_name.png"


def test_rename_unknown_asset_id_is_noop(tmp_path):
    store = AssetStore(tmp_path / "assets")
    store.rename("does-not-exist", "Nouveau Nom")  # ne lève pas


def test_rename_persists_across_reload(tmp_path):
    root = tmp_path / "assets"
    store1 = AssetStore(root)
    asset = store1.ingest_bytes(b"a", "old_name.png", AssetRole.CHAPTER_POV)
    store1.rename(asset.id, "Nouveau Nom")

    store2 = AssetStore(root)
    assert store2.get(asset.id).original_filename == "Nouveau Nom.png"


def test_load_migrates_legacy_hash_named_file_to_readable_name(tmp_path):
    """Projet créé avant que rename() ne touche au fichier physique : le fichier était resté
    nommé "<hash>.<ext>" alors que original_filename portait déjà le nom renommé dans l'index
    JSON. À l'ouverture, le fichier doit être aligné sur le nom lisible attendu."""
    root = tmp_path / "assets"
    images_dir = root / "images"
    images_dir.mkdir(parents=True)
    asset_id = "a" * 64
    (images_dir / f"{asset_id}.png").write_bytes(b"a")
    (root / "images_index.json").write_text(
        json.dumps([{
            "id": asset_id,
            "original_filename": "Nouveau Nom.png",
            "extension": "png",
            "role": "chapter_pov",
        }]),
        encoding="utf-8",
    )

    store = AssetStore(root)

    path = store.path_for(asset_id)
    assert path.name == "Nouveau Nom.png"
    assert path.exists()
    assert not (images_dir / f"{asset_id}.png").exists()
    assert store.migrated_on_load is True


def test_load_does_not_confuse_two_unmigrated_assets_of_same_extension(tmp_path):
    """Deux assets renommés avant migration, même extension : chaque fichier legacy
    "<hash>.<ext>" doit rejoindre SON propre asset (identifié par nom exact), jamais celui de
    l'autre simplement parce qu'ils partagent l'extension."""
    root = tmp_path / "assets"
    images_dir = root / "images"
    images_dir.mkdir(parents=True)
    id1, id2 = "a" * 64, "b" * 64
    (images_dir / f"{id1}.png").write_bytes(b"a")
    (images_dir / f"{id2}.png").write_bytes(b"b")
    (root / "images_index.json").write_text(
        json.dumps([
            {"id": id1, "original_filename": "Premier.png", "extension": "png", "role": "chapter_pov"},
            {"id": id2, "original_filename": "Second.png", "extension": "png", "role": "chapter_pov"},
        ]),
        encoding="utf-8",
    )

    store = AssetStore(root)

    assert store.path_for(id1).name == "Premier.png"
    assert store.path_for(id2).name == "Second.png"
    assert store.path_for(id1).read_bytes() == b"a"
    assert store.path_for(id2).read_bytes() == b"b"
