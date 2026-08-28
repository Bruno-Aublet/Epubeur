from model.text_utils import natural_sort_key

# Régression : un tri texte brut place "Chapitre12" avant "Chapitre2" (le caractère '1' précède
# '2'), alors qu'un humain nommant ses fichiers Chapitre1.odt, Chapitre2.odt... Chapitre12.odt
# attend l'ordre numérique normal.


def test_natural_sort_places_single_digit_before_double_digit():
    names = ["Chapitre12.odt", "Chapitre2.odt", "Chapitre1.odt"]
    assert sorted(names, key=natural_sort_key) == ["Chapitre1.odt", "Chapitre2.odt", "Chapitre12.odt"]


def test_natural_sort_is_case_insensitive():
    names = ["chapitre2.odt", "Chapitre10.odt"]
    assert sorted(names, key=natural_sort_key) == ["chapitre2.odt", "Chapitre10.odt"]


def test_natural_sort_handles_multiple_digit_groups():
    names = ["v2c10.odt", "v2c2.odt", "v10c1.odt"]
    assert sorted(names, key=natural_sort_key) == ["v2c2.odt", "v2c10.odt", "v10c1.odt"]


def test_natural_sort_falls_back_to_alphabetic_when_no_digits():
    names = ["banane.odt", "abricot.odt", "cerise.odt"]
    assert sorted(names, key=natural_sort_key) == ["abricot.odt", "banane.odt", "cerise.odt"]


def test_natural_sort_handles_purely_numeric_names():
    names = ["10.odt", "2.odt", "1.odt"]
    assert sorted(names, key=natural_sort_key) == ["1.odt", "2.odt", "10.odt"]
