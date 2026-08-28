"""Compile Epubeur en exécutable Windows (mode onedir) via PyInstaller et epubeur.spec.

Usage : python build_exe.py
Résultat : dist/Epubeur/Epubeur.exe
"""

import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
SPEC_FILE = PROJECT_ROOT / "epubeur.spec"


def main() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller n'est pas installé. Installe-le avec : pip install pyinstaller")
        sys.exit(1)

    for stale_dir in ("build", "dist"):
        path = PROJECT_ROOT / stale_dir
        if path.exists():
            shutil.rmtree(path)

    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(SPEC_FILE), "--noconfirm"],
        cwd=PROJECT_ROOT,
    )
    if result.returncode != 0:
        sys.exit(result.returncode)

    exe_path = PROJECT_ROOT / "dist" / "Epubeur" / "Epubeur.exe"
    if exe_path.exists():
        print(f"\nCompilation réussie : {exe_path}")
    else:
        print("\nLa compilation s'est terminée sans erreur mais l'exécutable est introuvable.")
        sys.exit(1)


if __name__ == "__main__":
    main()
