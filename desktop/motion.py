"""Animations de l'appli : courbes d'atténuation réalistes, propriétés graphiques animées (opacité, position,
halo), jamais de feuille de style recalculée en boucle.

- fade_in / enter : apparition d'un élément ou d'une page en fondu (jamais de déplacement d'un widget
  placé par un layout : il tremblerait) ;
- HoverGlow : halo qui s'allume au survol des boutons principaux, des cartes et du menu (ombre portée animée) ;
- slider : déplacement d'un widget placé à la main (repère du menu, OutBack pour un léger effet d'aimant) ;
- fade_window : apparition d'une fenêtre (opacité de la fenêtre) ;
- Spinner, CheckMark : micro-animations dessinées (chargement, validation), à la place de Lottie qui n'existe
  qu'en QML et alourdirait l'appli de plusieurs centaines de Mo.
"""
import math

from PySide6.QtCore import (QAbstractAnimation, QEasingCurve, QEvent, QObject, QPointF, QPropertyAnimation, QRectF,
                            QSequentialAnimationGroup, QPauseAnimation, Qt, QVariantAnimation)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QPushButton, QWidget

FAST, NORMAL, SLOW = 150, 240, 360


def _curve(kind):
    return QEasingCurve(kind)


def fade_in(widget, duration=NORMAL, delay=0):
    """Fait apparaître un widget en fondu (opacité 0 -> 1). Jamais de déplacement : le widget est placé par un
    layout, qui le replace à chaque recalcul (redimensionnement, autre carte qui arrive) ; animer sa position
    en même temps le fait trembler. L'effet est retiré à la fin (il coûte au dessin et bloquerait le halo)."""
    if widget.graphicsEffect() is not None and not isinstance(widget.graphicsEffect(), QGraphicsDropShadowEffect):
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    fade = QPropertyAnimation(effect, b"opacity", widget)
    fade.setDuration(duration)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    fade.setEasingCurve(_curve(QEasingCurve.Type.OutCubic))
    outer = fade
    if delay:
        outer = QSequentialAnimationGroup(widget)
        outer.addAnimation(QPauseAnimation(delay, widget))
        outer.addAnimation(fade)

    def done():
        if widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)
    outer.finished.connect(done)
    outer.start(QAbstractAnimation.DeleteWhenStopped)
    return outer


def enter(page):
    """Changement de page : fondu (InOutCubic). Pas de glissement : la page est placée par le QStackedWidget,
    qui la repositionne à chaque redimensionnement."""
    effect = QGraphicsOpacityEffect(page)
    effect.setOpacity(0.0)
    page.setGraphicsEffect(effect)
    fade = QPropertyAnimation(effect, b"opacity", page)
    fade.setDuration(NORMAL)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    fade.setEasingCurve(_curve(QEasingCurve.Type.InOutCubic))
    fade.finished.connect(lambda: page.graphicsEffect() is effect and page.setGraphicsEffect(None))
    fade.start(QAbstractAnimation.DeleteWhenStopped)


def slider(widget, duration=SLOW):
    """Animation de position réutilisable pour un widget placé à la main (pas par un layout), avec un léger
    dépassement (OutBack, effet « aimant »). Une seule par widget : on l'arrête avant de le replacer, sinon
    l'animation et le placement direct se disputent la position (tremblement)."""
    anim = QPropertyAnimation(widget, b"pos", widget)
    anim.setDuration(duration)
    anim.setEasingCurve(_curve(QEasingCurve.Type.OutBack))
    return anim


def fade_window(window, duration=NORMAL):
    window.setWindowOpacity(0.0)
    anim = QPropertyAnimation(window, b"windowOpacity", window)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(_curve(QEasingCurve.Type.OutCubic))
    anim.start(QAbstractAnimation.DeleteWhenStopped)


class HoverGlow(QObject):
    """Filtre d'événements posé sur l'application : halo animé (ombre portée colorée) au survol de tous les
    boutons, des cartes et des entrées du menu. Un seul filtre pour toute l'appli."""
    # genre -> (couleur, rayon du flou en px, opacité maximale 0-255)
    GLOWS = {"primary": (QColor(40, 200, 235), 34, 235), "stop": (QColor(255, 93, 108), 30, 225),
             "button": (QColor(52, 190, 200), 26, 200), "flat": (QColor(40, 207, 252), 18, 210),
             "winbtn": (QColor(120, 210, 230), 20, 170), "winbtn_close": (QColor(255, 70, 85), 24, 220),
             "card": (QColor(42, 170, 160), 30, 150), "navitem": (QColor(80, 230, 190), 28, 210)}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = {}   # widget -> animation de halo en cours

    def _kind(self, obj):
        if isinstance(obj, QPushButton):
            if not obj.isEnabled():
                return None
            if obj.objectName() in ("winbtn", "winbtn_close"):
                return obj.objectName()
            kind = obj.property("kind")
            return kind if kind in ("primary", "stop", "flat") else "button"
        if isinstance(obj, QWidget) and obj.objectName() in ("card", "navitem"):
            return obj.objectName()
        return None

    def eventFilter(self, obj, event):
        kind_of_event = event.type()
        if kind_of_event in (QEvent.Type.Enter, QEvent.Type.Leave):
            kind = self._kind(obj)
            if kind:
                self._animate(obj, kind, kind_of_event == QEvent.Type.Enter)
        return False

    def _animate(self, widget, kind, on):
        effect = widget.graphicsEffect()
        if effect is not None and not isinstance(effect, QGraphicsDropShadowEffect):
            return   # un fondu d'apparition est en cours : pas de halo par-dessus
        if effect is None:
            if not on:
                return
            effect = QGraphicsDropShadowEffect(widget)
            effect.setOffset(0, 0)
            effect.setBlurRadius(0)
            color = QColor(self.GLOWS[kind][0])
            color.setAlpha(0)
            effect.setColor(color)
            widget.setGraphicsEffect(effect)
        previous = self._running.pop(widget, None)
        if previous is not None:
            previous.stop()
            previous.deleteLater()
        base, radius, alpha = self.GLOWS[kind]
        start = min(1.0, effect.blurRadius() / radius)
        anim = QVariantAnimation(widget)
        anim.setDuration(FAST + 60 if on else FAST)
        anim.setStartValue(start)
        anim.setEndValue(1.0 if on else 0.0)
        anim.setEasingCurve(_curve(QEasingCurve.Type.OutQuad))

        def step(value):
            if widget.graphicsEffect() is not effect:
                return
            effect.setBlurRadius(radius * value)
            color = QColor(base)
            color.setAlpha(round(alpha * value))
            effect.setColor(color)

        def finished():
            if self._running.get(widget) is anim:
                del self._running[widget]
                anim.deleteLater()
            if not on and widget.graphicsEffect() is effect:
                widget.setGraphicsEffect(None)   # plus rien à dessiner au repos
        anim.valueChanged.connect(step)
        anim.finished.connect(finished)
        widget.destroyed.connect(lambda *_: self._running.pop(widget, None))
        self._running[widget] = anim   # suivie côté Python : jamais de pointeur vers une animation déjà détruite
        anim.start()


class Spinner(QWidget):
    """Indicateur de chargement : arc en dégradé qui tourne (InOutSine sur la longueur de l'arc)."""

    def __init__(self, size=22, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.angle = 0.0
        self.anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=1100, loopCount=-1)
        self.anim.valueChanged.connect(self._tick)

    def showEvent(self, event):
        self.anim.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.anim.stop()
        super().hideEvent(event)

    def _tick(self, value):
        self.angle = value
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(2.5, 2.5, self.width() - 5, self.height() - 5)
        pen = QPen(QColor(35, 64, 95), 3)
        p.setPen(pen)
        p.drawEllipse(r)
        sweep = 70 + 180 * (0.5 - 0.5 * math.cos(self.angle * 2 * math.pi))
        pen.setColor(QColor("#28cffc"))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(r, int(-self.angle * 360 * 16), int(sweep * 16))


class CheckMark(QWidget):
    """Coche de validation qui se dessine (OutCubic), dans un rond vert."""

    def __init__(self, size=48, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.progress = 0.0
        self.anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=SLOW + 140)
        self.anim.setEasingCurve(_curve(QEasingCurve.Type.OutCubic))
        self.anim.valueChanged.connect(self._tick)

    def play(self):
        self.progress = 0.0
        self.anim.start()

    def _tick(self, value):
        self.progress = value
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.width()
        circle = min(1.0, self.progress * 1.6)
        p.setPen(QPen(QColor(67, 233, 35, round(255 * circle)), 3))
        p.setBrush(QColor(67, 233, 35, round(40 * circle)))
        inset = 3 + (1 - circle) * s * 0.2
        p.drawEllipse(QRectF(inset, inset, s - 2 * inset, s - 2 * inset))
        tick = max(0.0, (self.progress - 0.35) / 0.65)
        if tick <= 0:
            return
        points = [QPointF(s * 0.28, s * 0.52), QPointF(s * 0.44, s * 0.67), QPointF(s * 0.73, s * 0.36)]
        lengths = [math.dist((points[0].x(), points[0].y()), (points[1].x(), points[1].y())),
                   math.dist((points[1].x(), points[1].y()), (points[2].x(), points[2].y()))]
        left = tick * sum(lengths)
        path = QPainterPath(points[0])
        for (a, b), length in zip(((points[0], points[1]), (points[1], points[2])), lengths):
            part = min(1.0, left / length) if length else 1.0
            path.lineTo(a + (b - a) * part)
            left -= length
            if left <= 0:
                break
        pen = QPen(QColor("#e6fff0"), 3.4)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
