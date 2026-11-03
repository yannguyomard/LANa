"""Détection de la machine et verdict de compatibilité d'un jeu."""
import glob
import os
import platform
import re
import shutil
import subprocess

from . import paths, system

# Outil nécessaire -> noms d'exécutables possibles
TOOLS = {"wine": ["wine", "wine64"], "java": ["java"],
         "luanti": ["luantiserver", "luanti", "minetestserver", "minetest"], "proot-distro": ["proot-distro"]}
# Applications macOS qui contiennent un outil (ex. Luanti installé par glisser-déposer ou Homebrew cask).
MAC_APPS = {"luanti": ["/Applications/Luanti.app/Contents/MacOS/luanti", "/Applications/minetest.app/Contents/MacOS/minetest"]}


def find_tool(name):
    """Chemin d'un outil (wine, java…) ou None. Pour java : le plus récent trouvé."""
    if name == "java":
        return find_java(0)
    search = os.pathsep.join(paths.TOOL_DIRS + [os.environ.get("PATH", "")])
    for exe in TOOLS.get(name, [name]):
        found = shutil.which(exe, path=search)
        if found:
            return found
    if system.IS_MAC:
        for path in MAC_APPS.get(name, []) + [os.path.expanduser("~" + p) for p in MAC_APPS.get(name, [])]:
            if os.access(path, os.X_OK):
                return path
    return None


def java_major(path):
    """Version majeure d'un Java (21, 25…), ou None s'il ne s'exécute pas.

    /usr/bin/java existe toujours sur macOS, même sans Java installé : on l'exécute pour le savoir.
    """
    try:
        proc = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_java_major(proc.stderr + proc.stdout) if proc.returncode == 0 else None


def parse_java_major(text):
    match = re.search(r'version "(\d+)(?:\.(\d+))?', text)
    if not match:
        return None
    major, minor = int(match.group(1)), match.group(2)
    return int(minor) if major == 1 and minor else major   # "1.8.0" désigne Java 8


def java_candidates():
    """Exécutables java possibles : JRE téléchargés par LANa, puis Java du système."""
    exe = "java.exe" if system.IS_WINDOWS else "java"
    layout = ("*", "Contents", "Home", "bin", exe) if system.IS_MAC else ("*", "bin", exe)   # le JRE macOS est un bundle
    found = sorted(glob.glob(os.path.join(paths.TOOLS_DIR, "java", *layout)))
    if os.environ.get("JAVA_HOME"):
        found.append(os.path.join(os.environ["JAVA_HOME"], "bin", exe))
    if system.IS_WINDOWS:
        for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if root:
                found += sorted(glob.glob(os.path.join(root, "*", "*", "bin", "java.exe")))   # Adoptium, Java, Zulu…
    search = os.pathsep.join(paths.TOOL_DIRS + [os.environ.get("PATH", "")])
    on_path = shutil.which("java", path=search)
    return [p for p in found if os.path.exists(p)] + ([on_path] if on_path else [])


def find_java(min_major):
    """Un Java d'au moins `min_major` (le plus récent), ou None."""
    best = None
    for path in java_candidates():
        major = java_major(path)
        if major is not None and major >= min_major and (best is None or major > best[0]):
            best = (major, path)
    return best[1] if best else None


def detect():
    ram = system.ram_bytes()
    probe = paths.HOME if os.path.isdir(paths.HOME) else os.path.expanduser("~")
    return {
        "ram_gb": round(ram / 2**30, 1) if ram else None,
        "disk_free_gb": round(shutil.disk_usage(probe).free / 2**30, 1),
        "cpu": system.cpu_name(),
        "arch": platform.machine(),
        "os": system.os_label(),
        "lan_ip": system.lan_ip(),
        "tools": {name: find_tool(name) for name in TOOLS if (name != "wine" or not system.IS_WINDOWS)
                  and (name != "proot-distro" or system.IS_ANDROID)},
    }


def verdict(requirements, needs, machine, compat=None):
    """Compare les besoins d'un jeu à la machine.

    Retourne {"level": "ok"|"warn"|"bad", "messages": [...], "missing": [outils]}.
    "bad" = le serveur ne tiendra probablement pas ; "warn" = il tournera, mais juste.
    `compat` ({"level", "note", "platforms"?}) déclare une incompatibilité constatée du jeu avec cette configuration.
    """
    level, messages = "ok", []

    def raise_to(new):
        nonlocal level
        if ("ok", "warn", "bad").index(new) > ("ok", "warn", "bad").index(level):
            level = new

    if compat and (not compat.get("platforms") or any(system.PLATFORM.startswith(p) for p in compat["platforms"])):
        # incompatibilité connue de ce jeu avec la configuration visée (constatée en test)
        raise_to(compat["level"])
        messages.append(compat["note"])
    ram = machine.get("ram_gb")
    if ram is not None:
        if ram < requirements.get("ram_gb_min", 0):
            raise_to("bad")
            messages.append("Mémoire insuffisante : %s Go disponibles, %s Go minimum requis." % (ram, requirements["ram_gb_min"]))
        elif ram < requirements.get("ram_gb_recommended", 0):
            raise_to("warn")
            messages.append("Mémoire juste : %s Go disponibles, %s Go recommandés. Prévoyez peu de joueurs." % (ram, requirements["ram_gb_recommended"]))
    need_disk = requirements.get("disk_gb", 0)
    if machine["disk_free_gb"] < need_disk * 1.2:
        raise_to("bad")
        messages.append("Espace disque insuffisant : %s Go libres, environ %s Go nécessaires." % (machine["disk_free_gb"], need_disk))
    missing = [t for t in needs if not machine["tools"].get(t)]
    if "java" in missing:
        messages.append("Java à installer dans Termux : « pkg install openjdk-21 » (ou plus récent selon la version du jeu)."
                        if system.IS_ANDROID else "Java sera téléchargé automatiquement (environ 50 Mo), sans toucher au système.")
        missing.remove("java")
    if missing:
        raise_to("warn")
        messages.append("Outil à installer : %s." % ", ".join(missing))
    if requirements.get("note"):
        messages.append(requirements["note"])
    return {"level": level, "messages": messages, "missing": missing}
