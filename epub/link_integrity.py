import posixpath
import re

from ebooklib import epub

_ID_ATTR_RE = re.compile(r'\bid="([^"]+)"')
_HREF_ATTR_RE = re.compile(r'\bhref="([^"]+)"')


def _get_html_items(book: "epub.EpubBook") -> list["epub.EpubHtml"]:
    return [item for item in book.get_items() if isinstance(item, epub.EpubHtml)]


def check_internal_link_integrity(book: "epub.EpubBook") -> list[str]:
    """Vérifie, sur le contenu XHTML déjà généré (avant écriture du zip), que :
    - chaque attribut id="..." est unique à l'intérieur de son propre fichier (une contrainte
      XML de base ; epubcheck la vérifie par document, pas globalement au paquet, car un lien
      inter-fichiers cible toujours fichier.xhtml#id, désambiguïsé par le nom de fichier) ;
    - chaque lien interne (href="#ancre" ou href="fichier.xhtml#ancre") cible bien un id qui
      existe réellement dans le fichier visé.
    Ne fait rien tant qu'aucun contenu ne produit de tels attributs (aujourd'hui aucune
    fonctionnalité de l'app n'en génère) — prête à attraper le problème dès qu'une fonctionnalité
    future (ex. notes de bas de page) commencera à écrire des ancres internes."""
    errors: list[str] = []
    html_items = _get_html_items(book)

    ids_by_file: dict[str, set[str]] = {}
    for item in html_items:
        content = item.get_content()
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        ids = _ID_ATTR_RE.findall(content)
        seen: set[str] = set()
        for id_value in ids:
            if id_value in seen:
                errors.append(
                    f"Identifiant « {id_value} » présent plusieurs fois dans « {item.file_name} »."
                )
            seen.add(id_value)
        ids_by_file[item.file_name] = seen

    for item in html_items:
        content = item.get_content()
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        for href in _HREF_ATTR_RE.findall(content):
            if "#" not in href:
                continue
            file_part, _, fragment = href.partition("#")
            if not fragment:
                continue
            if file_part:
                target_file = posixpath.normpath(posixpath.join(posixpath.dirname(item.file_name), file_part))
            else:
                target_file = item.file_name
            target_ids = ids_by_file.get(target_file)
            if target_ids is None or fragment not in target_ids:
                errors.append(
                    f"Lien interne cassé dans « {item.file_name} » : « {href} » ne correspond à "
                    f"aucun identifiant existant."
                )

    return errors
