import os

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(PKG_DIR)
GAMES_DIR = os.path.join(ROOT, "games")
WEB_DIR = os.path.join(ROOT, "web")

# Données de l'utilisateur (serveurs installés, outils, accès). LANA_HOME permet de la déplacer.
HOME = os.environ.get("LANA_HOME") or os.path.expanduser("~/LANa")
INSTANCES_DIR = os.path.join(HOME, "instances")
TOOLS_DIR = os.path.join(HOME, "tools")
AUTH_FILE = os.path.join(HOME, "auth.json")

from . import system

TOOL_DIRS = system.tool_dirs()
