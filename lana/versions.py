"""Versions installables d'un jeu, quand on peut en choisir une : versions de Minecraft, branches Steam, versions GitHub.

Chaque option : {"id", "label", "date"} (date en secondes, ou None). La première de la liste est la plus récente.
Les branches Steam viennent de api.steamcmd.net, miroir public des informations de SteamCMD : interroger SteamCMD
lui-même demanderait de lancer Wine pendant une minute à chaque ouverture de la liste.
"""
import calendar
import re
import threading
import time

from . import runtime

STEAM_INFO = "https://api.steamcmd.net/v1/info/%s"
GITHUB_RELEASES = "https://api.github.com/repos/%s/releases?per_page=30"
LATEST_STEAM = "public"
CACHE_SECONDS = 600
OLDEST_MINECRAFT = "1.2.5"   # Mojang ne publie pas de serveur pour les versions plus anciennes
VERSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")   # passe tel quel à SteamCMD : jamais de « + » ni d'espace

_cache = {}
_lock = threading.Lock()


class VersionError(Exception):
    pass


def kind(game):
    """Source des versions de ce jeu, ou None s'il n'y a qu'une version possible (lien fixe, archive fournie…)."""
    spec = game["install"]
    if spec["type"] == "steamcmd":
        return "steam"
    if spec["type"] == "mojang":
        return "minecraft"
    if spec["type"] == "download" and spec["source"]["kind"] == "github":
        return "github"
    return None


def _iso(stamp):
    try:
        return calendar.timegm(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):
        return None


def parse_minecraft(manifest):
    out = []
    for v in manifest["versions"]:
        if v["type"] == "release":
            out.append({"id": v["id"], "label": v["id"], "date": _iso(v.get("releaseTime"))})
        if v["id"] == OLDEST_MINECRAFT:
            break
    return out


def parse_steam(info, appid):
    branches = info["data"][str(appid)].get("depots", {}).get("branches", {})
    out = []
    for name, b in branches.items():
        if str(b.get("pwdrequired", "0")) == "1" or not VERSION_ID.match(name):   # branches à mot de passe : hors de portée
            continue
        desc = " ".join((b.get("description") or "").split())
        if name == LATEST_STEAM:
            label = "Dernière version (branche publique)"
        else:
            label = "%s — %s" % (name, desc) if desc and desc.lower() != name.lower() else name
        out.append({"id": name, "label": label, "date": int(b["timeupdated"]) if b.get("timeupdated") else None})
    out.sort(key=lambda o: (o["id"] != LATEST_STEAM, -(o["date"] or 0)))
    return out


def parse_github(releases):
    out = []
    for r in releases:
        if r.get("draft") or not VERSION_ID.match(r.get("tag_name", "")):
            continue
        label = r["tag_name"] + (" (préversion)" if r.get("prerelease") else "")
        out.append({"id": r["tag_name"], "label": label, "date": _iso(r.get("published_at"))})
    return out


def _fetch(game):
    k, spec = kind(game), game["install"]
    if k == "minecraft":
        return parse_minecraft(runtime.fetch_json(runtime.MOJANG_MANIFEST))
    if k == "steam":
        return parse_steam(runtime.fetch_json(STEAM_INFO % spec["appid"]), spec["appid"])
    if k == "github":
        return parse_github(runtime.fetch_json(GITHUB_RELEASES % spec["source"]["repo"]))
    return []


def available(game):
    """Options de version (liste vide si le jeu n'en propose qu'une). Gardées 10 minutes en mémoire."""
    if not kind(game):
        return []
    with _lock:
        hit = _cache.get(game["id"])
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    try:
        found = _fetch(game)
    except Exception as ex:  # noqa: BLE001 - réseau, JSON inattendu : l'interface affiche le message
        raise VersionError("Liste des versions indisponible pour l'instant (%s)" % ex)
    with _lock:
        _cache[game["id"]] = (time.time(), found)
    return found


def check(game, version):
    """Valide une version demandée par l'interface ; retourne l'identifiant à installer."""
    if not kind(game):
        raise VersionError("Ce jeu ne propose qu'une version")
    version = str(version)
    if not VERSION_ID.match(version):
        raise VersionError("Version invalide : %s" % version)
    return version
