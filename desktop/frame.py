"""Fenêtre sans cadre du système : barre de titre intégrée (déplacer, réduire, agrandir, fermer) et bords
invisibles pour redimensionner. Le déplacement et le redimensionnement passent par le système
(startSystemMove / startSystemResize) : l'ancrage aux bords de l'écran de Windows continue de marcher."""
from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from . import visuals
from .style import C

GRIP = 6   # épaisseur des bords de redimensionnement (px)


class WindowButton(QPushButton):
    def __init__(self, icon_name, tooltip, danger=False):
        super().__init__()
        self.setObjectName("winbtn_close" if danger else "winbtn")
        self.setFixedSize(46, 34)
        self.setToolTip(tooltip)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.set_icon(icon_name)

    def set_icon(self, icon_name):
        self.setIcon(visuals.icon(icon_name, C["ink2"], 18))
        self.setIconSize(QSize(18, 18))


class TitleBar(QWidget):
    """Bande du haut de la fenêtre : zone de déplacement (double-clic = agrandir) et boutons de la fenêtre."""

    def __init__(self, window):
        super().__init__()
        self.window_ = window
        self.setObjectName("titlebar")
        self.setFixedHeight(38)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addStretch(1)
        self.minimize = WindowButton("fenetre-reduire", "Réduire")
        self.maximize = WindowButton("fenetre-agrandir", "Agrandir")
        self.close_btn = WindowButton("fenetre-fermer", "Fermer", danger=True)
        self.minimize.clicked.connect(window.showMinimized)
        self.maximize.clicked.connect(self.toggle_maximized)
        self.close_btn.clicked.connect(window.close)
        for btn in (self.minimize, self.maximize, self.close_btn):
            row.addWidget(btn, 0, Qt.AlignTop)
        window.installEventFilter(self)

    def toggle_maximized(self):
        if self.window_.isMaximized():
            self.window_.showNormal()
        else:
            self.window_.showMaximized()

    def eventFilter(self, obj, event):
        if obj is self.window_ and event.type() == QEvent.Type.WindowStateChange:
            maxi = self.window_.isMaximized()
            self.maximize.set_icon("fenetre-restaurer" if maxi else "fenetre-agrandir")
            self.maximize.setToolTip("Restaurer" if maxi else "Agrandir")
        return False

    def mousePressEvent(self, event):
        start_move(self, event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle_maximized()


def start_move(widget, event):
    """Clic gauche sur une zone vide : le système déplace la fenêtre."""
    if event.button() == Qt.LeftButton:
        handle = widget.window().windowHandle()
        if handle is not None:
            handle.startSystemMove()


class ResizeGrip(QWidget):
    """Bord ou coin invisible de la fenêtre, qui lance le redimensionnement par le système."""
    CURSORS = {Qt.TopEdge: Qt.SizeVerCursor, Qt.BottomEdge: Qt.SizeVerCursor, Qt.LeftEdge: Qt.SizeHorCursor,
               Qt.RightEdge: Qt.SizeHorCursor}

    def __init__(self, window, edges):
        super().__init__(window)
        self.edges = edges
        if edges in self.CURSORS:
            self.setCursor(self.CURSORS[edges])
        elif edges in (Qt.TopEdge | Qt.LeftEdge, Qt.BottomEdge | Qt.RightEdge):
            self.setCursor(Qt.SizeFDiagCursor)
        else:
            self.setCursor(Qt.SizeBDiagCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.window().windowHandle() is not None:
            self.window().windowHandle().startSystemResize(self.edges)


class Grips:
    """Les 8 bords et coins, replacés à chaque redimensionnement, masqués quand la fenêtre est agrandie."""

    def __init__(self, window):
        self.window = window
        T, B, L, R = Qt.TopEdge, Qt.BottomEdge, Qt.LeftEdge, Qt.RightEdge
        self.grips = {edges: ResizeGrip(window, edges)
                      for edges in (T, B, L, R, T | L, T | R, B | L, B | R)}

    def place(self):
        w, h, g = self.window.width(), self.window.height(), GRIP
        T, B, L, R = Qt.TopEdge, Qt.BottomEdge, Qt.LeftEdge, Qt.RightEdge
        rects = {T: (g, 0, w - 2 * g, g), B: (g, h - g, w - 2 * g, g), L: (0, g, g, h - 2 * g),
                 R: (w - g, g, g, h - 2 * g), T | L: (0, 0, g, g), T | R: (w - g, 0, g, g),
                 B | L: (0, h - g, g, g), B | R: (w - g, h - g, g, g)}
        visible = not (self.window.isMaximized() or self.window.isFullScreen())
        for edges, grip in self.grips.items():
            grip.setGeometry(*rects[edges])
            grip.setVisible(visible)
            grip.raise_()
