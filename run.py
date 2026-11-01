#!/usr/bin/env python3
"""Lanceur de LANa : fonctionne depuis n'importe quel dossier (python3 /chemin/vers/run.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lana.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
