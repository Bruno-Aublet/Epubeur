import zipfile

from model.error_messages import (
    describe_epub_generation_error,
    describe_epub_open_error,
    describe_odt_open_error,
    describe_project_load_error,
    describe_project_save_error,
)


def test_describe_odt_open_error_bad_zip():
    msg = describe_odt_open_error(zipfile.BadZipFile("bad zip"), "roman.odt")
    assert "roman.odt" in msg
    assert "corrompu" in msg or "n'est pas" in msg


def test_describe_odt_open_error_key_error():
    msg = describe_odt_open_error(KeyError("content.xml"), "roman.odt")
    assert "roman.odt" in msg
    assert "structure attendue" in msg


def test_describe_odt_open_error_permission():
    msg = describe_odt_open_error(PermissionError("denied"), "roman.odt")
    assert "roman.odt" in msg
    assert "refusé" in msg


def test_describe_odt_open_error_generic_fallback_includes_original_message():
    msg = describe_odt_open_error(ValueError("something weird"), "roman.odt")
    assert "roman.odt" in msg
    assert "something weird" in msg


def test_describe_epub_open_error_bad_zip():
    msg = describe_epub_open_error(zipfile.BadZipFile("bad zip"), "livre.epub")
    assert "livre.epub" in msg
    assert "corrompu" in msg


def test_describe_project_load_error_file_not_found():
    msg = describe_project_load_error(FileNotFoundError("missing"), "MonProjet.epubeur")
    assert "MonProjet.epubeur" in msg


def test_describe_project_save_error_permission():
    msg = describe_project_save_error(PermissionError("denied"))
    assert "refusé" in msg


def test_describe_project_save_error_disk_full():
    exc = OSError("no space")
    exc.errno = 28
    msg = describe_project_save_error(exc)
    assert "disque" in msg.lower()


def test_describe_epub_generation_error_permission():
    msg = describe_epub_generation_error(PermissionError("denied"))
    assert "refusé" in msg


def test_describe_epub_generation_error_disk_full():
    exc = OSError("no space")
    exc.errno = 28
    msg = describe_epub_generation_error(exc)
    assert "disque" in msg.lower()
