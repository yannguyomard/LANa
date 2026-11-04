#!/bin/sh
# Essai de démarrage d'une AppImage sans bureau : écran virtuel (Xvfb), attente de la fenêtre « LANa », capture d'écran.
# Usage : sh packaging/linux/smoke-test.sh LANa-….AppImage   → résultat dans packaging/linux/build/smoke/
# Nécessite : xvfb, xdotool, imagemagick (commande `import`) et les bibliothèques X11 de Qt (libxcb-cursor0…).
set -eu
APPIMAGE=$(readlink -f "$1")
OUT="$(cd "$(dirname "$0")" && pwd)/build/smoke"
mkdir -p "$OUT"
export LANA_HOME="$(mktemp -d)"   # aucun serveur, aucune donnée de l'utilisateur
export APPIMAGE_EXTRACT_AND_RUN=1
export QT_QPA_PLATFORM=xcb
status=0
xvfb-run -a -s "-screen 0 1400x900x24" sh -c '
  "$0" >"$1/app.log" 2>&1 &
  pid=$!
  found=
  for i in $(seq 1 120); do
    if xdotool search --onlyvisible --name LANa >/dev/null 2>&1; then found=1; break; fi
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  sleep 4
  import -window root "$1/ecran.png" || true
  alive=
  kill -0 "$pid" 2>/dev/null && alive=1
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  [ -n "$found" ] && [ -n "$alive" ]
' "$APPIMAGE" "$OUT" || status=$?
echo "----- journal de l'appli -----"
cat "$OUT/app.log" || true
if [ "$status" -ne 0 ]; then echo "ÉCHEC : la fenêtre n'est pas apparue, ou l'appli s'est arrêtée seule." >&2; exit 1; fi
if grep -qE 'Traceback|Could not load the Qt platform plugin' "$OUT/app.log"; then echo "ÉCHEC : erreur dans le journal." >&2; exit 1; fi
echo "OK : la fenêtre LANa est apparue et l'appli tournait encore après quelques secondes."
