#!/bin/sh
# Construit LANa-<version>-linux-<arch>.AppImage (appli de bureau Qt, desktop/) pour l'architecture de la machine.
# À lancer sous Linux : le plus simple est le workflow GitHub « Linux (AppImage) », qui construit et essaie les deux
# architectures (x86_64 et aarch64). Résultat : packaging/linux/build/.
# Téléchargements (mis en cache dans packaging/linux/.cache, tous vérifiés par SHA-256) : Python autonome
# (python-build-standalone), appimagetool, et PySide6-Essentials depuis PyPI.
set -eu
[ "$(uname -s)" = Linux ] || { echo "À lancer sous Linux (voir .github/workflows/linux.yml)." >&2; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
CACHE="$HERE/.cache"
BUILD="$HERE/build"
APPDIR="$BUILD/LANa.AppDir"
PBS_TAG=20261026
PBS_PY=3.12.16
TOOL_VERSION=1.9.1

# Version de PySide6 choisie par architecture : la plus ancienne roue « manylinux » qui convient à `PySide6>=6.8`,
# pour tourner sur le plus de distributions possible (glibc 2.28 en x86_64, 2.31 en aarch64 : Raspberry Pi OS Bookworm).
case "$(uname -m)" in
  x86_64)
    ARCH=x86_64; PYSIDE="PySide6-Essentials==6.9.3"
    PBS_SHA=ce4f6d0a6cfdb3bed6e44c2f9affd85943c76a42e25ad3a259002f31d6fb8a20
    TOOL_SHA=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0 ;;
  aarch64|arm64)
    ARCH=aarch64; PYSIDE="PySide6-Essentials==6.8.0.2"
    PBS_SHA=bb4b6392670c5d3f93876996fcaa19858a4a413a0c7720144c18b0d6f1f0db2d
    TOOL_SHA=f0837e7448a0c1e4e650a93bb3e85802546e60654ef287576f46c71c126a9158 ;;
  *) echo "Architecture non gérée : $(uname -m)" >&2; exit 1 ;;
esac
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/lana/__init__.py")
OUT="$BUILD/LANa-$VERSION-linux-$ARCH.AppImage"

fetch() {   # url destination sha256
  [ -f "$2" ] || curl -fsSL -o "$2" "$1"
  echo "$3  $2" | sha256sum -c - >/dev/null 2>&1 || { echo "Empreinte incorrecte pour $(basename "$2")" >&2; rm -f "$2"; exit 1; }
}

# Toutes les suppressions ci-dessous passent par ${VARIABLE:?} : si une variable était vide, le script s'arrête
# au lieu de viser la racine du disque.
mkdir -p "$CACHE"
rm -rf "${BUILD:?}" && mkdir -p "$BUILD" "$APPDIR/usr"

# 1. Python autonome et appimagetool
pbs="cpython-$PBS_PY+$PBS_TAG-$ARCH-unknown-linux-gnu-install_only_stripped.tar.gz"
fetch "https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_TAG/$(printf %s "$pbs" | sed 's/+/%2B/')" "$CACHE/$pbs" "$PBS_SHA"
fetch "https://github.com/AppImage/appimagetool/releases/download/$TOOL_VERSION/appimagetool-$ARCH.AppImage" "$CACHE/appimagetool-$ARCH.AppImage" "$TOOL_SHA"
chmod +x "$CACHE/appimagetool-$ARCH.AppImage"

# 2. Python, allégé de ce que LANa n'utilise pas
PYDIR="$APPDIR/usr/python"
mkdir -p "$PYDIR"
tar xzf "$CACHE/$pbs" -C "$PYDIR" --strip-components 1
PY="$PYDIR/bin/python3"
LIB="$PYDIR/lib/python3.12"

# 3. PySide6 dans un dossier à part (site-packages de l'AppDir)
SITE="$APPDIR/usr/site-packages"
"$PY" -m pip install --disable-pip-version-check --no-cache-dir --no-compile --only-binary=:all: --target "$SITE" "$PYSIDE"
rm -rf "${PYDIR:?}/include" "${PYDIR:?}/share" "${PYDIR:?}/lib/pkgconfig" \
       "${LIB:?}/test" "${LIB:?}/idlelib" "${LIB:?}/tkinter" "${LIB:?}/turtledemo" "${LIB:?}/ensurepip" \
       "${LIB:?}/lib2to3" "${LIB:?}/pydoc_data" "${LIB:?}/site-packages/pip" "${LIB:?}/site-packages/setuptools"
rm -rf "${PYDIR:?}"/lib/tcl* "${PYDIR:?}"/lib/tk* "${PYDIR:?}"/lib/itcl* "${PYDIR:?}"/lib/thread* \
       "${LIB:?}"/config-3.12-* "${LIB:?}"/lib-dynload/_tkinter* "${LIB:?}"/site-packages/pip-* "${LIB:?}"/site-packages/setuptools-*

# 4. PySide6 réduit à ce qu'utilise l'appli : QtCore, QtGui, QtWidgets, QtSvg (et DBus, dont QtGui dépend)
P="$SITE/PySide6"
find "${P:?}" -maxdepth 1 -name 'Qt*.abi3.so' ! -name 'QtCore.*' ! -name 'QtGui.*' ! -name 'QtWidgets.*' ! -name 'QtSvg.*' -delete
find "${P:?}" -maxdepth 1 \( -name '*.pyi' -o -name 'libpyside6qml*' \) -delete
find "${P:?}" -maxdepth 1 -type f -perm -u+x ! -name 'lib*' ! -name '*.so' -delete   # outils : uic, rcc, designer…
rm -rf "${P:?}/include" "${P:?}/typesystems" "${P:?}/glue" "${P:?}/scripts" "${P:?}/Qt/qml" "${P:?}/Qt/metatypes" \
       "${P:?}/Qt/libexec" "${SITE:?}/shiboken6/include" "${SITE:?}/shiboken6_generator" "${SITE:?}/bin"
# On ne garde que la traduction française des boutons standard de Qt (Annuler, Oui, Non…), chargée par desktop/__main__.py.
find "${P:?}/Qt/translations" -type f ! -name 'qtbase_fr.qm' -delete 2>/dev/null || true
[ -f "$P/Qt/translations/qtbase_fr.qm" ] || echo "Avertissement : qtbase_fr.qm absent de PySide6, les boutons standard de Qt resteront en anglais." >&2
for pat in Quick Qml Designer Pdf 3D Help Multimedia Charts DataVisualization Graphs Location Positioning Sensors Bluetooth \
           Nfc RemoteObjects Scxml Serial Sql Test ShaderTools SpatialAudio StateMachine TextToSpeech VirtualKeyboard \
           HttpServer WebSockets WebChannel WebView NetworkAuth Labs LanguageServer UiTools \
           WaylandCompositor WaylandEglCompositorHwIntegration; do   # les deux derniers : le serveur Wayland, inutile ici
  find "${P:?}/Qt/lib" -name "libQt6${pat}*" -delete 2>/dev/null || true
done
for d in "$P"/Qt/plugins/*; do   # greffons : l'affichage (xcb, wayland, hors écran), les images et les thèmes
  case "$(basename "$d")" in
    platforms|imageformats|iconengines|platformthemes|platforminputcontexts|xcbglintegrations|generic|styles) ;;
    wayland-decoration-client|wayland-graphics-integration-client|wayland-shell-integration) ;;
    *) rm -rf "${d:?}" ;;
  esac
done
find "${P:?}/Qt/plugins/platforminputcontexts" -type f -name 'libqtvirtualkeyboard*' -delete   # dépend de QtVirtualKeyboard, supprimé
find "${P:?}/Qt/plugins/platforms" -type f \( -name 'libqeglfs*' -o -name 'libqlinuxfb*' -o -name 'libqvnc*' -o -name 'libqvkkhrdisplay*' \) -delete
find "${P:?}/Qt/plugins/imageformats" -type f ! -name 'libqsvg*' ! -name 'libqjpeg*' ! -name 'libqgif*' ! -name 'libqico*' -delete

# Garde-fou : aucune bibliothèque Qt restante ne doit dépendre d'une bibliothèque Qt, PySide ou Shiboken supprimée
broken=$(find "$SITE" -type f \( -name '*.so' -o -name '*.so.*' \) | while read -r f; do
  ldd "$f" 2>/dev/null | grep -E 'lib(Qt6|pyside6|shiboken6).*not found' | sed "s|^|$f : |"
done)
[ -z "$broken" ] || { echo "Dépendances Qt manquantes après l'allègement :" >&2; echo "$broken" >&2; exit 1; }

# 5. LANa (moteur, jeux, appli de bureau), sans les caches Python, puis précompilé
LANA="$APPDIR/usr/lana"
mkdir -p "$LANA/web/static"
tar -C "$ROOT" --exclude=__pycache__ -cf - lana games desktop | tar -C "$LANA" -xf -
cp -R "$ROOT/web/static/fonts" "$LANA/web/static/"
cp "$ROOT/LICENSE" "$LANA/" 2>/dev/null || true
PYTHONHOME="$PYDIR" "$PY" -m compileall -q "$LANA" "$SITE"

# 6. Lanceur, entrée de menu, icône
cp "$HERE/AppRun" "$APPDIR/AppRun" && chmod +x "$APPDIR/AppRun"
cp "$HERE/LANa.desktop" "$APPDIR/LANa.desktop"
cp "$ROOT/desktop/assets/logo.png" "$APPDIR/LANa.png"
ln -s LANa.png "$APPDIR/.DirIcon"

# 7. Image AppImage (APPIMAGE_EXTRACT_AND_RUN : appimagetool se lance sans FUSE, comme sur un serveur d'intégration)
ARCH=$ARCH APPIMAGE_EXTRACT_AND_RUN=1 "$CACHE/appimagetool-$ARCH.AppImage" "$APPDIR" "$OUT"
chmod +x "$OUT"
du -sh "$APPDIR" "$OUT"
