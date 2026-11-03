"""Apparence de l'appli : couleurs et polices du thème LANa du panneau (web/index.html)."""
import os

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

from . import core

C = {
    "bg": "#0e0e10", "bg2": "#121215", "surface": "#16161a", "surface2": "#1c1c21", "line": "#2c2c33",
    "ink": "#f0f0f0", "ink2": "#c7c7c7", "mut": "#9a9aa3", "faint": "#80808a",
    "acc": "#7c4dff", "acc2": "#d9ccff", "acc_hover": "#8f66ff", "ok": "#4ff0a6", "warn": "#ffb547", "bad": "#ff6b6b",
}
FONTS = {"display": "Segoe UI", "ui": "Segoe UI", "mono": "Consolas"}


def load_fonts():
    folder = os.path.join(core.ROOT, "web", "static", "fonts")
    for key, fname in (("display", "space-grotesk.woff2"), ("ui", "inter.woff2"), ("mono", "jetbrains-mono.woff2")):
        fid = QFontDatabase.addApplicationFont(os.path.join(folder, fname))
        families = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        if families:
            FONTS[key] = families[0]


QSS = """
QWidget { color: %(ink)s; font-family: "%(ui)s"; font-size: 10pt; }
QMainWindow, QDialog, #page { background: %(bg)s; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QToolTip { background: %(surface2)s; color: %(ink)s; border: 1px solid %(line)s; padding: 4px; }

QLabel[role="h1"] { font-family: "%(display)s"; font-size: 20pt; font-weight: 600; }
QLabel[role="h2"] { font-family: "%(display)s"; font-size: 14pt; font-weight: 600; }
QLabel[role="muted"] { color: %(mut)s; }
QLabel[role="caps"] { color: %(mut)s; font-size: 8pt; font-weight: 600; letter-spacing: 1px; }
QLabel[role="mono"] { font-family: "%(mono)s"; }
QLabel[role="warn"] { color: %(warn)s; }
QLabel[role="bad"] { color: %(bad)s; }
QLabel a { color: %(acc2)s; }

#topbar { background: %(bg2)s; border-bottom: 1px solid %(line)s; }
#card { background: %(surface)s; border: 1px solid %(line)s; border-radius: 10px; }
#card:hover { border-color: #3a3a44; }
#empty { background: %(surface)s; border: 1px dashed %(line)s; border-radius: 10px; }

QPushButton { background: %(surface2)s; border: 1px solid %(line)s; border-radius: 6px; padding: 7px 14px; }
QPushButton:hover { border-color: %(mut)s; }
QPushButton:disabled { color: %(faint)s; border-color: %(surface2)s; }
QPushButton[kind="primary"] { background: %(acc)s; border-color: %(acc)s; color: white; font-weight: 600; }
QPushButton[kind="primary"]:hover { background: %(acc_hover)s; }
QPushButton[kind="primary"]:disabled { background: #3d2f6e; border-color: #3d2f6e; color: #b9b0d6; }
QPushButton[kind="stop"] { background: transparent; border-color: %(bad)s; color: %(bad)s; font-weight: 600; }
QPushButton[kind="flat"] { background: transparent; border: none; color: %(mut)s; padding: 4px 6px; }
QPushButton[kind="flat"]:hover { color: %(ink)s; }
QPushButton[size="big"] { padding: 10px 20px; font-size: 11pt; }

QLineEdit, QPlainTextEdit, QComboBox, QListWidget, QSpinBox, QDoubleSpinBox {
    background: %(bg2)s; border: 1px solid %(line)s; border-radius: 6px; padding: 6px; selection-background-color: %(acc)s;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: %(acc)s; }
QSpinBox, QDoubleSpinBox { padding-right: 26px; min-width: 90px; }
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; width: 22px; background: %(surface2)s; border-left: 1px solid %(line)s;
}
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-position: top right; border-top-right-radius: 6px; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-position: bottom right; border-bottom-right-radius: 6px; }
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: %(line)s; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(%(up)s); width: 9px; height: 6px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url(%(down)s); width: 9px; height: 6px; }
QComboBox { padding-right: 26px; min-width: 120px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: none; }
QComboBox::down-arrow { image: url(%(down)s); width: 9px; height: 6px; }
QComboBox QAbstractItemView { background: %(surface2)s; border: 1px solid %(line)s; selection-background-color: %(acc)s; padding: 4px; }
QPlainTextEdit[role="log"] { font-family: "%(mono)s"; font-size: 9pt; color: %(ink2)s; }
QListWidget { padding: 4px; outline: none; }
QListWidget::item { padding: 8px; border-radius: 6px; }
QListWidget::item:selected { background: %(surface2)s; border: 1px solid %(acc)s; color: %(ink)s; }
QListWidget::item:hover { background: %(surface)s; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid %(mut)s; border-radius: 4px; background: %(bg2)s; }
QCheckBox::indicator:hover { border-color: %(acc2)s; }
QCheckBox::indicator:checked { background: %(acc)s; border-color: %(acc)s; image: url(%(check)s); }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: %(line)s; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: %(faint)s; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: %(line)s; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QTabWidget::pane { border: 1px solid %(line)s; border-radius: 8px; top: -1px; background: %(surface)s; }
QTabBar::tab { background: transparent; color: %(mut)s; padding: 8px 16px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: %(ink)s; border-bottom-color: %(acc)s; }
QTabBar::tab:hover { color: %(ink)s; }

QProgressBar { background: %(bg2)s; border: 1px solid %(line)s; border-radius: 4px; height: 8px; text-align: center; }
QProgressBar::chunk { background: %(acc)s; border-radius: 3px; }

QLabel[pill="stopped"] { color: %(mut)s; }
QLabel[pill="running"] { color: %(ok)s; }
QLabel[pill="busy"] { color: %(warn)s; }
QLabel[pill="error"] { color: %(bad)s; }
QLabel[pill] { background: %(bg2)s; border: 1px solid %(line)s; border-radius: 11px; padding: 3px 10px; font-size: 9pt; font-weight: 600; min-height: 16px; }
"""


def apply(app):
    load_fonts()
    app.setStyle("Fusion")
    pal = QPalette()
    for role, key in ((QPalette.Window, "bg"), (QPalette.Base, "bg2"), (QPalette.AlternateBase, "surface"),
                      (QPalette.Button, "surface2"), (QPalette.Text, "ink"), (QPalette.WindowText, "ink"),
                      (QPalette.ButtonText, "ink"), (QPalette.Highlight, "acc"), (QPalette.HighlightedText, "ink"),
                      (QPalette.ToolTipBase, "surface2"), (QPalette.ToolTipText, "ink"), (QPalette.Link, "acc2"),
                      (QPalette.PlaceholderText, "faint")):
        pal.setColor(role, QColor(C[key]))
    app.setPalette(pal)
    app.setFont(QFont(FONTS["ui"], 10))
    here = os.path.dirname(os.path.abspath(__file__))
    icons = {name: os.path.join(here, fname).replace("\\", "/")
             for name, fname in (("check", "check.svg"), ("up", "arrow-up.svg"), ("down", "arrow-down.svg"))}
    app.setStyleSheet(QSS % dict(C, **icons, **FONTS))
