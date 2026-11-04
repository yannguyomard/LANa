"""Tableau de bord : l'essentiel en un coup d'œil (serveurs en marche, machine) et raccourcis."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from . import motion, visuals
from .home import copy_button, state_of
from .style import C
from .widgets import Logo, Pill, label, set_prop


def _panel():
    frame = QFrame()
    frame.setObjectName("panel")
    return frame


class StatTile(QFrame):
    def __init__(self, title, icon_name):
        super().__init__()
        self.setObjectName("panel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(2)
        head = QHBoxLayout()
        icon = label()
        icon.setPixmap(visuals.icon_pixmap(icon_name, C["mut"], 18))
        head.addWidget(icon)
        head.addWidget(label(title.upper(), "caps"), 1)
        lay.addLayout(head)
        self.value = label("—", "stat")
        self.sub = label("", "muted")
        lay.addWidget(self.value)
        lay.addWidget(self.sub)

    def set(self, value, sub):
        self.value.setText(value)
        self.sub.setText(sub)


class DashboardPage(QWidget):
    new_requested = Signal()
    games_requested = Signal()
    servers_requested = Signal()
    open_requested = Signal(str)
    action_requested = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 26, 32, 26)
        outer.setSpacing(18)

        hero = _panel()
        h = QHBoxLayout(hero)
        h.setContentsMargins(24, 20, 24, 20)
        h.setSpacing(22)
        h.addWidget(Logo(96))
        text = QVBoxLayout()
        text.setSpacing(4)
        text.addWidget(label("Tableau de bord", "h1"))
        text.addWidget(label("Vos serveurs de jeu, prêts pour vos amis en quelques clics.", "muted", wrap=True))
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        new = set_prop(QPushButton("  Nouveau serveur"), "kind", "primary")
        new.setIcon(visuals.icon("plus", "#ffffff", 18))
        new.clicked.connect(self.new_requested)
        games = QPushButton("  Parcourir les jeux")
        games.setIcon(visuals.icon("jeux", C["ink2"], 18))
        games.clicked.connect(self.games_requested)
        for btn in (new, games):
            btn.setCursor(Qt.PointingHandCursor)
            buttons.addWidget(btn)
        buttons.addStretch(1)
        text.addSpacing(8)
        text.addLayout(buttons)
        h.addLayout(text, 1)
        outer.addWidget(hero)

        stats = QGridLayout()
        stats.setSpacing(14)
        self.running_tile = StatTile("En marche", "alimentation")
        self.servers_tile = StatTile("Serveurs", "serveurs")
        self.machine_tile = StatTile("Cet ordinateur", "tableau-de-bord")
        for i, tile in enumerate((self.running_tile, self.servers_tile, self.machine_tile)):
            stats.addWidget(tile, 0, i)
        outer.addLayout(stats)

        live = _panel()
        lv = QVBoxLayout(live)
        lv.setContentsMargins(20, 16, 20, 16)
        lv.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(label("SERVEURS EN MARCHE", "caps"), 1)
        all_btn = set_prop(QPushButton("Tous mes serveurs"), "kind", "flat")
        all_btn.clicked.connect(self.servers_requested)
        head.addWidget(all_btn)
        lv.addLayout(head)
        self.live_rows = QVBoxLayout()
        self.live_rows.setSpacing(6)
        lv.addLayout(self.live_rows)
        outer.addWidget(live)
        outer.addStretch(1)
        self.live_key = None

    def update_from(self, servers, transient, machine):
        running = [s for s in servers if state_of(s, transient) in ("running", "starting")]
        installing = [s for s in servers if state_of(s, transient) == "installing"]
        self.running_tile.set(str(len(running)), "sur %d serveur%s" % (len(servers), "s" if len(servers) > 1 else ""))
        self.servers_tile.set(str(len(servers)), ("%d en installation" % len(installing)) if installing else
                              ("installés sur cet ordinateur" if servers else "aucun pour l'instant"))
        if machine:
            self.machine_tile.set("%s Go" % str(round(machine.get("ram_gb") or 0)).replace(".", ","),
                                  "de mémoire · %s" % machine.get("os", ""))
        key = tuple((s["id"], state_of(s, transient), s.get("connect")) for s in running)
        if key == self.live_key:
            return
        self.live_key = key
        while self.live_rows.count():
            old = self.live_rows.takeAt(0).widget()
            if old:
                old.setParent(None)
                old.deleteLater()
        if not running:
            self.live_rows.addWidget(label("Aucun serveur ne tourne. Démarrez-en un depuis « Serveurs ».", "muted"))
        for i, s in enumerate(running):
            row = self._row(s, state_of(s, transient))
            self.live_rows.addWidget(row)
            motion.fade_in(row, delay=i * 45)

    def _row(self, server, state):
        row = QFrame()
        row.setObjectName("card")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(14, 10, 10, 10)
        lay.setSpacing(12)
        icon = label()
        icon.setPixmap(visuals.icon_pixmap("serveurs", C["cyan"], 20))
        lay.addWidget(icon)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(label(server.get("name", server["id"]), "h2"))
        pill = Pill()
        pill.set_state(state)
        names.addWidget(pill)
        lay.addLayout(names, 1)
        if server.get("connect"):
            lay.addWidget(label(server["connect"], "mono"))
            lay.addWidget(copy_button(lambda: server["connect"]))
        open_btn = QPushButton("Ouvrir")
        open_btn.clicked.connect(lambda: self.open_requested.emit(server["id"]))
        stop = set_prop(QPushButton("  Arrêter"), "kind", "stop")
        stop.setIcon(visuals.icon("alimentation", C["bad"], 16))
        stop.clicked.connect(lambda: self.action_requested.emit(server["id"], "stop"))
        for btn in (open_btn, stop):
            btn.setCursor(Qt.PointingHandCursor)
            lay.addWidget(btn)
        return row
