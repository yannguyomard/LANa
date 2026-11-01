"""Exécution des serveurs : Wine, SteamCMD, lancement et arrêt de processus."""
import os
import signal
import subprocess
import time
import urllib.request
import zipfile

from . import machine, paths

STEAMCMD_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"


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


def start_process(game, server_dir, prefix, log_path):
    """Lance le serveur dans son propre groupe de processus ; retourne le Popen."""
    run = game["run"]
    cmd = list(run["command"])
    env = dict(os.environ)
    if run["runtime"] == "wine":
        cmd = [machine.find_tool("wine")] + cmd
        env = wine_env(prefix)
    elif run["runtime"] == "java":
        cmd = [machine.find_tool("java")] + cmd
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


def stop_group(pgid, runtime, prefix, wait=30):
    """Arrêt propre (SIGTERM) puis forcé ; sous Wine, on termine aussi wineserver."""
    try:
        os.killpg(pgid, signal.SIGTERM)
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
