"""Différences entre macOS, Linux et Windows, regroupées au même endroit."""
import ctypes
import os
import platform
import re
import socket
import subprocess
import sys

PLATFORM = sys.platform
IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
# Android (Termux) : noyau Linux, mais sans glibc ; Python y annonce « android » ou « linux » selon sa version.
IS_ANDROID = sys.platform == "android" or "com.termux" in os.environ.get("PREFIX", "")
IS_LINUX = sys.platform.startswith("linux") or IS_ANDROID
IS_ARM = platform.machine().lower() in ("aarch64", "arm64", "armv7l", "armv8l", "arm")
# Linux sur ARM (téléphone, Raspberry Pi) : les serveurs compilés pour x86, Windows ou Linux, ne s'y lancent pas.
# Les Mac Apple Silicon ne sont pas concernés : Rosetta 2 y fait tourner Wine.
X86_ONLY_BLOCKED = IS_LINUX and IS_ARM


def tool_dirs():
    """Dossiers où chercher wine, java… : un lancement hors terminal n'a pas le PATH de l'utilisateur."""
    if IS_MAC:
        return ["/opt/local/bin", "/usr/local/bin", "/opt/homebrew/bin", "/usr/bin", "/bin"]
    if IS_ANDROID:
        return [os.path.join(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"), "bin")]
    if IS_LINUX:
        return ["/usr/local/bin", "/usr/bin", "/bin", "/usr/games"]
    return []


def getprop(key):
    """Propriété système Android (ex. ro.build.version.release), ou chaîne vide."""
    try:
        return subprocess.run(["getprop", key], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def uses_wine(runtime):
    """Les jeux Windows tournent sous Wine, sauf sous Windows où ils tournent tels quels."""
    return runtime == "wine" and not IS_WINDOWS


def os_label():
    if IS_MAC:
        return "macOS " + platform.mac_ver()[0]
    if IS_WINDOWS:
        return "Windows " + platform.release()
    if IS_ANDROID:
        return ("Android %s (Termux)" % getprop("ro.build.version.release")).replace("  ", " ")
    if IS_LINUX:
        try:
            with open("/etc/os-release", encoding="utf-8") as fh:
                match = re.search(r'^PRETTY_NAME="?([^"\n]+)', fh.read(), re.M)
            if match:
                return match.group(1)
        except OSError:
            pass
    return platform.system()


def parse_meminfo(text):
    """RAM totale en octets d'après /proc/meminfo, ou None."""
    match = re.search(r"^MemTotal:\s+(\d+)\s+kB", text, re.M)
    return int(match.group(1)) * 1024 if match else None


def parse_cpuinfo(text):
    match = re.search(r"^model name\s*:\s*(.+)$", text, re.M)
    return match.group(1).strip() if match else ""


def _sysctl(key):
    try:
        return subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _windows_ram_bytes():
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                    ("avail", ctypes.c_ulonglong), ("pagefile", ctypes.c_ulonglong), ("pagefile_free", ctypes.c_ulonglong),
                    ("virtual", ctypes.c_ulonglong), ("virtual_free", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
    status = MemoryStatus()
    status.length = ctypes.sizeof(MemoryStatus)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return status.total
    return None


def ram_bytes():
    if IS_MAC:
        mem = _sysctl("hw.memsize")
        return int(mem) if mem.isdigit() else None
    if IS_LINUX:
        return parse_meminfo(_read("/proc/meminfo"))
    if IS_WINDOWS:
        try:
            return _windows_ram_bytes()
        except (OSError, AttributeError):
            return None
    return None


def cpu_name():
    name = ""
    if IS_MAC:
        name = _sysctl("machdep.cpu.brand_string")
    elif IS_ANDROID:
        name = getprop("ro.soc.model") or getprop("ro.hardware") or parse_cpuinfo(_read("/proc/cpuinfo"))
    elif IS_LINUX:
        name = parse_cpuinfo(_read("/proc/cpuinfo"))
    return name or platform.processor()


def lan_ip():
    """Adresse de la machine sur le réseau local (aucun paquet n'est envoyé)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))   # adresse de documentation : sert seulement à choisir l'interface
            ip = sock.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    if IS_MAC:
        for iface in ("en0", "en1"):
            try:
                ip = subprocess.run(["ipconfig", "getifaddr", iface], capture_output=True, text=True, timeout=5).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                return ""
            if ip:
                return ip
    return ""
