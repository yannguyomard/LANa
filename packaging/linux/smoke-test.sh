#!/bin/sh
# Essai de démarrage d'une AppImage sans bureau : écran virtuel (Xvfb), attente de la fenêtre « LANa », capture d'écran.
# Usage : sh packaging/linux/smoke-test.sh LANa-….AppImage   → résultat dans packaging/linux/build/smoke/
# Nécessite : xvfb, xdotool, imagemagick (commande `import`) et les bibliothèques X11 de Qt (libxcb-cursor0…).
# L'essai échoue si la fenêtre n'apparaît pas, si l'appli s'arrête seule, ou s'il n'a laissé ni journal ni capture
# (un essai qui n'a pas vraiment tourné ne doit jamais passer pour réussi).
set -eu
APPIMAGE=$(readlink -f "$1")
OUT="$(cd "$(dirname "$0")" && pwd)/build/smoke"
mkdir -p "$OUT"
rm -f "$OUT/app.log" "$OUT/ecran.png"
export LANA_HOME="$(mktemp -d)"   # aucun serveur, aucune donnée de l'utilisateur
export APPIMAGE_EXTRACT_AND_RUN=1
export QT_QPA_PLATFORM=xcb

# Le script lancé dans l'écran virtuel est écrit dans un fichier : pas de guillemets imbriqués à surveiller.
cat > "$OUT/essai-interne.sh" <<'INNER'
#!/bin/sh
# $1 = AppImage, $2 = dossier de résultat
setsid "$1" >"$2/app.log" 2>&1 &   # son propre groupe : on arrête l'appli et ses enfants d'un coup
pid=$!
found=
for i in $(seq 1 120); do
  if xdotool search --onlyvisible --name LANa >/dev/null 2>&1; then found=1; break; fi
  kill -0 "$pid" 2>/dev/null || break
  sleep 1
done
sleep 8   # laisse finir les chargements en arrière-plan (état de la machine, serveurs) avant la capture
import -window root "$2/ecran.png" || true
alive=
kill -0 "$pid" 2>/dev/null && alive=1
kill -TERM -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
wait "$pid" 2>/dev/null || true
[ -n "$found" ] && [ -n "$alive" ]
INNER

status=0
xvfb-run -a -s "-screen 0 1400x900x24" sh "$OUT/essai-interne.sh" "$APPIMAGE" "$OUT" || status=$?
rm -f "$OUT/essai-interne.sh"

echo "----- journal de l'appli -----"
[ -f "$OUT/app.log" ] || { echo "ÉCHEC : l'appli n'a rien écrit, l'essai n'a pas tourné." >&2; exit 1; }
cat "$OUT/app.log"
[ -f "$OUT/ecran.png" ] || { echo "ÉCHEC : pas de capture d'écran, l'essai n'a pas tourné." >&2; exit 1; }
if [ "$status" -ne 0 ]; then echo "ÉCHEC : la fenêtre n'est pas apparue, ou l'appli s'est arrêtée seule." >&2; exit 1; fi
if grep -qE 'Traceback|Could not load the Qt platform plugin' "$OUT/app.log"; then echo "ÉCHEC : erreur dans le journal." >&2; exit 1; fi
echo "OK : la fenêtre LANa est apparue et l'appli tournait encore après quelques secondes."
