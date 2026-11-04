#!/bin/sh
# Construit LANa.app (appli de bureau Qt, desktop/) et LANa-<version>-macos.dmg, Intel et Apple Silicon, sans signature Apple.
# Usage : sh packaging/macos/build.sh        → packaging/macos/build/
# Téléchargements (mis en cache dans packaging/macos/.cache) : Python autonome (python-build-standalone, vérifié par
# SHA-256) et PySide6-Essentials depuis PyPI (vérifié par pip).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
CACHE="$HERE/.cache"
BUILD="$HERE/build"
PBS_TAG=20261026
PBS_PY=3.12.16
PYSIDE="PySide6-Essentials>=6.8"
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/lana/__init__.py")
APP="$BUILD/LANa.app"
RES="$APP/Contents/Resources"

mkdir -p "$CACHE/wheels"
rm -rf "$BUILD" && mkdir -p "$BUILD"

# 1. Les deux Python autonomes
base="https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_TAG"
[ -f "$CACHE/SHA256SUMS" ] || curl -fsSL -o "$CACHE/SHA256SUMS" "$base/SHA256SUMS"
for arch in x86_64 aarch64; do
  f="cpython-$PBS_PY+$PBS_TAG-$arch-apple-darwin-install_only_stripped.tar.gz"
  [ -f "$CACHE/$f" ] || curl -fsSL -o "$CACHE/$f" "$base/$(printf %s "$f" | sed 's/+/%2B/')"
  want=$(grep " $f\$" "$CACHE/SHA256SUMS" | cut -d' ' -f1)
  got=$(shasum -a 256 "$CACHE/$f" | cut -d' ' -f1)
  [ "$want" = "$got" ] || { echo "Empreinte incorrecte pour $f" >&2; rm -f "$CACHE/$f"; exit 1; }
done

# 2. Lanceur (binaire universel) et Info.plist
mkdir -p "$APP/Contents/MacOS" "$RES"
clang -O2 -arch x86_64 -arch arm64 -mmacosx-version-min=11.0 "$HERE/launcher.c" -o "$APP/Contents/MacOS/LANa"

# 3. Icône : le logo de l'appli (desktop/assets/logo.png) s'il existe, centré avec la marge des icônes macOS
icons="$BUILD/AppIcon.iconset" && mkdir -p "$icons"
src="$HERE/icon-1024.png"
if [ -f "$ROOT/desktop/assets/logo.png" ]; then
  src="$BUILD/icon-1024.png"
  sips -Z 824 "$ROOT/desktop/assets/logo.png" --out "$BUILD/logo-824.png" >/dev/null
  sips --padToHeightWidth 1024 1024 "$BUILD/logo-824.png" --out "$src" >/dev/null
fi
for s in 16 32 128 256 512; do
  sips -z $s $s "$src" --out "$icons/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2)); sips -z $d $d "$src" --out "$icons/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$icons" -o "$RES/AppIcon.icns"

# 4. Python, allégés de ce que LANa n'utilise pas
for arch in x86_64 aarch64; do
  dest="$RES/python-$( [ $arch = aarch64 ] && echo arm64 || echo x86_64 )"
  mkdir -p "$dest"
  tar xzf "$CACHE/cpython-$PBS_PY+$PBS_TAG-$arch-apple-darwin-install_only_stripped.tar.gz" -C "$dest" --strip-components 1
  lib="$dest/lib/python3.12"
  rm -rf "$dest/include" "$dest/share" "$dest"/lib/tcl* "$dest"/lib/tk* "$dest"/lib/itcl* "$dest"/lib/thread* "$dest/lib/pkgconfig" \
         "$lib/test" "$lib/idlelib" "$lib/tkinter" "$lib/turtledemo" "$lib/ensurepip" "$lib/lib2to3" "$lib/pydoc_data" \
         "$lib"/config-3.12-* "$lib"/lib-dynload/_tkinter*
done

# 5. PySide6 : roues « universal2 » (Intel et Apple Silicon dans les mêmes fichiers), installées une seule fois
host_py="$RES/python-$( [ "$(uname -m)" = arm64 ] && echo arm64 || echo x86_64 )/bin/python3"
"$host_py" -m pip download -q "$PYSIDE" --only-binary=:all: --python-version 3.12 --implementation cp \
  --platform macosx_13_0_universal2 --platform macosx_12_0_universal2 --platform macosx_11_0_universal2 -d "$CACHE/wheels"
"$host_py" -m pip install -q --no-index --find-links "$CACHE/wheels" --target "$RES/site-packages" "$PYSIDE"
for arch in x86_64 aarch64; do   # pip ne sert plus une fois l'app construite
  rm -rf "$RES/python-$( [ $arch = aarch64 ] && echo arm64 || echo x86_64 )"/lib/python3.12/site-packages/pip*
done
P="$RES/site-packages/PySide6"
# Seulement QtCore, QtGui, QtWidgets, QtSvg (et QtDBus dont QtGui dépend), et les greffons utiles.
find "$P" -maxdepth 1 -name 'Qt*.abi3.so' ! -name 'QtCore.*' ! -name 'QtGui.*' ! -name 'QtWidgets.*' ! -name 'QtSvg.*' -delete
find "$P" -maxdepth 1 \( -name '*.pyi' -o -name '*.app' -o -name 'libpyside6qml*' \) -exec rm -rf {} +
rm -rf "$P/include" "$P/typesystems" "$P/glue" "$P/scripts" "$P/Qt/qml" "$P/Qt/metatypes" "$P/Qt/libexec" \
       "$RES/site-packages/shiboken6/include" "$RES/site-packages"/*.dist-info/RECORD "$RES/site-packages/bin"
find "$P" -maxdepth 1 -type f -perm -u+x ! -name '*.so' ! -name '*.dylib' -delete   # outils (uic, rcc, lupdate…)
for fw in "$P"/Qt/lib/*.framework; do
  case "$(basename "$fw" .framework)" in QtCore|QtGui|QtWidgets|QtSvg|QtDBus) ;; *) rm -rf "$fw" ;; esac
done
for d in "$P"/Qt/plugins/*; do
  case "$(basename "$d")" in platforms|imageformats|iconengines|styles) ;; *) rm -rf "$d" ;; esac
done
find "$P/Qt/plugins/imageformats" -type f ! -name 'libqsvg*' ! -name 'libqicns*' ! -name 'libqico*' ! -name 'libqpng*' -delete
find "$P/Qt/translations" -type f ! -name 'qtbase_fr.qm' -delete 2>/dev/null || true
[ -f "$P/Qt/translations/qtbase_fr.qm" ] || echo "Avertissement : qtbase_fr.qm absent de PySide6, les boutons standard de Qt resteront en anglais." >&2

# 6. LANa (moteur, jeux, polices, appli de bureau), précompilé
mkdir -p "$RES/LANa"
for part in lana games desktop; do
  rsync -a --exclude __pycache__ --exclude .DS_Store "$ROOT/$part" "$RES/LANa/"
done
mkdir -p "$RES/LANa/web/static" && rsync -a "$ROOT/web/static/fonts" "$RES/LANa/web/static/"
cp "$ROOT/LICENSE" "$RES/LANa/" 2>/dev/null || true
PYTHONPATH="$RES/site-packages" "$host_py" -m compileall -q "$RES/LANa" "$RES/site-packages"

sed -e "s/@VERSION@/$VERSION/" -e "s/@MINOS@/13.0/" "$HERE/Info.plist" > "$APP/Contents/Info.plist"

# 7. Signature ad hoc (obligatoire pour lancer le code arm64), puis image disque
codesign --force --deep --sign - "$APP"
stage="$BUILD/dmg" && mkdir -p "$stage" && cp -R "$APP" "$stage/" && ln -s /Applications "$stage/Applications"
hdiutil create -quiet -volname "LANa $VERSION" -srcfolder "$stage" -format UDZO -ov "$BUILD/LANa-$VERSION-macos.dmg"
rm -rf "$stage" "$icons" "$BUILD/logo-824.png" "$BUILD/icon-1024.png"
du -sh "$APP" "$BUILD/LANa-$VERSION-macos.dmg"
