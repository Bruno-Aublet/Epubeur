import sys

from model.file_association import ensure_epbz_association


class _FakeWinreg:
    """Simule winreg : stocke les clés/valeurs en mémoire, permet de vérifier le nombre
    d'écritures et de forcer des OSError pour tester la robustesse."""

    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1

    def __init__(self, raise_on_write: bool = False, raise_on_read: bool = False):
        self.values: dict[str, str] = {}
        self.set_value_calls = 0
        self.raise_on_write = raise_on_write
        self.raise_on_read = raise_on_read

    def OpenKey(self, hive, key_path):
        if self.raise_on_read or key_path not in self.values:
            raise OSError("clé introuvable")
        return _FakeKeyContext(self, key_path)

    def CreateKey(self, hive, key_path):
        return _FakeKeyContext(self, key_path)

    def QueryValueEx(self, key_handle, name):
        return (self.values[key_handle.key_path], self.REG_SZ)

    def SetValueEx(self, key_handle, name, reserved, value_type, value):
        if self.raise_on_write:
            raise OSError("écriture refusée")
        self.set_value_calls += 1
        self.values[key_handle.key_path] = value


class _FakeKeyContext:
    def __init__(self, fake_winreg: _FakeWinreg, key_path: str):
        self.fake_winreg = fake_winreg
        self.key_path = key_path

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _make_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", r"C:\Epubeur\Epubeur.exe")
    monkeypatch.setattr(sys, "_MEIPASS", r"C:\Epubeur\_internal", raising=False)


def test_dev_mode_never_touches_registry(monkeypatch):
    """sys.frozen absent (lancement `python main.py`) : aucun appel winreg, jamais — vérifié en
    remplaçant l'import lui-même par une fonction qui échoue si jamais invoquée."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")

    import builtins
    real_import = builtins.__import__

    def fail_if_winreg_imported(name, *args, **kwargs):
        if name == "winreg":
            raise AssertionError("winreg ne doit jamais être importé en mode développement")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_if_winreg_imported)

    ensure_epbz_association()  # ne doit pas lever, ni tenter d'importer winreg


def test_non_windows_platform_never_touches_registry(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    ensure_epbz_association()  # ne doit pas lever, même si winreg n'existe pas sur cette plateforme


def test_writes_registry_when_frozen_on_windows(monkeypatch):
    _make_frozen(monkeypatch)
    fake = _FakeWinreg()

    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "winreg":
            return fake
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    ensure_epbz_association()

    assert fake.set_value_calls == 3  # progid + icône + extension mapping
    assert fake.values[r"Software\Classes\.epbz"] == "Epubeur.Project"
    assert fake.values[r"Software\Classes\Epubeur.Project\shell\open\command"] == r'"C:\Epubeur\Epubeur.exe" "%1"'
    assert fake.values[r"Software\Classes\Epubeur.Project\DefaultIcon"] == r"C:\Epubeur\_internal\Icons\Epubeur.ico"


def test_idempotent_second_call_writes_nothing(monkeypatch):
    _make_frozen(monkeypatch)
    fake = _FakeWinreg()

    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "winreg":
            return fake
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    ensure_epbz_association()
    first_call_count = fake.set_value_calls
    ensure_epbz_association()

    assert fake.set_value_calls == first_call_count  # rien de réécrit, la valeur était déjà bonne


def test_registry_write_failure_never_raises(monkeypatch):
    _make_frozen(monkeypatch)
    fake = _FakeWinreg(raise_on_write=True)

    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "winreg":
            return fake
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    ensure_epbz_association()  # ne doit lever aucune exception malgré l'échec d'écriture simulé
