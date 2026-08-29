import sys
from pathlib import Path


def ensure_epbz_association() -> None:
    """Enregistre Epubeur comme gestionnaire de l'extension .epbz dans le registre Windows
    (HKEY_CURRENT_USER, aucun droit administrateur requis), automatiquement à chaque lancement —
    silencieux, jamais de question posée à l'utilisateur. N'agit que sur un build PyInstaller
    "onedir" figé (sys.frozen), jamais en développement (python main.py) où sys.executable
    pointerait vers l'interpréteur Python nu plutôt que vers Epubeur.exe. Idempotent : compare la
    valeur déjà en registre à la valeur voulue avant d'écrire — si le dossier de l'application a
    été déplacé, sys.executable diffère de ce qui était enregistré, donc réécrit silencieusement.
    Toute erreur d'écriture registre (environnement restreint, ruche corrompue...) est absorbée :
    ne doit jamais empêcher le lancement normal de l'application."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    import winreg

    exe_path = sys.executable
    icon_path = str(Path(exe_path).parent / "Icons" / "Epubeur.ico")
    try:
        _ensure_progid(winreg, exe_path)
        _ensure_icon(winreg, icon_path)
        _ensure_extension_mapping(winreg)
    except OSError:
        pass


def _current_default_value(winreg, key_path: str) -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            return winreg.QueryValueEx(key, "")[0]
    except OSError:
        return None


def _ensure_progid(winreg, exe_path: str) -> None:
    command_key = r"Software\Classes\Epubeur.Project\shell\open\command"
    command = f'"{exe_path}" "%1"'
    if _current_default_value(winreg, command_key) == command:
        return
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, command_key) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)


def _ensure_icon(winreg, icon_path: str) -> None:
    icon_key = r"Software\Classes\Epubeur.Project\DefaultIcon"
    if _current_default_value(winreg, icon_key) == icon_path:
        return
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, icon_key) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, icon_path)


def _ensure_extension_mapping(winreg) -> None:
    ext_key = r"Software\Classes\.epbz"
    if _current_default_value(winreg, ext_key) == "Epubeur.Project":
        return
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, ext_key) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Epubeur.Project")
