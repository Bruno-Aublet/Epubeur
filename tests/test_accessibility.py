from epub.accessibility import build_accessibility_metadata
from model.document import Chapter, Document, ImageAnchor, Paragraph


def test_no_images_declares_textual_only():
    document = Document()
    chapter = Chapter.create(title="Sans image")
    document.chapters[chapter.id] = chapter

    metadata = build_accessibility_metadata(document)

    assert ("schema:accessMode", "textual") in metadata
    assert ("schema:accessMode", "visual") not in metadata
    assert ("schema:accessibilityFeature", "alternativeText") not in metadata


def test_image_without_alt_text_declares_visual_but_not_alternative_text():
    document = Document()
    chapter = Chapter.create(title="Avec image")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id="abc", alt_text=""))]
    document.chapters[chapter.id] = chapter

    metadata = build_accessibility_metadata(document)

    assert ("schema:accessMode", "visual") in metadata
    assert ("schema:accessibilityFeature", "alternativeText") not in metadata


def test_image_with_alt_text_declares_alternative_text():
    document = Document()
    chapter = Chapter.create(title="Avec image décrite")
    chapter.paragraphs = [Paragraph(image=ImageAnchor(asset_id="abc", alt_text="Un gobelin"))]
    document.chapters[chapter.id] = chapter

    metadata = build_accessibility_metadata(document)

    assert ("schema:accessibilityFeature", "alternativeText") in metadata


def test_one_image_without_alt_text_among_several_blocks_alternative_text():
    """Toutes les images doivent avoir une description, pas seulement certaines — sinon
    alternativeText serait une déclaration trompeuse pour les images non décrites."""
    document = Document()
    chapter = Chapter.create(title="Chapitre")
    chapter.paragraphs = [
        Paragraph(image=ImageAnchor(asset_id="a", alt_text="Décrite")),
        Paragraph(image=ImageAnchor(asset_id="b", alt_text="")),
    ]
    document.chapters[chapter.id] = chapter

    metadata = build_accessibility_metadata(document)

    assert ("schema:accessibilityFeature", "alternativeText") not in metadata


def test_always_declares_structural_navigation_and_hazard_none():
    document = Document()
    metadata = build_accessibility_metadata(document)

    assert ("schema:accessibilityFeature", "structuralNavigation") in metadata
    assert ("schema:accessibilityFeature", "readingOrder") in metadata
    assert ("schema:accessModeSufficient", "textual") in metadata
    assert ("schema:accessibilityHazard", "none") in metadata
