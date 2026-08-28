import zipfile
from pathlib import Path

from epub.font_obfuscation import (
    OBFUSCATION_LENGTH,
    build_encryption_xml,
    deobfuscate_extracted_epub,
    deobfuscate_font,
    obfuscate_font,
    parse_encryption_xml,
    postprocess_epub_zip,
)


def test_obfuscation_is_involutive():
    font_bytes = bytes(range(256)) * 10  # 2560 octets > OBFUSCATION_LENGTH
    book_uid = "urn:uuid:12345678-1234-1234-1234-123456789012"

    obfuscated = obfuscate_font(font_bytes, book_uid)
    assert obfuscated != font_bytes
    assert len(obfuscated) == len(font_bytes)

    restored = deobfuscate_font(obfuscated, book_uid)
    assert restored == font_bytes


def test_only_first_1040_bytes_touched():
    font_bytes = bytes(range(256)) * 10
    book_uid = "urn:uuid:abc"

    obfuscated = obfuscate_font(font_bytes, book_uid)
    assert obfuscated[OBFUSCATION_LENGTH:] == font_bytes[OBFUSCATION_LENGTH:]
    assert obfuscated[:OBFUSCATION_LENGTH] != font_bytes[:OBFUSCATION_LENGTH]


def test_different_book_uid_gives_different_obfuscation():
    font_bytes = bytes(range(256)) * 10
    a = obfuscate_font(font_bytes, "urn:uuid:aaaa")
    b = obfuscate_font(font_bytes, "urn:uuid:bbbb")
    assert a != b


def test_build_encryption_xml_contains_idpf_algorithm_and_href():
    xml = build_encryption_xml(["fonts/narrative.ttf"])
    assert "http://www.idpf.org/2008/embedding" in xml
    assert "fonts/narrative.ttf" in xml


def test_postprocess_epub_zip_injects_encryption_and_obfuscates(tmp_path):
    epub_path = tmp_path / "book.epub"
    font_bytes = bytes(range(256)) * 10
    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("fonts/narrative.ttf", font_bytes)
        zf.writestr("content.opf", "<package/>")

    book_uid = "urn:uuid:test-uid"
    postprocess_epub_zip(epub_path, [(font_bytes, "fonts/narrative.ttf")], book_uid)

    with zipfile.ZipFile(epub_path, "r") as zf:
        names = zf.namelist()
        assert "META-INF/encryption.xml" in names
        stored_font = zf.read("fonts/narrative.ttf")
        assert stored_font != font_bytes
        assert deobfuscate_font(stored_font, book_uid) == font_bytes
        assert zf.read("content.opf") == b"<package/>"


def test_postprocess_epub_zip_handles_two_simultaneous_fonts(tmp_path):
    epub_path = tmp_path / "book.epub"
    font_a = bytes(range(256)) * 10
    font_b = bytes(range(255, -1, -1)) * 10
    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("fonts/narrative.ttf", font_a)
        zf.writestr("fonts/other.ttf", font_b)
        zf.writestr("content.opf", "<package/>")

    book_uid = "urn:uuid:test-uid-multi"
    postprocess_epub_zip(
        epub_path,
        [(font_a, "fonts/narrative.ttf"), (font_b, "fonts/other.ttf")],
        book_uid,
    )

    with zipfile.ZipFile(epub_path, "r") as zf:
        enc = zf.read("META-INF/encryption.xml").decode()
        assert "fonts/narrative.ttf" in enc
        assert "fonts/other.ttf" in enc

        stored_a = zf.read("fonts/narrative.ttf")
        stored_b = zf.read("fonts/other.ttf")
        assert deobfuscate_font(stored_a, book_uid) == font_a
        assert deobfuscate_font(stored_b, book_uid) == font_b
        assert stored_a != stored_b


def test_parse_encryption_xml_extracts_hrefs():
    xml = build_encryption_xml(["EPUB/fonts/narrative.ttf", "EPUB/fonts/other.ttf"])
    hrefs = parse_encryption_xml(xml)
    assert hrefs == ["EPUB/fonts/narrative.ttf", "EPUB/fonts/other.ttf"]


def test_deobfuscate_extracted_epub_restores_font_on_disk(tmp_path):
    font_bytes = bytes(range(256)) * 10
    book_uid = "urn:uuid:preview-test"
    obfuscated = obfuscate_font(font_bytes, book_uid)

    extract_dir = tmp_path / "extracted"
    font_path = extract_dir / "EPUB" / "fonts" / "narrative.ttf"
    font_path.parent.mkdir(parents=True)
    font_path.write_bytes(obfuscated)

    meta_inf = extract_dir / "META-INF"
    meta_inf.mkdir()
    (meta_inf / "encryption.xml").write_text(build_encryption_xml(["EPUB/fonts/narrative.ttf"]), encoding="utf-8")

    deobfuscate_extracted_epub(extract_dir, book_uid)

    assert font_path.read_bytes() == font_bytes


def test_deobfuscate_extracted_epub_noop_without_encryption_xml(tmp_path):
    extract_dir = tmp_path / "extracted_plain"
    extract_dir.mkdir()
    # Ne doit pas lever d'exception si le livre n'a pas de police figée (pas d'encryption.xml)
    deobfuscate_extracted_epub(extract_dir, "urn:uuid:whatever")
