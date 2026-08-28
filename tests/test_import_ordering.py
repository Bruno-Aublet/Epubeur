import shutil
from pathlib import Path

from controller import ProjectController

FIXTURE = Path(__file__).parent / "fixtures" / "sample_simple.odt"


def _copy_fixture(tmp_path: Path, name: str) -> Path:
    dest = tmp_path / name
    shutil.copy(FIXTURE, dest)
    return dest


def _free_chapter_file_names(controller: ProjectController) -> list[str]:
    """Nom du fichier ODT source de chaque chapitre libre, dans l'ordre de structure.items —
    un même fichier peut apparaître plusieurs fois de suite (plusieurs chapitres par fichier)."""
    document = controller.project.document
    names = []
    for item in document.structure.items:
        if not isinstance(item, str):
            continue
        chapter = document.chapters[item]
        entry = next(f for f in controller.project.source_odt_files if f.id == chapter.source_odt_id)
        names.append(entry.path.name)
    return names


def test_files_imported_out_of_order_end_up_alphanumerically_sorted(tmp_path):
    """Régression (signalée plusieurs fois) : les chapitres doivent être ordonnés par nom de
    fichier ODT alphanumérique, PAS par l'ordre dans lequel les fichiers ont été glissés-déposés/
    importés dans l'application."""
    controller = ProjectController()

    controller.import_odt(_copy_fixture(tmp_path, "Chapitre3.odt"))
    controller.import_odt(_copy_fixture(tmp_path, "Chapitre1.odt"))
    controller.import_odt(_copy_fixture(tmp_path, "Chapitre2.odt"))

    names = _free_chapter_file_names(controller)
    # sample_simple.odt produit 2 chapitres par fichier importé — les deux du même fichier
    # doivent rester groupés et dans l'ordre alphanumérique des fichiers.
    assert names == ["Chapitre1.odt", "Chapitre1.odt", "Chapitre2.odt", "Chapitre2.odt",
                      "Chapitre3.odt", "Chapitre3.odt"]


def test_a_file_inserted_between_two_already_imported_files_lands_in_between(tmp_path):
    """Un fichier importé APRÈS coup, dont le nom se situe alphabétiquement entre deux fichiers
    déjà présents, doit s'insérer entre eux — pas retomber en fin de liste."""
    controller = ProjectController()

    controller.import_odt(_copy_fixture(tmp_path, "A.odt"))
    controller.import_odt(_copy_fixture(tmp_path, "C.odt"))
    controller.import_odt(_copy_fixture(tmp_path, "B.odt"))

    names = _free_chapter_file_names(controller)
    assert names == ["A.odt", "A.odt", "B.odt", "B.odt", "C.odt", "C.odt"]


def test_manual_reorder_is_not_undone_by_a_later_import(tmp_path):
    """Un réordonnancement manuel de l'utilisateur (drag & drop dans l'onglet Structure) ne doit
    jamais être écrasé par un import ultérieur — seul le NOUVEAU bloc de chapitres est inséré à
    sa position alphanumérique, l'ordre déjà établi pour les fichiers existants reste intact."""
    controller = ProjectController()
    controller.import_odt(_copy_fixture(tmp_path, "A.odt"))
    controller.import_odt(_copy_fixture(tmp_path, "B.odt"))

    # Réordonnancement manuel : l'utilisateur inverse B avant A dans structure.items.
    items = controller.project.document.structure.items
    items.reverse()
    manually_ordered = _free_chapter_file_names(controller)
    assert manually_ordered == ["B.odt", "B.odt", "A.odt", "A.odt"]

    # Un nouvel import de C.odt (alphabétiquement après A et B) doit s'ajouter en fin, sans
    # jamais remettre A avant B.
    controller.import_odt(_copy_fixture(tmp_path, "C.odt"))
    final_order = _free_chapter_file_names(controller)
    assert final_order == ["B.odt", "B.odt", "A.odt", "A.odt", "C.odt", "C.odt"]


def test_natural_sort_places_chapter2_before_chapter12(tmp_path):
    """Régression : un tri texte brut classerait "Chapitre12.odt" avant "Chapitre2.odt" (le
    caractère '1' précède '2') — le tri doit être numérique (naturel), pas lexicographique brut,
    pour respecter l'ordre attendu par l'utilisateur qui nomme ses fichiers Chapitre1, Chapitre2,
    ... Chapitre12 sans zéros de remplissage."""
    controller = ProjectController()

    controller.import_odt(_copy_fixture(tmp_path, "Chapitre12.odt"))
    controller.import_odt(_copy_fixture(tmp_path, "Chapitre1.odt"))
    controller.import_odt(_copy_fixture(tmp_path, "Chapitre2.odt"))
    controller.import_odt(_copy_fixture(tmp_path, "Chapitre10.odt"))

    names = _free_chapter_file_names(controller)
    assert names == ["Chapitre1.odt", "Chapitre1.odt", "Chapitre2.odt", "Chapitre2.odt",
                      "Chapitre10.odt", "Chapitre10.odt", "Chapitre12.odt", "Chapitre12.odt"]
