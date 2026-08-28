from model.chapter_numbering import extract_chapter_number


def test_extracts_number_from_simple_title():
    assert extract_chapter_number("Chapitre 7 : L'état des forces") == 7


def test_extracts_number_case_insensitive():
    assert extract_chapter_number("CHAPITRE 12 : Le message") == 12


def test_returns_none_for_title_without_number():
    assert extract_chapter_number("Premier Prologue : Saevros") is None
    assert extract_chapter_number("Épilogue") is None


def test_extracts_first_number_when_multiple_present():
    assert extract_chapter_number("Chapitre 3, partie 2") == 3
