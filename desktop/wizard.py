"""Assistant « Nouveau serveur » : choisir le jeu, le nommer, installer."""
import html

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLineEdit, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from . import core
from .widgets import label, run_async, set_prop

LEVEL_TEXT = {"ok": "", "warn": "⚠ ", "bad": "✕ "}


class NewServerDialog(QDialog):
    installed = Signal(str)        # id du serveur prêt
    changed = Signal()             # la liste des serveurs a changé
    start_requested = Signal(str)

    def __init__(self, parent, advanced):
        super().__init__(parent)
        self.advanced = advanced
        self.setWindowTitle("Nouveau serveur")
        self.resize(640, 560)
        self.games = []
        self.chosen = None
        self.instance_id = None
        self.job_id = None
        self.archive = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        self.step = label("", "caps")
        self.title = label("", "h1")
        root.addWidget(self.step)
        root.addWidget(self.title)
        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)
        self.pages.addWidget(self._page_game())
        self.pages.addWidget(self._page_details())
        self.pages.addWidget(self._page_install())

        buttons = QHBoxLayout()
        self.back = QPushButton("Retour")
        self.back.clicked.connect(lambda: self._go(0))
        self.next = set_prop(QPushButton("Continuer"), "kind", "primary")
        self.next.clicked.connect(self._next)
        self.cancel = QPushButton("Annuler")
        self.cancel.clicked.connect(self.reject)
        buttons.addWidget(self.back)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel)
        buttons.addWidget(self.next)
        root.addLayout(buttons)

        self.timer = QTimer(self, interval=700, timeout=self._poll)
        self._go(0)
        run_async(core.catalog, done=self._catalog_loaded, failed=self._catalog_failed)

    # ---------- étape 1 : le jeu ----------

    def _page_game(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit(placeholderText="Rechercher un jeu…")
        self.search.textChanged.connect(self._fill_games)
        lay.addWidget(self.search)
        self.game_list = QListWidget()
        self.game_list.setWordWrap(True)
        self.game_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.game_list.currentItemChanged.connect(lambda *_: self._update_buttons())
        self.game_list.itemDoubleClicked.connect(lambda *_: self._next())
        lay.addWidget(self.game_list, 1)
        self.show_all = QCheckBox("Afficher aussi les jeux qui ne tourneront pas sur cet ordinateur")
        self.show_all.toggled.connect(self._fill_games)
        lay.addWidget(self.show_all)
        return page

    def _catalog_loaded(self, games):
        self.games = sorted(games, key=lambda g: g["name"].lower())
        self._fill_games()

    def _catalog_failed(self, message):
        self.game_list.clear()
        self.game_list.addItem("Catalogue illisible : " + message)

    def _fill_games(self):
        words = self.search.text().strip().lower()
        self.game_list.clear()
        for g in self.games:
            level = g["verdict"]["level"]
            if level == "bad" and not self.show_all.isChecked():
                continue
            if words and words not in g["name"].lower():
                continue
            notes = []
            if g["untested"] and self.advanced:
                notes.append("non testé")
            if level != "ok" and g["verdict"]["messages"]:
                notes.append(g["verdict"]["messages"][0])
            text = LEVEL_TEXT[level] + g["name"] + ("\n" + " · ".join(notes) if notes else "")
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, g)
            if level == "bad":
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.game_list.addItem(item)
        if not self.game_list.count():
            self.game_list.addItem("Aucun jeu ne correspond." if words else "Aucun jeu compatible trouvé.")
        self._update_buttons()

    # ---------- étape 2 : les détails ----------

    def _page_details(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(label("Nom du serveur", "caps"))
        self.name = QLineEdit()
        self.name.setMaxLength(60)
        lay.addWidget(self.name)
        self.needs = label("", "muted", wrap=True)
        lay.addWidget(self.needs)
        self.warnings = label("", "warn", wrap=True)
        lay.addWidget(self.warnings)

        self.version_box = QWidget()
        vlay = QVBoxLayout(self.version_box)
        vlay.setContentsMargins(0, 6, 0, 0)
        vlay.addWidget(label("Version", "caps"))
        self.version = QComboBox()
        vlay.addWidget(self.version)
        lay.addWidget(self.version_box)

        self.upload_box = QWidget()
        ulay = QVBoxLayout(self.upload_box)
        ulay.setContentsMargins(0, 6, 0, 0)
        ulay.addWidget(label("Fichiers du serveur", "caps"))
        self.upload_help = label("", "muted", wrap=True)
        self.upload_help.setOpenExternalLinks(True)
        ulay.addWidget(self.upload_help)
        pick = QHBoxLayout()
        self.upload_name = label("Aucune archive choisie", "muted")
        choose = QPushButton("Choisir l'archive…")
        choose.clicked.connect(self._pick_archive)
        pick.addWidget(choose)
        pick.addWidget(self.upload_name, 1)
        ulay.addLayout(pick)
        lay.addWidget(self.upload_box)

        self.eula = QCheckBox()
        self.eula.toggled.connect(self._update_buttons)
        self.eula_link = label("", wrap=True)
        self.eula_link.setOpenExternalLinks(True)
        lay.addSpacing(6)
        lay.addWidget(self.eula)
        lay.addWidget(self.eula_link)
        lay.addStretch(1)
        return page

    def _show_details(self):
        g = self.chosen
        self.name.setText(g["name"])
        req = g["requirements"]
        bits = ["Mémoire conseillée : %s Go" % req.get("ram_gb_recommended", req.get("ram_gb_min", "?")),
                "Espace disque : %s Go" % req.get("disk_gb", "?")]
        self.needs.setText(" · ".join(bits) + ("\n" + req["note"] if req.get("note") else ""))
        messages = g["verdict"]["messages"] if g["verdict"]["level"] != "ok" else []
        self.warnings.setText("\n".join(messages))
        self.warnings.setVisible(bool(messages))

        upload = g["install_type"] == "upload"
        self.upload_box.setVisible(upload)
        self.upload_help.setText(html.escape(g["install_help"]))
        self.version_box.setVisible(self.advanced and bool(g["versions"]) and not upload)
        if self.version_box.isVisible():
            self.version.clear()
            self.version.addItem("Dernière version (recommandé)", "")
            self.version.addItem("Chargement de la liste…", None)
            run_async(core.version_options, g["id"], done=self._versions_loaded, failed=self._versions_failed)

        eula = g.get("eula")
        self.eula.setVisible(bool(eula))
        self.eula_link.setVisible(bool(eula))
        self.eula.setChecked(False)
        if eula:
            self.eula.setText("J'ai lu et j'accepte : " + eula["label"])
            self.eula_link.setText('<a href="%s">Lire le contrat</a>' % html.escape(eula["url"]))

    def _versions_loaded(self, options):
        self.version.removeItem(1)
        for opt in options:
            self.version.addItem(opt["label"], opt["id"])

    def _versions_failed(self, message):
        self.version.setItemText(1, message)

    def _pick_archive(self):
        path, _ = QFileDialog.getOpenFileName(self, "Archive des fichiers du serveur", "",
                                              "Archives (*.zip *.tar *.tar.gz *.tgz);;Tous les fichiers (*)")
        if path:
            self.archive = path
            self.upload_name.setText(path)
            self._update_buttons()

    # ---------- étape 3 : l'installation ----------

    def _page_install(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.status = label("", "muted", wrap=True)
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)
        self.details_btn = set_prop(QPushButton("Afficher les détails"), "kind", "flat")
        self.details_btn.clicked.connect(lambda: self._toggle_details(not self.details.isVisible()))
        lay.addWidget(self.details_btn, 0, Qt.AlignLeft)
        self.details = QPlainTextEdit(readOnly=True)
        set_prop(self.details, "role", "log")
        lay.addWidget(self.details, 1)
        self._toggle_details(self.advanced)
        lay.addStretch(0)
        return page

    def _toggle_details(self, shown):
        self.details.setVisible(shown)
        self.details_btn.setText("Masquer les détails" if shown else "Afficher les détails")

    def _install(self):
        g = self.chosen
        accept = self.eula.isChecked()
        version = self.version.currentData() if self.version_box.isVisible() else None
        self._go(2)
        self.status.setText("Préparation…")

        def work():
            sid = core.create(g["id"], self.name.text())
            try:
                if g["install_type"] == "upload":
                    core.install_upload(sid, self.archive, accept)
                    return sid, None
                return sid, core.install(sid, accept, version)["id"]
            except Exception:
                core.delete(sid)   # rien d'installé : pas de serveur fantôme dans la liste
                raise

        run_async(work, done=self._install_started, failed=self._install_failed)

    def _install_started(self, result):
        self.instance_id, self.job_id = result
        self.changed.emit()
        if self.job_id is None:
            self._finished(True, "")
            return
        self.status.setText("Téléchargement et installation de %s. Cela peut prendre plusieurs minutes ; "
                            "vous pouvez fermer cette fenêtre, l'installation continue." % self.chosen["name"])
        self.cancel.setText("Fermer")
        self.timer.start()

    def _install_failed(self, message):
        self._finished(False, message)

    def _poll(self):
        snap = core.job(self.job_id)
        if not snap:
            return
        self.details.setPlainText("\n".join(snap["lines"]))
        self.details.verticalScrollBar().setValue(self.details.verticalScrollBar().maximum())
        if snap["state"] != "running":
            self.timer.stop()
            last = snap["lines"][-1] if snap["lines"] else ""
            self._finished(snap["state"] == "done", last)

    def _finished(self, ok, message):
        self.bar.setRange(0, 1)
        self.bar.setValue(1 if ok else 0)
        self.changed.emit()
        self.back.hide()
        if ok:
            self.title.setText("Votre serveur est prêt !")
            self.status.setText("« %s » est installé. Démarrez-le, puis donnez son adresse à vos amis." % self.name.text())
            self.next.setText("Démarrer maintenant")
            self.next.setEnabled(True)
            self.next.show()
            self.cancel.setText("Fermer")
            self.installed.emit(self.instance_id)
        else:
            self.title.setText("L'installation a échoué")
            set_prop(self.status, "role", "bad")
            self.status.setText(message or "Erreur inconnue.")
            self._toggle_details(True)
            self.next.hide()
            self.cancel.setText("Fermer")
            # Échec avant la création du serveur : on peut recommencer ici. Sinon il reste dans la liste avec « Réessayer ».
            self.back.setText("Recommencer")
            self.back.setVisible(self.instance_id is None)

    # ---------- navigation ----------

    def _go(self, index):
        self.pages.setCurrentIndex(index)
        self.step.setText("ÉTAPE %d SUR 3" % (index + 1))
        self.title.setText(["Quel jeu ?", "Votre serveur", "Installation"][index])
        if index == 0:
            set_prop(self.status, "role", "muted")
            self.back.setText("Retour")
        self.back.setVisible(index == 1)
        self.next.setText("Installer" if index == 1 else "Continuer")
        self.next.setVisible(index < 2)
        self._update_buttons()

    def _update_buttons(self, *_):
        index = self.pages.currentIndex()
        if index == 0:
            item = self.game_list.currentItem()
            self.next.setEnabled(bool(item and item.data(Qt.UserRole)))
        elif index == 1 and self.chosen:
            ok = not (self.chosen.get("eula") and not self.eula.isChecked())
            if self.chosen["install_type"] == "upload" and not self.archive:
                ok = False
            self.next.setEnabled(ok)

    def _next(self):
        index = self.pages.currentIndex()
        if index == 0:
            item = self.game_list.currentItem()
            if not (item and item.data(Qt.UserRole)):
                return
            self.chosen = item.data(Qt.UserRole)
            self.archive = ""
            self.upload_name.setText("Aucune archive choisie")
            self._go(1)
            self._show_details()
            self._update_buttons()
        elif index == 1:
            self._install()
        elif self.instance_id:
            self.start_requested.emit(self.instance_id)
            self.accept()
