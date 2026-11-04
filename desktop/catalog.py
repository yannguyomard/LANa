"""Page « Jeux » : le catalogue, filtré par défaut aux jeux qui tournent sur cet ordinateur."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLineEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from . import core, motion, visuals
from .style import C
from .widgets import label, run_async, set_prop

COLUMNS = 3


class GamesPage(QWidget):
    create_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        self.games = []
        self.advanced = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 26, 32, 26)
        outer.setSpacing(16)
        outer.addWidget(label("Jeux", "h1"))

        bar = QHBoxLayout()
        bar.setSpacing(12)
        self.search = QLineEdit(placeholderText="Rechercher un jeu")
        self.search.addAction(visuals.icon("recherche", C["mut"], 18), QLineEdit.LeadingPosition)
        self.search.setMaximumWidth(380)
        self.search.textChanged.connect(self._fill)
        bar.addWidget(self.search)
        self.show_all = QCheckBox("Afficher aussi les jeux qui ne tourneront pas sur cet ordinateur")
        self.show_all.toggled.connect(self._fill)
        bar.addWidget(self.show_all)
        bar.addStretch(1)
        outer.addLayout(bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.grid = QGridLayout(holder)
        self.grid.setContentsMargins(0, 0, 4, 0)
        self.grid.setSpacing(14)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)
        self.status = label("Chargement du catalogue…", "muted")
        self.grid.addWidget(self.status, 0, 0)

    def load(self):
        if not self.games:
            run_async(core.catalog, done=self._loaded, failed=lambda m: self.status.setText("Catalogue illisible : " + m))

    def set_advanced(self, advanced):
        self.advanced = advanced
        self._fill()

    def _loaded(self, games):
        self.games = sorted(games, key=lambda g: g["name"].lower())
        self._fill()

    def _fill(self, *_):
        if not self.games:
            return
        while self.grid.count():
            old = self.grid.takeAt(0).widget()
            if old:
                old.setParent(None)
                old.deleteLater()
        words = self.search.text().strip().lower()
        shown = [g for g in self.games
                 if (self.show_all.isChecked() or g["verdict"]["level"] != "bad") and (not words or words in g["name"].lower())]
        for i, g in enumerate(shown):
            card = self._card(g)
            self.grid.addWidget(card, i // COLUMNS, i % COLUMNS)
            if i < 12:   # les premières cartes apparaissent en cascade, les suivantes sont hors de vue
                motion.fade_in(card, delay=i * 35)
        if not shown:
            self.grid.addWidget(label("Aucun jeu ne correspond.", "muted"), 0, 0)
        for c in range(COLUMNS):
            self.grid.setColumnStretch(c, 1)
        self.grid.setRowStretch(len(shown) // COLUMNS + 1, 1)

    def _card(self, g):
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)
        head = QHBoxLayout()
        icon = label()
        icon.setPixmap(visuals.icon_pixmap("jeux", C["cyan"], 22))
        head.addWidget(icon)
        head.addWidget(label(g["name"], "h2", wrap=True), 1)
        lay.addLayout(head)
        req = g["requirements"]
        lay.addWidget(label("%s Go de mémoire conseillés" % req.get("ram_gb_recommended", req.get("ram_gb_min", "?")),
                            "muted"))
        level = g["verdict"]["level"]
        notes = list(g["verdict"]["messages"]) if level != "ok" else []
        if g["untested"] and self.advanced:
            notes.append("Pas encore testé.")
        if notes:
            lay.addWidget(label(notes[0], "bad" if level == "bad" else "warn", wrap=True))
        lay.addStretch(1)
        create = set_prop(QPushButton("  Créer un serveur"), "kind", "primary")
        create.setIcon(visuals.icon("plus", "#ffffff", 16))
        create.setCursor(Qt.PointingHandCursor)
        create.setEnabled(level != "bad")
        create.clicked.connect(lambda: self.create_requested.emit(g["id"]))
        lay.addWidget(create)
        return card
