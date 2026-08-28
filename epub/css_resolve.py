import tinycss2

from model.styles import CharFormat, VerticalAlign


def parse_stylesheet_rules(css_text: str) -> dict[str, dict[str, str]]:
    """Parse une feuille CSS et retourne {selecteur_simple: {propriete: valeur}}.
    Ne gère que les sélecteurs simples (.classe, balise, #id) — suffisant pour la
    cascade "classe + inline" utilisée par les exports EPUB courants (Calibre, Word, etc.)."""
    rules: dict[str, dict[str, str]] = {}
    stylesheet = tinycss2.parse_stylesheet(css_text, skip_comments=True, skip_whitespace=True)
    for rule in stylesheet:
        if rule.type != "qualified-rule":
            continue
        selector = tinycss2.serialize(rule.prelude).strip()
        declarations = tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True)
        props: dict[str, str] = {}
        for decl in declarations:
            if decl.type == "declaration":
                value = tinycss2.serialize(decl.value).strip()
                props[decl.lower_name] = value
        for simple_selector in selector.split(","):
            simple_selector = simple_selector.strip()
            if simple_selector:
                rules.setdefault(simple_selector, {}).update(props)
    return rules


def _extract_url_from_src(tokens) -> str | None:
    """Extrait la première URL d'une déclaration `src: url(...)` — gère les deux formes
    tinycss2 possibles : url("...") -> FunctionBlock avec un StringToken en argument,
    url(...) sans guillemets -> URLToken directement."""
    for tok in tokens:
        type_name = type(tok).__name__
        if type_name == "URLToken":
            return tok.value
        if type_name == "FunctionBlock" and tok.name.lower() == "url":
            for arg in tok.arguments:
                if type(arg).__name__ == "StringToken":
                    return arg.value
    return None


def extract_font_face_rules(css_text: str) -> dict[str, list[tuple[str, int, bool]]]:
    """Parse les blocs @font-face d'une feuille CSS et retourne {family: [(url, weight, italic), ...]}.
    Une famille peut avoir plusieurs @font-face (une par variante physique embarquée : Regular,
    Bold, Italic, etc.), donc chaque bloc trouvé est accumulé dans la liste plutôt que d'écraser
    les précédents. parse_stylesheet_rules() ignore silencieusement les at-rules (dont
    @font-face fait partie, filtrées par `rule.type != "qualified-rule"`) — nécessaire pour
    retrouver, au réimport, quel(s) fichier(s) de police correspondent à quelle famille
    (encryption.xml donne les hrefs obfusqués mais pas leur correspondance avec un nom de
    famille ni leur weight/style)."""
    families_to_variants: dict[str, list[tuple[str, int, bool]]] = {}
    stylesheet = tinycss2.parse_stylesheet(css_text, skip_comments=True, skip_whitespace=True)
    for rule in stylesheet:
        if rule.type != "at-rule" or rule.at_keyword.lower() != "font-face":
            continue
        if rule.content is None:
            continue
        declarations = tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True)
        family = None
        url = None
        weight = 400
        italic = False
        for decl in declarations:
            if decl.type != "declaration":
                continue
            if decl.lower_name == "font-family":
                value = tinycss2.serialize(decl.value).strip()
                family = value.strip('"').strip("'")
            elif decl.lower_name == "src":
                url = _extract_url_from_src(decl.value)
            elif decl.lower_name == "font-weight":
                raw = tinycss2.serialize(decl.value).strip()
                weight = int(raw) if raw.isdigit() else (700 if raw in ("bold", "bolder") else 400)
            elif decl.lower_name == "font-style":
                raw = tinycss2.serialize(decl.value).strip()
                italic = raw in ("italic", "oblique")
        if family and url:
            families_to_variants.setdefault(family, []).append((url, weight, italic))
    return families_to_variants


def _apply_declarations(fmt: CharFormat, declarations: dict[str, str]) -> CharFormat:
    bold = fmt.bold
    italic = fmt.italic
    underline = fmt.underline
    strikethrough = fmt.strikethrough
    vertical_align = fmt.vertical_align
    font_name = fmt.font_name

    weight = declarations.get("font-weight")
    if weight is not None:
        bold = weight in ("bold", "bolder") or (weight.isdigit() and int(weight) >= 600)

    style = declarations.get("font-style")
    if style is not None:
        italic = style in ("italic", "oblique")

    decoration = declarations.get("text-decoration") or declarations.get("text-decoration-line")
    if decoration is not None:
        underline = "underline" in decoration
        strikethrough = "line-through" in decoration

    vertical = declarations.get("vertical-align")
    if vertical == "super":
        vertical_align = VerticalAlign.SUPERSCRIPT
    elif vertical == "sub":
        vertical_align = VerticalAlign.SUBSCRIPT

    family = declarations.get("font-family")
    if family is not None:
        font_name = family.split(",")[0].strip().strip('"').strip("'")

    return CharFormat(
        bold=bold,
        italic=italic,
        underline=underline,
        strikethrough=strikethrough,
        vertical_align=vertical_align,
        font_name=font_name,
    )


class CssResolver:
    """Résolution CSS pour l'import d'EPUB externes : cascade classes + inline + héritage,
    même logique de résolution qu'un lecteur EPUB — pas une devinette heuristique."""

    def __init__(self, css_texts: list[str]):
        self.rules: dict[str, dict[str, str]] = {}
        for css_text in css_texts:
            for selector, props in parse_stylesheet_rules(css_text).items():
                self.rules.setdefault(selector, {}).update(props)

    def resolve_element_format(self, tag_name: str, classes: list[str], inline_style: str | None,
                                inherited: CharFormat) -> CharFormat:
        fmt = inherited

        tag_selector = self.rules.get(tag_name)
        if tag_selector:
            fmt = _apply_declarations(fmt, tag_selector)

        for cls in classes:
            class_rules = self.rules.get(f".{cls}")
            if class_rules:
                fmt = _apply_declarations(fmt, class_rules)

        if inline_style:
            inline_decls = tinycss2.parse_declaration_list(inline_style, skip_comments=True, skip_whitespace=True)
            inline_props = {
                decl.lower_name: tinycss2.serialize(decl.value).strip()
                for decl in inline_decls
                if decl.type == "declaration"
            }
            if inline_props:
                fmt = _apply_declarations(fmt, inline_props)

        return fmt
