import zipfile

from lxml import etree


def describe_odt_open_error(exc: Exception, file_name: str) -> str:
    """Traduit une exception technique de lecture ODT en message compréhensible."""
    if isinstance(exc, zipfile.BadZipFile):
        return (f"« {file_name} » n'est pas un fichier .odt valide (le fichier est corrompu ou "
                f"n'est pas réellement un document ODT). Réenregistrez-le depuis LibreOffice Writer.")
    if isinstance(exc, KeyError):
        return (f"« {file_name} » ne contient pas la structure attendue d'un document ODT "
                f"(fichier interne manquant : {exc}). Réenregistrez-le depuis LibreOffice Writer.")
    if isinstance(exc, etree.XMLSyntaxError):
        return f"« {file_name} » contient du contenu illisible (XML invalide). Réenregistrez-le depuis LibreOffice Writer."
    if isinstance(exc, FileNotFoundError):
        return f"« {file_name} » est introuvable — le fichier a peut-être été déplacé ou supprimé."
    if isinstance(exc, PermissionError):
        return f"« {file_name} » ne peut pas être lu (accès refusé). Vérifiez qu'il n'est pas ouvert dans un autre programme."
    return f"« {file_name} » n'a pas pu être ouvert : {exc}"


def describe_epub_open_error(exc: Exception, file_name: str) -> str:
    """Traduit une exception technique de lecture EPUB en message compréhensible."""
    if isinstance(exc, zipfile.BadZipFile):
        return f"« {file_name} » n'est pas un fichier .epub valide (fichier corrompu)."
    if isinstance(exc, FileNotFoundError):
        return f"« {file_name} » est introuvable — le fichier a peut-être été déplacé ou supprimé."
    if isinstance(exc, PermissionError):
        return f"« {file_name} » ne peut pas être lu (accès refusé). Vérifiez qu'il n'est pas ouvert dans un autre programme."
    return f"« {file_name} » n'a pas pu être importé : {exc}"


def describe_project_load_error(exc: Exception, file_name: str) -> str:
    """Traduit une exception technique de chargement de projet .epbz en message compréhensible."""
    if isinstance(exc, zipfile.BadZipFile):
        return f"« {file_name} » n'est pas un fichier .epbz valide (fichier corrompu)."
    if isinstance(exc, (FileNotFoundError, KeyError)):
        return (f"« {file_name} » ne contient pas de projet Epubeur valide "
                f"(fichier project.epubeur.json introuvable dans l'archive).")
    if isinstance(exc, PermissionError):
        return f"« {file_name} » ne peut pas être lu (accès refusé)."
    return f"Impossible de charger le projet « {file_name} » : {exc}"


def describe_project_save_error(exc: Exception) -> str:
    """Traduit une exception technique de sauvegarde de projet en message compréhensible."""
    if isinstance(exc, PermissionError):
        return "Impossible d'enregistrer le projet : accès refusé. Vérifiez que le dossier n'est pas en lecture seule."
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return "Impossible d'enregistrer le projet : espace disque insuffisant."
    return f"Impossible d'enregistrer le projet : {exc}"


def describe_epub_generation_error(exc: Exception) -> str:
    """Traduit une exception technique de génération EPUB en message compréhensible."""
    if isinstance(exc, PermissionError):
        return ("Impossible d'écrire le fichier EPUB : accès refusé. Vérifiez que le fichier n'est pas "
                "déjà ouvert ailleurs, et que le dossier n'est pas en lecture seule.")
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return "Impossible d'écrire le fichier EPUB : espace disque insuffisant."
    if isinstance(exc, FileNotFoundError):
        return "Impossible d'écrire le fichier EPUB : le dossier de destination n'existe pas."
    return f"Erreur inattendue pendant la génération de l'EPUB : {exc}"
