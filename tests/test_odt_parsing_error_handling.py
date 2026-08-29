from pathlib import Path

import controller as controller_module
from controller import ProjectController

FIXTURE = Path(__file__).parent / "fixtures" / "sample_simple.odt"


def _raise_value_error(*args, **kwargs):
    raise ValueError("cas limite imprévu dans le parsing ODT")


def test_import_odt_reports_error_when_split_into_chapters_raises(qapp, monkeypatch):
    """Régression : seule l'ouverture initiale (OdtSource/StyleResolver) était protégée par
    try/except — une exception levée par split_into_chapters (le plus gros du travail de
    parsing) remontait non gérée jusqu'à l'UI, plantant l'application au lieu d'afficher un
    message d'erreur propre, alors que l'ouverture basique du fichier avait réussi."""
    monkeypatch.setattr(controller_module, "split_into_chapters", _raise_value_error)

    controller = ProjectController()
    errors: list[str] = []
    controller.error_occurred.connect(errors.append)

    result = controller.import_odt(FIXTURE)  # ne doit pas lever

    assert result is None
    assert len(errors) == 1
    assert FIXTURE.name in errors[0]
    assert controller.project.document.chapters == {}
    assert controller.project.source_odt_files == []


def test_replace_odt_reports_error_when_split_into_chapters_raises(qapp, monkeypatch):
    """Même régression que import_odt, côté replace_odt — avec un risque supplémentaire :
    un _snapshot_structure() appelé avant l'échec aurait empilé un état d'annulation inutile."""
    controller = ProjectController()
    entry = controller.import_odt(FIXTURE)
    assert entry is not None

    monkeypatch.setattr(controller_module, "split_into_chapters", _raise_value_error)
    errors: list[str] = []
    controller.error_occurred.connect(errors.append)
    can_undo_before = controller.can_undo()

    result = controller.replace_odt(FIXTURE)  # ne doit pas lever

    assert result is None
    assert len(errors) == 1
    assert FIXTURE.name in errors[0]
    # Le projet reste intact (chapitres d'origine toujours là) et aucun snapshot inutile n'a
    # été empilé sur la pile undo suite à cet échec.
    assert list(controller.project.document.chapters.keys()) == entry.chapter_ids
    assert controller.can_undo() == can_undo_before
