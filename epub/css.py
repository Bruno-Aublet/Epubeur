from dataclasses import dataclass

from model.document import ImageDisplaySize

# Habillage de texte (style:wrap ODF) : float:left repousse le texte qui l'entoure vers la
# droite de l'image -> marge à droite ; float:right -> marge à gauche, symétriquement.
# margin-bottom conservé dans les deux cas, cohérent avec la règle img générique de BASE_CSS.
# Constante séparée (pas seulement noyée dans BASE_CSS) : réutilisée telle quelle par
# ui/chapter_preview.py, qui a besoin de cette règle précise sans le reste de BASE_CSS (déjà
# couvert par son propre <style> adapté au rendu Qt Rich Text).
IMAGE_WRAP_CSS = """
img[data-epubeur-image-wrap="left"] {
  float: left;
  margin: 0 1em 1em 0;
}
img[data-epubeur-image-wrap="right"] {
  float: right;
  margin: 0 0 1em 1em;
}
"""

BASE_CSS = """
body { margin: 1em; }
h1 { font-size: 1.4em; text-align: center; margin-bottom: 1.5em; }
p { margin: 0 0 0.8em 0; line-height: 1.4; }
/* Un paragraphe totalement vide (Entrée simple répétée dans Writer, sans texte ni saut de
   ligne manuel) n'a que margin-bottom : plusieurs à la suite voient leurs marges fusionner
   (margin collapsing CSS standard, spec CSS2.1 §8.3.1) et deviennent quasi invisibles dans
   la plupart des lecteurs (Calibre, Chromium…), même si le paragraphe est bien présent dans
   le fichier. min-height casse le collapsing en donnant à la boîte un contenu non nul, sans
   affecter les paragraphes contenant du texte. */
p:empty { min-height: 1em; }
.align-center { text-align: center; }
.align-right { text-align: right; }
.align-justify { text-align: justify; }
blockquote { margin: 1em 2em; font-style: italic; }
ul, ol { margin: 0.5em 0 0.8em 1.5em; }
img { max-width: 100%; display: block; margin: 0 auto 1em auto; }

""" + IMAGE_WRAP_CSS + """

/* Bordures/fond fixes ici (pas dérivés des styles de cellule ODF, hors scope de cette
   première version) : un tableau totalement sans bordure serait illisible dans la plupart des
   liseuses, qui n'appliquent aucun style de tableau par défaut contrairement à un navigateur.
   border-collapse évite le double-trait entre cellules adjacentes. */
table { border-collapse: collapse; margin: 0 0 1em 0; width: 100%; }
th, td { border: 1px solid #999; padding: 0.4em 0.6em; text-align: left; vertical-align: top; }
th { font-weight: bold; background: #f0f0f0; }

/* Cible directement la balise aside, sans sélecteur d'attribut de namespace
   (aside[epub|type~="footnote"] nécessiterait une déclaration @namespace inutile ici : aucun
   autre usage de <aside> n'existe dans le HTML généré par l'app). */
aside {
  margin-top: 1.5em;
  padding-top: 0.5em;
  border-top: 1px solid #999;
  font-size: 0.85em;
}
aside p { margin: 0 0 0.4em 0; }

.epubeur-part-title-page {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
  width: 100%;
  margin: 0;
  text-align: center;
  box-sizing: border-box;
}
.epubeur-part-title-page h1 {
  font-size: 2em;
  margin: 0;
  text-align: center;
}

.epubeur-back-cover-page {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
  width: 100%;
  margin: 0;
  box-sizing: border-box;
}
.epubeur-back-cover-page img {
  max-width: 100%;
  max-height: 100vh;
  margin: 0;
}
"""

LOCKED_FONT_FACE_TEMPLATE = """
@font-face {{
  font-family: "{family}";
  src: url("../fonts/{font_href}");
  font-weight: {weight};
  font-style: {style};
}}
"""

LOCKED_FONT_CLASS_TEMPLATE = """
.{locked_class} {{
  font-family: "{family}" !important;
}}
"""

IMAGE_SIZE_RULE_TEMPLATE = """
img[data-epubeur-image="{asset_id}"] {{
  max-width: {percent}%;
}}
"""


@dataclass
class LockedFontFaceSpec:
    family: str
    css_class: str
    font_href: str  # nom de fichier relatif à fonts/, ex. "MaPolice.ttf"
    weight: int = 400
    italic: bool = False


def build_css(locked_font_specs: list[LockedFontFaceSpec] | None = None,
               image_display_sizes: dict[str, ImageDisplaySize] | None = None) -> str:
    css = BASE_CSS
    emitted_classes: set[str] = set()
    for spec in locked_font_specs or []:
        css += LOCKED_FONT_FACE_TEMPLATE.format(
            family=spec.family,
            font_href=spec.font_href,
            weight=spec.weight,
            style="italic" if spec.italic else "normal",
        )
        if spec.css_class not in emitted_classes:
            css += LOCKED_FONT_CLASS_TEMPLATE.format(family=spec.family, locked_class=spec.css_class)
            emitted_classes.add(spec.css_class)
    for asset_id, size in (image_display_sizes or {}).items():
        if size.value == 100:
            continue
        css += IMAGE_SIZE_RULE_TEMPLATE.format(asset_id=asset_id, percent=size.value)
    return css
