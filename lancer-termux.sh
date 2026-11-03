#!/data/data/com.termux/files/usr/bin/sh
# Lance LANa sur Android, dans Termux. Garde le téléphone éveillé tant que LANa tourne.
# Usage : sh lancer-termux.sh          (panneau sur le téléphone : http://localhost:8765)
#         sh lancer-termux.sh --lan    (panneau aussi accessible depuis les autres appareils du wifi)
cd "$(dirname "$0")" || exit 1
command -v python >/dev/null 2>&1 || { echo "Python manque : pkg install python"; exit 1; }
command -v java >/dev/null 2>&1 || echo "Java manque pour Minecraft : pkg install openjdk-21"
termux-wake-lock 2>/dev/null
trap 'termux-wake-unlock 2>/dev/null' EXIT
python run.py "$@"
