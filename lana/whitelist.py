"""Liste blanche des joueurs (Minecraft Java) : qui peut entrer sur le serveur.

Déclarée par le jeu dans `whitelist` : fichier (whitelist.json), réglages qui l'activent (white-list, enforce-whitelist)
et commandes de console. Serveur arrêté, LANa modifie le fichier ; serveur en marche, il passe par la console
(« whitelist add … »), pour que le serveur tienne lui-même sa liste à jour sans redémarrage.
"""
import hashlib
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import uuid

from . import config, runtime

MOJANG_PROFILE = "https://api.mojang.com/users/profiles/minecraft/%s"
NAME_RE = re.compile(r"^\w{3,16}$")

_lock = threading.Lock()


class WhitelistError(Exception):
    """Erreur destinée à être affichée telle quelle à l'utilisateur."""


def spec(game):
    return game.get("whitelist")


def _need(inst):
    found = spec(inst.game)
    if not found:
        raise WhitelistError("Ce jeu n'a pas de liste blanche gérée par LANa")
    return found


def _path(inst):
    return os.path.join(inst.server_dir, _need(inst)["file"])


def _read(inst):
    try:
        with open(_path(inst), encoding="utf-8") as fh:
            data = json.load(fh)
        return [e for e in data if isinstance(e, dict) and e.get("name")]
    except (OSError, ValueError):
        return []


def _write(inst, entries):
    path = _path(inst)
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2)
    os.replace(path + ".tmp", path)


def _true(value):
    """Valeur d'un réglage oui/non, qu'il soit déjà converti (champ connu) ou brut (« true » dans le fichier)."""
    return value is True or str(value).strip().lower() == "true"


def _settings(inst):
    return config.read_file(inst.game, inst.server_dir)


def offline_uuid(name):
    """UUID d'un joueur sur un serveur hors ligne (online-mode=false), calculé comme le fait Minecraft."""
    digest = bytearray(hashlib.md5(("OfflinePlayer:" + name).encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30   # version 3
    digest[8] = (digest[8] & 0x3F) | 0x80   # variante RFC 4122
    return str(uuid.UUID(bytes=bytes(digest)))


def mojang_profile(name):
    """(nom exact, UUID) d'un compte Minecraft, d'après Mojang ; WhitelistError si le compte n'existe pas."""
    try:
        data = runtime.fetch_json(MOJANG_PROFILE % urllib.parse.quote(name))
    except urllib.error.HTTPError as ex:
        if ex.code in (204, 404):
            raise WhitelistError("Aucun compte Minecraft ne s'appelle « %s »" % name)
        raise WhitelistError("Mojang ne répond pas (%s), réessayez plus tard" % ex.code)
    except (OSError, ValueError):
        raise WhitelistError("Mojang ne répond pas, réessayez plus tard")
    if not data or "id" not in data:
        raise WhitelistError("Aucun compte Minecraft ne s'appelle « %s »" % name)
    return data["name"], str(uuid.UUID(data["id"]))


def _console(inst, key, **values):
    """Envoie une commande au serveur en marche ; False s'il ne tourne pas ou n'a pas de console (lancé avant LANa 0.1)."""
    command = _need(inst).get("console", {}).get(key)
    if not command or not inst.running():
        return False
    return runtime.send_console(inst.log_path, [command.format(**values)])


def known_players(inst):
    """Joueurs déjà vus par le serveur (usercache.json), pour proposer leurs noms."""
    try:
        with open(os.path.join(inst.server_dir, "usercache.json"), encoding="utf-8") as fh:
            return sorted({e["name"] for e in json.load(fh) if isinstance(e, dict) and e.get("name")}, key=str.lower)
    except (OSError, ValueError):
        return []


def state(inst):
    s = _need(inst)
    values = _settings(inst)
    entries = _read(inst)
    listed = {e["name"].lower() for e in entries}
    return {"enabled": _true(values.get(s["toggle"])), "online_mode": _true(values.get("online-mode", True)),
            "entries": sorted(({"name": e["name"], "uuid": e.get("uuid", "")} for e in entries), key=lambda e: e["name"].lower()),
            "suggestions": [n for n in known_players(inst) if n.lower() not in listed], "running": inst.running(),
            "path": _path(inst)}


def add(inst, name):
    name = str(name or "").strip()
    if not NAME_RE.match(name):
        raise WhitelistError("Pseudo invalide : 3 à 16 lettres, chiffres ou _")
    with _lock:
        entries = _read(inst)
        if any(e["name"].lower() == name.lower() for e in entries):
            raise WhitelistError("%s est déjà dans la liste" % name)
        if not _true(_settings(inst).get("online-mode", True)):
            exact, player_id = name, offline_uuid(name)
        else:
            exact, player_id = mojang_profile(name)
        if _console(inst, "add", name=exact):
            # Le serveur ajoute le joueur et réécrit lui-même le fichier.
            return "%s ajouté à la liste blanche (appliqué tout de suite)" % exact
        entries.append({"uuid": player_id, "name": exact})
        _write(inst, entries)
    note = " Redémarrez le serveur pour l'appliquer." if inst.running() else ""
    return "%s ajouté à la liste blanche.%s" % (exact, note)


def remove(inst, name):
    with _lock:
        entries = _read(inst)
        kept = [e for e in entries if e["name"].lower() != str(name).lower()]
        if len(kept) == len(entries):
            raise WhitelistError("%s n'est pas dans la liste" % name)
        if _console(inst, "remove", name=name):
            return "%s retiré de la liste blanche (appliqué tout de suite)" % name
        _write(inst, kept)
    note = " Redémarrez le serveur pour l'appliquer." if inst.running() else ""
    return "%s retiré de la liste blanche.%s" % (name, note)


def set_enabled(inst, enabled):
    """Active ou coupe la liste blanche ; `enforce` exclut aussi les joueurs déjà connectés qui n'y sont pas."""
    s = _need(inst)
    with _lock:
        values = _settings(inst)
        values[s["toggle"]] = bool(enabled)
        if s.get("enforce"):
            values[s["enforce"]] = bool(enabled)
        config.write_file(inst.game, inst.server_dir, values)
        live = _console(inst, "on" if enabled else "off")
    if enabled and not _read(inst):
        tail = " La liste est vide : personne ne pourra entrer tant que vous n'y ajoutez pas de joueurs."
    else:
        tail = ""
    when = " (appliqué tout de suite)." if live else "." + (" Redémarrez le serveur pour l'appliquer." if inst.running() else "")
    return "Liste blanche %s%s%s" % ("activée" if enabled else "désactivée", when, tail)
