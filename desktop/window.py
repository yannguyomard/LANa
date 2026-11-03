"""Fenêtre principale : barre du haut, accueil et page d'un serveur, actions et rafraîchissement."""
import html
import os

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QMainWindow, QMessageBox,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from . import core
from .home import HomePage, Transient
from .server import ServerPage
from .widgets import Logo, label, run_async, set_prop
from .wizard import NewServerDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("LANa", "LANa")
        self.advanced = self.settings.value("advanced", False, type=bool)
        self.transient = Transient()
        self.servers = []
        self.game_names = {}
        self.loading = False
        self.closing_ok = False

        self.setWindowTitle("LANa")
        self.resize(980, 680)
        self.setMinimumSize(720, 520)
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._topbar())
        self.stack = QStackedWidget()
        self.home = HomePage()
        self.page = ServerPage()
        self.stack.addWidget(self.home)
        self.stack.addWidget(self.page)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.home.new_requested.connect(self.new_server)
        self.home.open_requested.connect(self.open_server)
        self.home.action_requested.connect(self.act)
        self.page.back_requested.connect(lambda: self.stack.setCurrentWidget(self.home))
        self.page.action_requested.connect(self.act)
        self.page.set_advanced(self.advanced)

        core.start_services()
        run_async(core.catalog, done=self._names_loaded)
        self.timer = QTimer(self, interval=2500, timeout=self.refresh)
        self.timer.start()
        self.refresh()

    def _topbar(self):
        bar = QFrame()
        bar.setObjectName("topbar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(20, 10, 16, 10)
        row.setSpacing(10)
        row.addWidget(Logo(26))
        title = label("LANa", "h2")
        row.addWidget(title)
        row.addWidget(label("Serveurs de jeu pour vos amis", "muted"))
        row.addStretch(1)
        self.mode = label("", "caps")
        row.addWidget(self.mode)
        prefs = set_prop(QPushButton("Préférences"), "kind", "flat")
        prefs.clicked.connect(self.preferences)
        row.addWidget(prefs)
        self._show_mode()
        return bar

    def _show_mode(self):
        self.mode.setText("MODE AVANCÉ" if self.advanced else "")

    # ---------- données ----------

    def _names_loaded(self, catalog):
        self.game_names = {g["id"]: g["name"] for g in catalog}
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

        run_async(core.servers, done=done, failed=failed)

    def _render(self):
        self.home.update_from(self.servers, self.transient, self.game_names)
        if self.stack.currentWidget() is self.page:
            current = next((s for s in self.servers if s["id"] == self.page.server_id), None)
            if current is None:
                self.stack.setCurrentWidget(self.home)
            else:
                self.page.update_from(current, self.transient, self.game_names.get(current["game"], current["game"]))

    def _server(self, server_id):
        return next((s for s in self.servers if s["id"] == server_id), None)

    # ---------- navigation ----------

    def open_server(self, server_id):
        self.page.show_server(server_id)
        self.stack.setCurrentWidget(self.page)
        self._render()

    def new_server(self):
        dialog = NewServerDialog(self, self.advanced)
        dialog.changed.connect(self.refresh)
        dialog.start_requested.connect(lambda sid: (self.open_server(sid), self.act(sid, "start")))
        dialog.finished.connect(lambda *_: (self.refresh(), dialog.deleteLater()))
        dialog.open()

    def preferences(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Préférences")
        lay = QVBoxLayout(dialog)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(10)
        lay.addWidget(label("Préférences", "h2"))
        adv = QCheckBox("Mode avancé")
        adv.setChecked(self.advanced)
        lay.addWidget(adv)
        lay.addWidget(label("Affiche le journal des serveurs, le choix de version à l'installation, les jeux non testés "
                            "et les chemins des fichiers.", "muted", wrap=True))
        lay.addSpacing(8)
        lay.addWidget(label("Dossier des serveurs", "caps"))
        row = QHBoxLayout()
        path = label(core.data_dir(), "mono")
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(path, 1)
        open_dir = QPushButton("Ouvrir")
        open_dir.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(core.data_dir())))
        row.addWidget(open_dir)
        lay.addLayout(row)
        lay.addWidget(label("LANa %s" % core.VERSION, "muted"))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(dialog.accept)
        lay.addWidget(buttons)
        dialog.setMinimumWidth(460)
        if dialog.exec():
            self.advanced = adv.isChecked()
            self.settings.setValue("advanced", self.advanced)
            self.page.set_advanced(self.advanced)
            self._show_mode()
            self._render()

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
        eula = server.get("eula")
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
            self.stack.setCurrentWidget(self.home)
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
