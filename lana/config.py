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

FLAT_FORMATS = ("properties", "ue_options", "ini", "cfg", "xml_props", "xml_elements", "arma", "none")


def is_flat(game):
    """Formats à clés plates (.properties, .ini, .cfg, xml, OptionSettings d'Unreal) : la clé entière désigne le réglage."""
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


# ---------- formats texte « clé = valeur » (ini à sections, cfg, xml) ----------
#
# Chaque réglage a une clé plate : "[Section]Clé" pour un .ini, le nom de la commande pour un .cfg,
# l'attribut name (xml_props) ou le nom de l'élément (xml_elements). Le fichier est réécrit ligne à ligne :
# ordre, commentaires et réglages inconnus de LANa sont conservés ; les nouveaux vont à la fin (de leur section).

BOOL_TEXT = {"ini": ("True", "False"), "cfg": ("1", "0"), "xml_props": ("true", "false"), "xml_elements": ("true", "false"),
             "arma": ("1", "0")}
CFG_SET_WORDS = ("set", "sets", "seta", "setr")
INI_KEY = re.compile(r"^\[([^\]]*)\](.+)$")
XML_PROP = re.compile(r'<property\s+name="([^"]+)"\s+value="([^"]*)"\s*/>')
XML_ELEM = re.compile(r"^(\s*)<([A-Za-z_][\w.-]*)>([^<]*)</\2>")
ARMA_LINE = re.compile(r"^(\s*)([A-Za-z_]\w*)\s*=\s*(.*?)\s*;(.*)$")   # DayZ / Arma : clé = valeur;  (pas les tableaux clé[])


def _text_coerce(field, raw):
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        raw = raw[1:-1]
    t = field["type"]
    try:
        if t == "bool":
            return raw.lower() in ("true", "1", "yes", "on")
        if t == "int":
            return int(float(raw))
        if t == "float":
            return float(raw)
    except ValueError:
        return field.get("default")
    return raw


def _text_value(game, field, value):
    spec = game["config"]
    fmt = spec["format"]
    if isinstance(value, bool):
        yes, no = spec.get("bools", BOOL_TEXT[fmt])
        return yes if value else no
    if isinstance(value, float):
        text = ("%.6f" % value).rstrip("0").rstrip(".") if fmt != "ini" else "%.6f" % value
    else:
        text = str(value)
    if fmt == "xml_props" or fmt == "xml_elements":
        return text.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
    if fmt in ("cfg", "arma") and spec.get("quote", True) and (field is None or field["type"] in ("text", "enum")):
        return '"%s"' % text.replace('"', "'")
    return text


def _xml_unescape(text):
    return text.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _trailing_comment(line):
    """Commentaire « // … » en fin de ligne (hors guillemets), avec l'espace qui le précède."""
    quoted = False
    for i, c in enumerate(line):
        if c == '"':
            quoted = not quoted
        elif not quoted and line.startswith("//", i) and line[:i].strip():
            j = i
            while j > 0 and line[j - 1] in " \t":
                j -= 1
            return line[j:]
    return ""


def _parse_cfg_line(line):
    """(clé, préfixe) d'une ligne de .cfg, ou (None, None) pour un commentaire ou une ligne vide."""
    stripped = line.strip()
    if not stripped or stripped.startswith(("//", "#", ";")):
        return None, None, None
    words = stripped.split(None, 1)
    prefix = ""
    if words[0].lower() in CFG_SET_WORDS and len(words) > 1:
        prefix = words[0] + " "
        words = words[1].split(None, 1)
    rest = words[1] if len(words) > 1 else ""
    if rest.startswith('"'):
        end = rest.find('"', 1)
        rest = rest[:end + 1] if end > 0 else rest
    else:
        rest = rest.split("//")[0].strip()
    return words[0], prefix, rest


def _read_text_format(game, path):
    fmt = game["config"]["format"]
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        lines = fh.read().splitlines()
    raw, section = {}, ""
    for line in lines:
        if fmt == "ini":
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped[1:-1]
            elif stripped and not stripped.startswith((";", "#")) and "=" in stripped:
                key, _, value = stripped.partition("=")
                raw["[%s]%s" % (section, key.strip())] = value
        elif fmt == "cfg":
            key, _prefix, value = _parse_cfg_line(line)
            if key:
                raw[key] = value
        elif fmt == "arma":
            match = ARMA_LINE.match(line)
            if match and not line.strip().startswith("//"):
                raw[match.group(2)] = match.group(3)
        elif fmt == "xml_props":
            for name, value in XML_PROP.findall(line):
                raw[name] = _xml_unescape(value)
        else:
            match = XML_ELEM.match(line)
            if match:
                raw[match.group(2)] = _xml_unescape(match.group(3))
    fields = {f["key"]: f for f in game["fields"]}
    return {k: _text_coerce(fields[k], v) if k in fields else v for k, v in raw.items()}


def _write_text_format(game, path, data):
    fmt = game["config"]["format"]
    fields = {f["key"]: f for f in game["fields"]}
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            lines = fh.read().splitlines()
    pending = dict(data)
    value = lambda k: _text_value(game, fields.get(k), pending.pop(k))   # noqa: E731

    def changed(key, old_raw):
        """Faut-il réécrire cette ligne ? Seulement pour un réglage connu de LANa dont la valeur a changé :
        les lignes inconnues (exec, tableaux, doublons…) restent telles quelles."""
        if key not in pending:
            return False
        if key not in fields:
            pending.pop(key)
            return False
        if _text_coerce(fields[key], old_raw) == pending[key]:
            pending.pop(key)
            return False
        return True

    out, section, section_end = [], "", {}
    for line in lines:
        if fmt == "ini":
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped[1:-1]
            elif stripped and not stripped.startswith((";", "#")) and "=" in stripped:
                key = "[%s]%s" % (section, stripped.partition("=")[0].strip())
                if changed(key, stripped.partition("=")[2]):
                    line = "%s=%s" % (stripped.partition("=")[0].strip(), value(key))
            out.append(line)
            section_end[section] = len(out)
        elif fmt == "cfg":
            key, prefix, old = _parse_cfg_line(line)
            if key and changed(key, old):
                line = "%s%s %s%s" % (prefix, key, value(key), _trailing_comment(line))
            out.append(line)
        elif fmt == "arma":
            match = ARMA_LINE.match(line)
            if match and not line.strip().startswith("//") and changed(match.group(2), match.group(3)):
                line = "%s%s = %s;%s" % (match.group(1), match.group(2), value(match.group(2)), match.group(4))
            out.append(line)
        elif fmt == "xml_props":
            def swap(m):
                return '<property name="%s" value="%s"/>' % (m.group(1), value(m.group(1))) if changed(m.group(1), _xml_unescape(m.group(2))) else m.group(0)
            out.append(XML_PROP.sub(swap, line))
        else:
            match = XML_ELEM.match(line)
            if match and changed(match.group(2), _xml_unescape(match.group(3))):
                line = "%s<%s>%s</%s>%s" % (match.group(1), match.group(2), value(match.group(2)), match.group(2), line[match.end():])
            out.append(line)
    # réglages absents du fichier
    if fmt == "ini":
        for key in list(pending):
            sect, name = INI_KEY.match(key).groups()
            entry = "%s=%s" % (name, value(key))
            if sect in section_end:
                pos = section_end[sect]
                out.insert(pos, entry)
                section_end = {s: e + 1 if e >= pos else e for s, e in section_end.items()}
            else:
                out += (["", "[%s]" % sect] if out else ["[%s]" % sect]) + [entry]
                section_end[sect] = len(out)
    elif fmt == "cfg":
        prefix = game["config"].get("prefix", "")
        out += ["%s%s %s" % (prefix, k, value(k)) for k in list(pending)]
    elif fmt == "arma":
        out += ["%s = %s;" % (k, value(k)) for k in list(pending)]
    elif fmt == "xml_props":
        extra = ['\t<property name="%s" value="%s"/>' % (k, value(k)) for k in list(pending)]
        close = next((i for i in range(len(out) - 1, -1, -1) if out[i].strip().startswith("</")), None)
        if close is None:
            out = ["<?xml version=\"1.0\"?>", "<ServerSettings>"] + out + extra + ["</ServerSettings>"]
        else:
            out[close:close] = extra
    else:
        extra = ["\t<%s>%s</%s>" % (k, value(k), k) for k in list(pending)]
        close = next((i for i in range(len(out) - 1, -1, -1) if out[i].strip().startswith("</")), None)
        root = game["config"].get("root", "config")
        if close is None:
            out = ["<%s>" % root] + out + extra + ["</%s>" % root]
        else:
            out[close:close] = extra
    return "\n".join(out) + "\n"


TEXT_FORMATS = ("ini", "cfg", "xml_props", "xml_elements", "arma")


def read_file(game, root):
    path = _config_path(game, root)
    if not os.path.exists(path):
        return {}
    fmt = game["config"]["format"]
    if fmt == "none":
        return {}
    if fmt == "ue_options":
        return _read_ue_options(game, path)
    if fmt in TEXT_FORMATS:
        return _read_text_format(game, path)
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
    if game["config"]["format"] == "none":   # jeu réglé seulement en ligne de commande (réglages « lana: »)
        return
    path = _config_path(game, root)
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fmt = game["config"]["format"]
    if fmt == "ue_options":
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(_write_ue_options(game, path, data))
    elif fmt in TEXT_FORMATS:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(_write_text_format(game, path, data))
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
