from epub.css_resolve import CssResolver
from epub.html_normalize import html_to_paragraphs

# Régression : un EPUB produit par un autre logiciel qu'Epubeur (Calibre, Sigil, export web...)
# peut légitimement contenir <section>/<article>, <figure>/<figcaption> et des <aside> génériques
# (sans epub:type="footnote") — aucun de ces tags n'était reconnu par _visit_container avant ce
# correctif : ni ul/ol/blockquote/p/table, ni le cas spécial "aside" (toujours sauté). Leur contenu
# disparaissait donc silencieusement à la réimportation, même mécanisme que le bug déjà corrigé
# pour text:section côté lecture ODT.


def test_section_content_is_not_lost_on_reimport():
    xhtml = """<html><body><div class="epubeur-chapter">
<p>Avant.</p>
<section><p>Texte dans la section.</p></section>
<p>Après.</p>
</div></body></html>"""
    resolver = CssResolver([])
    paragraphs, _footnotes, _image_wraps = html_to_paragraphs(xhtml, resolver)

    texts = [p.plain_text() for p in paragraphs]
    assert texts == ["Avant.", "Texte dans la section.", "Après."]


def test_nested_sections_are_both_traversed_on_reimport():
    xhtml = """<html><body><div class="epubeur-chapter">
<section><section><p>Profondément imbriqué.</p></section></section>
</div></body></html>"""
    resolver = CssResolver([])
    paragraphs, _footnotes, _image_wraps = html_to_paragraphs(xhtml, resolver)

    assert [p.plain_text() for p in paragraphs] == ["Profondément imbriqué."]


def test_article_content_is_not_lost_on_reimport():
    xhtml = """<html><body><div class="epubeur-chapter">
<article><p>Contenu d'article.</p></article>
</div></body></html>"""
    resolver = CssResolver([])
    paragraphs, _footnotes, _image_wraps = html_to_paragraphs(xhtml, resolver)

    assert [p.plain_text() for p in paragraphs] == ["Contenu d'article."]


def test_figure_with_caption_is_not_lost_on_reimport():
    xhtml = """<html><body><div class="epubeur-chapter">
<figure>
<p><img data-epubeur-image="img-1"/></p>
<figcaption>Légende de l'image.</figcaption>
</figure>
</div></body></html>"""
    resolver = CssResolver([])
    paragraphs, _footnotes, _image_wraps = html_to_paragraphs(xhtml, resolver)

    assert len(paragraphs) == 2
    assert paragraphs[0].image is not None
    assert paragraphs[0].image.asset_id == "img-1"
    assert paragraphs[1].plain_text() == "Légende de l'image."


def test_generic_aside_content_is_not_lost_on_reimport():
    xhtml = """<html><body><div class="epubeur-chapter">
<p>Avant.</p>
<aside><p>Encart hors-note.</p></aside>
<p>Après.</p>
</div></body></html>"""
    resolver = CssResolver([])
    paragraphs, footnotes, _image_wraps = html_to_paragraphs(xhtml, resolver)

    texts = [p.plain_text() for p in paragraphs]
    assert texts == ["Avant.", "Encart hors-note.", "Après."]
    assert footnotes == {}


def test_footnote_aside_is_still_excluded_from_body_and_routed_to_footnotes():
    """Non-régression : un <aside epub:type="footnote"> continue de ne PAS apparaître dans le
    corps du chapitre (il est retiré et placé dans le dict de notes séparé)."""
    xhtml = """<html><body><div class="epubeur-chapter">
<p>Texte<a epub:type="noteref" href="#note-1">1</a>.</p>
<aside epub:type="footnote" id="note-1"><p>Contenu de la note.</p></aside>
</div></body></html>"""
    resolver = CssResolver([])
    paragraphs, footnotes, _image_wraps = html_to_paragraphs(xhtml, resolver)

    assert len(paragraphs) == 1
    assert "1" in footnotes
    assert footnotes["1"][0].plain_text() == "Contenu de la note."


def test_section_inside_footnote_body_is_not_lost():
    xhtml = """<html><body><div class="epubeur-chapter">
<p>Texte<a epub:type="noteref" href="#note-1">1</a>.</p>
<aside epub:type="footnote" id="note-1"><section><p>Note avec section.</p></section></aside>
</div></body></html>"""
    resolver = CssResolver([])
    _paragraphs, footnotes, _image_wraps = html_to_paragraphs(xhtml, resolver)

    assert footnotes["note-1".replace("note-", "")][0].plain_text() == "Note avec section."
