"""Page « Réglages » de l'appli (pas ceux d'un serveur) : mode avancé, dossier des données, version."""
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from . import core
from .widgets import label


class PrefsPage(QWidget):
    advanced_changed = Signal(bool)

    def __init__(self, advanced):
        super().__init__()
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 26, 32, 26)
        outer.setSpacing(16)
        outer.addWidget(label("Réglages", "h1"))

        panel = QFrame()
        panel.setObjectName("panel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(8)
        lay.addWidget(label("AFFICHAGE", "caps"))
        self.adv = QCheckBox("Mode avancé")
        self.adv.setChecked(advanced)
        self.adv.toggled.connect(self.advanced_changed)
        lay.addWidget(self.adv)
        lay.addWidget(label("Montre tous les réglages des serveurs (ports, performances…), le journal, le choix de "
                            "version à l'installation, les jeux non testés et les chemins des fichiers.",
                            "muted", wrap=True))
        lay.addSpacing(12)
        lay.addWidget(label("DOSSIER DES SERVEURS", "caps"))
        row = QHBoxLayout()
        path = label(core.data_dir(), "mono")
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(path, 1)
        open_dir = QPushButton("Ouvrir")
        open_dir.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(core.data_dir())))
        row.addWidget(open_dir)
        lay.addLayout(row)
        lay.addSpacing(12)
        lay.addWidget(label("À PROPOS", "caps"))
        lay.addWidget(label("LANa %s · logiciel libre (MIT)" % core.VERSION, "muted"))
        outer.addWidget(panel)
        outer.addStretch(1)
