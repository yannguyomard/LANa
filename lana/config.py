"""Lecture, validation et écriture de la config d'un serveur, pilotées par la définition du jeu.

Chaque champ de la définition a une clé `key` : chemin pointé dans le fichier de config
(ex. "gameSettings.enableDurability"). Les clés inconnues du fichier sont toujours conservées.
"""
import copy
import json
import os
import re
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

FLAT_FORMATS = ("properties", "ue_options")


def is_flat(game):
    """Formats sans sections (.properties, OptionSettings d'Unreal) : la clé entière est le nom du réglage."""
    return game["config"]["format"] in FLAT_FORMATS


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


def _split_top_level(text):
    """Découpe "A=1,B=\"x,y\",C=(1,2)" aux virgules qui ne sont ni entre guillemets ni entre parenthèses."""
    parts, cur, depth, quoted, i = [], [], 0, False, 0
    while i < len(text):
        c = text[i]
        if quoted:
            cur.append(c)
            if c == "\\" and i + 1 < len(text):
                i += 1
                cur.append(text[i])
            elif c == '"':
                quoted = False
        elif c == '"':
            quoted = True
            cur.append(c)
        elif c in "(":
            depth += 1
            cur.append(c)
        elif c == ")":
            depth -= 1
            cur.append(c)
        elif c == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    if cur:
        parts.append("".join(cur))
    return parts


def _find_option_line(lines):
    for i, line in enumerate(lines):
        if line.strip().startswith("OptionSettings="):
            return i
    return None


def _ue_coerce(field, raw):
    t = field["type"]
    try:
        if t == "bool":
            return raw.strip().lower() == "true"
        if t == "int":
            return int(float(raw))
        if t == "float":
            return float(raw)
    except ValueError:
        return field.get("default")
    if t == "text":
        raw = raw.strip()
        if len(raw) >= 2 and raw[0] == raw[-1] == '"':
            raw = raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        return raw
    return raw.strip()


def _ue_stringify(field, value):
    """Valeur typée -> texte tel que l'écrit le jeu (True/False, 6 décimales, chaînes entre guillemets)."""
    if field is None:
        return str(value)
    t = field["type"]
    if t == "bool":
        return "True" if value else "False"
    if t == "float":
        return "%.6f" % value
    if t == "text":
        return '"%s"' % str(value).replace("\\", "\\\\").replace('"', '\\"')
    return str(value)


def _read_ue_options(game, path):
    with open(path, encoding="utf-8-sig") as fh:
        lines = fh.read().splitlines()
    idx = _find_option_line(lines)
    if idx is None:
        return {}
    body = lines[idx].strip()[len("OptionSettings="):].strip()
    if body.startswith("(") and body.endswith(")"):
        body = body[1:-1]
    fields = {f["key"]: f for f in game["fields"]}
    out = {}
    for token in _split_top_level(body):
        key, _, raw = token.partition("=")
        key = key.strip()
        if key:
            out[key] = _ue_coerce(fields[key], raw) if key in fields else raw
    return out


def _write_ue_options(game, path, data):
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    fields = {f["key"]: f for f in game["fields"]}
    option = "OptionSettings=(%s)" % ",".join("%s=%s" % (k, _ue_stringify(fields.get(k), v)) for k, v in data.items())
    idx = _find_option_line(lines)
    if idx is None:
        lines += ["[%s]" % game["config"].get("section", "/Script/Engine.Settings"), option]
    else:
        lines[idx] = option
    return "\n".join(lines) + "\n"


def read_file(game, root):
    path = _config_path(game, root)
    if not os.path.exists(path):
        return {}
    if game["config"]["format"] == "ue_options":
        return _read_ue_options(game, path)
    if not is_flat(game):
        with open(path, encoding="utf-8-sig") as fh:  # -sig : certains jeux écrivent un BOM
            return json.load(fh)
    props = {}
    with open(path, encoding="utf-8-sig") as fh:
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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    if game["config"]["format"] == "ue_options":
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(_write_ue_options(game, path, data))
    elif not is_flat(game):
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
    return fill(copy.deepcopy(game["config"].get("initial", {})))


def _deep_merge(base, extra):
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def write_initial(game, root):
    """Crée la config de départ : copie du fichier par défaut du jeu (`seed_from`, si présent), puis
    valeurs imposées par LANa (`initial`). Partir du fichier du jeu évite d'inventer ses valeurs par défaut."""
    spec = game["config"]
    target = _config_path(game, root)
    seed = os.path.join(root, spec["seed_from"]) if spec.get("seed_from") else None
    if seed and os.path.exists(seed):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(seed, target)
    data = read_file(game, root)
    write_file(game, root, _deep_merge(data, initial_config(game)))


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
        if field.get("pattern") and value and not re.match(field["pattern"], value):
            raise ValueError("%s : %s" % (label, field.get("pattern_hint", "caractères non permis")))
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
