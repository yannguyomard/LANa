"""Exécution des serveurs : Wine, SteamCMD, lancement et arrêt de processus."""
import hashlib
import json
import os
import signal
import subprocess
import tarfile
import time
import urllib.request
import zipfile

from . import machine, paths

STEAMCMD_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
ADOPTIUM_JRE = "https://api.adoptium.net/v3/binary/latest/%d/ga/mac/x64/jre/hotspot/normal/eclipse"
USER_AGENT = "LANa"


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def download(url, dest, job, label, sha1=None):
    """Télécharge url vers dest (par blocs, avec progression) et vérifie l'empreinte SHA-1 si fournie."""
    job.log("Téléchargement : %s…" % label)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest, done, last_pct = hashlib.sha1(), 0, -1
    tmp = dest + ".part"
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length", 0))
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if total and done * 10 // total != last_pct:
                last_pct = done * 10 // total
                job.log("  %d %%" % (last_pct * 10))
    if sha1 and digest.hexdigest() != sha1:
        os.remove(tmp)
        raise RuntimeError("Empreinte incorrecte pour %s : téléchargement corrompu ou altéré." % label)
    os.replace(tmp, dest)


def _safe_extract(tar_path, dest):
    """Extrait une archive en refusant tout membre qui sortirait de dest (liens compris)."""
    base = os.path.realpath(dest)
    with tarfile.open(tar_path) as tar:
        for m in tar.getmembers():
            target = os.path.realpath(os.path.join(base, m.name))
            if target != base and not target.startswith(base + os.sep):
                raise RuntimeError("Archive invalide : %s" % m.name)
            if m.issym() or m.islnk():
                link = os.path.realpath(os.path.join(os.path.dirname(target), m.linkname))
                if not link.startswith(base + os.sep):
                    raise RuntimeError("Archive invalide : lien vers l'extérieur (%s)" % m.name)
        tar.extractall(base)


def ensure_java(min_major, job):
    """Chemin d'un Java >= min_major ; télécharge un JRE portable (Eclipse Temurin) dans ~/LANa si besoin."""
    found = machine.find_java(min_major)
    if found:
        return found
    job.log("Java %d introuvable : installation d'un JRE portable (Eclipse Temurin), sans toucher au système." % min_major)
    folder = os.path.join(paths.TOOLS_DIR, "java")
    os.makedirs(folder, exist_ok=True)
    archive = os.path.join(folder, "jre-%d.tar.gz" % min_major)
    download(ADOPTIUM_JRE % min_major, archive, job, "Java %d (environ 50 Mo)" % min_major)
    _safe_extract(archive, folder)
    os.remove(archive)
    found = machine.find_java(min_major)
    if not found:
        raise RuntimeError("Le JRE téléchargé ne s'exécute pas sur cette machine.")
    return found


def mojang_install(game, server_dir, job, version=None):
    """Télécharge server.jar (Mojang) pour `version` (dernière version stable par défaut).

    Retourne {"version": ..., "java_min": ...}. L'acceptation du CLUF est gérée par l'appelant.
    """
    spec = game["install"]
    manifest = fetch_json(MOJANG_MANIFEST)
    version = version or manifest["latest"]["release"]
    entry = next((v for v in manifest["versions"] if v["id"] == version), None)
    if not entry:
        raise RuntimeError("Version Minecraft inconnue : %s" % version)
    meta = fetch_json(entry["url"])
    server = meta["downloads"].get("server")
    if not server:
        raise RuntimeError("Mojang ne propose pas de serveur pour la version %s." % version)
    java_min = meta.get("javaVersion", {}).get("majorVersion", 8)
    ensure_java(java_min, job)
    os.makedirs(server_dir, exist_ok=True)
    download(server["url"], os.path.join(server_dir, spec["check_file"]), job,
             "serveur Minecraft %s (%d Mo)" % (version, server["size"] // 2**20), sha1=server["sha1"])
    return {"version": version, "java_min": java_min}


def wine_env(prefix):
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(paths.TOOL_DIRS + [env.get("PATH", "")])
    env["WINEPREFIX"] = prefix
    env["WINEARCH"] = "win64"
    env["WINEDEBUG"] = "-all"
    return env


def init_prefix(prefix, job):
    if os.path.isdir(os.path.join(prefix, "drive_c")):
        return
    wine = machine.find_tool("wine")
    if not wine:
        raise RuntimeError("Wine n'est pas installé.")
    job.log("Création de l'environnement Wine (une minute environ)…")
    os.makedirs(prefix, exist_ok=True)
    subprocess.run([wine, "wineboot", "-i"], env=wine_env(prefix), capture_output=True, timeout=600)
    if not os.path.isdir(os.path.join(prefix, "drive_c")):
        raise RuntimeError("Wine n'a pas pu créer son environnement.")


def ensure_steamcmd(job):
    """Télécharge SteamCMD pour Windows (outil officiel de Valve) s'il est absent."""
    folder = os.path.join(paths.TOOLS_DIR, "steamcmd")
    exe = os.path.join(folder, "steamcmd.exe")
    if os.path.exists(exe):
        return exe
    job.log("Téléchargement de SteamCMD (Valve)…")
    os.makedirs(folder, exist_ok=True)
    archive = os.path.join(folder, "steamcmd.zip")
    urllib.request.urlretrieve(STEAMCMD_URL, archive)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(folder)
    return exe


def windows_path(path):
    return "Z:" + path.replace("/", "\\")


def steamcmd_install(game, server_dir, prefix, job):
    """Installe ou met à jour un serveur via SteamCMD sous Wine.

    SteamCMD se met à jour lui-même au premier lancement puis s'arrête : on relance
    jusqu'à ce que les fichiers du jeu soient là.
    """
    spec = game["install"]
    wine = machine.find_tool("wine")
    exe = ensure_steamcmd(job)
    os.makedirs(server_dir, exist_ok=True)
    check = os.path.join(server_dir, spec["check_file"])
    for attempt in range(1, 4):
        job.log("SteamCMD, passage %d : téléchargement du serveur (plusieurs Go)…" % attempt)
        cmd = [wine, exe, "+force_install_dir", windows_path(server_dir), "+login", "anonymous",
               "+app_update", str(spec["appid"]), "validate", "+quit"]
        proc = subprocess.Popen(cmd, cwd=os.path.dirname(exe), env=wine_env(prefix),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        last = ""
        for line in proc.stdout:
            line = line.strip()
            # Une ligne de progression par pas de 5 % suffit.
            if line.startswith("[") and "%" in line.split("]")[0]:
                tag = line[:5]
                if tag == last:
                    continue
                last = tag
            if line:
                job.log(line)
        proc.wait()
        if os.path.exists(check):
            return
    raise RuntimeError("SteamCMD n'a pas installé %s après 3 essais." % spec["check_file"])


def start_process(game, server_dir, prefix, log_path, settings=None, java_min=0):
    """Lance le serveur dans son propre groupe de processus ; retourne le Popen.

    `settings` remplit les {jetons} de la commande (ex. {memory_mb} pour la mémoire de Java).
    """
    run = game["run"]
    cmd = [a.format(**(settings or {})) if "{" in a else a for a in run["command"]]
    env = dict(os.environ)
    if run["runtime"] == "wine":
        cmd = [machine.find_tool("wine")] + cmd
        env = wine_env(prefix)
    elif run["runtime"] == "java":
        java = machine.find_java(java_min)
        if not java:
            raise RuntimeError("Java %d ou plus récent est requis." % java_min)
        cmd = [java] + cmd
    env.update(run.get("env", {}))
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    log = open(log_path, "ab")
    log.write(("\n===== Démarrage %s =====\n" % time.strftime("%Y-%m-%d %H:%M:%S")).encode())
    log.flush()
    try:
        return subprocess.Popen(cmd, cwd=os.path.join(server_dir, run.get("cwd", ".")), env=env,
                                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True)
    finally:
        log.close()  # le processus enfant garde sa propre copie du descripteur


def group_alive(pgid):
    # Le chef de groupe a pour pid le pgid : on récupère son état de sortie, sinon il reste
    # zombie et le groupe paraît vivant. ChildProcessError = ce n'est pas notre enfant.
    try:
        os.waitpid(pgid, os.WNOHANG)
    except ChildProcessError:
        pass
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def stop_group(pgid, runtime, prefix, wait=30, sig=signal.SIGTERM):
    """Arrêt propre (`sig`, SIGTERM par défaut) puis forcé ; sous Wine, on termine aussi wineserver."""
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass
    for _ in range(wait):
        if not group_alive(pgid):
            break
        time.sleep(1)
    if group_alive(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if runtime == "wine":
        wineserver = machine.find_tool("wine")
        if wineserver:
            subprocess.run([os.path.join(os.path.dirname(wineserver), "wineserver"), "-k"],
                           env=wine_env(prefix), capture_output=True)
    time.sleep(1)
    return not group_alive(pgid)
