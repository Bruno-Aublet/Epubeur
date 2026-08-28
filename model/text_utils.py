import re


def flatten_to_single_line(text: str) -> str:
    """Aplati un texte pouvant contenir des '\\n' (saut de ligne manuel Maj+Entrée dans
    Writer) en une seule ligne, pour tout contexte où plusieurs lignes n'ont pas de sens
    (listes, titres de sommaire, infobulles, balise <title> du head XHTML)."""
    return " ".join(text.split("\n"))


_DIGIT_CHUNK_RE = re.compile(r"(\d+)")


def natural_sort_key(text: str) -> tuple:
    """Clé de tri « naturel » : découpe `text` en morceaux alternant texte/nombre, chaque morceau
    numérique étant comparé comme un entier plutôt que caractère par caractère — sans ça, un tri
    alphabétique classique place "Chapitre12" avant "Chapitre2" (le caractère '1' précède '2'),
    alors qu'un humain s'attend à l'ordre numérique normal. Insensible à la casse (même
    convention que les tris par nom de fichier déjà en place ailleurs dans le projet, ex.
    controller.py::_insert_free_chapters_in_alphanumeric_order, ui/structure_editor.py::
    _file_and_position_sort_key). Chaque morceau numérique est encodé comme (1, int(chunk)) et
    chaque morceau texte comme (0, chunk) : le tuple (0, ...) trie toujours avant (1, ...), ce qui
    évite un TypeError si un texte pair se termine juste avant un morceau numérique de l'autre
    (comparer un int et un str lèverait sinon une exception en Python 3)."""
    chunks = _DIGIT_CHUNK_RE.split(text.lower())
    return tuple((1, int(chunk)) if chunk.isdigit() else (0, chunk) for chunk in chunks if chunk)
