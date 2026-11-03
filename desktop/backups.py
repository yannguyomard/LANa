"""Onglet « Sauvegardes » : sauvegarder, restaurer, exporter, importer.

Le moteur garde les 10 dernières archives et en fait une à chaque arrêt du serveur ; restaurer ou importer
archive d'abord la sauvegarde actuelle (« avant-import »).
"""
import os
import re

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QMessageBox, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from . import core
from .widgets import label, run_async, set_prop

MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre"]
KINDS = {"avant-arret": "Automatique, à l'arrêt du serveur", "manuelle": "Faite à la main",
         "avant-import": "Faite avant une restauration ou un import", "export": "Faite pour un export"}
NAME = re.compile(r"^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})-([a-z0-9-]*)\.tar\.gz$")


def describe(name):
    """« 3 novembre 2026 à 21:15 », « Automatique, à l'arrêt du serveur » d'après le nom de l'archive."""
    m = NAME.match(name)
    if not m:
        return name, ""
    y, mo, d, h, mi, _, kind = m.groups()
    when = "%d %s %s à %s:%s" % (int(d), MONTHS[int(mo) - 1], y, h, mi)
    return when, KINDS.get(kind, kind)


class BackupsTab(QWidget):
    def __init__(self):
        super().__init__()
        self.server = None
        self.advanced = False
        self.key = None
        self.busy = False
        self.running = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)

        self.intro = label("LANa fait une sauvegarde à chaque arrêt du serveur et garde les 10 dernières. "
                           "Restaurer une sauvegarde remet le monde dans l'état de ce moment-là ; le monde actuel "
                           "est d'abord mis de côté, rien n'est perdu.", "muted", wrap=True)
        outer.addWidget(self.intro)

        actions = QHBoxLayout()
        self.now = set_prop(QPushButton("Sauvegarder maintenant"), "kind", "primary")
        self.now.clicked.connect(self._backup_now)
        self.export_now = QPushButton("Exporter le monde actuel…")
        self.export_now.clicked.connect(lambda: self._export(""))
        self.import_btn = QPushButton("Importer une sauvegarde…")
        self.import_btn.clicked.connect(self._import)
        for btn in (self.now, self.export_now, self.import_btn):
            btn.setCursor(Qt.PointingHandCursor)
            actions.addWidget(btn)
        actions.addStretch(1)
        outer.addLayout(actions)
        self.warning = label("", "warn", wrap=True)
        outer.addWidget(self.warning)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.rows = QVBoxLayout(holder)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(0)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)

        self.paths = QHBoxLayout()
        self.paths_label = label("", "muted")
        self.paths_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.paths.addWidget(self.paths_label, 1)
        self.open_save = set_prop(QPushButton("Dossier du monde"), "kind", "flat")
        self.open_save.clicked.connect(lambda: self._open_dir(self.server.get("save_path")))
        self.open_backups = set_prop(QPushButton("Dossier des archives"), "kind", "flat")
        self.open_backups.clicked.connect(lambda: self._open_dir(self.server.get("backup_dir")))
        self.paths.addWidget(self.open_save)
        self.paths.addWidget(self.open_backups)
        outer.addLayout(self.paths)

    # ---------- affichage ----------

    def update_from(self, server, advanced, running):
        self.server, self.running = server, running
        installed = server.get("installed")
        for btn in (self.now, self.export_now, self.import_btn):
            btn.setVisible(bool(installed))
        self.now.setEnabled(not self.busy)
        self.export_now.setEnabled(not self.busy)
        self.import_btn.setEnabled(not self.busy and not running)
        self.warning.setText("Arrêtez le serveur pour restaurer ou importer une sauvegarde." if running and installed else "")
        self.warning.setVisible(bool(self.warning.text()))
        show_paths = advanced and bool(installed)
        self.paths_label.setText(("Monde : %s\nArchives : %s" % (server.get("save_path", ""), server.get("backup_dir", "")))
                                 if show_paths else "")
        for w in (self.paths_label, self.open_save, self.open_backups):
            w.setVisible(show_paths)

        backups = server.get("backups") or []
        key = (server["id"], tuple(b["name"] for b in backups), running, advanced, self.busy, bool(installed))
        if key == self.key:
            return
        self.key, self.advanced = key, advanced
        while self.rows.count():
            old = self.rows.takeAt(0).widget()
            if old:
                old.setParent(None)   # retirée tout de suite, pas seulement à la suppression différée
                old.deleteLater()
        if not installed:
            self.rows.addWidget(label("Les sauvegardes seront disponibles une fois le serveur installé.", "muted"))
        elif not backups:
            self.rows.addWidget(label("Aucune sauvegarde pour l'instant : la première sera faite au premier arrêt "
                                      "du serveur, ou maintenant avec « Sauvegarder maintenant ».", "muted", wrap=True))
        for b in backups:
            self.rows.addWidget(self._row(b))
        self.rows.addStretch(1)

    def _row(self, b):
        row = QFrame()
        row.setStyleSheet("QFrame#bkrow { border-bottom: 1px solid #1b3048; }")
        row.setObjectName("bkrow")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(4, 10, 4, 10)
        lay.setSpacing(10)
        when, kind = describe(b["name"])
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label(when))
        size = "moins de 0,1 Mo" if b["size_mb"] < 0.1 else ("%s Mo" % b["size_mb"]).replace(".", ",")
        sub = "%s · %s" % (kind, size) if kind else size
        if self.advanced:
            sub += " · " + b["name"]
        text.addWidget(label(sub, "muted"))
        lay.addLayout(text, 1)
        export = set_prop(QPushButton("Exporter…"), "kind", "flat")
        export.clicked.connect(lambda: self._export(b["name"]))
        restore = QPushButton("Restaurer")
        restore.setEnabled(not self.running and not self.busy)
        restore.setToolTip("Arrêtez le serveur pour restaurer" if self.running else "")
        restore.clicked.connect(lambda: self._restore(b["name"]))
        for btn in (export, restore):
            btn.setCursor(Qt.PointingHandCursor)
            lay.addWidget(btn)
        return row

    # ---------- actions ----------

    def _work(self, fn, args, ok_message, error_title):
        self.busy = True
        self.update_from(self.server, self.advanced, self.running)

        def done(result):
            self.busy = False
            self.key = None
            QMessageBox.information(self, "Sauvegardes", ok_message(result) if callable(ok_message) else ok_message)

        def failed(message):
            self.busy = False
            self.key = None
            QMessageBox.warning(self, error_title, message)

        run_async(fn, *args, done=done, failed=failed)

    def _backup_now(self):
        self._work(core.backup, (self.server["id"], "manuelle"), "Sauvegarde faite.", "Sauvegarde impossible")

    def _export(self, name):
        default = "%s-%s" % (self.server["id"], name or "monde.tar.gz")
        dest, _ = QFileDialog.getSaveFileName(self, "Exporter la sauvegarde",
                                              os.path.join(os.path.expanduser("~"), "Downloads", default),
                                              "Archive LANa (*.tar.gz)")
        if not dest:
            return
        if not dest.endswith(".tar.gz"):
            dest += ".tar.gz"
        self._work(core.export_backup, (self.server["id"], name, dest),
                   "Sauvegarde exportée :\n%s\n\nPour la remettre, ici ou sur un autre ordinateur : "
                   "« Importer une sauvegarde »." % dest, "Export impossible")

    def _restore(self, name):
        when, _ = describe(name)
        answer = QMessageBox.question(self, "Restaurer une sauvegarde",
                                      "Remettre le monde dans son état du %s ?\n\nLe monde actuel est d'abord "
                                      "archivé : vous pourrez y revenir." % when,
                                      QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer == QMessageBox.Yes:
            self._work(core.restore, (self.server["id"], name), "Sauvegarde restaurée.", "Restauration impossible")

    def _import(self):
        formats = self.server.get("import_formats") or [{"label": "Archive LANa", "extensions": [".tar.gz"]}]
        patterns = " ".join("*" + e for f in formats for e in f["extensions"])
        filters = ";;".join(["Sauvegardes (%s)" % patterns] +
                            ["%s (%s)" % (f["label"], " ".join("*" + e for e in f["extensions"])) for f in formats])
        path, _ = QFileDialog.getOpenFileName(self, "Importer une sauvegarde", os.path.expanduser("~"), filters)
        if not path:
            return
        answer = QMessageBox.question(self, "Importer une sauvegarde",
                                      "Remplacer le monde de ce serveur par :\n%s\n\nLe monde actuel est d'abord "
                                      "archivé : vous pourrez y revenir." % os.path.basename(path),
                                      QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer == QMessageBox.Yes:
            self._work(core.import_save, (self.server["id"], path),
                       lambda message: message + ". L'ancien monde est archivé.", "Import impossible")

    def _open_dir(self, path):
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path if os.path.isdir(path) else os.path.dirname(path)))
