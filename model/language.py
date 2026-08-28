import re

# Codes ISO 639-1 (deux lettres), liste complète et stable — ne change pratiquement jamais,
# codée en dur plutôt que dépendre d'un paquet externe (ex. langcodes/babel).
ISO_639_1_CODES = frozenset({
    "aa", "ab", "ae", "af", "ak", "am", "an", "ar", "as", "av", "ay", "az",
    "ba", "be", "bg", "bh", "bi", "bm", "bn", "bo", "br", "bs",
    "ca", "ce", "ch", "co", "cr", "cs", "cu", "cv", "cy",
    "da", "de", "dv", "dz",
    "ee", "el", "en", "eo", "es", "et", "eu",
    "fa", "ff", "fi", "fj", "fo", "fr", "fy",
    "ga", "gd", "gl", "gn", "gu", "gv",
    "ha", "he", "hi", "ho", "hr", "ht", "hu", "hy", "hz",
    "ia", "id", "ie", "ig", "ii", "ik", "io", "is", "it", "iu",
    "ja", "jv",
    "ka", "kg", "ki", "kj", "kk", "kl", "km", "kn", "ko", "kr", "ks", "ku", "kv", "kw", "ky",
    "la", "lb", "lg", "li", "ln", "lo", "lt", "lu", "lv",
    "mg", "mh", "mi", "mk", "ml", "mn", "mr", "ms", "mt", "my",
    "na", "nb", "nd", "ne", "ng", "nl", "nn", "no", "nr", "nv", "ny",
    "oc", "oj", "om", "or", "os",
    "pa", "pi", "pl", "ps", "pt",
    "qu",
    "rm", "rn", "ro", "ru", "rw",
    "sa", "sc", "sd", "se", "sg", "si", "sk", "sl", "sm", "sn", "so", "sq", "sr", "ss", "st",
    "su", "sv", "sw",
    "ta", "te", "tg", "th", "ti", "tk", "tl", "tn", "to", "tr", "ts", "tt", "tw", "ty",
    "ug", "uk", "ur", "uz",
    "ve", "vi", "vo",
    "wa", "wo",
    "xh",
    "yi", "yo",
    "za", "zh", "zu",
})

# Nom français de chaque langue ISO 639-1 ci-dessus — même liste, même ordre, pour vérifier
# l'exhaustivité par simple comparaison visuelle. Utilisé pour la liste déroulante de langue de
# l'onglet Métadonnées (ui/generate_panel.py) : un utilisateur ne peut pas être censé connaître
# les codes ISO de mémoire, contrairement à un nom de langue en clair.
LANGUAGE_NAMES_FR = {
    "aa": "Afar", "ab": "Abkhaze", "ae": "Avestique", "af": "Afrikaans", "ak": "Akan",
    "am": "Amharique", "an": "Aragonais", "ar": "Arabe", "as": "Assamais", "av": "Avar",
    "ay": "Aymara", "az": "Azéri",
    "ba": "Bachkir", "be": "Biélorusse", "bg": "Bulgare", "bh": "Bihari", "bi": "Bichlamar",
    "bm": "Bambara", "bn": "Bengali", "bo": "Tibétain", "br": "Breton", "bs": "Bosniaque",
    "ca": "Catalan", "ce": "Tchétchène", "ch": "Chamorro", "co": "Corse", "cr": "Cri",
    "cs": "Tchèque", "cu": "Slavon d'église", "cv": "Tchouvache", "cy": "Gallois",
    "da": "Danois", "de": "Allemand", "dv": "Maldivien", "dz": "Dzongkha",
    "ee": "Éwé", "el": "Grec", "en": "Anglais", "eo": "Espéranto", "es": "Espagnol",
    "et": "Estonien", "eu": "Basque",
    "fa": "Persan", "ff": "Peul", "fi": "Finnois", "fj": "Fidjien", "fo": "Féroïen",
    "fr": "Français", "fy": "Frison occidental",
    "ga": "Irlandais", "gd": "Gaélique écossais", "gl": "Galicien", "gn": "Guarani",
    "gu": "Gujarati", "gv": "Mannois",
    "ha": "Haoussa", "he": "Hébreu", "hi": "Hindi", "ho": "Hiri motu", "hr": "Croate",
    "ht": "Créole haïtien", "hu": "Hongrois", "hy": "Arménien", "hz": "Héréro",
    "ia": "Interlingua", "id": "Indonésien", "ie": "Interlingue", "ig": "Igbo",
    "ii": "Yi du Sichuan", "ik": "Inupiak", "io": "Ido", "is": "Islandais", "it": "Italien",
    "iu": "Inuktitut",
    "ja": "Japonais", "jv": "Javanais",
    "ka": "Géorgien", "kg": "Kikongo", "ki": "Kikuyu", "kj": "Kuanyama", "kk": "Kazakh",
    "kl": "Groenlandais", "km": "Khmer", "kn": "Kannada", "ko": "Coréen", "kr": "Kanouri",
    "ks": "Cachemiri", "ku": "Kurde", "kv": "Komi", "kw": "Cornique", "ky": "Kirghize",
    "la": "Latin", "lb": "Luxembourgeois", "lg": "Ganda", "li": "Limbourgeois",
    "ln": "Lingala", "lo": "Lao", "lt": "Lituanien", "lu": "Luba-katanga", "lv": "Letton",
    "mg": "Malgache", "mh": "Marshallais", "mi": "Maori", "mk": "Macédonien",
    "ml": "Malayalam", "mn": "Mongol", "mr": "Marathi", "ms": "Malais", "mt": "Maltais",
    "my": "Birman",
    "na": "Nauruan", "nb": "Norvégien bokmål", "nd": "Ndébélé du Nord", "ne": "Népalais",
    "ng": "Ndonga", "nl": "Néerlandais", "nn": "Norvégien nynorsk", "no": "Norvégien",
    "nr": "Ndébélé du Sud", "nv": "Navajo", "ny": "Chichewa",
    "oc": "Occitan", "oj": "Ojibwé", "om": "Oromo", "or": "Oriya", "os": "Ossète",
    "pa": "Pendjabi", "pi": "Pali", "pl": "Polonais", "ps": "Pachto", "pt": "Portugais",
    "qu": "Quechua",
    "rm": "Romanche", "rn": "Roundi", "ro": "Roumain", "ru": "Russe", "rw": "Kinyarwanda",
    "sa": "Sanskrit", "sc": "Sarde", "sd": "Sindhi", "se": "Same du Nord", "sg": "Sango",
    "si": "Cingalais", "sk": "Slovaque", "sl": "Slovène", "sm": "Samoan", "sn": "Shona",
    "so": "Somali", "sq": "Albanais", "sr": "Serbe", "ss": "Swati", "st": "Sotho du Sud",
    "su": "Soundanais", "sv": "Suédois", "sw": "Swahili",
    "ta": "Tamoul", "te": "Télougou", "tg": "Tadjik", "th": "Thaï", "ti": "Tigrigna",
    "tk": "Turkmène", "tl": "Tagalog", "tn": "Tswana", "to": "Tongien", "tr": "Turc",
    "ts": "Tsonga", "tt": "Tatar", "tw": "Twi", "ty": "Tahitien",
    "ug": "Ouïghour", "uk": "Ukrainien", "ur": "Ourdou", "uz": "Ouzbek",
    "ve": "Venda", "vi": "Vietnamien", "vo": "Volapük",
    "wa": "Wallon", "wo": "Wolof",
    "xh": "Xhosa",
    "yi": "Yiddish", "yo": "Yoruba",
    "za": "Zhuang", "zh": "Chinois", "zu": "Zoulou",
}

_LANGUAGE_TAG_RE = re.compile(r"^([a-zA-Z]{2,3})(-[a-zA-Z0-9]+)*$")


def is_valid_language_code(raw: str) -> bool:
    """Valide un code de langue : forme générale BCP-47 (ex. "fr", "en-US", "pt-BR"), et si le
    sous-tag principal fait deux lettres, vérifie en plus son appartenance à la table ISO 639-1
    (attrape les codes bien formés mais inexistants, ex. "zz")."""
    raw = raw.strip()
    if not raw:
        return False
    match = _LANGUAGE_TAG_RE.fullmatch(raw)
    if not match:
        return False
    primary = match.group(1).lower()
    if len(primary) == 2:
        return primary in ISO_639_1_CODES
    return True
