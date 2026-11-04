"""Appli de bureau LANa : python -m desktop (depuis la racine du dépôt)."""
import faulthandler
import os
import shutil
import sys

from PySide6.QtCore import QLibraryInfo, QLocale, QLockFile, QTranslator
from PySide6.QtWidgets import QApplication, QMessageBox

from . import core, motion, style
from .widgets import app_icon
from .window import MainWindow, data_lock_path


def redirect_log():
    """Lancée par LANa.exe (sans console visible), l'appli écrit sa sortie et ses erreurs dans appli.log, dans le
    dossier des serveurs ; le journal précédent est gardé dans appli.precedent.log."""
    if not os.environ.get("LANA_APP_LOG"):
        return
    os.makedirs(core.data_dir(), exist_ok=True)
    path = os.path.join(core.data_dir(), "appli.log")
    if os.path.exists(path):
        shutil.copyfile(path, os.path.join(core.data_dir(), "appli.precedent.log"))
    log = open(path, "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log
    faulthandler.enable(log)   # plantage du processus : la pile Python est écrite dans le journal


def french_qt(app):
    """Boutons standard de Qt (Oui, Annuler…) en français : traductions de Qt livrées avec PySide6."""
    translator = QTranslator(app)
    if translator.load(QLocale(QLocale.French), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(translator)
    return translator


def main():
    redirect_log()
    if sys.platform == "win32":
        # Icône propre dans la barre des tâches (sinon celle de Python).
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LANa.Desktop")
    app = QApplication(sys.argv)
    app.setApplicationName("LANa")
    app.setOrganizationName("LANa")
    app.setWindowIcon(app_icon())
    french_qt(app)
    style.apply(app)

    os.makedirs(core.data_dir(), exist_ok=True)
    lock = QLockFile(data_lock_path())
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, "LANa", "LANa est déjà ouvert sur cet ordinateur.")
        return 0

    glow = motion.HoverGlow(app)   # halo au survol, pour toute l'appli
    app.installEventFilter(glow)
    window = MainWindow()
    motion.fade_window(window)
    window.show()
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
