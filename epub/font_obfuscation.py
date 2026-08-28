import hashlib
import zipfile
from pathlib import Path
from xml.etree import ElementTree

IDPF_ALGORITHM_URI = "http://www.idpf.org/2008/embedding"
OBFUSCATION_LENGTH = 1040


def _obfuscation_key(book_uid: str) -> bytes:
    cleaned = book_uid.replace(" ", "").replace("-", "").replace("urn:uuid:", "")
    return hashlib.sha1(cleaned.encode("utf-8")).digest()


def obfuscate_font(font_bytes: bytes, book_uid: str) -> bytes:
    """Algorithme d'obfuscation IDPF : XOR des OBFUSCATION_LENGTH premiers octets avec
    la clé SHA-1 (20 octets) dérivée du book_uid, répétée en boucle. Reste inchangé."""
    key = _obfuscation_key(book_uid)
    key_len = len(key)

    head = font_bytes[:OBFUSCATION_LENGTH]
    tail = font_bytes[OBFUSCATION_LENGTH:]

    obfuscated_head = bytes(byte ^ key[i % key_len] for i, byte in enumerate(head))
    return obfuscated_head + tail


def deobfuscate_font(obfuscated_bytes: bytes, book_uid: str) -> bytes:
    """L'opération XOR est involutive : même fonction que obfuscate_font."""
    return obfuscate_font(obfuscated_bytes, book_uid)


def build_encryption_xml(font_item_hrefs: list[str]) -> str:
    entries = "\n".join(
        f'''  <enc:EncryptedData>
    <enc:EncryptionMethod Algorithm="{IDPF_ALGORITHM_URI}"/>
    <enc:CipherData>
      <enc:CipherReference URI="{href}"/>
    </enc:CipherData>
  </enc:EncryptedData>'''
        for href in font_item_hrefs
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:enc="http://www.w3.org/2001/04/xmlenc#">
{entries}
</encryption>"""


def parse_encryption_xml(encryption_xml: str) -> list[str]:
    """Extrait les URI (chemins dans le zip) des ressources obfusquées IDPF déclarées
    dans META-INF/encryption.xml. Ignore les entrées utilisant un autre algorithme."""
    ns = {"enc": "http://www.w3.org/2001/04/xmlenc#"}
    root = ElementTree.fromstring(encryption_xml)
    hrefs = []
    for entry in root.findall("enc:EncryptedData", ns):
        method = entry.find("enc:EncryptionMethod", ns)
        if method is None or method.get("Algorithm") != IDPF_ALGORITHM_URI:
            continue
        cipher_ref = entry.find("enc:CipherData/enc:CipherReference", ns)
        if cipher_ref is not None and cipher_ref.get("URI"):
            hrefs.append(cipher_ref.get("URI"))
    return hrefs


def deobfuscate_extracted_epub(extract_dir: Path, book_uid: str) -> None:
    """Après extraction d'un .epub sur disque (ex: pour un aperçu), désobfusque sur place
    les polices marquées dans META-INF/encryption.xml — nécessaire car un visualiseur HTML
    générique (pas un vrai lecteur EPUB) ne sait pas le faire lui-même à la volée."""
    extract_dir = Path(extract_dir)
    encryption_path = extract_dir / "META-INF" / "encryption.xml"
    if not encryption_path.exists():
        return

    hrefs = parse_encryption_xml(encryption_path.read_text(encoding="utf-8"))
    for href in hrefs:
        font_path = extract_dir / href
        if not font_path.exists():
            continue
        obfuscated = font_path.read_bytes()
        font_path.write_bytes(deobfuscate_font(obfuscated, book_uid))


def postprocess_epub_zip(epub_path: Path, fonts: list[tuple[bytes, str]], book_uid: str) -> None:
    """Rouvre le zip EPUB écrit par ebooklib pour y remplacer chaque police par sa version
    obfusquée IDPF et injecter META-INF/encryption.xml (non géré nativement par ebooklib).
    fonts : liste de (font_bytes, font_href_dans_le_zip), une entrée par police à obfusquer."""
    epub_path = Path(epub_path)
    obfuscated_by_href = {href: obfuscate_font(data, book_uid) for data, href in fonts}
    encryption_xml = build_encryption_xml([href for _, href in fonts])

    with zipfile.ZipFile(epub_path, "r") as zin:
        entries = {item.filename: zin.read(item.filename) for item in zin.infolist()}

    entries.update(obfuscated_by_href)
    entries["META-INF/encryption.xml"] = encryption_xml.encode("utf-8")

    with zipfile.ZipFile(epub_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in entries.items():
            if name == "mimetype":
                zout.writestr(name, data, compress_type=zipfile.ZIP_STORED)
            else:
                zout.writestr(name, data)
