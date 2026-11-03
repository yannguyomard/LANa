"""Animations de l'appli : courbes d'atténuation réalistes, propriétés graphiques animées (opacité, position,
halo), jamais de feuille de style recalculée en boucle.

- fade_in / enter : apparition d'un élément ou d'une page (fondu + léger glissement, OutCubic) ;
- HoverGlow : halo qui s'allume au survol des boutons principaux, des cartes et du menu (ombre portée animée) ;
- slide : déplacement d'un widget (indicateur du menu, OutBack pour un léger effet d'aimant) ;
- fade_window : apparition d'une fenêtre (opacité de la fenêtre) ;
- Spinner, CheckMark : micro-animations dessinées (chargement, validation), à la place de Lottie qui n'existe
  qu'en QML et alourdirait l'appli de plusieurs centaines de Mo.
"""
import math

from PySide6.QtCore import (QAbstractAnimation, QEasingCurve, QEvent, QObject, QPoint, QPointF, QPropertyAnimation,
                            QRectF, QSequentialAnimationGroup, QParallelAnimationGroup, QPauseAnimation, Qt,
                            QVariantAnimation)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QPushButton, QWidget

FAST, NORMAL, SLOW = 150, 240, 360


def _curve(kind):
    return QEasingCurve(kind)


def fade_in(widget, duration=NORMAL, delay=0, rise=8):
    """Fait apparaître un widget : opacité 0 -> 1 et montée de quelques pixels. L'effet est retiré à la fin
    (un QGraphicsEffect coûte au dessin et empêcherait le halo de survol)."""
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
    group = QParallelAnimationGroup(widget)
    group.addAnimation(fade)
    if rise:
        # Le glissement se fait sur la position une fois la mise en page faite (sinon le layout l'écrase).
        start = {}

        def follow(value):
            if "pos" not in start:
                start["pos"] = widget.pos()
            widget.move(start["pos"].x(), start["pos"].y() + round(rise * (1 - value)))
        fade.valueChanged.connect(follow)
    outer = group
    if delay:
        outer = QSequentialAnimationGroup(widget)
        outer.addAnimation(QPauseAnimation(delay, widget))
        outer.addAnimation(group)

    def done():
        if widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)
    outer.finished.connect(done)
    outer.start(QAbstractAnimation.DeleteWhenStopped)
    return outer


def enter(page):
    """Changement de page : fondu et glissement depuis la droite (InOutCubic)."""
    effect = QGraphicsOpacityEffect(page)
    effect.setOpacity(0.0)
    page.setGraphicsEffect(effect)
    fade = QPropertyAnimation(effect, b"opacity", page)
    fade.setDuration(NORMAL)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    fade.setEasingCurve(_curve(QEasingCurve.Type.InOutCubic))
    slide = QPropertyAnimation(page, b"pos", page)
    slide.setDuration(NORMAL + 40)
    slide.setStartValue(QPoint(24, 0))
    slide.setEndValue(QPoint(0, 0))
    slide.setEasingCurve(_curve(QEasingCurve.Type.OutCubic))
    group = QParallelAnimationGroup(page)
    group.addAnimation(fade)
    group.addAnimation(slide)
    group.finished.connect(lambda: page.graphicsEffect() is effect and page.setGraphicsEffect(None))
    group.start(QAbstractAnimation.DeleteWhenStopped)


def slide(widget, target, duration=SLOW):
    """Déplace un widget vers target (QPoint) avec un léger dépassement (OutBack, effet « aimant »)."""
    anim = QPropertyAnimation(widget, b"pos", widget)
    anim.setDuration(duration)
    anim.setStartValue(widget.pos())
    anim.setEndValue(target)
    anim.setEasingCurve(_curve(QEasingCurve.Type.OutBack))
    anim.start(QAbstractAnimation.DeleteWhenStopped)
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
    """Filtre d'événements posé sur l'application : halo animé (ombre portée colorée) au survol des boutons
    principaux, des boutons d'arrêt, des cartes et des entrées du menu. Un seul filtre pour toute l'appli."""
    COLORS = {"primary": QColor(40, 200, 230), "stop": QColor(255, 93, 108), "card": QColor(42, 160, 150),
              "navitem": QColor(80, 230, 190)}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = {}   # widget -> animation de halo en cours

    def _kind(self, obj):
        if isinstance(obj, QPushButton) and obj.property("kind") in ("primary", "stop"):
            return obj.property("kind") if obj.isEnabled() else None
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
            color = QColor(self.COLORS[kind])
            color.setAlpha(0)
            effect.setColor(color)
            widget.setGraphicsEffect(effect)
        previous = self._running.pop(widget, None)
        if previous is not None:
            previous.stop()
            previous.deleteLater()
        start = effect.blurRadius() / 26.0
        anim = QVariantAnimation(widget)
        anim.setDuration(FAST + 60 if on else FAST)
        anim.setStartValue(start)
        anim.setEndValue(1.0 if on else 0.0)
        anim.setEasingCurve(_curve(QEasingCurve.Type.OutQuad))
        base = QColor(self.COLORS[kind])

        def step(value):
            if widget.graphicsEffect() is not effect:
                return
            effect.setBlurRadius(26.0 * value)
            color = QColor(base)
            color.setAlpha(round(150 * value))
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
