"""Fenêtre principale : menu latéral (tableau de bord, serveurs, jeux, réglages), pages, actions, rafraîchissement."""
import html
import os

from PySide6.QtCore import QEvent, QPoint, QSettings, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMainWindow, QMessageBox, QStackedWidget, QVBoxLayout, QWidget

from . import core, motion
from .frame import Grips, TitleBar, start_move
from .catalog import GamesPage
from .dashboard import DashboardPage
from .home import HomePage, Transient
from .prefs import PrefsPage
from .server import ServerPage
from .widgets import Backdrop, Logo, NavItem, label, run_async
from .wizard import NewServerDialog

NAV = [("dashboard", "tableau-de-bord", "Tableau de bord"), ("servers", "serveurs", "Serveurs"),
       ("games", "jeux", "Jeux"), ("prefs", "reglages", "Réglages")]


class Sidebar(QFrame):
    """Menu latéral ; un clic sur une zone vide déplace la fenêtre (elle n'a plus de barre de titre système)."""

    def mousePressEvent(self, event):
        start_move(self, event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.window().titlebar.toggle_maximized()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Pas de cadre Windows : barre de titre, boutons et bords de redimensionnement sont ceux de l'appli.
        # Les boutons réduire/agrandir restent déclarés au système (clic sur l'icône de la barre des tâches).
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowMinMaxButtonsHint)
        self.settings = QSettings("LANa", "LANa")
        self.advanced = self.settings.value("advanced", False, type=bool)
        self.transient = Transient()
        self.servers = []
        self.machine = None
        self.loading = False
        self.closing_ok = False

        self.setWindowTitle("LANa")
        self.resize(1100, 720)
        self.setMinimumSize(860, 560)
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

        central = Backdrop()
        central.setObjectName("backdrop")
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._sidebar())
        right = QWidget()
        column = QVBoxLayout(right)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.titlebar = TitleBar(self)
        column.addWidget(self.titlebar)
        self.stack = QStackedWidget()
        self.dashboard = DashboardPage()
        self.home = HomePage()
        self.page = ServerPage()
        self.games = GamesPage()
        self.prefs = PrefsPage(self.advanced)
        self.pages = {"dashboard": self.dashboard, "servers": self.home, "games": self.games, "prefs": self.prefs}
        for widget in (self.dashboard, self.home, self.page, self.games, self.prefs):
            self.stack.addWidget(widget)
        column.addWidget(self.stack, 1)
        lay.addWidget(right, 1)
        self.setCentralWidget(central)
        self.grips = Grips(self)

        self.dashboard.new_requested.connect(self.new_server)
        self.dashboard.games_requested.connect(lambda: self.go("games"))
        self.dashboard.servers_requested.connect(lambda: self.go("servers"))
        self.dashboard.open_requested.connect(self.open_server)
        self.dashboard.action_requested.connect(self.act)
        self.home.new_requested.connect(self.new_server)
        self.home.open_requested.connect(self.open_server)
        self.home.action_requested.connect(self.act)
        self.page.back_requested.connect(lambda: self.go("servers"))
        self.page.action_requested.connect(self.act)
        self.games.create_requested.connect(self.new_server)
        self.prefs.advanced_changed.connect(self.set_advanced)
        self.page.set_advanced(self.advanced)
        self.games.set_advanced(self.advanced)

        core.start_services()
        run_async(core.machine, done=self._machine_loaded)
        self.timer = QTimer(self, interval=2500, timeout=self.refresh)
        self.timer.start()
        self.go("dashboard")
        self.refresh()
        self.games.load()   # en arrière-plan dès l'ouverture : la page Jeux est prête au premier clic

    def _sidebar(self):
        bar = Sidebar()
        bar.setObjectName("sidebar")
        bar.setFixedWidth(250)
        col = QVBoxLayout(bar)
        col.setContentsMargins(22, 24, 18, 20)
        col.setSpacing(8)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        brand.addWidget(Logo(52))
        name = label("LANa")
        name.setObjectName("brand")
        brand.addWidget(name, 1)
        col.addLayout(brand)
        col.addSpacing(26)
        self.nav = {}
        for key, icon_name, text in NAV:
            item = NavItem(icon_name, text)
            item.clicked.connect(lambda key=key: self.go(key))
            self.nav[key] = item
            col.addWidget(item)
        col.addStretch(1)
        # Repère de l'entrée active : glisse d'une entrée à l'autre (OutBack)
        self.indicator = QFrame(bar)
        self.indicator.setObjectName("navindicator")
        self.indicator.setFixedSize(4, 30)
        self.indicator_key = None
        self.mode = label("", "caps")
        col.addWidget(self.mode)
        self._show_mode()
        return bar

    def _show_mode(self):
        self.mode.setText("MODE AVANCÉ" if self.advanced else "")

    def _show_page(self, widget):
        if self.stack.currentWidget() is not widget:
            self.stack.setCurrentWidget(widget)
            motion.enter(widget)

    def _activate(self, key):
        for k, item in self.nav.items():
            item.set_active(k == key)
        self._place_indicator(animate=self.indicator_key is not None and self.isVisible())
        self.indicator_key = key

    def _place_indicator(self, animate=True):
        key = next((k for k, item in self.nav.items() if item.property("active") == "true"), None)
        if key is None:
            return
        item = self.nav[key]
        target = QPoint(6, item.y() + (item.height() - self.indicator.height()) // 2)
        if animate:
            motion.slide(self.indicator, target)
        else:
            self.indicator.move(target)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, lambda: self._place_indicator(animate=False))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.grips.place()
        self._place_indicator(animate=False)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self.grips.place()

    def go(self, key):
        """Affiche une page du menu ; la page d'un serveur compte comme « Serveurs »."""
        widget = self.pages.get(key, self.page)
        self._show_page(widget)
        self._activate(key)
        if key == "games":
            self.games.load()
        self._render()

    def set_advanced(self, advanced):
        self.advanced = advanced
        self.settings.setValue("advanced", advanced)
        self.page.set_advanced(advanced)
        self.games.set_advanced(advanced)
        self._show_mode()
        self._render()

    # ---------- données ----------

    def _machine_loaded(self, machine):
        self.machine = machine
        self._render()

    def refresh(self):
        if self.loading:
            return
        self.loading = True

        def done(servers):
            self.loading = False
            self.servers = servers
            self._render()

        def failed(message):
            self.loading = False
            self.statusBar().showMessage("Lecture des serveurs impossible : " + message, 8000)

        detail = self.page.server_id if self.stack.currentWidget() is self.page else None
        run_async(core.servers, detail, done=done, failed=failed)

    def _render(self):
        self.home.update_from(self.servers, self.transient)
        self.dashboard.update_from(self.servers, self.transient, self.machine)
        if self.stack.currentWidget() is self.page:
            current = next((s for s in self.servers if s["id"] == self.page.server_id), None)
            if current is None:
                self.go("servers")
            elif current.get("installed") and "fields" not in current:
                # Résumé seulement (serveur arrêté, page tout juste ouverte) : on attend le détail complet.
                self.refresh()
            else:
                self.page.update_from(current, self.transient)

    def _server(self, server_id):
        return next((s for s in self.servers if s["id"] == server_id), None)

    # ---------- navigation ----------

    def open_server(self, server_id):
        self.page.show_server(server_id)
        self._show_page(self.page)
        self._activate("servers")
        self._render()

    def new_server(self, game_id=None):
        dialog = NewServerDialog(self, self.advanced, game_id or None)
        dialog.changed.connect(self.refresh)
        dialog.start_requested.connect(lambda sid: (self.open_server(sid), self.act(sid, "start")))
        dialog.finished.connect(lambda *_: (self.refresh(), dialog.deleteLater()))
        dialog.open()

    # ---------- actions ----------

    def act(self, server_id, action):
        server = self._server(server_id)
        if not server or not action:
            return
        name = server.get("name", server_id)
        if action == "start":
            self.transient.set(server_id, "starting", core.startup_seconds(server["game"]))
            self._run(core.start, server_id, "Démarrage de « %s » impossible" % name)
        elif action == "stop":
            self.transient.set(server_id, "stopping", 600)
            self._run(core.stop, server_id, "Arrêt de « %s » impossible" % name)
        elif action == "restart":
            self.transient.set(server_id, "stopping", 600)

            def restarted(_):
                self.transient.set(server_id, "starting", core.startup_seconds(server["game"]))
                self.refresh()

            run_async(core.restart, server_id, done=restarted,
                      failed=lambda m: self._failed("Redémarrage de « %s » impossible" % name, server_id, m))
        elif action == "retry":
            self.retry(server)
        elif action == "delete":
            self.delete(server)
        self._render()

    def _run(self, fn, server_id, error_title):
        def done(_):
            if self.transient.get(server_id) == "stopping":
                self.transient.clear(server_id)
            self.refresh()

        run_async(fn, server_id, done=done, failed=lambda m: self._failed(error_title, server_id, m))

    def _failed(self, title, server_id, message):
        self.transient.clear(server_id)
        self.refresh()
        QMessageBox.warning(self, "LANa", "%s.\n\n%s" % (title, message))

    def retry(self, server):
        eula = core.game(server["game"]).get("eula")   # le résumé d'un serveur arrêté ne la contient pas
        if eula:
            box = QMessageBox(QMessageBox.Question, "Réessayer l'installation",
                              "Ce jeu demande d'accepter son contrat de licence :<br><a href=\"%s\">%s</a><br><br>"
                              "L'acceptez-vous ?" % (html.escape(eula["url"]), html.escape(eula["label"])),
                              QMessageBox.Yes | QMessageBox.No, self)
            box.setTextFormat(Qt.RichText)
            if box.exec() != QMessageBox.Yes:
                return
        run_async(core.install, server["id"], bool(eula), done=lambda _: self.refresh(),
                  failed=lambda m: self._failed("Installation impossible", server["id"], m))

    def delete(self, server):
        answer = QMessageBox.warning(
            self, "Supprimer le serveur",
            "Supprimer « %s » ?\n\nLe serveur, ses mondes et ses sauvegardes seront effacés de cet ordinateur. "
            "C'est définitif." % server.get("name", server["id"]),
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer != QMessageBox.Yes:
            return

        def done(_):
            self.go("servers")
            self.refresh()

        run_async(core.delete, server["id"], done=done,
                  failed=lambda m: self._failed("Suppression impossible", server["id"], m))

    # ---------- fermeture ----------

    def closeEvent(self, event):
        if self.closing_ok:
            self.settings.setValue("geometry", self.saveGeometry())
            event.accept()
            return
        try:
            running = core.running_servers()
        except Exception:  # noqa: BLE001 - au pire on ferme sans demander
            running = []
        if not running:
            self.closing_ok = True
            self.close()
            event.accept()
            return
        event.ignore()
        names = "\n".join("  •  " + s["name"] for s in running)
        box = QMessageBox(QMessageBox.Question, "Fermer LANa",
                          ("Un serveur tourne :" if len(running) == 1 else "%d serveurs tournent :" % len(running))
                          + "\n" + names, parent=self)
        box.setInformativeText("Les laisser tourner : vos amis peuvent continuer à jouer, LANa les retrouvera à sa "
                               "prochaine ouverture.")
        stop = box.addButton("Les arrêter et fermer", QMessageBox.AcceptRole)
        keep = box.addButton("Les laisser tourner", QMessageBox.DestructiveRole)
        box.addButton("Annuler", QMessageBox.RejectRole)
        box.setDefaultButton(stop)
        box.exec()
        if box.clickedButton() is keep:
            self.closing_ok = True
            self.close()
        elif box.clickedButton() is stop:
            self._stop_all_and_close(running)

    def _stop_all_and_close(self, running):
        for s in running:
            self.transient.set(s["id"], "stopping", 600)
        self._render()
        self.setEnabled(False)
        self.statusBar().showMessage("Arrêt des serveurs (avec sauvegarde)…")

        def work():
            errors = []
            for s in running:
                try:
                    core.stop(s["id"])
                except Exception as ex:  # noqa: BLE001
                    errors.append("%s : %s" % (s["name"], ex))
            return errors

        def done(errors):
            self.setEnabled(True)
            if errors and QMessageBox.warning(self, "Fermer LANa", "Certains serveurs ne se sont pas arrêtés :\n\n"
                                              + "\n".join(errors) + "\n\nFermer quand même ?",
                                              QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                self.refresh()
                return
            self.closing_ok = True
            self.close()

        run_async(work, done=done)


def data_lock_path():
    return os.path.join(core.data_dir(), "appli.lock")
