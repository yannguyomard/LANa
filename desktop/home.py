"""Accueil : « Mes serveurs », une carte par serveur avec son état et le bouton principal."""
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from .widgets import Pill, label, set_prop


class Transient:
    """États passagers que le moteur ne connaît pas : « démarrage… » et « arrêt… »."""

    def __init__(self):
        self._until = {}

    def set(self, instance_id, state, seconds):
        self._until[instance_id] = (state, time.time() + seconds)

    def clear(self, instance_id):
        self._until.pop(instance_id, None)

    def get(self, instance_id):
        state, until = self._until.get(instance_id, (None, 0))
        return state if time.time() < until else None


def state_of(server, transient):
    if server.get("broken"):
        return "broken"
    job = server.get("job")
    if job and job["state"] == "running":
        return "installing"
    if not server["installed"]:
        return "incomplete"
    passing = transient.get(server["id"])
    if passing == "stopping":
        return "stopping"
    if server["running"]:
        return "starting" if passing == "starting" else "running"
    return "stopped"


def copy_button(get_text):
    btn = set_prop(QPushButton("Copier"), "kind", "flat")
    btn.setCursor(Qt.PointingHandCursor)

    def copy():
        QGuiApplication.clipboard().setText(get_text())
        btn.setText("Copié ✓")

    btn.clicked.connect(copy)
    return btn


class ServerCard(QFrame):
    open_requested = Signal(str)
    action_requested = Signal(str, str)   # id, "start" | "stop" | "retry" | "delete"

    def __init__(self, server_id):
        super().__init__()
        self.server_id = server_id
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 14, 14, 14)
        row.setSpacing(16)

        text = QVBoxLayout()
        text.setSpacing(4)
        self.game = label("", "caps")
        self.name = label("", "h2")
        state_row = QHBoxLayout()
        state_row.setSpacing(10)
        self.pill = Pill()
        self.detail = label("", "muted")
        self.address = ""
        self.copy = copy_button(lambda: self.address)
        state_row.addWidget(self.pill)
        state_row.addWidget(self.detail)
        state_row.addWidget(self.copy)
        state_row.addStretch(1)
        text.addWidget(self.game)
        text.addWidget(self.name)
        text.addLayout(state_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        text.addWidget(self.progress)
        row.addLayout(text, 1)

        self.secondary = QPushButton()
        self.primary = set_prop(set_prop(QPushButton(), "kind", "primary"), "size", "big")
        self.primary.setMinimumWidth(130)
        for btn in (self.secondary, self.primary):
            btn.setCursor(Qt.PointingHandCursor)
            row.addWidget(btn, 0, Qt.AlignVCenter)
        self.primary.clicked.connect(lambda: self.action_requested.emit(self.server_id, self.primary.property("action")))
        self.secondary.clicked.connect(lambda: self.action_requested.emit(self.server_id, self.secondary.property("action")))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.open_requested.emit(self.server_id)

    def update_from(self, server, state, game_name):
        self.game.setText(game_name.upper())
        self.name.setText(server.get("name", server["id"]))
        self.pill.set_state(state)
        self.progress.setVisible(state == "installing")
        self.address = server.get("connect") or ""
        detail = ""
        if state in ("running", "starting") and self.address:
            detail = "Adresse pour vos amis : " + self.address
        elif state == "incomplete":
            job = server.get("job")
            detail = job["lines"][-1] if job and job["state"] == "error" and job["lines"] else "L'installation n'est pas allée au bout."
        elif state == "broken":
            detail = server["broken"]
        self.detail.setText(detail)
        self.copy.setVisible(state in ("running", "starting") and bool(self.address))
        if self.copy.text() != "Copier" and not self.copy.underMouse():
            self.copy.setText("Copier")

        if state in ("running", "starting"):
            self._set(self.primary, "Arrêter", "stop", "stop")
        elif state == "stopped":
            self._set(self.primary, "Démarrer", "start", "primary")
        elif state == "incomplete":
            self._set(self.primary, "Réessayer", "retry", "primary")
        else:
            self._set(self.primary, Pill.TEXT[state], None, "primary")
        self.primary.setEnabled(self.primary.property("action") is not None)
        self.secondary.setVisible(state in ("incomplete", "broken"))
        self._set(self.secondary, "Supprimer", "delete", None)

    @staticmethod
    def _set(btn, text, action, kind):
        btn.setText(text)
        btn.setProperty("action", action)
        if kind is not None and btn.property("kind") != kind:
            set_prop(btn, "kind", kind)


class HomePage(QWidget):
    new_requested = Signal()
    open_requested = Signal(str)
    action_requested = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 24, 32, 24)
        outer.setSpacing(18)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("Mes serveurs", "h1"))
        self.summary = label("", "muted")
        titles.addWidget(self.summary)
        head.addLayout(titles, 1)
        add = set_prop(set_prop(QPushButton("+  Nouveau serveur"), "kind", "primary"), "size", "big")
        add.setCursor(Qt.PointingHandCursor)
        add.clicked.connect(self.new_requested)
        head.addWidget(add, 0, Qt.AlignBottom)
        outer.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.list = QVBoxLayout(holder)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(10)
        self.list.addStretch(1)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)

        self.empty = QFrame()
        self.empty.setObjectName("empty")
        box = QVBoxLayout(self.empty)
        box.setContentsMargins(30, 40, 30, 40)
        box.setSpacing(8)
        for widget in (label("Aucun serveur pour l'instant", "h2"),
                       label("Choisissez un jeu : LANa télécharge le serveur, le règle pour cet ordinateur "
                             "et vous donne l'adresse à partager avec vos amis.", "muted", wrap=True)):
            widget.setAlignment(Qt.AlignCenter)
            box.addWidget(widget)
        start = set_prop(QPushButton("Créer mon premier serveur"), "kind", "primary")
        start.clicked.connect(self.new_requested)
        box.addWidget(start, 0, Qt.AlignCenter)
        self.empty.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.list.insertWidget(0, self.empty)

        self.cards = {}

    def update_from(self, servers, transient, game_names):
        seen = set()
        for i, server in enumerate(servers):
            sid = server["id"]
            seen.add(sid)
            card = self.cards.get(sid)
            if card is None:
                card = self.cards[sid] = ServerCard(sid)
                card.open_requested.connect(self.open_requested)
                card.action_requested.connect(self.action_requested)
                self.list.insertWidget(i, card)
            card.update_from(server, state_of(server, transient), game_names.get(server["game"], server["game"]))
        for sid in list(self.cards):
            if sid not in seen:
                self.cards.pop(sid).deleteLater()
        self.empty.setVisible(not servers)
        running = sum(1 for s in servers if s.get("running"))
        if servers:
            self.summary.setText("%d serveur%s, %d en marche" % (len(servers), "s" if len(servers) > 1 else "", running))
        else:
            self.summary.setText("")
