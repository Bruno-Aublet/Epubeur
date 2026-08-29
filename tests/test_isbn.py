from model.isbn import is_valid_isbn, normalize_isbn


def test_normalize_isbn_strips_dashes_and_spaces():
    assert normalize_isbn("978-2-1234-5680-3") == "9782123456803"
    assert normalize_isbn("2 123456 80 2") == "2123456802"


def test_normalize_isbn_strips_unicode_dash_variants():
    """Régression : un ISBN copié depuis une fiche BnF/Amazon (souvent rendu avec un en-dash
    par le CSS du site) était rejeté comme invalide alors qu'il était parfaitement correct —
    seul le caractère de tiret posait problème, avec un message trompeur pointant vers la clé
    de contrôle."""
    assert normalize_isbn("978‐2‑1234‒5680–3") == "9782123456803"  # hyphen, nb-hyphen, figure dash, en dash
    assert normalize_isbn("978—2—1234—5680—3") == "9782123456803"  # em dash
    assert normalize_isbn("978−2−1234−5680−3") == "9782123456803"  # minus sign


def test_valid_isbn_13_with_en_dash():
    assert is_valid_isbn("978–2–1234–5680–3") is True


def test_valid_isbn_13():
    assert is_valid_isbn("978-2-1234-5680-3") is True


def test_valid_isbn_10():
    assert is_valid_isbn("2-1234-5680-2") is True


def test_invalid_isbn_wrong_check_digit():
    assert is_valid_isbn("978-2-1234-5680-4") is False
    assert is_valid_isbn("2-1234-5680-1") is False


def test_invalid_isbn_wrong_length():
    assert is_valid_isbn("12345") is False
    assert is_valid_isbn("") is False


def test_invalid_isbn_non_digit_characters():
    assert is_valid_isbn("978-2-ABCD-5680-4") is False
