"""Apparence de l'appli : identité LANa (bleu nuit, dégradé bleu -> vert, titres étroits en capitales)."""
import os
import sys

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

C = {
    "bg": "#0d141e", "bg2": "#0f1925", "surface": "#132131", "surface2": "#182a3d",
    "line": "#23405f", "line_soft": "#1b3048", "teal": "#2a8f8a",
    "ink": "#e6f3f3", "ink2": "#b5cfd4", "mut": "#6fa3ad", "faint": "#4d6e78",
    "blue": "#1b84fa", "blue_deep": "#1065e2", "cyan": "#28cffc", "green": "#43e923", "title": "#69da88",
    "ok": "#58f431", "warn": "#ffc247", "bad": "#ff5d6c",
}
# Dégradé de l'identité (logo, bouton principal, barres de progression)
GRADIENT = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1b6bfa, stop:0.5 #22b8f0, stop:1 #43d64a)"
GRADIENT_HOVER = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3a82ff, stop:0.5 #45c8f5, stop:1 #5ee865)"
FONTS = {}
# Polices choisies selon le système, sans jamais demander à Qt une famille absente : la première absente lui fait
# indexer tous les alias de polices (3 s sur un Mac de 2015), et QFontDatabase.families() coûte autant.
# Bahnschrift et Consolas sont livrées avec tous les Windows que Qt 6 accepte (10 1809 et plus récents).
WINDOWS = sys.platform == "win32"


def load_fonts():
    """Bahnschrift sous Windows, sinon Barlow embarquée : titres et menu étroits, texte courant normal."""
    if WINDOWS:
        FONTS.update(ui="Bahnschrift", display="Bahnschrift SemiBold SemiCondensed",
                     nav="Bahnschrift SemiBold SemiCondensed", strong="normal", mono="Consolas")
        return
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
    loaded = set()
    for fname in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if fname.endswith(".ttf"):
            loaded.update(QFontDatabase.applicationFontFamilies(
                QFontDatabase.addApplicationFont(os.path.join(folder, fname))))
    system = QFontDatabase.systemFont(QFontDatabase.GeneralFont).family()
    narrow = "Barlow Semi Condensed" if "Barlow Semi Condensed" in loaded else system
    FONTS.update(ui="Barlow" if "Barlow" in loaded else system, display=narrow, nav=narrow, strong="600")
    # Menlo est toujours présente sur Mac ; ailleurs, la police à chasse fixe déclarée par le système.
    FONTS["mono"] = "Menlo" if sys.platform == "darwin" else QFontDatabase.systemFont(QFontDatabase.FixedFont).family()


QSS = """
QWidget { color: %(ink)s; font-family: "%(ui)s"; font-size: 10pt; }
QMainWindow, QDialog { background: %(bg)s; }
#page, #backdrop QStackedWidget { background: transparent; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QToolTip { background: %(surface2)s; color: %(ink)s; border: 1px solid %(line)s; padding: 4px; }

QLabel[role="h1"] { font-family: "%(display)s"; font-size: 22pt; font-weight: %(strong)s; }
QLabel[role="h2"] { font-family: "%(display)s"; font-size: 14pt; font-weight: %(strong)s; }
QLabel[role="muted"] { color: %(mut)s; }
QLabel[role="caps"] { color: %(mut)s; font-family: "%(nav)s"; font-size: 9pt; font-weight: %(strong)s; letter-spacing: 1px; }
QLabel[role="mono"] { font-family: "%(mono)s"; color: %(ink2)s; }
QLabel[role="warn"] { color: %(warn)s; }
QLabel[role="bad"] { color: %(bad)s; }
QLabel[role="stat"] { font-family: "%(display)s"; font-size: 26pt; font-weight: %(strong)s; color: %(title)s; }
QLabel a { color: %(cyan)s; }

#sidebar { background: rgba(10, 17, 26, 0.72); border-right: 1px solid %(line_soft)s; }
#brand { font-family: "%(display)s"; font-size: 18pt; font-weight: %(strong)s; color: %(ink)s; }
#navtile { background: rgba(19, 33, 49, 0.9); border: 1px solid %(line)s; border-radius: 10px; }
#navtext { font-family: "%(nav)s"; font-size: 12pt; font-weight: %(strong)s; color: %(mut)s; letter-spacing: 1px; }
#navitem:hover #navtext { color: %(ink2)s; }
#navitem:hover #navtile { border-color: %(teal)s; }
#navitem[active="true"] #navtile { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1a5f8a, stop:1 #1f8f7a);
                                   border: 1px solid #6fe3c8; }
#navitem[active="true"] #navtext { color: %(title)s; }

#card { background: rgba(19, 33, 49, 0.88); border: 1px solid %(line)s; border-radius: 12px; }
#card:hover { border-color: %(teal)s; }
#card[live="true"] { border-color: #2f9a5a; }
#panel { background: rgba(19, 33, 49, 0.82); border: 1px solid %(line)s; border-radius: 14px; }
#empty { background: rgba(19, 33, 49, 0.6); border: 1px dashed %(line)s; border-radius: 12px; }

QPushButton { background: rgba(24, 42, 61, 0.9); border: 1px solid %(line)s; border-radius: 8px; padding: 7px 14px; }
QPushButton:hover { border-color: %(teal)s; }
QPushButton:disabled { color: %(faint)s; border-color: %(line_soft)s; }
QPushButton[kind="primary"] { background: %(gradient)s; border: none; color: #ffffff; font-family: "%(nav)s";
                              font-size: 11pt; font-weight: %(strong)s; padding: 8px 16px; }
QPushButton[kind="primary"]:hover { background: %(gradient_hover)s; }
QPushButton[kind="primary"]:disabled { background: #1d3550; color: #7f9db0; }
QPushButton[kind="stop"] { background: rgba(255, 93, 108, 0.08); border: 1px solid %(bad)s; color: %(bad)s;
                           font-family: "%(nav)s"; font-size: 11pt; font-weight: %(strong)s; }
QPushButton[kind="stop"]:hover { background: rgba(255, 93, 108, 0.16); }
QPushButton[kind="flat"] { background: transparent; border: none; color: %(mut)s; padding: 4px 6px; }
QPushButton[kind="flat"]:hover { color: %(cyan)s; }
QPushButton[size="big"] { padding: 10px 22px; font-size: 12pt; }

QLineEdit, QPlainTextEdit, QComboBox, QListWidget, QSpinBox, QDoubleSpinBox {
    background: %(bg2)s; border: 1px solid %(line)s; border-radius: 8px; padding: 6px; selection-background-color: %(blue)s;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: %(cyan)s; }
QSpinBox, QDoubleSpinBox { padding-right: 26px; min-width: 90px; }
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; width: 22px; background: %(surface2)s; border-left: 1px solid %(line)s;
}
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-position: top right; border-top-right-radius: 8px; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-position: bottom right; border-bottom-right-radius: 8px; }
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: %(line)s; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(%(up)s); width: 9px; height: 6px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url(%(down)s); width: 9px; height: 6px; }
QComboBox { padding-right: 26px; min-width: 120px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: none; }
QComboBox::down-arrow { image: url(%(down)s); width: 9px; height: 6px; }
QComboBox QAbstractItemView { background: %(surface2)s; border: 1px solid %(line)s; selection-background-color: %(blue)s; padding: 4px; }
QPlainTextEdit[role="log"] { font-family: "%(mono)s"; font-size: 9pt; color: %(ink2)s; }
QListWidget { padding: 4px; outline: none; }
QListWidget::item { padding: 8px; border-radius: 8px; }
QListWidget::item:selected { background: %(surface2)s; border: 1px solid %(cyan)s; color: %(ink)s; }
QListWidget::item:hover { background: %(surface)s; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid %(mut)s; border-radius: 4px; background: %(bg2)s; }
QCheckBox::indicator:hover { border-color: %(cyan)s; }
QCheckBox::indicator:checked { background: %(blue)s; border-color: %(cyan)s; image: url(%(check)s); }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: %(line)s; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: %(teal)s; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: %(line)s; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QTabWidget::pane { border: 1px solid %(line)s; border-radius: 12px; top: -1px; background: rgba(19, 33, 49, 0.88); }
QTabBar::tab { background: transparent; color: %(mut)s; padding: 8px 16px; border-bottom: 2px solid transparent;
               font-family: "%(nav)s"; font-size: 11pt; font-weight: %(strong)s; }
QTabBar::tab:selected { color: %(title)s; border-bottom-color: %(green)s; }
QTabBar::tab:hover { color: %(ink)s; }

QProgressBar { background: #192231; border: none; border-radius: 3px; height: 6px; text-align: center; }
QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 %(blue_deep)s, stop:1 %(cyan)s);
                      border-radius: 3px; }

QLabel[pill] { background: transparent; border: none; padding: 0; font-size: 10pt; }
QLabel[pill="stopped"] { color: %(mut)s; }
QLabel[pill="running"] { color: %(ok)s; }
QLabel[pill="busy"] { color: %(cyan)s; }
QLabel[pill="error"] { color: %(bad)s; }
"""


def apply(app):
    load_fonts()
    app.setStyle("Fusion")
    pal = QPalette()
    for role, key in ((QPalette.Window, "bg"), (QPalette.Base, "bg2"), (QPalette.AlternateBase, "surface"),
                      (QPalette.Button, "surface2"), (QPalette.Text, "ink"), (QPalette.WindowText, "ink"),
                      (QPalette.ButtonText, "ink"), (QPalette.Highlight, "blue"), (QPalette.HighlightedText, "ink"),
                      (QPalette.ToolTipBase, "surface2"), (QPalette.ToolTipText, "ink"), (QPalette.Link, "cyan"),
                      (QPalette.PlaceholderText, "faint")):
        pal.setColor(role, QColor(C[key]))
    app.setPalette(pal)
    app.setFont(QFont(FONTS["ui"], 10))
    here = os.path.dirname(os.path.abspath(__file__))
    icons = {name: os.path.join(here, fname).replace("\\", "/")
             for name, fname in (("check", "check.svg"), ("up", "arrow-up.svg"), ("down", "arrow-down.svg"))}
    app.setStyleSheet(QSS % dict(C, gradient=GRADIENT, gradient_hover=GRADIENT_HOVER, **icons, **FONTS))
