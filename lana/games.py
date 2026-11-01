"""Chargement des définitions de jeu (games/*.json)."""
import json
import os

from . import paths

REQUIRED = ("id", "name", "install", "run", "requirements", "fields")
_cache = {}


def load_all():
    if _cache:
        return _cache
    for fname in sorted(os.listdir(paths.GAMES_DIR)):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(paths.GAMES_DIR, fname), encoding="utf-8") as fh:
            game = json.load(fh)
        missing = [k for k in REQUIRED if k not in game]
        if missing:
            raise ValueError("%s : champs manquants %s" % (fname, ", ".join(missing)))
        _cache[game["id"]] = game
    return _cache


def get(game_id):
    games = load_all()
    if game_id not in games:
        raise KeyError("Jeu inconnu : %s" % game_id)
    return games[game_id]


def needs(game):
    """Outils externes requis par le jeu (wine, java…)."""
    runtime = game["run"].get("runtime")
    return [runtime] if runtime in ("wine", "java") else []
