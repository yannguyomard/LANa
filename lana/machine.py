"""Détection de la machine et verdict de compatibilité d'un jeu."""
import os
import platform
import shutil
import subprocess

from . import paths

# Outil nécessaire -> noms d'exécutables possibles
TOOLS = {"wine": ["wine", "wine64"], "java": ["java"]}


def find_tool(name):
    """Chemin d'un outil (wine, java…) ou None."""
    search = os.pathsep.join(paths.TOOL_DIRS + [os.environ.get("PATH", "")])
    for exe in TOOLS.get(name, [name]):
        found = shutil.which(exe, path=search)
        if found and (name != "java" or _java_works(found)):
            return found
    return None


def _java_works(path):
    """/usr/bin/java existe toujours sur macOS, même sans Java : on vérifie qu'il s'exécute."""
    try:
        return subprocess.run([path, "-version"], capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _sysctl(key):
    try:
        return subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def lan_ip():
    try:
        for iface in ("en0", "en1"):
            ip = subprocess.run(["ipconfig", "getifaddr", iface], capture_output=True, text=True, timeout=5).stdout.strip()
            if ip:
                return ip
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def detect():
    mem = _sysctl("hw.memsize")
    probe = paths.HOME if os.path.isdir(paths.HOME) else os.path.expanduser("~")
    return {
        "ram_gb": round(int(mem) / 2**30, 1) if mem.isdigit() else None,
        "disk_free_gb": round(shutil.disk_usage(probe).free / 2**30, 1),
        "cpu": _sysctl("machdep.cpu.brand_string") or platform.processor(),
        "arch": platform.machine(),
        "macos": platform.mac_ver()[0],
        "lan_ip": lan_ip(),
        "tools": {name: find_tool(name) for name in TOOLS},
    }


def verdict(requirements, needs, machine):
    """Compare les besoins d'un jeu à la machine.

    Retourne {"level": "ok"|"warn"|"bad", "messages": [...], "missing": [outils]}.
    "bad" = le serveur ne tiendra probablement pas ; "warn" = il tournera, mais juste.
    """
    level, messages = "ok", []

    def raise_to(new):
        nonlocal level
        if ("ok", "warn", "bad").index(new) > ("ok", "warn", "bad").index(level):
            level = new

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
    if missing:
        raise_to("warn")
        messages.append("Outil à installer : %s." % ", ".join(missing))
    if requirements.get("note"):
        messages.append(requirements["note"])
    return {"level": level, "messages": messages, "missing": missing}
