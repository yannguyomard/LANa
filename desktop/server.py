"""Page d'un serveur : état, boutons, adresse à partager ; journal en mode avancé."""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QPlainTextEdit, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from . import core
from .backups import BackupsTab
from .home import copy_button, state_of
from .settings import SettingsTab, display_value, summary_fields
from .widgets import Pill, label, run_async, set_prop


class ServerPage(QWidget):
    back_requested = Signal()
    action_requested = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        self.server_id = None
        self.server = None
        self.advanced = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 18, 32, 24)
        outer.setSpacing(14)

        back = set_prop(QPushButton("←  Mes serveurs"), "kind", "flat")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.back_requested)
        outer.addWidget(back, 0, Qt.AlignLeft)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        self.game = label("", "caps")
        self.name = label("", "h1")
        self.pill = Pill()
        titles.addWidget(self.game)
        titles.addWidget(self.name)
        titles.addWidget(self.pill, 0, Qt.AlignLeft)
        head.addLayout(titles, 1)
        self.restart = QPushButton("Redémarrer")
        self.primary = set_prop(set_prop(QPushButton(), "kind", "primary"), "size", "big")
        self.primary.setMinimumWidth(140)
        for btn in (self.restart, self.primary):
            btn.setCursor(Qt.PointingHandCursor)
            head.addWidget(btn, 0, Qt.AlignBottom)
        self.restart.clicked.connect(lambda: self.action_requested.emit(self.server_id, "restart"))
        self.primary.clicked.connect(lambda: self.action_requested.emit(self.server_id, self.primary.property("action")))
        outer.addLayout(head)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_overview(), "Aperçu")
        self.settings = SettingsTab()
        self.settings.restart_requested.connect(lambda: self.action_requested.emit(self.server_id, "restart"))
        self.tabs.addTab(self.settings, "Réglages")
        self.backups = BackupsTab()
        self.tabs.addTab(self.backups, "Sauvegardes")
        self.log_tab = self._tab_log()
        self.tabs.currentChanged.connect(lambda *_: self._refresh_log())
        outer.addWidget(self.tabs, 1)

        self.log_timer = QTimer(self, interval=2000, timeout=self._refresh_log)

    # ---------- onglets ----------

    def _tab_overview(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(16)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.addWidget(label("Sur votre réseau (même box)", "caps"), 0, 0, 1, 2)
        self.lan = label("", "mono")
        self.lan.setTextInteractionFlags(Qt.TextSelectableByMouse)
        grid.addWidget(self.lan, 1, 0)
        self.lan_copy = copy_button(lambda: (self.server or {}).get("connect", ""))
        grid.addWidget(self.lan_copy, 1, 1, Qt.AlignLeft)
        grid.addWidget(label("Depuis Internet", "caps"), 2, 0, 1, 2)
        self.wan = label("", "mono", wrap=True)
        self.wan.setTextInteractionFlags(Qt.TextSelectableByMouse)
        grid.addWidget(self.wan, 3, 0)
        self.wan_copy = copy_button(lambda: (self.server or {}).get("connect_wan", ""))
        grid.addWidget(self.wan_copy, 3, 1, Qt.AlignLeft)
        grid.setColumnStretch(0, 1)
        lay.addLayout(grid)

        self.hint = label("", "muted", wrap=True)
        lay.addWidget(self.hint)

        lay.addSpacing(6)
        head = QHBoxLayout()
        head.addWidget(label("Réglages principaux", "caps"))
        head.addStretch(1)
        edit = set_prop(QPushButton("Modifier les réglages"), "kind", "flat")
        edit.setCursor(Qt.PointingHandCursor)
        edit.clicked.connect(lambda: self.tabs.setCurrentWidget(self.settings))
        head.addWidget(edit)
        lay.addLayout(head)
        self.summary = QGridLayout()
        self.summary.setHorizontalSpacing(18)
        self.summary.setVerticalSpacing(6)
        self.summary.setColumnStretch(1, 1)
        lay.addLayout(self.summary)
        self.summary_key = None
        lay.addStretch(1)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #1b3048;")
        lay.addWidget(line)
        foot = QHBoxLayout()
        self.folder = label("", "muted")
        self.folder.setTextInteractionFlags(Qt.TextSelectableByMouse)
        foot.addWidget(self.folder, 1)
        delete = set_prop(QPushButton("Supprimer ce serveur…"), "kind", "flat")
        delete.clicked.connect(lambda: self.action_requested.emit(self.server_id, "delete"))
        foot.addWidget(delete)
        lay.addLayout(foot)
        return tab

    def _tab_log(self):
        self.log = QPlainTextEdit(readOnly=True)
        self.log.setLineWrapMode(QPlainTextEdit.NoWrap)
        set_prop(self.log, "role", "log")
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addWidget(self.log)
        return tab

    def _refresh_log(self):
        if self.server_id and self.tabs.currentWidget() is self.log_tab and self.isVisible():
            run_async(core.log_tail, self.server_id, done=self._show_log)

    def _show_log(self, text):
        bar = self.log.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 4
        if text != self.log.toPlainText():
            self.log.setPlainText(text or "(journal vide : le serveur n'a pas encore été démarré)")
            if at_end:
                bar.setValue(bar.maximum())

    # ---------- état ----------

    def show_server(self, server_id):
        self.server_id = server_id
        self.server = None
        self.summary_key = None
        self.settings.server = None
        self.backups.key = None
        self.log.clear()
        self.tabs.setCurrentIndex(0)

    def set_advanced(self, advanced):
        self.advanced = advanced
        has = self.tabs.indexOf(self.log_tab) >= 0
        if advanced and not has:
            self.tabs.addTab(self.log_tab, "Journal")
            self.log_timer.start()
        elif not advanced and has:
            self.tabs.removeTab(self.tabs.indexOf(self.log_tab))
            self.log_timer.stop()
        if self.server:
            self.settings.load(self.server, advanced, force=True)

    def update_from(self, server, transient):
        self.server = server
        state = state_of(server, transient)
        self.game.setText(server.get("game_name", server["game"]).upper())
        self.name.setText(server.get("name", server["id"]))
        self.pill.set_state(state)

        if state in ("running", "starting"):
            self._button("Arrêter", "stop", "stop")
        elif state == "stopped":
            self._button("Démarrer", "start", "primary")
        elif state == "incomplete":
            self._button("Réessayer l'installation", "retry", "primary")
        else:
            self._button(Pill.TEXT[state], None, "primary")
        self.restart.setVisible(state == "running")

        live = state in ("running", "starting")
        connect = server.get("connect") or "—"
        self.lan.setText(connect if server["installed"] else "—")
        self.lan_copy.setVisible(server["installed"] and bool(server.get("connect")))
        upnp = server.get("upnp") or {}
        if server.get("connect_wan"):
            self.wan.setText(server["connect_wan"])
        elif upnp.get("state") == "error":
            self.wan.setText(upnp.get("message", ""))
        elif upnp.get("enabled"):
            self.wan.setText("Ouverture des ports sur la box en cours…" if live else "Disponible quand le serveur tourne.")
        else:
            self.wan.setText("Non ouvert : seuls les joueurs de votre réseau peuvent venir.")
        self.wan_copy.setVisible(bool(server.get("connect_wan")))

        if state == "starting":
            self.hint.setText("Le serveur démarre : attendez un peu avant de vous connecter.")
        elif live:
            self.hint.setText("Dans le jeu, choisissez de rejoindre un serveur et entrez l'adresse ci-dessus.")
        elif state == "stopped":
            self.hint.setText("Démarrez le serveur pour que vos amis puissent le rejoindre.")
        else:
            self.hint.setText("")
        self.folder.setText(server.get("save_path", "") if self.advanced else "")
        self._update_summary(server)
        self.settings.load(server, self.advanced)
        self.backups.update_from(server, self.advanced, state in ("running", "starting", "stopping"))

    def _update_summary(self, server):
        rows = []
        if server.get("installed"):
            values = server.get("values") or {}
            rows = [(f["label"], display_value(f, values.get(f["key"], f.get("default"))))
                    for f in summary_fields(server.get("fields", []))]
        key = repr(rows)
        if key == self.summary_key:
            return
        self.summary_key = key
        while self.summary.count():
            old = self.summary.takeAt(0).widget()
            old.setParent(None)
            old.deleteLater()
        if not rows:
            self.summary.addWidget(label("Disponibles une fois le serveur installé.", "muted"), 0, 0, 1, 2)
        for i, (name, value) in enumerate(rows):
            self.summary.addWidget(label(name, "muted"), i, 0)
            shown = label(value)
            shown.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.summary.addWidget(shown, i, 1)

    def _button(self, text, action, kind):
        self.primary.setText(text)
        self.primary.setProperty("action", action)
        self.primary.setEnabled(action is not None)
        if self.primary.property("kind") != kind:
            set_prop(self.primary, "kind", kind)
