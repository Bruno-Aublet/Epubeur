"""Lance la suite de tests automatisés du projet (pytest).

Usage : python run_tests.py
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent


def main() -> None:
    try:
        import pytest  # noqa: F401
    except ImportError:
        print("pytest n'est pas installé. Installe-le avec : pip install pytest")
        sys.exit(1)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short", "-ra"],
        cwd=PROJECT_ROOT,
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
