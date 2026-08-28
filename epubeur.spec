# -*- mode: python ; coding: utf-8 -*-
# Build en mode "onedir" (un dossier contenant l'exe + ses dépendances, pas un exe unique) :
# démarrage plus rapide qu'en onefile, et plus facile à déboguer (fichiers visibles).

from pathlib import Path

import PySide6

block_cipher = None

# qtbase_fr.qm traduit les boutons standards (Oui/Non/Annuler/OK) et menus contextuels natifs
# (Copier/Coller...) en français (voir main.py) — PyInstaller n'embarque pas automatiquement le
# dossier translations/ de PySide6, il faut le déclarer explicitement, au même chemin relatif
# que dans l'installation (PySide6/translations/) pour que QLibraryInfo.path(...) continue de
# le trouver une fois compilé.
qtbase_fr_source = str(Path(PySide6.__file__).parent / "translations" / "qtbase_fr.qm")

# LICENSE doit être présent à côté de l'exe compilé (mode onedir) pour que la boîte
# "À propos d'Epubeur" (ui/about_dialog.py::_license_path) puisse afficher son texte complet,
# pas seulement en développement.
# __file__ n'existe pas dans ce contexte (PyInstaller exécute le .spec via exec()) : on utilise
# SPECPATH, injecté automatiquement par PyInstaller dans le namespace du spec.
license_source = str(Path(SPECPATH) / "LICENSE")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[(qtbase_fr_source, "PySide6/translations"), (license_source, ".")],
    # winreg n'est importé qu'à l'intérieur d'une fonction (model/file_association.py), pas en
    # tête de module — l'analyseur statique de PyInstaller le détecte normalement quand même,
    # mais on le déclare explicitement ici pour ne courir aucun risque : sans lui, l'association
    # de fichier .epbz échouerait silencieusement sur le build compilé (rattrapé par le try/except
    # de ensure_epbz_association, donc pas de plantage, mais l'association ne se ferait jamais).
    hiddenimports=["winreg"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Epubeur",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version="version_info.txt",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Epubeur",
)
