from model.thema import THEMA_CODES, thema_children, thema_label, thema_parent_chain


def test_exactly_26_root_categories():
    roots = [code for code, (_, parent) in THEMA_CODES.items() if parent == ""]
    assert len(roots) == 26


def test_no_orphaned_codes():
    """Chaque CodeParent non-racine doit résoudre vers une clé existante de THEMA_CODES."""
    orphans = [code for code, (_, parent) in THEMA_CODES.items() if parent and parent not in THEMA_CODES]
    assert orphans == []


def test_thema_children_of_empty_string_returns_the_26_roots():
    roots = thema_children("")
    assert len(roots) == 26
    assert all(isinstance(pair, tuple) and len(pair) == 2 for pair in roots)


def test_thema_children_sorted_alphabetically_by_label():
    roots = thema_children("")
    labels = [label for _code, label in roots]
    assert labels == sorted(labels)


def test_thema_children_of_leaf_code_is_empty():
    # "ABK" (Contrefaçon, falsification et vol d'œuvres d'art) est un exemple de code terminal
    # connu (vérifié lors de la génération) — pas de sous-catégorie.
    assert thema_children("ABK") == []


def test_thema_label_known_code():
    assert thema_label("A") == "Arts"


def test_thema_label_unknown_code_returns_code_itself():
    assert thema_label("ZZZZZ") == "ZZZZZ"


def test_thema_parent_chain_for_root():
    assert thema_parent_chain("A") == ["A"]


def test_thema_parent_chain_for_deep_code():
    chain = thema_parent_chain("AFCC")
    assert chain == ["A", "AF", "AFC", "AFCC"]
    # Chaque maillon doit être un vrai code du référentiel.
    for code in chain:
        assert code in THEMA_CODES


def test_thema_parent_chain_for_empty_code():
    assert thema_parent_chain("") == []
