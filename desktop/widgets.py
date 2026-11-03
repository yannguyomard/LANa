"""Briques communes : travail en arrière-plan, logo, fond, menu latéral, pastille d'état."""
import math

from PySide6.QtCore import QObject, QPointF, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from . import visuals
from .style import C

_alive = set()   # garde les signaux en vie jusqu'à leur livraison


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn, args):
        super().__init__()
        self.fn, self.args, self.signals = fn, args, _Signals()

    def run(self):
        try:
            result = self.fn(*self.args)
        except Exception as ex:  # noqa: BLE001 - toute erreur remonte à l'interface
            self._emit(self.signals.failed, str(ex) or ex.__class__.__name__)
        else:
            self._emit(self.signals.done, result)

    @staticmethod
    def _emit(signal, value):
        try:
            signal.emit(value)
        except RuntimeError:   # appli fermée pendant la tâche : plus personne à prévenir
            pass


def run_async(fn, *args, done=None, failed=None):
    """Appelle fn(*args) dans un fil d'arrière-plan ; done(résultat) ou failed(message) dans le fil de l'interface."""
    task = _Task(fn, args)
    sig = task.signals
    _alive.add(sig)

    def finish(*_):
        _alive.discard(sig)

    if done:
        sig.done.connect(done)
    if failed:
        sig.failed.connect(failed)
    sig.done.connect(finish)
    sig.failed.connect(finish)
    QThreadPool.globalInstance().start(task)


class Logo(QLabel):
    """Logo LANa (desktop/assets/logo.svg)."""

    def __init__(self, size=40, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setPixmap(visuals.logo_pixmap(size))


def app_icon():
    return visuals.app_icon()


class Backdrop(QWidget):
    """Fond de la fenêtre : bleu nuit, halos sarcelle dans les coins et réseau d'hexagones discret."""

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(C["bg"]))
        for cx, cy, radius, color in ((0, h, max(w, h) * 0.55, QColor(26, 90, 90, 70)),
                                      (w, 0, max(w, h) * 0.5, QColor(35, 110, 100, 60)),
                                      (w * 0.55, h * 0.35, max(w, h) * 0.45, QColor(27, 107, 250, 18))):
            grad = QRadialGradient(cx, cy, radius)
            grad.setColorAt(0, color)
            grad.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(self.rect(), grad)
        # Hexagones à plat, plus visibles vers les bords droits et bas
        size = 46.0
        dx, dy = size * 1.5, size * math.sqrt(3)
        pen = QPen(QColor(60, 140, 150, 26))
        pen.setWidthF(1.0)
        p.setPen(pen)
        col = 0
        x = -size
        while x < w + size:
            y = -dy + (dy / 2 if col % 2 else 0)
            while y < h + dy:
                points = [QPointF(x + size * math.cos(math.radians(a)), y + size * math.sin(math.radians(a)))
                          for a in range(0, 360, 60)]
                p.drawPolygon(points)
                y += dy
            x += dx
            col += 1
        # Fenêtre sans cadre système : fin liseré pour la détacher du bureau (inutile une fois agrandie)
        if not self.window().isMaximized():
            p.setPen(QPen(QColor(C["line"]), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(0, 0, w - 1, h - 1)


class NavItem(QWidget):
    """Entrée du menu latéral : tuile avec icône, libellé en capitales."""
    clicked = Signal()

    def __init__(self, icon_name, text):
        super().__init__()
        self.setObjectName("navitem")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.icon_name = icon_name
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(14)
        self.tile = QLabel()
        self.tile.setObjectName("navtile")
        self.tile.setFixedSize(46, 46)
        self.tile.setAlignment(Qt.AlignCenter)
        self.text = QLabel(text.upper())
        self.text.setObjectName("navtext")
        row.addWidget(self.tile)
        row.addWidget(self.text, 1)
        self.set_active(False)

    def set_active(self, active):
        set_prop(self, "active", "true" if active else "false")
        for child in (self.tile, self.text):
            child.style().unpolish(child)
            child.style().polish(child)
        self.tile.setPixmap(visuals.icon_pixmap(self.icon_name, "#e9fffb" if active else C["mut"], 24))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


class Pill(QLabel):
    """Pastille d'état d'un serveur."""
    TEXT = {"stopped": "Arrêté", "running": "En marche", "starting": "Démarrage…", "stopping": "Arrêt…",
            "installing": "Installation…", "incomplete": "Installation incomplète", "broken": "Illisible"}
    KIND = {"stopped": "stopped", "running": "running", "starting": "busy", "stopping": "busy",
            "installing": "busy", "incomplete": "error", "broken": "error"}

    def set_state(self, state):
        self.setText("●  " + self.TEXT[state])
        self.setProperty("pill", self.KIND[state])
        self.style().unpolish(self)
        self.style().polish(self)
        # Largeur d'après la police réellement appliquée par la feuille de style (padding 10 px de chaque côté,
        # bordure, marge) : sinon le texte touche le bord avec certaines polices (Mac).
        self.setMinimumWidth(self.fontMetrics().horizontalAdvance(self.text()) + 30)


def set_prop(widget, name, value):
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    return widget


def label(text="", role=None, wrap=False):
    lab = QLabel(text)
    if role:
        lab.setProperty("role", role)
    if wrap:
        lab.setWordWrap(True)
    return lab
