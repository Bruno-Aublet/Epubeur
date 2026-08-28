from model.document import Document, iter_all_paragraphs


def build_accessibility_metadata(document: Document) -> list[tuple[str, str]]:
    """Métadonnées d'accessibilité EPUB3 (spec schema.org), déduites automatiquement du contenu
    réel — jamais saisies par l'utilisateur, pour ne jamais risquer une déclaration mensongère.
    Retourne une liste de (property, value) à poser via book.add_metadata(None, "meta", value,
    {"property": property}).

    Toujours vraies pour tout livre généré par cette app (aucune fonctionnalité audio/vidéo/
    animation, sommaire + repères de navigation toujours générés, cf. epub/toc.py) :
    - accessMode: textual (+ visual si au moins une image existe)
    - accessModeSufficient: textual (le texte seul suffit à tout comprendre, aucune image n'est
      indispensable à la compréhension dans un roman/essai)
    - accessibilityFeature: structuralNavigation, readingOrder
    - accessibilityHazard: none

    Dépend réellement du contenu :
    - accessibilityFeature: alternativeText, seulement si CHAQUE image utilisée dans le livre a
      une description non vide — document.image_alt_texts (saisie dans l'onglet Images) prime
      sur ImageAnchor.alt_text (svg:desc brut lu à l'import ODT), cf. epub/html_render.py — sinon
      omis plutôt que déclaré à tort."""
    image_asset_ids: set[str] = set()
    all_images_have_alt_text = True
    for chapter in document.chapters.values():
        for para in iter_all_paragraphs(chapter.paragraphs):
            if para.image is not None:
                asset_id = para.image.asset_id
                image_asset_ids.add(asset_id)
                alt_text = document.image_alt_texts.get(asset_id) or para.image.alt_text
                if not alt_text.strip():
                    all_images_have_alt_text = False

    access_modes = ["textual"]
    if image_asset_ids:
        access_modes.append("visual")

    features = ["structuralNavigation", "readingOrder"]
    if image_asset_ids and all_images_have_alt_text:
        features.append("alternativeText")

    metadata: list[tuple[str, str]] = []
    for mode in access_modes:
        metadata.append(("schema:accessMode", mode))
    metadata.append(("schema:accessModeSufficient", "textual"))
    for feature in features:
        metadata.append(("schema:accessibilityFeature", feature))
    metadata.append(("schema:accessibilityHazard", "none"))
    return metadata
