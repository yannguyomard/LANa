"""Chargement des définitions de jeu (games/*.json)."""
import json
import os

from . import paths, system

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
        _cache[game["id"]] = apply_platform(game)
    return _cache


def apply_platform(game):
    """Une clé « nom_linux » (au premier niveau, dans `install` ou dans `config`) remplace « nom » quand le serveur
    tourne nativement sous Linux ; sinon elle est ignorée. Ex. : config.file_linux pour …/LinuxServer/….
    """
    linux = platform(game) == "linux"
    for section in (game, game.get("install", {}), game.get("config", {})):
        for key in [k for k in section if k.endswith("_linux")]:
            value = section.pop(key)
            if linux:
                section[key[:-len("_linux")]] = value
    return game


def get(game_id):
    games = load_all()
    if game_id not in games:
        raise KeyError("Jeu inconnu : %s" % game_id)
    return games[game_id]


def run_spec(game):
    """Section `run` effective sur ce système : un jeu peut fournir une variante native pour Linux (`run.linux`)
    ou pour Windows (`run.windows`), qui remplace alors les clés de base."""
    run = dict(game["run"])
    override = run.pop("linux", None) if system.IS_LINUX else run.pop("windows", None) if system.IS_WINDOWS else None
    run.pop("linux", None)
    run.pop("windows", None)
    if override:
        run.update(override)
    return run


def platform(game):
    """Plateforme des fichiers serveur à installer : "linux" si le jeu tourne nativement sous Linux ici, sinon "windows"
    (les jeux Windows tournent sous Wine sur macOS et Linux)."""
    return "linux" if system.IS_LINUX and run_spec(game)["runtime"] != "wine" else "windows"


def download_keys(game):
    """Clés à essayer, dans l'ordre, pour choisir le fichier à télécharger (`source.urls` ou `source.assets`) :
    variante ARM d'abord sur processeur ARM, version macOS pour un serveur natif sur Mac, puis la plateforme."""
    plat = platform(game)
    native_mac = system.IS_MAC and run_spec(game)["runtime"] != "wine"
    base = "mac" if native_mac else plat
    keys = [base + "-arm64"] if system.IS_ARM and base != "windows" else []
    return keys + [base] + ([plat] if base != plat else [])


def cpu_compat(game):
    """Incompatibilité due au processeur (serveur x86 sur Linux ARM), au format de `compat`, ou None.

    Sur un téléphone ou un Raspberry Pi tournent les serveurs Java et ceux qui déclarent `arm` :
    "native" (programme de la machine, ex. paquet Termux) ou "glibc" (binaire Linux ARM64 ; sous Android,
    il tourne dans un Debian installé par proot-distro).
    """
    if system.X86_ONLY_BLOCKED and run_spec(game).get("runtime") != "java" and not game.get("arm"):
        return {"level": "bad", "note": "Serveur prévu pour les processeurs x86 (PC, Mac Intel) : il ne se lance pas sur ce "
                                        "processeur ARM (téléphone, Raspberry Pi)."}
    return None


def uses_proot(game):
    """Sous Android, un binaire Linux glibc ne tourne que dans un Debian proot-distro."""
    return system.IS_ANDROID and game.get("arm") == "glibc"


def needs(game):
    """Outils externes requis par le jeu (wine, java…)."""
    run = run_spec(game)
    runtime = run.get("runtime")
    if runtime == "java" or system.uses_wine(runtime):
        return [runtime]
    out = [run["tool"]] if runtime == "tool" else []
    if uses_proot(game):
        out.append("proot-distro")
    return out
