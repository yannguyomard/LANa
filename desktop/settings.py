"""Onglet « Réglages » d'un serveur : formulaire construit depuis les champs du jeu (games/*.json).

Mode simple : les réglages qui parlent à tout le monde (nom, joueurs, mot de passe, mode de jeu…).
Mode avancé : tous les champs, y compris réseau, performances et sauvegardes, et le fichier de configuration.
"""
import os

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLineEdit,
                               QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from . import core
from .widgets import label, run_async, set_prop

def is_essential(field):
    """Réglage montré à un débutant : ceux que games/*.json ne marque pas "advanced" (ports, performances…)."""
    return not field.get("advanced") and field["type"] != "collection"


def summary_fields(fields):
    """Réglages repris dans l'Aperçu : les principaux, sans les cases à cocher."""
    return [f for f in fields if is_essential(f) and f["type"] in ("text", "int", "enum")][:6]


def display_value(field, value):
    if field["type"] == "enum":
        return (field.get("labels") or {}).get(value, value)
    if field["type"] == "bool":
        return "Oui" if value else "Non"
    if value in ("", None):
        return "(vide)"
    return str(value)


class SettingsTab(QWidget):
    restart_requested = Signal()
    saved = Signal()

    def __init__(self):
        super().__init__()
        self.server = None
        self.advanced = False
        self.inputs = {}       # clé -> (champ, fonction qui lit la valeur)
        self.loaded = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll, 1)

        bar = QHBoxLayout()
        bar.setContentsMargins(20, 10, 20, 14)
        self.note = label("", "muted", wrap=True)
        bar.addWidget(self.note, 1)
        self.file_btn = QPushButton("Ouvrir le fichier de configuration")
        self.file_btn.clicked.connect(self._open_file)
        bar.addWidget(self.file_btn)
        self.reset = QPushButton("Annuler les modifications")
        self.reset.clicked.connect(lambda: self.load(self.server, self.advanced, force=True))
        bar.addWidget(self.reset)
        self.save = set_prop(QPushButton("Enregistrer"), "kind", "primary")
        self.save.clicked.connect(self._save)
        bar.addWidget(self.save)
        outer.addLayout(bar)

    # ---------- construction ----------

    def load(self, server, advanced, force=False):
        """(Re)construit le formulaire ; ne touche pas à une saisie en cours sauf si force."""
        same = self.server and server and self.server["id"] == server["id"]
        if same and not force and self.advanced == advanced and self.inputs:
            self.server = server
            return
        if same and not force and self.is_dirty():
            self.server = server
            return
        self.server, self.advanced = server, advanced
        self.inputs = {}
        self.loaded = dict(server.get("values") or {})
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)

        if not server.get("installed"):
            lay.addWidget(label("Les réglages seront disponibles une fois le serveur installé.", "muted"))
            lay.addStretch(1)
            self.scroll.setWidget(page)
            self._update_bar()
            return

        fields = [f for f in server["fields"] if advanced or is_essential(f)]
        hidden = len([f for f in server["fields"] if f["type"] != "collection"]) - len(
            [f for f in fields if f["type"] != "collection"])
        groups = []
        for f in fields:
            if f["group"] not in groups:
                groups.append(f["group"])
        # Un seul formulaire pour toutes les sections : les colonnes restent alignées.
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        for n, group in enumerate(groups):
            title = label(group.upper(), "caps")
            title.setContentsMargins(0, 0 if n == 0 else 14, 0, 0)
            form.addRow(title)
            for f in (f for f in fields if f["group"] == group):
                widget = self._input(f, self.loaded.get(f["key"], f.get("default")))
                if widget is None:
                    continue
                form.addRow(label(f["label"], wrap=True) if f["type"] != "bool" else QWidget(), widget)
                if f.get("hint"):
                    hint = label(f["hint"], "muted", wrap=True)
                    hint.setContentsMargins(0, 0, 0, 4)
                    # Largeur fixe : QFormLayout calcule mal la hauteur d'un texte replié sinon (dernière ligne coupée).
                    hint.setFixedWidth(420)
                    hint.setMinimumHeight(hint.heightForWidth(420))
                    form.addRow(QWidget(), hint)
        lay.addLayout(form)
        lay.addStretch(1)
        self.scroll.setWidget(page)
        self.note.setText("" if advanced or hidden <= 0 else
                          "%d réglage%s technique%s (ports, performances…) en mode avancé." %
                          (hidden, "s" if hidden > 1 else "", "s" if hidden > 1 else ""))
        self._update_bar()

    def _input(self, f, value):
        t, key = f["type"], f["key"]
        if t == "bool":
            w = QCheckBox(f["label"])
            w.setChecked(bool(value))
            w.toggled.connect(self._update_bar)
            get = w.isChecked
        elif t == "text":
            w = QLineEdit(str(value if value is not None else ""))
            w.setMaxLength(f.get("maxlen", 200))
            if not f.get("required", True):
                w.setPlaceholderText("(vide)")
            w.textChanged.connect(self._update_bar)
            get = lambda w=w: w.text().strip()   # noqa: E731
        elif t == "int":
            w = QSpinBox()
            w.setRange(int(f.get("min", 0)), int(f.get("max", 2**31 - 1)))
            w.setValue(int(value if value is not None else w.minimum()))
            w.valueChanged.connect(self._update_bar)
            get = w.value
        elif t in ("float", "minutes_ns"):
            w = QDoubleSpinBox()
            w.setDecimals(0 if t == "minutes_ns" else 2)
            w.setRange(float(f.get("min", 0)), float(f.get("max", 1e9)))
            w.setSingleStep(1 if t == "minutes_ns" else 0.1)
            w.setValue(float(value if value is not None else w.minimum()))
            w.valueChanged.connect(self._update_bar)
            get = w.value
        elif t == "enum":
            w = QComboBox()
            for opt in f["options"]:
                w.addItem((f.get("labels") or {}).get(opt, opt), opt)
            index = w.findData(value)
            w.setCurrentIndex(max(index, 0))
            w.currentIndexChanged.connect(self._update_bar)
            get = w.currentData
        elif t == "tags":
            w = QWidget()
            row = QHBoxLayout(w)
            row.setContentsMargins(0, 0, 0, 0)
            boxes = []
            for opt in f["options"]:
                cb = QCheckBox((f.get("labels") or {}).get(opt, opt))
                cb.setChecked(opt in (value or []))
                cb.toggled.connect(self._update_bar)
                row.addWidget(cb)
                boxes.append((opt, cb))
            row.addStretch(1)
            get = lambda boxes=boxes: [o for o, cb in boxes if cb.isChecked()]   # noqa: E731
        else:
            return None   # collection : modifiable dans le fichier de configuration (mode avancé)
        if t not in ("bool", "tags"):
            w.setMaximumWidth(420)
        self.inputs[key] = (f, get)
        return w

    # ---------- état ----------

    def values(self):
        return {key: get() for key, (f, get) in self.inputs.items()}

    def is_dirty(self):
        current = self.values()
        for key, value in current.items():
            before = self.loaded.get(key)
            if isinstance(value, float) and isinstance(before, (int, float)):
                if abs(value - before) > 1e-9:
                    return True
            elif value != before:
                return True
        return False

    def _update_bar(self, *_):
        dirty = bool(self.inputs) and self.is_dirty()
        self.save.setEnabled(dirty)
        self.reset.setEnabled(dirty)
        self.save.setVisible(bool(self.inputs))
        self.reset.setVisible(bool(self.inputs))
        self.file_btn.setVisible(self.advanced and bool(self.server and self.server.get("installed")))

    # ---------- actions ----------

    def _save(self):
        server, values = self.server, self.values()
        self.save.setEnabled(False)

        def done(_):
            self.loaded = dict(self.loaded, **values)
            self._update_bar()
            self.saved.emit()
            if server.get("running"):
                answer = QMessageBox.question(self, "Réglages enregistrés",
                                              "Les nouveaux réglages s'appliqueront au prochain démarrage.\n\n"
                                              "Redémarrer le serveur maintenant ?",
                                              QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                if answer == QMessageBox.Yes:
                    self.restart_requested.emit()

        def failed(message):
            self._update_bar()
            QMessageBox.warning(self, "Réglages non enregistrés", message)

        run_async(core.write_config, server["id"], values, done=done, failed=failed)

    def _open_file(self):
        path = core.config_path(self.server["id"])
        # Pas d'application associée à .cfg/.ini sur certains systèmes : on ouvre alors le dossier.
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
