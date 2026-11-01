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

def get_path(data, path, default=_MISSING, flat=False):
    if flat:
        return data.get(path, default)
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def set_path(data, path, value, flat=False):
    if flat:
        data[path] = value
        return
    parts = path.split(".")
    cur = data
    for part in parts[:-1]:
        if not isinstance(cur.get(part), dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


# ---------- fichier (pilotes de format) ----------

def is_flat(game):
    """Les fichiers .properties n'ont pas de sections : la clé entière est le nom de la propriété."""
    return game["config"]["format"] == "properties"


def _config_path(game, root):
    return os.path.join(root, game["config"]["file"])


def _coerce(field, text):
    """Texte d'un fichier .properties -> valeur typée selon le champ."""
    t = field["type"]
    try:
        if t == "bool":
            return text.strip().lower() == "true"
        if t == "int":
            return int(text)
        if t == "float":
            return float(text)
    except ValueError:
        return field.get("default")
    return text


def _stringify(value):
    return str(value).lower() if isinstance(value, bool) else str(value)


def read_file(game, root):
    path = _config_path(game, root)
    if not os.path.exists(path):
        return {}
    if not is_flat(game):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    props = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                props[key.strip()] = value
    fields = {f["key"]: f for f in game["fields"]}
    return {k: _coerce(fields[k], v) if k in fields else v for k, v in props.items()}


def write_file(game, root, data):
    path = _config_path(game, root)
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    tmp = path + ".tmp"
    if not is_flat(game):
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
    else:
        # On garde l'ordre et les commentaires du fichier existant ; les nouvelles clés vont à la fin.
        lines = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        pending = dict(data)
        out = []
        for line in lines:
            key = line.partition("=")[0].strip()
            if line.strip() and not line.lstrip().startswith("#") and "=" in line and key in pending:
                out.append("%s=%s" % (key, _stringify(pending.pop(key))))
            else:
                out.append(line)
        out += ["%s=%s" % (k, _stringify(v)) for k, v in pending.items()]
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out) + "\n")
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
        if any(c in value for c in "\r\n\x00"):
            raise ValueError("%s : les sauts de ligne ne sont pas permis" % label)
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
    flat = is_flat(game)
    for field in game["fields"]:
        stored = get_path(data, field["key"], flat=flat)
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
    flat = is_flat(game)
    for field in game["fields"]:
        key = field["key"]
        if key not in values:
            continue
        if field["type"] != "collection":
            set_path(data, key, _from_ui_value(field, values[key]), flat=flat)
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
        set_path(data, key, built, flat=flat)
    return data
