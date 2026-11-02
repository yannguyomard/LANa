"""Suivi des joueurs : connexions lues dans le journal du serveur, historique et statistiques.

Un jeu déclare dans sa définition (`players`) deux expressions régulières, `join` et `leave`, avec les groupes
nommés `name` (obligatoire), `id`, `time` (HH:MM:SS) et `date` (AAAA-MM-JJ) s'ils existent. LANa lit le journal
au fil de l'eau, retient chaque session et calcule les statistiques ; `players.json` garde l'historique.
Pour Minecraft, les fichiers de statistiques du monde ajoutent des chiffres de jeu (morts, distance…).
"""
import hashlib
import json
import os
import re
import threading
import time

MAX_EVENTS = 100
MAX_READ = 4 << 20          # on lit le journal par blocs de 4 Mo au plus
STALE_LOG_SECONDS = 86400   # un journal plus vieux qu'un jour n'est pas rejoué à la première lecture
POLL_SECONDS = 10

_lock = threading.RLock()
_compiled = {}


# ---------- lecture du journal ----------

def _patterns(game):
    spec = game["players"]
    if game["id"] not in _compiled:
        _compiled[game["id"]] = (re.compile(spec["join"]), re.compile(spec["leave"]))
    return _compiled[game["id"]]


def resolve_time(groups, now):
    """Horodatage d'une ligne : date + heure si le journal les donne, sinon l'heure du jour la plus récente."""
    clock = groups.get("time")
    if not clock:
        return now
    try:
        hh, mm, ss = (int(x) for x in clock.split(":")[:3])
        if groups.get("date"):
            y, m, d = (int(x) for x in groups["date"].split("-"))
            return time.mktime((y, m, d, hh, mm, ss, 0, 0, -1))
        today = time.localtime(now)
        stamp = time.mktime((today.tm_year, today.tm_mon, today.tm_mday, hh, mm, ss, 0, 0, -1))
    except (ValueError, OverflowError):
        return now
    return stamp - 86400 if stamp > now + 120 else stamp   # une heure « dans le futur » date d'hier


def parse_line(game, line, now):
    """(kind, name, id, timestamp) pour une ligne de connexion ou de départ, sinon None."""
    join, leave = _patterns(game)
    for kind, pattern in (("join", join), ("leave", leave)):
        match = pattern.search(line)
        if match:
            groups = match.groupdict()
            name = (groups.get("name") or "").strip()
            if name:
                return kind, name, (groups.get("id") or "").strip(), resolve_time(groups, now)
    return None


# ---------- état ----------

def _store_path(inst):
    return os.path.join(inst.dir, "players.json")


def _load(inst):
    try:
        with open(_store_path(inst), encoding="utf-8") as fh:
            state = json.load(fh)
        if isinstance(state, dict) and isinstance(state.get("players"), dict):
            return state
    except (OSError, ValueError):
        pass
    return {"offset": None, "head": "", "log": "", "players": {}, "events": [], "peak": {"count": 0, "at": None}}


def _save(inst, state):
    tmp = _store_path(inst) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    os.replace(tmp, _store_path(inst))


def _online(state):
    return [p for p in state["players"].values() if p.get("online_since")]


def _event(state, kind, player, stamp):
    state["events"].append({"t": stamp, "kind": kind, "name": player["name"]})
    del state["events"][:-MAX_EVENTS]


def apply_event(state, kind, name, pid, stamp):
    key = pid or name.lower()
    player = state["players"].get(key)
    if player is None:
        player = state["players"][key] = {"name": name, "id": pid, "first_seen": None, "last_seen": None,
                                         "sessions": 0, "seconds": 0, "longest": 0, "online_since": None}
    if kind == "join":
        if player.get("online_since"):
            return   # déjà en ligne : ligne rejouée ou doublon
        player.update(name=name, online_since=stamp, last_seen=stamp)
        player["first_seen"] = player["first_seen"] or stamp
        player["sessions"] += 1
        _event(state, "join", player, stamp)
        count = len(_online(state))
        if count > state["peak"]["count"]:
            state["peak"] = {"count": count, "at": stamp}
    else:
        close_session(state, player, stamp, "leave")


def close_session(state, player, stamp, kind="leave"):
    start = player.get("online_since")
    if not start:
        return
    length = max(0, stamp - start)
    player["seconds"] += length
    player["longest"] = max(player["longest"], length)
    player["online_since"] = None
    player["last_seen"] = max(stamp, start)
    _event(state, kind, player, player["last_seen"])


def log_path(inst):
    """Journal où chercher les connexions (même choix que l'affichage du journal)."""
    own = inst.game.get("log_file")
    path = os.path.join(inst.server_dir, own) if own else None
    return path if path and os.path.exists(path) else inst.log_path


def supported(game):
    return bool(game.get("players"))


def update(inst):
    """Lit les nouvelles lignes du journal et met l'historique à jour ; retourne l'état."""
    game = inst.game
    if not supported(game) or not inst.meta().get("installed"):
        return None
    with _lock:
        state = _load(inst)
        now = time.time()
        path = log_path(inst)
        mtime = now
        if os.path.exists(path):
            size, mtime = os.path.getsize(path), os.path.getmtime(path)
            with open(path, "rb") as fh:
                head = hashlib.md5(fh.read(256)).hexdigest()
                offset = state["offset"]
                if offset is None:   # première lecture : rejouer le journal seulement s'il est récent
                    offset = 0 if now - mtime < STALE_LOG_SECONDS else size
                elif state["log"] != path or state["head"] != head or size < offset:
                    offset = 0       # journal recréé ou remplacé : on repart du début
                fh.seek(offset)
                chunk = fh.read(MAX_READ)
            end = chunk.rfind(b"\n") + 1   # jamais de ligne coupée
            for raw in chunk[:end].decode("utf-8", "replace").splitlines():
                found = parse_line(game, raw, now)
                if found:
                    apply_event(state, found[0], found[1], found[2], found[3])
            state.update(offset=offset + end, head=head, log=path)
        if not inst.running():   # serveur arrêté : plus personne n'est connecté
            for player in _online(state):
                close_session(state, player, min(now, mtime), "stop")
        _save(inst, state)
        return state


# ---------- statistiques ----------

def summarize(state, now=None):
    now = now or time.time()
    players = []
    for player in state["players"].values():
        live = max(0, now - player["online_since"]) if player.get("online_since") else 0
        players.append({"name": player["name"], "id": player.get("id", ""), "online": bool(player.get("online_since")),
                        "online_since": player.get("online_since"), "first_seen": player["first_seen"],
                        "last_seen": player["last_seen"], "sessions": player["sessions"],
                        "seconds": player["seconds"] + live, "longest": max(player["longest"], live)})
    total_sessions = sum(p["sessions"] for p in players)
    total_seconds = sum(p["seconds"] for p in players)
    best = max(players, key=lambda p: p["longest"], default=None)
    return {"players": players, "events": list(reversed(state["events"]))[:30],
            "totals": {"unique": len(players), "online": sum(1 for p in players if p["online"]),
                       "seconds": total_seconds, "sessions": total_sessions,
                       "average_session": total_seconds / total_sessions if total_sessions else 0,
                       "peak": state["peak"]["count"], "peak_at": state["peak"]["at"],
                       "longest_session": {"name": best["name"], "seconds": best["longest"]} if best and best["longest"] else None}}


# Statistiques Minecraft : (clé, libellé, unité, calcul à partir du fichier de statistiques du joueur)
def _custom(stats):
    return stats.get("minecraft:custom", {})


MINECRAFT_STATS = [
    ("playtime", "Temps de jeu (monde)", "s", lambda s: (_custom(s).get("minecraft:play_time", _custom(s).get("minecraft:play_one_minute", 0))) / 20),
    ("deaths", "Morts", "n", lambda s: _custom(s).get("minecraft:deaths", 0)),
    ("mob_kills", "Monstres tués", "n", lambda s: _custom(s).get("minecraft:mob_kills", 0)),
    ("player_kills", "Joueurs tués", "n", lambda s: _custom(s).get("minecraft:player_kills", 0)),
    ("distance", "Distance parcourue", "km", lambda s: sum(v for k, v in _custom(s).items() if k.endswith("_one_cm")) / 100000),
    ("mined", "Blocs minés", "n", lambda s: sum(s.get("minecraft:mined", {}).values())),
    ("jumps", "Sauts", "n", lambda s: _custom(s).get("minecraft:jump", 0)),
]
MINECRAFT_LEADERS = [("playtime", "Plus gros joueur"), ("deaths", "Le plus de morts"), ("distance", "Plus grand explorateur"),
                     ("mined", "Plus gros mineur"), ("mob_kills", "Chasseur de monstres")]


def _json_file(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def minecraft_stats(inst):
    """Statistiques par joueur lues dans le monde : {nom en minuscules: {nom, uuid, stats, advancements}}."""
    world = os.path.join(inst.server_dir, inst.game["savegame"])
    names = {}
    cache = _json_file(os.path.join(inst.server_dir, "usercache.json"))
    for entry in cache if isinstance(cache, list) else []:
        if isinstance(entry, dict) and entry.get("uuid") and entry.get("name"):
            names[entry["uuid"].lower()] = entry["name"]
    out = {}
    folder = os.path.join(world, "stats")
    for fname in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not fname.endswith(".json"):
            continue
        uuid = fname[:-5].lower()
        data = _json_file(os.path.join(folder, fname))
        if not isinstance(data, dict) or uuid not in names:
            continue   # sans nom connu on ne sait pas de qui il s'agit
        raw = data.get("stats", {})
        values = {key: calc(raw) for key, _label, _unit, calc in MINECRAFT_STATS}
        adv = _json_file(os.path.join(world, "advancements", fname))
        if isinstance(adv, dict):
            values["advancements"] = sum(1 for k, v in adv.items() if isinstance(v, dict) and v.get("done")
                                         and not k.startswith("minecraft:recipes/"))
        out[names[uuid].lower()] = {"name": names[uuid], "uuid": uuid, "stats": values}
    return out


def minecraft_extras(inst, summary):
    """Ajoute aux joueurs leurs statistiques de jeu, et ceux du monde jamais vus par LANa ; calcule les records."""
    found = minecraft_stats(inst)
    by_name = {p["name"].lower(): p for p in summary["players"]}
    for low, info in found.items():
        player = by_name.get(low)
        if player is None:   # joueur passé avant LANa (monde importé, serveur déjà ancien)
            player = {"name": info["name"], "id": info["uuid"], "online": False, "online_since": None, "first_seen": None,
                      "last_seen": None, "sessions": 0, "seconds": 0, "longest": 0, "before_lana": True}
            summary["players"].append(player)
            by_name[low] = player
        player["stats"] = [{"key": k, "label": label, "unit": unit, "value": info["stats"][k]}
                           for k, label, unit, _calc in MINECRAFT_STATS]
        if "advancements" in info["stats"]:
            player["stats"].append({"key": "advancements", "label": "Progrès accomplis", "unit": "n", "value": info["stats"]["advancements"]})
    summary["totals"]["unique"] = len(summary["players"])
    records = []
    for key, label in MINECRAFT_LEADERS:
        ranked = [(p["stats"][i]["value"], p["name"]) for p in summary["players"] if "stats" in p
                  for i, s in enumerate(p["stats"]) if s["key"] == key]
        if ranked and max(ranked)[0] > 0:
            top = max(ranked)
            unit = next(u for k, _l, u, _c in MINECRAFT_STATS if k == key)
            records.append({"label": label, "name": top[1], "value": top[0], "unit": unit})
    summary["records"] = records
    return summary


EXTRAS = {"minecraft": minecraft_extras}


def report(inst):
    """Joueurs d'un serveur : historique, statut, statistiques. None si le jeu ne le permet pas."""
    state = update(inst)
    if state is None:
        return None
    summary = summarize(state)
    extra = EXTRAS.get(inst.game["players"].get("stats"))
    if extra:
        summary = extra(inst, summary)
    summary["players"].sort(key=lambda p: (not p["online"], -(p["last_seen"] or 0), p["name"].lower()))
    return summary


# ---------- suivi en arrière-plan ----------

def track_forever(list_instances):
    """Met à jour les historiques toutes les POLL_SECONDS pour que les sessions soient horodatées au bon moment."""
    while True:
        try:
            for inst in list_instances():
                if supported(inst.game):
                    update(inst)
        except Exception as ex:   # noqa: BLE001 - le suivi ne doit jamais s'arrêter
            print("Suivi des joueurs : %s" % ex)
        time.sleep(POLL_SECONDS)
