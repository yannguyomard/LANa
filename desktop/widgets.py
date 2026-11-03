"""Briques communes : travail en arrière-plan, logo, pastille d'état."""
from PySide6.QtCore import QObject, QRectF, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QLabel, QWidget

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


# Logo 8×8 du panneau : (x, y, largeur, hauteur, couleur, opacité)
LOGO = [(1, 1, 3, 3, "acc2", 1), (4, 4, 3, 3, "ok", 1), (4, 1, 3, 1, "acc2", .55), (1, 5, 3, 1, "acc2", .55)]


def paint_logo(painter, rect):
    s = rect.width() / 8
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(rect, 1.2 * s, 1.2 * s)
    painter.fillPath(path, QColor(C["acc"]))
    painter.setRenderHint(QPainter.Antialiasing, False)
    for x, y, w, h, col, op in LOGO:
        painter.setOpacity(op)
        painter.fillRect(QRectF(rect.x() + x * s, rect.y() + y * s, w * s, h * s), QColor(C[col]))
    painter.setOpacity(1)


def app_icon():
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        paint_logo(p, QRectF(0, 0, size, size))
        p.end()
        icon.addPixmap(pix)
    return icon


class Logo(QWidget):
    def __init__(self, size=28, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        paint_logo(p, QRectF(0, 0, self.width(), self.height()))


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
