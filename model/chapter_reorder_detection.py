import difflib

from model.document import Chapter, Table

_SIGNATURE_LENGTH = 200  # assez pour distinguer deux chapitres, court pour rester rapide
_MISMATCH_THRESHOLD = 0.4  # en dessous, deux textes sont jugés trop différents pour être "le même"


def _chapter_signature(chapter: Chapter) -> str:
    """Texte de début du chapitre, utilisé comme empreinte grossière de contenu — pas un hash
    exact (une reformulation légère du premier paragraphe est acceptée), juste de quoi détecter
    qu'un chapitre a changé de position plutôt que de contenu."""
    parts = []
    length = 0
    for block in chapter.paragraphs:
        if isinstance(block, Table):
            continue
        text = block.plain_text().strip()
        if not text:
            continue
        parts.append(text)
        length += len(text)
        if length >= _SIGNATURE_LENGTH:
            break
    return " ".join(parts)[:_SIGNATURE_LENGTH]


def detect_reordered_chapters(old_chapters: list[Chapter], new_chapters: list[Chapter]) -> bool:
    """Détecte si des chapitres ont probablement changé d'ordre relatif entre old_chapters et
    new_chapters (même longueur, appariés par position) — cas où replace_odt() apparie les
    chapitres par simple position et ne peut pas le remarquer lui-même puisque le compte total
    reste identique (son seul avertissement actuel se déclenche uniquement sur un changement de
    nombre de chapitres). Heuristique : pour chaque position i, le nouveau chapitre à cette
    position doit ressembler le PLUS à l'ancien chapitre i parmi tous les anciens chapitres —
    si un autre ancien chapitre lui ressemble nettement mieux, c'est le signe qu'ils ont permuté.
    Ne prétend pas être exact (un texte réécrit peut échapper à la détection), seulement réduire
    le risque de mélange totalement silencieux."""
    if len(old_chapters) != len(new_chapters) or not old_chapters:
        return False

    old_signatures = [_chapter_signature(c) for c in old_chapters]
    new_signatures = [_chapter_signature(c) for c in new_chapters]

    for i, new_sig in enumerate(new_signatures):
        if not new_sig or not old_signatures[i]:
            continue  # signature vide (chapitre sans texte) : rien de fiable à comparer

        own_ratio = difflib.SequenceMatcher(None, old_signatures[i], new_sig).ratio()
        best_other_ratio = max(
            (difflib.SequenceMatcher(None, old_sig, new_sig).ratio()
             for j, old_sig in enumerate(old_signatures) if j != i),
            default=0.0,
        )
        if best_other_ratio > own_ratio and best_other_ratio >= _MISMATCH_THRESHOLD:
            return True

    return False
