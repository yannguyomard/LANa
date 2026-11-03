"""Logo et icônes (desktop/assets/), rendus en image à la bonne taille et dans la couleur voulue."""
import os

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_cache = {}


def _ratio():
    screen = QGuiApplication.primaryScreen()
    return screen.devicePixelRatio() if screen else 1.0


def _render(svg_bytes, size):
    ratio = _ratio()
    pix = QPixmap(round(size * ratio), round(size * ratio))
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg_bytes)).render(painter, QRectF(0, 0, pix.width(), pix.height()))
    painter.end()
    pix.setDevicePixelRatio(ratio)
    return pix


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def icon_pixmap(name, color, size=20):
    """Icône au trait (assets/icons/<name>.svg, dessinée en noir) recolorée."""
    key = ("icon", name, color, size)
    if key not in _cache:
        svg = _read(os.path.join(FOLDER, "icons", name + ".svg")).replace(b"#000000", color.encode())
        _cache[key] = _render(svg, size)
    return _cache[key]


def icon(name, color, size=20):
    return QIcon(icon_pixmap(name, color, size))


def logo_pixmap(size):
    """Logo complet ; version simplifiée (manette + éclair) en dessous de 48 px, où la fusée devient illisible."""
    key = ("logo", size)
    if key not in _cache:
        _cache[key] = _render(_read(os.path.join(FOLDER, "logo.svg" if size >= 48 else "logo-mark.svg")), size)
    return _cache[key]


def app_icon():
    out = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        out.addPixmap(logo_pixmap(size))
    return out
