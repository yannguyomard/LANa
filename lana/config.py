"""Lecture, validation et écriture de la config d'un serveur, pilotées par la définition du jeu.

Chaque champ de la définition a une clé `key` : chemin pointé dans le fichier de config
(ex. "gameSettings.enableDurability"). Les clés inconnues du fichier sont toujours conservées.
"""
import copy
import json
import os
import secrets
import shutil

NS_PER_MIN = 60 * 10**9
_MISSING = object()


# ---------- chemins pointés ----------

def get_path(data, path, default=_MISSING):
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def set_path(data, path, value):
    parts = path.split(".")
    cur = data
    for part in parts[:-1]:
        if not isinstance(cur.get(part), dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


# ---------- fichier (pilotes de format) ----------

def read_file(game, root):
    path = os.path.join(root, game["config"]["file"])
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_file(game, root, data):
    path = os.path.join(root, game["config"]["file"])
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def initial_config(game):
    """Config de départ du jeu ; les jetons "{random}" deviennent des mots de passe aléatoires."""
    def fill(node):
        if isinstance(node, dict):
            return {k: fill(v) for k, v in node.items()}
        if isinstance(node, list):
            return [fill(v) for v in node]
        if isinstance(node, str) and node == "{random}":
            return secrets.token_urlsafe(9)
        return node
    return fill(copy.deepcopy(game["config"]["initial"]))


# ---------- conversion fichier <-> interface ----------

def _to_ui_value(field, stored):
    if field["type"] == "minutes_ns":
        return round(float(stored) / NS_PER_MIN, 2)
    return stored


def _from_ui_value(field, value):
    """Valide une valeur venue de l'interface et la convertit pour le fichier."""
    label, t = field["label"], field["type"]
    if t == "bool":
        if not isinstance(value, bool):
            raise ValueError("%s : oui ou non attendu" % label)
        return value
    if t == "text":
        value = str(value).strip()
        if field.get("required", True) and not value:
            raise ValueError("%s : ne peut pas être vide" % label)
        if len(value) > field.get("maxlen", 200):
            raise ValueError("%s : trop long" % label)
        return value
    if t == "enum":
        if value not in field["options"]:
            raise ValueError("%s : valeur inconnue" % label)
        return value
    if t == "tags":
        if not isinstance(value, list) or any(v not in field["options"] for v in value):
            raise ValueError("%s : étiquette inconnue" % label)
        return list(value)
    if t in ("int", "float", "minutes_ns"):
        try:
            num = float(value)
        except (TypeError, ValueError):
            raise ValueError("%s : nombre attendu" % label)
        if not field["min"] <= num <= field["max"]:
            raise ValueError("%s : doit être entre %s et %s" % (label, field["min"], field["max"]))
        if t == "int":
            return int(num)
        if t == "minutes_ns":
            return int(round(num * NS_PER_MIN))
        return num
    raise ValueError("%s : type de champ inconnu (%s)" % (label, t))


def _default_ui(field):
    if field["type"] == "collection":
        return []
    return field.get("default")


def to_ui(game, data):
    """Valeurs du fichier au format de l'interface, avec les défauts du jeu pour les clés absentes."""
    out = {}
    for field in game["fields"]:
        stored = get_path(data, field["key"])
        if field["type"] == "collection":
            items = [] if stored is _MISSING else stored
            out[field["key"]] = [
                {sub["key"]: (_to_ui_value(sub, it[sub["key"]]) if sub["key"] in it else _default_ui(sub))
                 for sub in field["item"]}
                for it in items
            ]
        elif stored is _MISSING:
            out[field["key"]] = _default_ui(field)
        else:
            out[field["key"]] = _to_ui_value(field, stored)
    return out


def apply_ui(game, data, values):
    """Applique les valeurs de l'interface sur une copie de `data` ; ValueError si invalide."""
    data = copy.deepcopy(data)
    for field in game["fields"]:
        key = field["key"]
        if key not in values:
            continue
        if field["type"] != "collection":
            set_path(data, key, _from_ui_value(field, values[key]))
            continue
        items = values[key]
        if not isinstance(items, list) or len(items) < field.get("min_items", 0):
            raise ValueError("%s : il en faut au moins %s" % (field["label"], field.get("min_items", 0)))
        built = []
        for raw in items:
            built.append({sub["key"]: _from_ui_value(sub, raw.get(sub["key"], sub.get("default")))
                          for sub in field["item"]})
        for unique in field.get("unique", []):
            seen = [it[unique] for it in built]
            if len(set(seen)) != len(seen):
                raise ValueError("%s : « %s » doit être différent pour chaque entrée" % (field["label"], unique))
        set_path(data, key, built)
    return data
