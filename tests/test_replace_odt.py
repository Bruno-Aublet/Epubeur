import zipfile
from pathlib import Path

from controller import ProjectController
from model.document import ImageDisplaySize, ImageWrap, LockedFont, LockedFontFile, Part

MANIFEST_XML = ('<?xml version="1.0"?>'
                 '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>')

NS_ATTRS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink"'
)

STYLES_XML = """<?xml version="1.0"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0">
  <office:styles>
    <style:style style:name="Heading_20_1" style:display-name="Heading 1" style:family="paragraph"/>
  </office:styles>
</office:document-styles>
"""

TWO_CHAPTERS_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un (brut)</text:h>
      <text:p>Texte du premier chapitre, version originale.</text:p>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Deux (brut)</text:h>
      <text:p>Texte du second chapitre, version originale.</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

TWO_CHAPTERS_CORRECTED_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un (corrigé)</text:h>
      <text:p>Texte du premier chapitre, CORRIGÉ.</text:p>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Deux (corrigé)</text:h>
      <text:p>Texte du second chapitre, CORRIGÉ.</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

TWO_CHAPTERS_SWAPPED_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Deux (brut)</text:h>
      <text:p>Texte du second chapitre, version originale.</text:p>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un (brut)</text:h>
      <text:p>Texte du premier chapitre, version originale.</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

THREE_CHAPTERS_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un (brut)</text:h>
      <text:p>Un.</text:p>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Deux (brut)</text:h>
      <text:p>Deux.</text:p>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Trois (brut)</text:h>
      <text:p>Trois.</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

ONE_CHAPTER_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Unique (brut)</text:h>
      <text:p>Seul chapitre.</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

TWO_CHAPTERS_WITH_IMAGE_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un (brut)</text:h>
      <text:p><draw:frame><draw:image xlink:href="Pictures/img.png"/></draw:frame></text:p>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Deux (brut)</text:h>
      <text:p>Texte du second chapitre.</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

TWO_CHAPTERS_WITH_IMAGE_CORRECTED_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {NS_ATTRS}>
  <office:body>
    <office:text>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Un (corrigé)</text:h>
      <text:p><draw:frame><draw:image xlink:href="Pictures/img.png"/></draw:frame></text:p>
      <text:p>Une phrase ajoutée lors de la correction.</text:p>
      <text:h text:style-name="Heading_20_1" text:outline-level="1">Chapitre Deux (corrigé)</text:h>
      <text:p>Texte du second chapitre, corrigé.</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""


def _make_fixture(tmp_path: Path, content_xml: str, name: str, with_image: bool = False) -> Path:
    fixture_path = tmp_path / name
    with zipfile.ZipFile(fixture_path, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        zf.writestr("content.xml", content_xml)
        zf.writestr("styles.xml", STYLES_XML)
        zf.writestr("META-INF/manifest.xml", MANIFEST_XML)
        if with_image:
            zf.writestr("Pictures/img.png", b"\x89PNG fake bytes, always identical")
    return fixture_path


def _write_content(fixture_path: Path, content_xml: str) -> None:
    """Réécrit content.xml dans un .odt déjà existant, en préservant le reste du zip — simule
    l'utilisateur qui corrige le fichier dans Writer puis l'enregistre au même chemin."""
    import shutil
    tmp_copy = fixture_path.with_suffix(".tmp.odt")
    with zipfile.ZipFile(fixture_path, "r") as zin, zipfile.ZipFile(tmp_copy, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "content.xml":
                data = content_xml.encode("utf-8")
            zout.writestr(item, data)
    shutil.move(str(tmp_copy), str(fixture_path))


def test_find_source_odt_by_path_matches_existing_import(tmp_path):
    controller = ProjectController()
    fixture = _make_fixture(tmp_path, TWO_CHAPTERS_XML, "book.odt")
    controller.import_odt(fixture)

    assert controller.find_source_odt_by_path(fixture) is not None


def test_find_source_odt_by_path_returns_none_for_unknown_path(tmp_path):
    controller = ProjectController()
    fixture = _make_fixture(tmp_path, TWO_CHAPTERS_XML, "book.odt")

    assert controller.find_source_odt_by_path(fixture) is None


def test_replace_odt_same_count_updates_text_and_preserves_custom_title(tmp_path):
    controller = ProjectController()
    fixture = _make_fixture(tmp_path, TWO_CHAPTERS_XML, "book.odt")
    entry = controller.import_odt(fixture)
    old_ids = list(entry.chapter_ids)

    # Renommage manuel du premier chapitre par l'utilisateur.
    controller.project.document.chapters[old_ids[0]].title = "Mon titre personnalisé"
    controller.project.document.chapters[old_ids[0]].title_visible = False

    _write_content(fixture, TWO_CHAPTERS_CORRECTED_XML)
    controller.replace_odt(fixture)

    new_ids = entry.chapter_ids
    assert len(new_ids) == 2
    assert set(new_ids).isdisjoint(old_ids)  # les anciens ids ont bien disparu
    assert controller.project.document.chapters[new_ids[0]].title == "Mon titre personnalisé"
    assert controller.project.document.chapters[new_ids[0]].title_visible is False
    # Le second chapitre n'a jamais été renommé : garde son titre brut (celui du 2e ancien
    # chapitre, "Chapitre Deux (brut)", pas celui du nouveau fichier).
    assert controller.project.document.chapters[new_ids[1]].title == "Chapitre Deux (brut)"
    assert "CORRIGÉ" in controller.project.document.chapters[new_ids[0]].paragraphs[0].plain_text()
    for old_id in old_ids:
        assert old_id not in controller.project.document.chapters


def test_replace_odt_same_count_preserves_position_in_part(tmp_path):
    controller = ProjectController()
    fixture = _make_fixture(tmp_path, TWO_CHAPTERS_XML, "book.odt")
    entry = controller.import_odt(fixture)
    old_ids = list(entry.chapter_ids)

    part = Part.create("Ma partie")
    part.chapter_ids = [old_ids[1]]
    controller.project.document.structure.items = [old_ids[0], part]

    _write_content(fixture, TWO_CHAPTERS_CORRECTED_XML)
    controller.replace_odt(fixture)

    new_ids = entry.chapter_ids
    items = controller.project.document.structure.items
    assert items[0] == new_ids[0]
    assert isinstance(items[1], Part)
    assert items[1].chapter_ids == [new_ids[1]]


def test_replace_odt_preserves_free_position_after_manual_reorder(tmp_path):
    controller = ProjectController()
    fixture = _make_fixture(tmp_path, TWO_CHAPTERS_XML, "book.odt")
    entry = controller.import_odt(fixture)
    old_ids = list(entry.chapter_ids)

    # Réordonnancement manuel : le 2e chapitre passe avant le 1er.
    controller.project.document.structure.items = [old_ids[1], old_ids[0]]

    _write_content(fixture, TWO_CHAPTERS_CORRECTED_XML)
    controller.replace_odt(fixture)

    new_ids = entry.chapter_ids
    items = controller.project.document.structure.items
    assert items == [new_ids[1], new_ids[0]]


def test_replace_odt_preserves_image_settings_for_unchanged_image_bytes(tmp_path):
    controller = ProjectController()
    fixture = _make_fixture(tmp_path, TWO_CHAPTERS_WITH_IMAGE_XML, "book.odt", with_image=True)
    entry = controller.import_odt(fixture)
    old_chapter = controller.project.document.chapters[entry.chapter_ids[0]]
    asset_id = old_chapter.paragraphs[0].image.asset_id

    controller.project.document.image_display_sizes[asset_id] = ImageDisplaySize.SMALL
    controller.project.document.image_wraps[asset_id] = ImageWrap.LEFT

    _write_content(fixture, TWO_CHAPTERS_WITH_IMAGE_CORRECTED_XML)
    controller.replace_odt(fixture)

    new_chapter = controller.project.document.chapters[entry.chapter_ids[0]]
    new_asset_id = new_chapter.paragraphs[0].image.asset_id
    assert new_asset_id == asset_id  # octets identiques -> même hash -> même asset_id
    assert controller.project.document.image_display_sizes[asset_id] == ImageDisplaySize.SMALL
    assert controller.project.document.image_wraps[asset_id] == ImageWrap.LEFT


def test_replace_odt_locked_fonts_untouched(tmp_path):
    controller = ProjectController()
    fixture = _make_fixture(tmp_path, TWO_CHAPTERS_XML, "book.odt")
    controller.import_odt(fixture)
    controller.project.document.locked_fonts.append(
        LockedFont(family="Ma Police", files=[LockedFontFile(file_path="C:/fonts/mapolice.ttf")]))

    _write_content(fixture, TWO_CHAPTERS_CORRECTED_XML)
    controller.replace_odt(fixture)

    assert len(controller.project.document.locked_fonts) == 1
    assert controller.project.document.locked_fonts[0].family == "Ma Police"


def test_replace_odt_more_new_chapters_appends_free_and_warns(tmp_path):
    controller = ProjectController()
    fixture = _make_fixture(tmp_path, TWO_CHAPTERS_XML, "book.odt")
    entry = controller.import_odt(fixture)
    old_ids = list(entry.chapter_ids)

    warnings: list[str] = []
    controller.warning_occurred.connect(warnings.append)

    _write_content(fixture, THREE_CHAPTERS_XML)
    controller.replace_odt(fixture)

    assert len(entry.chapter_ids) == 3
    for old_id in old_ids:
        assert old_id not in controller.project.document.chapters
    assert entry.chapter_ids[2] in controller.project.document.structure.free_chapter_ids()
    assert any("3 chapitre" in w and "2" in w for w in warnings)


def test_replace_odt_fewer_new_chapters_deletes_extra_old_and_warns(tmp_path):
    controller = ProjectController()
    fixture = _make_fixture(tmp_path, TWO_CHAPTERS_XML, "book.odt")
    entry = controller.import_odt(fixture)
    old_ids = list(entry.chapter_ids)

    warnings: list[str] = []
    controller.warning_occurred.connect(warnings.append)

    _write_content(fixture, ONE_CHAPTER_XML)
    controller.replace_odt(fixture)

    assert len(entry.chapter_ids) == 1
    for old_id in old_ids:
        assert old_id not in controller.project.document.chapters
    assert old_ids[1] not in controller.project.document.structure.all_referenced_chapter_ids()
    assert any("1 chapitre" in w and "2" in w for w in warnings)


def test_replace_odt_warns_when_same_count_but_chapters_reordered(tmp_path):
    """Régression : si l'utilisateur permute deux chapitres dans Writer puis réimporte via
    « remplacer », le nombre de chapitres reste identique (2 -> 2), donc l'avertissement sur un
    changement de nombre ne se déclenche jamais — alors que l'appariement par position colle
    silencieusement le titre de l'ancien chapitre 1 sur le texte qui est en fait l'ancien
    chapitre 2, et vice-versa."""
    controller = ProjectController()
    fixture = _make_fixture(tmp_path, TWO_CHAPTERS_XML, "book.odt")
    entry = controller.import_odt(fixture)
    old_ids = list(entry.chapter_ids)

    controller.project.document.chapters[old_ids[0]].title = "Mon titre personnalisé un"
    controller.project.document.chapters[old_ids[1]].title = "Mon titre personnalisé deux"

    warnings: list[str] = []
    controller.warning_occurred.connect(warnings.append)

    _write_content(fixture, TWO_CHAPTERS_SWAPPED_XML)
    controller.replace_odt(fixture)

    assert len(entry.chapter_ids) == 2
    assert any("ordre différent" in w for w in warnings)


def test_replace_odt_does_not_warn_about_reorder_when_chapters_only_corrected(tmp_path):
    """Pas de faux positif : un simple texte corrigé/reformulé (sans permutation) ne doit pas
    déclencher l'avertissement d'ordre différent — seule une vraie permutation le doit."""
    controller = ProjectController()
    fixture = _make_fixture(tmp_path, TWO_CHAPTERS_XML, "book.odt")
    controller.import_odt(fixture)

    warnings: list[str] = []
    controller.warning_occurred.connect(warnings.append)

    _write_content(fixture, TWO_CHAPTERS_CORRECTED_XML)
    controller.replace_odt(fixture)

    assert not any("ordre différent" in w for w in warnings)


def test_replace_odt_undo_restores_pre_replace_state(tmp_path):
    controller = ProjectController()
    fixture = _make_fixture(tmp_path, TWO_CHAPTERS_XML, "book.odt")
    entry = controller.import_odt(fixture)
    old_ids = list(entry.chapter_ids)
    old_titles = [controller.project.document.chapters[cid].title for cid in old_ids]

    _write_content(fixture, TWO_CHAPTERS_CORRECTED_XML)
    controller.replace_odt(fixture)
    assert entry.chapter_ids != old_ids

    controller.undo()

    # undo() restaure project.source_odt_files par un clone profond : `entry` (capturé avant
    # l'undo) n'est donc plus le même objet que celui désormais dans controller.project — relire
    # depuis le controller, pas depuis la variable locale.
    restored_entry = controller.find_source_odt_by_path(fixture)
    assert restored_entry.chapter_ids == old_ids
    for cid, title in zip(old_ids, old_titles):
        assert controller.project.document.chapters[cid].title == title
