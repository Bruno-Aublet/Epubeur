from pathlib import Path

from model.assets import AssetStore
from model.document import ImageDisplaySize, LockedFont, LockedFontFile, Part
from model.epbz import load_project_epbz, save_project_epbz
from model.project import ProjectMeta
from model.serialization import document_from_dict
from odt.chapter_detector import split_into_chapters
from odt.reader import OdtSource
from odt.styles_cascade import StyleResolver

FIXTURE = Path(__file__).parent / "fixtures" / "sample_simple.odt"


def _save_and_load(project: ProjectMeta, asset_store: AssetStore, epbz_path: Path):
    save_project_epbz(project, asset_store, epbz_path)
    return load_project_epbz(epbz_path)


def _make_project(tmp_path) -> tuple[ProjectMeta, AssetStore]:
    asset_store = AssetStore(tmp_path / "assets")
    source = OdtSource(FIXTURE)
    resolver = StyleResolver(source)
    chapters = split_into_chapters(source, resolver, source_odt_id="odt-1", asset_store=asset_store)

    project = ProjectMeta()
    for ch in chapters:
        project.document.chapters[ch.id] = ch  # pas add_chapter() : structure posée explicitement ensuite
    part = Part.create(title="Partie I")
    part.chapter_ids = [c.id for c in chapters]
    project.document.structure.items.append(part)

    # Chemin réel dans tmp_path (pas C:/Windows/Fonts/..., non fiable/absent selon la machine) —
    # pour que save_project_epbz puisse effectivement hasher+embarquer ce fichier de police.
    font_file = tmp_path / "SpecialNarrative.ttf"
    font_file.write_bytes(b"\x00\x01\x00\x00 fake ttf bytes")
    project.document.locked_fonts = [
        LockedFont(family="SpecialNarrative", files=[LockedFontFile(file_path=str(font_file))])
    ]

    from model.project import SourceOdtFile
    entry = SourceOdtFile.create(FIXTURE, 0)
    entry.chapter_ids = [c.id for c in chapters]
    project.source_odt_files.append(entry)

    return project, asset_store


def test_save_and_load_roundtrip_preserves_chapters_and_structure(tmp_path):
    project, asset_store = _make_project(tmp_path)
    epbz_path = tmp_path / "MyProject.epbz"
    loaded, _extract_dir, warnings = _save_and_load(project, asset_store, epbz_path)

    assert len(loaded.document.chapters) == len(project.document.chapters)
    assert set(loaded.document.chapters.keys()) == set(project.document.chapters.keys())

    for cid, chapter in project.document.chapters.items():
        loaded_chapter = loaded.document.chapters[cid]
        assert loaded_chapter.title == chapter.title
        assert len(loaded_chapter.paragraphs) == len(chapter.paragraphs)
        for orig_p, loaded_p in zip(chapter.paragraphs, loaded_chapter.paragraphs):
            assert orig_p.plain_text() == loaded_p.plain_text()
            assert orig_p.kind == loaded_p.kind
            assert orig_p.align == loaded_p.align

    assert len(loaded.document.structure.parts()) == 1
    assert loaded.document.structure.parts()[0].title == "Partie I"
    assert [lf.family for lf in loaded.document.locked_fonts] == ["SpecialNarrative"]


def test_save_and_load_roundtrip_preserves_run_formatting(tmp_path):
    project, asset_store = _make_project(tmp_path)
    epbz_path = tmp_path / "MyProject.epbz"
    loaded, _extract_dir, _warnings = _save_and_load(project, asset_store, epbz_path)

    for cid, chapter in project.document.chapters.items():
        loaded_chapter = loaded.document.chapters[cid]
        for orig_p, loaded_p in zip(chapter.paragraphs, loaded_chapter.paragraphs):
            for orig_r, loaded_r in zip(orig_p.runs, loaded_p.runs):
                assert orig_r.fmt == loaded_r.fmt


def test_load_missing_project_file_raises(tmp_path):
    import pytest
    with pytest.raises(Exception):
        load_project_epbz(tmp_path / "nonexistent.epbz")


def test_load_warns_on_missing_source_odt(tmp_path):
    project, asset_store = _make_project(tmp_path)
    project.source_odt_files[0].path = Path("C:/nonexistent/missing.odt")
    epbz_path = tmp_path / "MyProject.epbz"

    _loaded, _extract_dir, warnings = _save_and_load(project, asset_store, epbz_path)
    assert any("introuvable" in w for w in warnings)


def test_image_display_sizes_roundtrip(tmp_path):
    project, asset_store = _make_project(tmp_path)
    asset_id = next(iter(project.document.chapters))
    project.document.image_display_sizes[asset_id] = ImageDisplaySize.SMALL
    epbz_path = tmp_path / "MyProject.epbz"

    loaded, _extract_dir, _warnings = _save_and_load(project, asset_store, epbz_path)
    assert loaded.document.image_display_sizes[asset_id] == ImageDisplaySize.SMALL


def test_missing_image_display_sizes_key_defaults_to_empty_dict():
    legacy_dict = {
        "chapters": {},
        "structure": {"parts": []},
        "locked_font_family": None,
        "locked_font_file": None,
        "cover_asset_id": None,
        "back_cover_asset_id": None,
    }
    document = document_from_dict(legacy_dict)
    assert document.image_display_sizes == {}


def test_image_alt_texts_roundtrip(tmp_path):
    project, asset_store = _make_project(tmp_path)
    asset_id = next(iter(project.document.chapters))
    project.document.image_alt_texts[asset_id] = "Un gobelin brandissant une épée"
    epbz_path = tmp_path / "MyProject.epbz"

    loaded, _extract_dir, _warnings = _save_and_load(project, asset_store, epbz_path)
    assert loaded.document.image_alt_texts[asset_id] == "Un gobelin brandissant une épée"


def test_missing_image_alt_texts_key_defaults_to_empty_dict():
    legacy_dict = {
        "chapters": {},
        "structure": {"parts": []},
        "locked_font_family": None,
        "locked_font_file": None,
        "cover_asset_id": None,
        "back_cover_asset_id": None,
    }
    document = document_from_dict(legacy_dict)
    assert document.image_alt_texts == {}


def test_legacy_single_locked_font_format_migrates_to_list():
    """Régression : les projets sauvegardés avant le support multi-polices (format_version 1)
    utilisaient deux clés JSON singulières locked_font_family/locked_font_file, absentes de
    locked_fonts. Doit migrer vers une liste à un élément, pas planter ni perdre l'info."""
    legacy_dict = {
        "chapters": {},
        "structure": {"parts": []},
        "locked_font_family": "OldStyleFont",
        "locked_font_file": "C:/Windows/Fonts/arial.ttf",
        "cover_asset_id": None,
        "back_cover_asset_id": None,
    }
    document = document_from_dict(legacy_dict)
    assert len(document.locked_fonts) == 1
    assert document.locked_fonts[0].family == "OldStyleFont"
    assert len(document.locked_fonts[0].files) == 1
    assert document.locked_fonts[0].files[0].file_path == "C:/Windows/Fonts/arial.ttf"


def test_legacy_format_without_any_locked_font_migrates_to_empty_list():
    legacy_dict = {
        "chapters": {},
        "structure": {"parts": []},
        "locked_font_family": None,
        "locked_font_file": None,
        "cover_asset_id": None,
        "back_cover_asset_id": None,
    }
    document = document_from_dict(legacy_dict)
    assert document.locked_fonts == []


def test_v2_single_file_path_migrates_to_one_element_files_list():
    """Régression : les projets sauvegardés avant le support multi-fichiers-par-police
    (format_version 2) avaient locked_fonts avec un file_path singulier par entrée, sans clé
    'files'. Doit migrer vers files=[LockedFontFile(...)] avec weight/style par défaut."""
    legacy_dict = {
        "chapters": {},
        "structure": {"parts": []},
        "locked_fonts": [{"family": "OldMultiFont", "file_path": "C:/Windows/Fonts/arial.ttf"}],
        "cover_asset_id": None,
        "back_cover_asset_id": None,
    }
    document = document_from_dict(legacy_dict)
    assert len(document.locked_fonts) == 1
    lf = document.locked_fonts[0]
    assert lf.family == "OldMultiFont"
    assert len(lf.files) == 1
    assert lf.files[0].file_path == "C:/Windows/Fonts/arial.ttf"
    assert lf.files[0].weight == 400
    assert lf.files[0].italic is False


def test_v3_parts_only_format_migrates_free_chapters_to_end_of_sequence():
    """Régression : les projets sauvegardés avant le support des chapitres libres
    (format_version 3) n'avaient que "parts" — un chapitre jamais référencé par aucune
    part.chapter_ids était un orphelin invisible. Doit migrer vers un élément libre en fin
    de séquence, pas être perdu."""
    legacy_dict = {
        "chapters": {
            "chap-a": {"id": "chap-a", "title": "A", "paragraphs": []},
            "chap-b": {"id": "chap-b", "title": "B", "paragraphs": []},
            "chap-free": {"id": "chap-free", "title": "Libre", "paragraphs": []},
        },
        "structure": {"parts": [
            {"id": "part-1", "title": "Partie I", "chapter_ids": ["chap-a", "chap-b"]},
        ]},
        "cover_asset_id": None,
        "back_cover_asset_id": None,
    }
    document = document_from_dict(legacy_dict)
    assert len(document.structure.items) == 2
    assert document.structure.items[0].title == "Partie I"
    assert document.structure.items[1] == "chap-free"


def test_v4_items_format_roundtrips_free_chapter_position(tmp_path):
    project, asset_store = _make_project(tmp_path)
    doc = project.document
    part = doc.structure.parts()[0]
    # Retire un chapitre de la partie pour en faire un élément libre placé en TÊTE de
    # séquence, avant la partie — vérifie que cette position exacte survit au round-trip.
    free_chapter_id = part.chapter_ids.pop()
    doc.structure.items = [free_chapter_id, part]

    epbz_path = tmp_path / "MyProject.epbz"
    loaded, _extract_dir, _warnings = _save_and_load(project, asset_store, epbz_path)

    assert len(loaded.document.structure.items) == 2
    assert loaded.document.structure.items[0] == free_chapter_id
    assert loaded.document.structure.items[1].title == part.title
    assert loaded.document.structure.items[1].chapter_ids == part.chapter_ids


def test_locked_font_with_multiple_files_roundtrips(tmp_path):
    project, asset_store = _make_project(tmp_path)
    font_regular = tmp_path / "JMHTypewriter-Regular.ttf"
    font_regular.write_bytes(b"regular font bytes")
    font_bold = tmp_path / "JMHTypewriter-Bold.ttf"
    font_bold.write_bytes(b"bold font bytes")
    project.document.locked_fonts = [
        LockedFont(family="JMHTypewriter", files=[
            LockedFontFile(file_path=str(font_regular), weight=400, italic=False, style_name="Regular"),
            LockedFontFile(file_path=str(font_bold), weight=700, italic=False, style_name="Bold"),
        ])
    ]
    epbz_path = tmp_path / "MyProject.epbz"

    loaded, extract_dir, _warnings = _save_and_load(project, asset_store, epbz_path)
    assert len(loaded.document.locked_fonts) == 1
    lf = loaded.document.locked_fonts[0]
    assert lf.family == "JMHTypewriter"
    assert len(lf.files) == 2
    by_weight = {f.weight: f for f in lf.files}
    # Les polices figées sont désormais embarquées dans le .epbz (fonts/<sha256>.<ext>), extraites
    # dans extract_dir au chargement — le chemin n'est plus l'original externe (voir aussi
    # test_epbz.py pour la vérification octet-à-octet du contenu embarqué).
    assert Path(by_weight[400].file_path).read_bytes() == b"regular font bytes"
    assert by_weight[400].italic is False
    assert Path(by_weight[700].file_path).read_bytes() == b"bold font bytes"
    assert by_weight[700].style_name == "Bold"
    assert str(extract_dir) in by_weight[400].file_path


def test_serialization_round_trips_page_break_before(tmp_path):
    project, asset_store = _make_project(tmp_path)
    chapter = next(iter(project.document.chapters.values()))
    chapter.paragraphs[0].page_break_before = True

    epbz_path = tmp_path / "MyProject.epbz"
    loaded, _extract_dir, _warnings = _save_and_load(project, asset_store, epbz_path)

    loaded_chapter = loaded.document.chapters[chapter.id]
    assert loaded_chapter.paragraphs[0].page_break_before is True
    assert all(p.page_break_before is False for p in loaded_chapter.paragraphs[1:])
