"""Gestionnaire de mods : recherche et installation automatiques, dépôt manuel, activation, mises à jour, réglages.

Sources (`mods.provider` dans la définition du jeu) :
  - modrinth      Minecraft (Java), avec un moteur Fabric (mods) ou Paper (plugins) installé par LANa ;
  - thunderstore  Valheim, V Rising : mods BepInEx, chargeur BepInEx installé automatiquement ;
  - umod          Rust : plugins Oxide (uMod), Oxide installé automatiquement ;
  - workshop      Workshop Steam (Project Zomboid, ARK, Unturned) : LANa écrit les numéros dans la config du jeu
                  et le serveur télécharge lui-même les objets au démarrage.
Tous les jeux qui déclarent un dossier (`mods.dir`) acceptent aussi le dépôt manuel de fichiers.

Chaque serveur garde la liste de ses mods dans <instance>/mods.json : fichiers posés, version, source,
dépendances. Un mod désactivé est rangé dans <instance>/mods-disabled/, hors de portée du jeu.
"""
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.parse
import zipfile

from . import games, jobs, runtime, system

MODRINTH = "https://api.modrinth.com/v2"
FABRIC_META = "https://meta.fabricmc.net/v2/versions"
PAPER = "https://fill.papermc.io/v3/projects/paper/versions/%s/builds/latest"
THUNDERSTORE = "https://thunderstore.io"
UMOD = "https://umod.org"
OXIDE = "OxideMod/Oxide.Rust"
STEAM_DETAILS = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
STEAM_COLLECTION = "https://api.steampowered.com/ISteamRemoteStorage/GetCollectionDetails/v1/"
CONFIG_EXT = (".cfg", ".json", ".yml", ".yaml", ".toml", ".properties", ".txt", ".ini", ".xml", ".conf", ".json5")
MAX_CONFIG_BYTES = 512 * 1024
MAX_MOD_BYTES = 1024 * 2**20
PAGE = 20
# Moteurs du serveur Minecraft : le fichier lancé à la place de server.jar, et le dossier des extensions.
MC_LOADERS = {
    "vanilla": {"label": "Vanilla (sans mods)", "jar": "server.jar", "dir": None, "kind": None},
    "fabric": {"label": "Fabric (mods)", "jar": "fabric-server-launch.jar", "dir": "mods", "kind": "mod",
               "loaders": ["fabric"]},
    "paper": {"label": "Paper (plugins)", "jar": "paper.jar", "dir": "plugins", "kind": "plugin",
              "loaders": ["paper", "spigot", "bukkit"]},
}
THUNDERSTORE_SKIP = {"manifest.json", "icon.png", "readme.md", "changelog.md", "license", "license.md", "license.txt"}
BEPINEX_DIRS = ("plugins", "config", "patchers", "core", "monomod")
WORKSHOP_ID = re.compile(r"(?:\?id=|^)(\d{6,12})")
MOD_ID_LINE = re.compile(r"Mod\s*ID\s*:\s*([^\s\[<\]]+)", re.I)

_locks = {}
_locks_guard = threading.Lock()


class ModError(Exception):
    """Erreur destinée à être affichée telle quelle à l'utilisateur."""


def _lock(inst):
    with _locks_guard:
        return _locks.setdefault(inst.id, threading.RLock())


def spec(game):
    return game.get("mods")


def _need_spec(inst):
    found = spec(inst.game)
    if not found:
        raise ModError("Ce jeu n'a pas de gestion de mods dans LANa")
    return found


# ---------- utilitaires ----------

def _inside(base, rel):
    """Chemin absolu de rel sous base, en refusant tout ce qui en sortirait."""
    if not rel or os.path.isabs(rel) or "\\" in rel:
        raise ModError("Chemin refusé : %s" % rel)
    base = os.path.realpath(base)
    path = os.path.realpath(os.path.join(base, rel))
    if path == base or not path.startswith(base + os.sep):
        raise ModError("Chemin refusé : %s" % rel)
    return path


def _friendly(ex):
    """Message lisible pour une erreur réseau."""
    code = getattr(ex, "code", None)
    if code == 429:
        return "le site limite le nombre de demandes, réessayez dans une minute"
    if code == 404:
        return "introuvable chez la source (retiré ?)"
    return str(getattr(ex, "reason", "") or ex)


def _safe_name(text):
    return re.sub(r"[^A-Za-z0-9._-]", "_", text)[:80] or "mod"


def _get_json(url, data=None):
    if data is None:
        return runtime.fetch_json(url)
    req = runtime.urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                         headers={"User-Agent": runtime.USER_AGENT})
    with runtime.urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def _download(url, dest, job, label, sha1=None, sha256=None):
    runtime.download(url, dest, job, label, sha1=sha1)
    if sha256:
        digest = hashlib.sha256()
        with open(dest, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        if digest.hexdigest() != sha256:
            os.remove(dest)
            raise RuntimeError("Empreinte incorrecte pour %s : téléchargement corrompu ou altéré." % label)


def _zip_members(path):
    """Entrées d'un zip, vérifiées : pas de chemin absolu, pas de « .. », pas de lien, taille bornée."""
    with zipfile.ZipFile(path) as zf:
        out, total = [], 0
        for info in zf.infolist():
            name = info.filename
            if name.startswith("__MACOSX/") or name.endswith(".DS_Store"):
                continue
            parts = name.replace("\\", "/").split("/")
            if name.startswith("/") or ".." in parts or ":" in parts[0]:
                raise ModError("Archive refusée : chemin %s" % name)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ModError("Archive refusée : lien symbolique (%s)" % name)
            total += info.file_size
            if total > MAX_MOD_BYTES:
                raise ModError("Archive refusée : plus de %d Mo une fois décompressée" % (MAX_MOD_BYTES // 2**20))
            out.append(info)
        return out


def _extract(path, mapping, root):
    """Extrait chaque membre du zip vers root/<mapping(nom)> (None = ignoré) ; retourne les chemins posés."""
    written = []
    with zipfile.ZipFile(path) as zf:
        for info in _zip_members(path):
            if info.is_dir():
                continue
            rel = mapping(info.filename.replace("\\", "/"))
            if not rel:
                continue
            dest = _inside(root, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            written.append(rel)
    return written


# ---------- liste des mods d'un serveur ----------

def _manifest_path(inst):
    return os.path.join(inst.dir, "mods.json")


def _load(inst):
    try:
        with open(_manifest_path(inst), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    data.setdefault("entries", {})
    data.setdefault("written", {})
    return data


def _save(inst, data):
    tmp = _manifest_path(inst) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, _manifest_path(inst))


def _disabled_dir(inst, key):
    return os.path.join(inst.dir, "mods-disabled", _safe_name(key))


def mc_loader(inst):
    return inst.meta().get("mc_loader", "vanilla")


def mods_dir(inst):
    """Dossier (relatif au serveur) où vont les fichiers de mods, ou None (Minecraft vanilla, Workshop seul)."""
    s = _need_spec(inst)
    if s["provider"] == "modrinth":
        return MC_LOADERS[mc_loader(inst)]["dir"]
    return s.get("dir")


def _owner_files(data):
    owned = set()
    for e in data["entries"].values():
        owned.update(e.get("files", []))
    return owned


def _found_files(inst, data):
    """Fichiers déjà dans le dossier des mods sans que LANa les y ait mis (copiés à la main, d'un autre serveur…)."""
    rel_dir = mods_dir(inst)
    if not rel_dir:
        return []
    folder = os.path.join(inst.server_dir, rel_dir)
    if not os.path.isdir(folder):
        return []
    owned = _owner_files(data)
    out = []
    for name in sorted(os.listdir(folder)):
        rel = rel_dir + "/" + name
        if name.startswith(".") or rel in owned or any(o.startswith(rel + "/") for o in owned):
            continue
        out.append(rel)
    return out


def _entry_payload(e):
    keep = ("key", "provider", "project", "name", "version", "kind", "enabled", "auto", "icon", "url", "summary",
            "required_by", "files", "items", "mod_ids", "loader", "installed_at")
    return {k: e.get(k) for k in keep}


def state(inst):
    s = _need_spec(inst)
    with _lock(inst):
        data = _load(inst)
        entries = list(data["entries"].values())
        found = _found_files(inst, data)
    loader = None
    if s["provider"] == "modrinth":
        cur = mc_loader(inst)
        loader = {"current": cur, "options": [{"id": k, "label": v["label"]} for k, v in MC_LOADERS.items()],
                  "kind": MC_LOADERS[cur]["kind"], "mc_version": inst.meta().get("version", "")}
        entries = [e for e in entries if e.get("loader") in (None, cur)]
    out_dir = mods_dir(inst)
    return {
        "provider": s["provider"], "provider_label": PROVIDER_LABELS[s["provider"]],
        "note": s.get("note", ""), "verified": s.get("verified", True),
        "loader": loader, "dir": out_dir, "dir_path": os.path.join(inst.server_dir, out_dir) if out_dir else "",
        "extensions": s.get("extensions", [".zip"]), "manual": bool(out_dir),
        "workshop_url": "https://steamcommunity.com/app/%s/workshop/" % s["appid"] if s["provider"] == "workshop" else "",
        "entries": sorted((_entry_payload(e) for e in entries), key=lambda e: (e["kind"] != "loader", (e["name"] or "").lower())),
        "found": [{"key": "found:" + rel, "name": os.path.basename(rel), "path": rel} for rel in found],
        "hidden": len(data["entries"]) - len(entries),
        "config_files": config_files(inst),
        "running": inst.running(),
    }


PROVIDER_LABELS = {"modrinth": "Modrinth", "thunderstore": "Thunderstore", "umod": "uMod", "workshop": "Workshop Steam"}


# ---------- recherche ----------

def search(inst, query, page=0):
    s = _need_spec(inst)
    query = (query or "").strip()[:100]
    page = max(0, min(int(page or 0), 50))
    try:
        if s["provider"] == "modrinth":
            return _search_modrinth(inst, query, page)
        if s["provider"] == "thunderstore":
            return _search_thunderstore(s, query, page)
        if s["provider"] == "umod":
            return _search_umod(s, query, page)
        if s["provider"] == "workshop":
            return _search_workshop(s, query)
    except ModError:
        raise
    except Exception as ex:  # noqa: BLE001 - réseau, réponse inattendue
        raise ModError("Recherche impossible pour l'instant : %s" % _friendly(ex))
    return {"results": [], "total": 0}


def _installed_projects(inst):
    return {e.get("project") for e in _load(inst)["entries"].values()}


def _search_modrinth(inst, query, page):
    loader = MC_LOADERS[mc_loader(inst)]
    if not loader["kind"]:
        raise ModError("Choisissez d'abord un moteur : Fabric pour les mods, Paper pour les plugins")
    facets = [["project_type:%s" % loader["kind"]], ["categories:%s" % l for l in loader["loaders"]]]
    mc = inst.meta().get("version")
    if mc:
        facets.append(["versions:%s" % mc])
    if loader["kind"] == "mod":
        facets.append(["server_side:required", "server_side:optional"])
    url = "%s/search?%s" % (MODRINTH, urllib.parse.urlencode({
        "query": query, "facets": json.dumps(facets), "limit": PAGE, "offset": page * PAGE,
        "index": "relevance" if query else "downloads"}))
    d = runtime.fetch_json(url)
    mine = _installed_projects(inst)
    return {"total": d.get("total_hits", 0), "results": [{
        "project": h["project_id"], "name": h["title"], "summary": h.get("description", ""),
        "author": h.get("author", ""), "downloads": h.get("downloads", 0), "icon": h.get("icon_url") or "",
        "url": "https://modrinth.com/%s/%s" % (h.get("project_type", "mod"), h.get("slug", h["project_id"])),
        "installed": h["project_id"] in mine, "versions": True,
        "side": "client" if h.get("server_side") == "unsupported" else "server" if h.get("server_side") == "required" else ""}
        for h in d.get("hits", [])]}


def _search_thunderstore(s, query, page):
    url = "%s/api/cyberstorm/listing/%s/?%s" % (THUNDERSTORE, s["community"], urllib.parse.urlencode(
        {"q": query, "ordering": "most-downloaded", "page": page + 1, "deprecated": "False", "nsfw": "False"}))
    d = runtime.fetch_json(url)
    loader = s.get("loader", "")
    out = []
    for r in d.get("results", []):
        cats = {c.get("slug") for c in r.get("categories", [])}
        if cats & {"modpacks"} or cats == {"tools"} or r["name"].lower() == "r2modman":   # gestionnaires, packs : pas des mods
            continue
        out.append({"project": "%s-%s" % (r["namespace"], r["name"]), "name": r["name"].replace("_", " "),
                    "summary": r.get("description", ""), "author": r["namespace"], "downloads": r.get("download_count", 0),
                    "icon": r.get("icon_url") or "", "url": "%s/c/%s/p/%s/%s/" % (THUNDERSTORE, s["community"], r["namespace"], r["name"]),
                    "installed": False, "loader": "%s-%s" % (r["namespace"], r["name"]) == loader, "versions": False,
                    "side": "server" if "server-side" in cats else "client" if "client-side" in cats else ""})
    return {"total": d.get("count", 0), "results": out}


def _search_umod(s, query, page):
    url = "%s/plugins/search.json?%s" % (UMOD, urllib.parse.urlencode(
        {"query": query, "page": page + 1, "sort": "downloads" if not query else "relevance", "sortdir": "desc",
         "categories[0]": s["game"]}))
    d = runtime.fetch_json(url)
    return {"total": d.get("total", 0), "results": [{
        "project": x["slug"], "name": x["title"], "summary": x.get("description", ""), "author": x.get("author", ""),
        "downloads": x.get("downloads", 0), "icon": x.get("icon_url") or "", "url": "%s/plugins/%s" % (UMOD, x["slug"]),
        "installed": False, "versions": False} for x in d.get("data", [])]}


def _workshop_details(ids):
    data = {"itemcount": len(ids)}
    for i, v in enumerate(ids):
        data["publishedfileids[%d]" % i] = v
    return _get_json(STEAM_DETAILS, data)["response"].get("publishedfiledetails", [])


def _search_workshop(s, query):
    """Pas de recherche publique sans clé Steam : on accepte un numéro ou un lien d'objet ou de collection."""
    ids = _parse_workshop_ids(query)
    if not ids:
        return {"total": 0, "results": [], "hint": "Collez le lien d'un objet ou d'une collection du Workshop."}
    ids = _expand_collections(ids)
    out = []
    for d in _workshop_details(ids[:50]):
        if d.get("result") != 1:
            continue
        ok = str(d.get("consumer_app_id")) == str(s["appid"])
        out.append({"project": d["publishedfileid"], "name": d.get("title", d["publishedfileid"]),
                    "summary": _strip_bbcode(d.get("description", ""))[:300] if ok else "Cet objet appartient à un autre jeu.",
                    "author": "", "downloads": d.get("subscriptions", 0), "icon": d.get("preview_url", ""),
                    "url": "https://steamcommunity.com/sharedfiles/filedetails/?id=%s" % d["publishedfileid"],
                    "installed": False, "versions": False, "wrong_game": not ok})
    return {"total": len(out), "results": out}


def _parse_workshop_ids(text):
    ids = []
    for part in re.split(r"[\s,;]+", text or ""):
        m = WORKSHOP_ID.search(part)
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


def _expand_collections(ids):
    """Remplace chaque collection par ses objets."""
    data = {"collectioncount": len(ids)}
    for i, v in enumerate(ids):
        data["publishedfileids[%d]" % i] = v
    try:
        found = _get_json(STEAM_COLLECTION, data)["response"].get("collectiondetails", [])
    except Exception:  # noqa: BLE001 - pas une collection, ou Steam indisponible : on garde les numéros tels quels
        return ids
    out = []
    for c in found:
        children = [x["publishedfileid"] for x in c.get("children", [])] if c.get("result") == 1 else []
        for v in children or [c["publishedfileid"]]:
            if v not in out:
                out.append(v)
    return out or ids


def _strip_bbcode(text):
    text = re.sub(r"\[img\].*?\[/img\]", " ", text, flags=re.I | re.S)
    text = re.sub(r"https?://\S+", " ", text)
    return re.sub(r"\s+", " ", re.sub(r"\[[^\]]{0,200}\]", " ", text)).strip()


# ---------- versions d'un mod (Modrinth) ----------

def project_versions(inst, project):
    s = _need_spec(inst)
    if s["provider"] != "modrinth":
        raise ModError("Choix de version disponible pour les mods Minecraft seulement")
    try:
        found = _modrinth_versions(inst, project)
    except Exception as ex:  # noqa: BLE001
        raise ModError("Versions indisponibles (%s)" % ex)
    return [{"id": v["id"], "label": v["version_number"] + ("" if v.get("version_type") == "release" else " (%s)" % v["version_type"]),
             "date": v.get("date_published", "")[:10]} for v in found[:40]]


def _modrinth_versions(inst, project):
    if not re.match(r"^[A-Za-z0-9_-]{2,64}$", project or ""):
        raise ModError("Projet invalide")
    loader = MC_LOADERS[mc_loader(inst)]
    params = {"loaders": json.dumps(loader["loaders"] or [])}
    if inst.meta().get("version"):
        params["game_versions"] = json.dumps([inst.meta()["version"]])
    return runtime.fetch_json("%s/project/%s/version?%s" % (MODRINTH, project, urllib.parse.urlencode(params)))


# ---------- installation ----------

def install(inst, project, version=None):
    """Installe un mod (et ses dépendances, et le chargeur s'il manque) en tâche de fond ; retourne la tâche."""
    s = _need_spec(inst)
    project = str(project or "").strip()
    if not project:
        raise ModError("Aucun mod choisi")
    if s["provider"] == "modrinth" and not MC_LOADERS[mc_loader(inst)]["kind"]:
        raise ModError("Choisissez d'abord un moteur : Fabric pour les mods, Paper pour les plugins")
    if s["provider"] == "workshop":
        return _install_workshop(inst, s, project)

    def work(job):
        try:
            _install_work(inst, s, project, version, job)
        except ModError:
            raise
        except (OSError, ValueError, KeyError) as ex:
            raise ModError(_friendly(ex))
        job.log("Terminé." + (" Redémarrez le serveur pour charger les mods." if inst.running() else ""))
    return jobs.start("Mods de %s" % inst.meta().get("name", inst.id), work)


def _install_work(inst, s, project, version, job):
    with _lock(inst):
        data = _load(inst)
        try:
            if s["provider"] == "modrinth":
                _install_modrinth(inst, data, project, version, job, required_by=None)
            elif s["provider"] == "thunderstore":
                _ensure_bepinex(inst, s, data, job)
                _install_thunderstore(inst, s, data, project, job, required_by=None, seen=set())
            elif s["provider"] == "umod":
                _ensure_oxide(inst, data, job)
                _install_umod(inst, s, data, project, job)
        finally:
            _save(inst, data)   # ce qui est posé (chargeur, dépendances) reste suivi même si la suite échoue


def _add_entry(data, entry):
    old = data["entries"].get(entry["key"], {})
    entry.setdefault("enabled", True)
    entry["required_by"] = sorted(set(old.get("required_by", [])) | set(entry.get("required_by", [])))
    entry["installed_at"] = time.time()
    data["entries"][entry["key"]] = entry


def _remove_files(inst, entry):
    base = inst.server_dir if entry.get("enabled", True) else _disabled_dir(inst, entry["key"])
    for rel in entry.get("files", []):
        try:
            path = _inside(base, rel)
        except ModError:
            continue
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            os.remove(path)
    if not entry.get("enabled", True):
        shutil.rmtree(_disabled_dir(inst, entry["key"]), ignore_errors=True)


def _install_modrinth(inst, data, project, version, job, required_by, depth=0):
    key = "modrinth:" + project
    if depth > 8:
        return
    current = data["entries"].get(key)
    if required_by and current:   # dépendance déjà là : on note seulement qui en a besoin
        current["required_by"] = sorted(set(current.get("required_by", [])) | {required_by})
        return
    found = _modrinth_versions(inst, project)
    if version:
        found = [v for v in found if v["id"] == version]
    if not found:
        raise ModError("Aucune version de ce mod pour Minecraft %s avec %s" % (
            inst.meta().get("version", "?"), MC_LOADERS[mc_loader(inst)]["label"]))
    stable = [v for v in found if v.get("version_type") == "release"]
    v = found[0] if version else (stable or found)[0]
    files = [f for f in v["files"] if f.get("primary")] or v["files"][:1]
    if not files:
        raise ModError("Ce mod ne publie pas de fichier")
    f = files[0]
    if not re.match(r"^[A-Za-z0-9 ._+()\[\]-]+\.jar$", f["filename"]):
        raise ModError("Nom de fichier inattendu : %s" % f["filename"])
    info = runtime.fetch_json("%s/project/%s" % (MODRINTH, project))
    if required_by:
        job.log("Dépendance requise : %s" % info.get("title", project))
    rel_dir = mods_dir(inst)
    folder = os.path.join(inst.server_dir, rel_dir)
    os.makedirs(folder, exist_ok=True)
    if current:
        _remove_files(inst, current)
    _download(f["url"], os.path.join(folder, f["filename"]), job, "%s %s" % (info.get("title", project), v["version_number"]),
              sha1=f.get("hashes", {}).get("sha1"))
    _add_entry(data, {"key": key, "provider": "modrinth", "project": project, "name": info.get("title", project),
                      "version": v["version_number"], "version_id": v["id"], "kind": MC_LOADERS[mc_loader(inst)]["kind"],
                      "auto": True, "icon": info.get("icon_url") or "", "summary": info.get("description", ""),
                      "url": "https://modrinth.com/%s/%s" % (info.get("project_type", "mod"), info.get("slug", project)),
                      "files": [rel_dir + "/" + f["filename"]], "loader": mc_loader(inst),
                      "required_by": [required_by] if required_by else [], "pinned": bool(version)})
    for dep in v.get("dependencies", []):
        if dep.get("dependency_type") == "required" and dep.get("project_id"):
            _install_modrinth(inst, data, dep["project_id"], None, job, required_by=key, depth=depth + 1)


def _thunderstore_package(full):
    if not re.match(r"^[A-Za-z0-9_]+-[A-Za-z0-9_]+$", full):
        raise ModError("Mod invalide : %s" % full)
    ns, name = full.split("-", 1)
    return runtime.fetch_json("%s/api/experimental/package/%s/%s/" % (THUNDERSTORE, ns, name))


def _thunderstore_mapping(members, full):
    """Où ranger chaque fichier d'un mod Thunderstore, à la manière de r2modman."""
    names = [m.filename.replace("\\", "/") for m in members if not m.is_dir()]
    tops = {n.split("/")[0].lower() for n in names if "/" in n}
    plug = "BepInEx/plugins/%s/" % full

    def mapping(name):
        if name.lower() in THUNDERSTORE_SKIP:
            return None
        head, _, rest = name.partition("/")
        if "bepinex" in tops:
            return name if head.lower() == "bepinex" and rest else None
        if rest and head.lower() in BEPINEX_DIRS:
            return ("BepInEx/%s/%s/%s" % (head.lower(), full, rest)) if head.lower() == "plugins" else "BepInEx/%s/%s" % (head.lower(), rest)
        return plug + name
    return mapping


def _install_thunderstore(inst, s, data, full, job, required_by, seen):
    if full in seen or full == s.get("loader"):
        return
    seen.add(full)
    key = "thunderstore:" + full
    current = data["entries"].get(key)
    if required_by and current:
        current["required_by"] = sorted(set(current.get("required_by", [])) | {required_by})
        return
    pkg = _thunderstore_package(full)
    latest = pkg["latest"]
    with tempfile.TemporaryDirectory(dir=inst.dir) as tmp:
        archive = os.path.join(tmp, "mod.zip")
        _download(latest["download_url"], archive, job, "%s %s" % (pkg["name"], latest["version_number"]))
        members = _zip_members(archive)
        if current:
            _remove_files(inst, current)
        files = _extract(archive, _thunderstore_mapping(members, full), inst.server_dir)
    _add_entry(data, {"key": key, "provider": "thunderstore", "project": full, "name": pkg["name"].replace("_", " "),
                      "version": latest["version_number"], "kind": "mod", "auto": True, "icon": latest.get("icon", ""),
                      "summary": latest.get("description", ""), "url": pkg.get("package_url", ""), "files": files,
                      "required_by": [required_by] if required_by else []})
    for dep in latest.get("dependencies", []):
        dep_full = dep.rsplit("-", 1)[0]
        if dep_full != s.get("loader"):
            job.log("Dépendance requise : %s" % dep_full)
            _install_thunderstore(inst, s, data, dep_full, job, required_by=key, seen=seen)


def _ensure_bepinex(inst, s, data, job):
    key = "thunderstore:" + s["loader"]
    if key in data["entries"] and os.path.exists(os.path.join(inst.server_dir, "BepInEx", "core")):
        return
    job.log("Installation du chargeur de mods BepInEx (une seule fois)…")
    pkg = _thunderstore_package(s["loader"])
    latest = pkg["latest"]
    with tempfile.TemporaryDirectory(dir=inst.dir) as tmp:
        archive = os.path.join(tmp, "bepinex.zip")
        _download(latest["download_url"], archive, job, "BepInEx %s" % latest["version_number"])
        members = _zip_members(archive)
        # Le pack range BepInEx/, winhttp.dll… dans un dossier : c'est ce dossier qu'on pose à la racine du serveur.
        root = next((m.filename.split("/")[0] + "/" for m in members if m.filename.split("/")[1:2] == ["BepInEx"]), "")
        files = _extract(archive, lambda n: n[len(root):] if n.startswith(root) and n[len(root):] else None, inst.server_dir)
    if not any(f.startswith("BepInEx/core/") for f in files):
        raise ModError("Le pack BepInEx téléchargé ne contient pas BepInEx/core")
    tops = sorted({f.split("/")[0] for f in files})
    _add_entry(data, {"key": key, "provider": "thunderstore", "project": s["loader"], "name": "BepInEx (chargeur de mods)",
                      "version": latest["version_number"], "kind": "loader", "auto": True, "icon": latest.get("icon", ""),
                      "summary": "Charge les mods au démarrage du serveur. Installé automatiquement.",
                      "url": pkg.get("package_url", ""), "files": [t for t in tops if t != "BepInEx"] + ["BepInEx/core"]})


def _ensure_oxide(inst, data, job):
    key = "umod:oxide"
    if key in data["entries"] and os.path.isdir(os.path.join(inst.server_dir, "RustDedicated_Data", "Managed")) \
            and os.path.exists(os.path.join(inst.server_dir, "RustDedicated_Data", "Managed", "Oxide.Core.dll")):
        return
    job.log("Installation d'Oxide (uMod), le chargeur de plugins de Rust…")
    release = runtime.fetch_json("https://api.github.com/repos/%s/releases/latest" % OXIDE)
    wanted = "Oxide.Rust-linux.zip" if games.platform(inst.game) == "linux" else "Oxide.Rust.zip"
    asset = next((a for a in release.get("assets", []) if a["name"] == wanted), None)
    if not asset:
        raise ModError("Oxide n'est pas publié pour cette plateforme")
    with tempfile.TemporaryDirectory(dir=inst.dir) as tmp:
        archive = os.path.join(tmp, "oxide.zip")
        _download(asset["browser_download_url"], archive, job, "Oxide %s" % release.get("tag_name", ""))
        files = _extract(archive, lambda n: n, inst.server_dir)
    os.makedirs(os.path.join(inst.server_dir, "oxide", "plugins"), exist_ok=True)
    _add_entry(data, {"key": key, "provider": "umod", "project": "oxide", "name": "Oxide (chargeur de plugins)",
                      "version": release.get("tag_name", ""), "kind": "loader", "auto": True, "icon": "",
                      "summary": "À réinstaller après chaque mise à jour de Rust (bouton « Mettre à jour »).",
                      "url": "https://umod.org/games/rust", "files": files})


def _install_umod(inst, s, data, slug, job):
    if not re.match(r"^[a-z0-9-]{1,80}$", slug):
        raise ModError("Plugin invalide")
    key = "umod:" + slug
    info = runtime.fetch_json("%s/plugins/%s.json" % (UMOD, slug))
    url = info.get("download_url", "")
    name = url.rsplit("/", 1)[-1]
    if not re.match(r"^[A-Za-z0-9_]+\.cs$", name) or not url.startswith(UMOD + "/"):
        raise ModError("Plugin sans fichier téléchargeable")
    rel = s["dir"] + "/" + name
    current = data["entries"].get(key)
    if current:
        _remove_files(inst, current)
    os.makedirs(os.path.join(inst.server_dir, s["dir"]), exist_ok=True)
    _download(url, os.path.join(inst.server_dir, rel), job, info.get("title", slug))
    _add_entry(data, {"key": key, "provider": "umod", "project": slug, "name": info.get("title", slug),
                      "version": info.get("latest_release_version_formatted", ""), "kind": "plugin", "auto": True,
                      "icon": info.get("icon_url") or "", "summary": info.get("description", ""),
                      "url": "%s/plugins/%s" % (UMOD, slug), "files": [rel]})


def _install_workshop(inst, s, text):
    ids = _expand_collections(_parse_workshop_ids(text))
    if not ids:
        raise ModError("Numéro ou lien du Workshop non reconnu")
    try:
        details = _workshop_details(ids[:100])
    except Exception as ex:  # noqa: BLE001
        raise ModError("Steam ne répond pas (%s)" % ex)
    added = []
    with _lock(inst):
        data = _load(inst)
        for d in details:
            if d.get("result") != 1 or str(d.get("consumer_app_id")) != str(s["appid"]):
                continue
            mod_ids = []
            if s.get("mod_ids"):
                for m in MOD_ID_LINE.findall(d.get("description", "")):
                    if m not in mod_ids:
                        mod_ids.append(m.strip(".,;"))
            _add_entry(data, {"key": "workshop:" + d["publishedfileid"], "provider": "workshop", "project": d["publishedfileid"],
                              "name": d.get("title", d["publishedfileid"]), "version": "", "kind": "workshop", "auto": True,
                              "icon": d.get("preview_url", ""), "summary": _strip_bbcode(d.get("description", ""))[:200],
                              "url": "https://steamcommunity.com/sharedfiles/filedetails/?id=%s" % d["publishedfileid"],
                              "items": [d["publishedfileid"]], "mod_ids": mod_ids, "files": []})
            added.append(d.get("title", d["publishedfileid"]))
        if not added:
            raise ModError("Aucun objet de ce jeu dans ce lien")
        _sync_workshop(inst, s, data)
        _save(inst, data)
    return "%d objet(s) ajouté(s) : %s. Le serveur les télécharge au prochain démarrage." % (len(added), ", ".join(added[:5]))


def _pz_mod_value(inst, mod_id):
    """Project Zomboid Build 42 attend « \\ModID » ; Build 41 (branche legacy41) l'identifiant seul."""
    return mod_id if inst.meta().get("version") == "legacy41" else "\\" + mod_id


def _sync_workshop(inst, s, data):
    """Réécrit les listes d'objets dans la config du jeu, en gardant celles ajoutées à la main hors de LANa."""
    enabled = [e for e in data["entries"].values() if e["provider"] == "workshop" and e.get("enabled", True)]
    for target in s.get("targets", []):
        what = target["what"]
        values = []
        for e in enabled:
            for v in e.get("items" if what == "items" else "mod_ids", []):
                v = _pz_mod_value(inst, v) if target.get("prefix_pz") else v
                if v not in values:
                    values.append(v)
        tag = target.get("file", "") + "|" + target.get("key", target.get("json_list", ""))
        before = set(data["written"].get(tag, []))
        existing = _read_target(inst, target)
        final = [v for v in existing if v not in before and v not in values] + values
        _write_target(inst, target, final)
        data["written"][tag] = values


def _target_path(inst, target):
    rel = target.get("file") or inst.game["config"]["file"]
    return _inside(inst.server_dir, rel)


def _read_target(inst, target):
    path = _target_path(inst, target)
    if not os.path.exists(path):
        return []
    if "json_list" in target:
        try:
            with open(path, encoding="utf-8-sig") as fh:
                return [str(v) for v in json.load(fh).get(target["json_list"], [])]
        except (OSError, ValueError, AttributeError):
            return []
    section, key = _split_key(target["key"])
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        current = ""
        for line in fh.read().splitlines():
            st = line.strip()
            if st.startswith("[") and st.endswith("]"):
                current = st[1:-1]
            elif "=" in st and current == section and st.partition("=")[0].strip() == key:
                return [v for v in st.partition("=")[2].strip().split(target["sep"]) if v]
    return []


def _split_key(full):
    m = re.match(r"^\[([^\]]+)\](.+)$", full)
    return (m.group(1), m.group(2)) if m else ("", full)


def _write_target(inst, target, values):
    path = _target_path(inst, target)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if "json_list" in target:
        doc = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8-sig") as fh:
                    doc = json.load(fh)
            except (OSError, ValueError):
                doc = {}
        doc[target["json_list"]] = [int(v) if v.isdigit() else v for v in values]
        text = json.dumps(doc, indent=2)
    else:
        section, key = _split_key(target["key"])
        lines = []
        if os.path.exists(path):
            with open(path, encoding="utf-8-sig", errors="replace") as fh:
                lines = fh.read().splitlines()
        new = "%s=%s" % (key, target["sep"].join(values))
        current, done, out, section_end = "", False, [], None
        for line in lines:
            st = line.strip()
            if st.startswith("[") and st.endswith("]"):
                current = st[1:-1]
            elif "=" in st and current == section and st.partition("=")[0].strip() == key and not done:
                line, done = new, True
            out.append(line)
            if current == section:
                section_end = len(out)
        if not done:
            if section and section_end is None:
                out += ([""] if out else []) + ["[%s]" % section]
                section_end = len(out)
            out.insert(section_end if section_end is not None else len(out), new)
        text = "\n".join(out) + "\n"
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(path + ".tmp", path)


def set_mod_ids(inst, key, mod_ids):
    """Utilisateurs avancés : identifiants de mods (Project Zomboid) d'un objet du Workshop, corrigés à la main."""
    s = _need_spec(inst)
    clean = [m for m in (str(x).strip().lstrip("\\") for x in mod_ids) if re.match(r"^[A-Za-z0-9 _.'&()-]{1,80}$", m)]
    with _lock(inst):
        data = _load(inst)
        e = data["entries"].get(key)
        if not e or e["provider"] != "workshop":
            raise ModError("Objet introuvable")
        e["mod_ids"] = clean
        _sync_workshop(inst, s, data)
        _save(inst, data)
    return "Identifiants enregistrés"


# ---------- manuel ----------

def upload(inst, tmp_path, filename):
    """Dépose un fichier de mod (ou une archive .zip, extraite) dans le dossier des mods."""
    s = _need_spec(inst)
    rel_dir = mods_dir(inst)
    if not rel_dir:
        raise ModError("Choisissez d'abord un moteur : Fabric pour les mods, Paper pour les plugins"
                       if s["provider"] == "modrinth" else "Ce jeu ne prend pas de fichiers de mods")
    name = os.path.basename(filename or "")
    ext = os.path.splitext(name)[1].lower()
    allowed = [".jar"] if s["provider"] == "modrinth" else [e.lower() for e in s.get("extensions", [".zip"])]
    if ext not in allowed:
        raise ModError("Format non accepté ici : %s (attendu : %s)" % (ext or "sans extension", ", ".join(allowed)))
    if not re.match(r"^[A-Za-z0-9 ._+()\[\]'-]{1,120}$", name):
        raise ModError("Nom de fichier refusé : %s" % name)
    key = "manual:" + name
    with _lock(inst):
        data = _load(inst)
        old = data["entries"].get(key)
        if old:
            _remove_files(inst, old)
        folder = os.path.join(inst.server_dir, rel_dir)
        os.makedirs(folder, exist_ok=True)
        if ext == ".zip":
            if not zipfile.is_zipfile(tmp_path):
                raise ModError("Ce fichier .zip est illisible")
            members = _zip_members(tmp_path)
            stem = _safe_name(os.path.splitext(name)[0])
            if s["provider"] == "thunderstore":
                mapping = _thunderstore_mapping(members, stem)
            else:
                tops = {m.filename.split("/")[0] for m in members}
                single = len(tops) == 1 and any("/" in m.filename for m in members)
                # Une archive qui contient déjà son dossier est posée telle quelle ; sinon dans un dossier à son nom.
                mapping = (lambda n: rel_dir + "/" + n) if single else (lambda n: "%s/%s/%s" % (rel_dir, stem, n))
            files = _extract(tmp_path, mapping, inst.server_dir)
            tops = sorted({"/".join(f.split("/")[:len(rel_dir.split("/")) + 1]) for f in files
                           if f.startswith(rel_dir + "/")} | {f for f in files if not f.startswith(rel_dir + "/")})
        else:
            shutil.copyfile(tmp_path, os.path.join(folder, name))
            tops = [rel_dir + "/" + name]
        _add_entry(data, {"key": key, "provider": "manual", "project": name, "name": name, "version": "", "kind": "manual",
                          "auto": False, "icon": "", "summary": "Ajouté à la main", "url": "", "files": tops,
                          "loader": mc_loader(inst) if s["provider"] == "modrinth" else None})
        _save(inst, data)
    return "%s ajouté%s" % (name, " : redémarrez le serveur pour le charger" if inst.running() else "")


# ---------- activer, désactiver, retirer ----------

def _found_entry(inst, data, key):
    rel = key[len("found:"):]
    if rel not in _found_files(inst, data):
        raise ModError("Fichier introuvable")
    return {"key": key, "provider": "manual", "project": os.path.basename(rel), "name": os.path.basename(rel),
            "kind": "manual", "auto": False, "files": [rel], "enabled": True, "loader": mc_loader(inst)}


def toggle(inst, key, enabled):
    with _lock(inst):
        data = _load(inst)
        if key.startswith("found:"):   # fichier déposé hors de LANa : on le prend en charge au premier geste
            data["entries"]["manual:" + key[6:]] = e = dict(_found_entry(inst, data, key), key="manual:" + key[6:])
        else:
            e = data["entries"].get(key)
        if not e:
            raise ModError("Mod introuvable")
        if e["kind"] == "loader" and not enabled:
            raise ModError("Le chargeur ne se désactive pas : désactivez les mods eux-mêmes, ou retirez-le")
        if bool(e.get("enabled", True)) != bool(enabled):
            src, dst = (inst.server_dir, _disabled_dir(inst, e["key"])) if not enabled else (_disabled_dir(inst, e["key"]), inst.server_dir)
            for rel in e.get("files", []):
                a, b = _inside(src, rel), _inside(dst, rel)
                if os.path.exists(a):
                    os.makedirs(os.path.dirname(b), exist_ok=True)
                    if os.path.exists(b):
                        shutil.rmtree(b) if os.path.isdir(b) else os.remove(b)
                    shutil.move(a, b)
            if enabled:
                shutil.rmtree(_disabled_dir(inst, e["key"]), ignore_errors=True)
            e["enabled"] = bool(enabled)
        if e["provider"] == "workshop":
            _sync_workshop(inst, spec(inst.game), data)
        _save(inst, data)
    return "%s %s%s" % (e["name"], "activé" if enabled else "désactivé", " : redémarrez le serveur pour l'appliquer" if inst.running() else "")


def remove(inst, key):
    with _lock(inst):
        data = _load(inst)
        if key.startswith("found:"):
            e = _found_entry(inst, data, key)
        else:
            e = data["entries"].get(key)
        if not e:
            raise ModError("Mod introuvable")
        users = [data["entries"][k]["name"] for k in e.get("required_by", []) if k in data["entries"]]
        if users:
            raise ModError("%s est nécessaire à : %s. Retirez-les d'abord." % (e["name"], ", ".join(users)))
        if e["kind"] == "loader" and any(x["kind"] != "loader" and x.get("provider") == e["provider"] for x in data["entries"].values()):
            raise ModError("Retirez d'abord les mods qui utilisent ce chargeur")
        _remove_files(inst, e)
        data["entries"].pop(e["key"], None)
        for other in data["entries"].values():   # dépendances orphelines : elles restent, mais ne sont plus « requises »
            if e["key"] in other.get("required_by", []):
                other["required_by"].remove(e["key"])
        if e["provider"] == "workshop":
            _sync_workshop(inst, spec(inst.game), data)
        _save(inst, data)
    return "%s retiré" % e["name"]


# ---------- mises à jour ----------

def _latest(inst, s, e):
    if e["provider"] == "modrinth":
        found = _modrinth_versions(inst, e["project"])
        stable = [v for v in found if v.get("version_type") == "release"] or found
        return stable[0]["version_number"] if stable else None
    if e["provider"] == "thunderstore":
        return _thunderstore_package(e["project"])["latest"]["version_number"]
    if e["provider"] == "umod":
        if e["project"] == "oxide":
            return runtime.fetch_json("https://api.github.com/repos/%s/releases/latest" % OXIDE).get("tag_name")
        return runtime.fetch_json("%s/plugins/%s.json" % (UMOD, e["project"])).get("latest_release_version_formatted")
    return None


def check_updates(inst):
    """Mods qui ont une version plus récente : {clé: nouvelle version}."""
    s = _need_spec(inst)
    with _lock(inst):
        entries = [dict(e) for e in _load(inst)["entries"].values() if e.get("auto") and e["provider"] != "workshop"
                   and e.get("enabled", True) and not e.get("pinned") and e.get("loader") in (None, mc_loader(inst))]
    out = {}
    for e in entries:
        try:
            latest = _latest(inst, s, e)
        except Exception:  # noqa: BLE001 - un mod retiré de sa source ne bloque pas les autres
            continue
        if latest and latest != e.get("version"):
            out[e["key"]] = latest
    return out


def update(inst, keys=None):
    """Met à jour les mods demandés (tous ceux qui ont du nouveau par défaut) ; retourne la tâche."""
    s = _need_spec(inst)

    def work(job):
        wanted = check_updates(inst)
        todo = [k for k in wanted if keys is None or k in keys]
        if not todo:
            job.log("Tout est à jour.")
            return
        with _lock(inst):
            data = _load(inst)
            for k in todo:
                e = data["entries"].get(k)
                if not e:
                    continue
                job.log("Mise à jour de %s : %s → %s" % (e["name"], e.get("version") or "?", wanted[k]))
                needed = e.get("required_by", [])
                if e["provider"] == "modrinth":
                    _install_modrinth(inst, data, e["project"], None, job, required_by=None)
                elif e["provider"] == "thunderstore":
                    if e["kind"] == "loader":
                        data["entries"].pop(k)
                        _ensure_bepinex(inst, s, data, job)
                    else:
                        _install_thunderstore(inst, s, data, e["project"], job, required_by=None, seen=set())
                elif e["provider"] == "umod":
                    if e["project"] == "oxide":
                        data["entries"].pop(k)
                        _ensure_oxide(inst, data, job)
                    else:
                        _install_umod(inst, s, data, e["project"], job)
                data["entries"][k]["required_by"] = sorted(set(data["entries"][k].get("required_by", [])) | set(needed))
                _save(inst, data)
        job.log("Mises à jour terminées." + (" Redémarrez le serveur pour les charger." if inst.running() else ""))
    return jobs.start("Mise à jour des mods", work)


# ---------- moteur Minecraft ----------

def set_loader(inst, loader):
    """Installe Fabric ou Paper (ou revient à vanilla) ; serveur arrêté. Retourne la tâche."""
    s = _need_spec(inst)
    if s["provider"] != "modrinth" or loader not in MC_LOADERS:
        raise ModError("Moteur inconnu")
    if inst.running():
        raise ModError("Arrêtez le serveur avant de changer de moteur")

    def work(job):
        _install_loader(inst, loader, job)
        meta = inst.meta()
        meta["mc_loader"] = loader
        inst._save_meta(meta)
        job.log("Moteur : %s." % MC_LOADERS[loader]["label"])
    return jobs.start("Moteur Minecraft : %s" % MC_LOADERS[loader]["label"], work)


def _install_loader(inst, loader, job):
    mc = inst.meta().get("version")
    if loader == "vanilla":
        return
    if not mc:
        raise ModError("Version de Minecraft inconnue : réinstallez une version depuis la section Version")
    if loader == "fabric":
        loaders = runtime.fetch_json("%s/loader/%s" % (FABRIC_META, mc))
        stable = [l for l in loaders if l["loader"].get("stable")] or loaders
        if not stable:
            raise ModError("Fabric n'existe pas pour Minecraft %s" % mc)
        installers = runtime.fetch_json("%s/installer" % FABRIC_META)
        inst_v = next((i for i in installers if i.get("stable")), installers[0])["version"]
        url = "%s/loader/%s/%s/%s/server/jar" % (FABRIC_META, mc, stable[0]["loader"]["version"], inst_v)
        runtime.download(url, os.path.join(inst.server_dir, MC_LOADERS["fabric"]["jar"]), job,
                         "Fabric %s pour Minecraft %s" % (stable[0]["loader"]["version"], mc))
        with open(os.path.join(inst.server_dir, "fabric-server-launcher.properties"), "w", encoding="utf-8") as fh:
            fh.write("serverJar=server.jar\n")
    elif loader == "paper":
        try:
            build = runtime.fetch_json(PAPER % mc)
        except Exception:  # noqa: BLE001
            raise ModError("Paper n'existe pas (encore) pour Minecraft %s" % mc)
        d = build["downloads"]["server:default"]
        _download(d["url"], os.path.join(inst.server_dir, MC_LOADERS["paper"]["jar"]), job,
                  "Paper %s (build %s)" % (mc, build.get("id")), sha256=d.get("checksums", {}).get("sha256"))


def after_install(inst, job):
    """Après une (ré)installation du jeu : Minecraft garde son moteur, à la nouvelle version ; Oxide est réinstallé."""
    s = spec(inst.game)
    if not s:
        return
    if s["provider"] == "modrinth" and mc_loader(inst) != "vanilla":
        job.log("Le moteur %s suit la nouvelle version." % MC_LOADERS[mc_loader(inst)]["label"])
        _install_loader(inst, mc_loader(inst), job)
        job.log("Les mods installés pour une autre version de Minecraft peuvent ne plus se charger : "
                "« Rechercher les mises à jour » dans la section Mods.")
    elif s["provider"] == "umod":
        with _lock(inst):
            data = _load(inst)
            if "umod:oxide" in data["entries"]:
                job.log("Rust a été mis à jour : réinstallation d'Oxide.")
                data["entries"].pop("umod:oxide")
                _ensure_oxide(inst, data, job)
                _save(inst, data)


def launch_overrides(inst):
    """Ce qui change au lancement : fichier .jar du moteur Minecraft, chargeur BepInEx sous Wine, arguments."""
    s = spec(inst.game)
    out = {"replace": {}, "env": {}, "args": []}
    if not s:
        return out
    if s["provider"] == "modrinth":
        jar = MC_LOADERS[mc_loader(inst)]["jar"]
        if jar != "server.jar" and os.path.exists(os.path.join(inst.server_dir, jar)):
            out["replace"]["server.jar"] = jar
    elif s["provider"] == "thunderstore" and os.path.exists(os.path.join(inst.server_dir, "winhttp.dll")):
        if system.uses_wine(games.run_spec(inst.game)["runtime"]):
            out["env"]["WINEDLLOVERRIDES"] = "winhttp=n,b"   # Wine doit charger le winhttp.dll de BepInEx
    elif s["provider"] == "workshop" and s.get("args"):
        data = _load(inst)
        if any(e["provider"] == "workshop" and e.get("enabled", True) for e in data["entries"].values()):
            out["args"] = list(s["args"])
    return out


# ---------- réglages des mods (utilisateurs avancés) ----------

def _config_roots(inst):
    s = spec(inst.game) or {}
    roots = list(s.get("config_dirs", []))
    if s.get("provider") == "modrinth":
        roots = ["config"] if mc_loader(inst) == "fabric" else ["plugins"] if mc_loader(inst) == "paper" else []
    return roots


def config_files(inst):
    out = []
    for root in _config_roots(inst):
        base = os.path.join(inst.server_dir, root)
        if not os.path.isdir(base):
            continue
        for dirpath, dirs, files in os.walk(base):
            depth = os.path.relpath(dirpath, base).count(os.sep)
            if depth >= 3:
                dirs[:] = []
            for name in sorted(files):
                path = os.path.join(dirpath, name)
                if name.lower().endswith(CONFIG_EXT) and os.path.getsize(path) <= MAX_CONFIG_BYTES:
                    out.append(os.path.relpath(path, inst.server_dir).replace(os.sep, "/"))
            if len(out) > 300:
                return sorted(out)
    return sorted(out)


def _config_path(inst, rel):
    if rel not in config_files(inst):
        raise ModError("Fichier de réglages introuvable : %s" % rel)
    return _inside(inst.server_dir, rel)


def read_config(inst, rel):
    with open(_config_path(inst, rel), encoding="utf-8", errors="replace") as fh:
        return fh.read()


def write_config(inst, rel, text):
    path = _config_path(inst, rel)
    if len(text.encode("utf-8")) > MAX_CONFIG_BYTES:
        raise ModError("Fichier trop volumineux")
    shutil.copy2(path, path + ".bak")
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(path + ".tmp", path)
    return "%s enregistré (copie de l'ancien : .bak)%s" % (os.path.basename(rel), " : redémarrez le serveur pour l'appliquer" if inst.running() else "")
