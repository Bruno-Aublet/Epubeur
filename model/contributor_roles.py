"""Codes MARC Relator (scheme="marc:relators", standard maintenu par la Bibliothèque du
Congrès américaine, largement utilisé dans les métadonnées EPUB3/ONIX) — sous-ensemble
pertinent pour un livre narratif. Le code brut (ex. "trl") n'est jamais montré à l'utilisateur,
seul le libellé français l'est ; le code n'est écrit que dans le fichier OPF généré."""

CONTRIBUTOR_ROLE_LABELS: dict[str, str] = {
    "": "(rôle non précisé)",
    "trl": "Traducteur",
    "ill": "Illustrateur",
    "edt": "Éditeur / rédacteur",
    "aui": "Préfacier",
    "pht": "Photographe",
    "cov": "Concepteur de couverture",
    "nrt": "Narrateur",
    "ctb": "Contributeur",
}
