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


def test_rename_does_not_touch_physical_file_path(tmp_path):
    store = AssetStore(tmp_path / "assets")
    asset = store.ingest_bytes(b"a", "old_name.png", AssetRole.CHAPTER_POV)
    path_before = store.path_for(asset.id)

    store.rename(asset.id, "Nouveau Nom")

    assert store.path_for(asset.id) == path_before
    assert path_before.exists()


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
