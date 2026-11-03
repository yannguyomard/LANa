"""Appli de bureau LANa : python -m desktop (depuis la racine du dépôt)."""
import os
import sys

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

from . import core, motion, style
from .widgets import app_icon
from .window import MainWindow, data_lock_path


def main():
    if sys.platform == "win32":
        # Icône propre dans la barre des tâches (sinon celle de Python).
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LANa.Desktop")
    app = QApplication(sys.argv)
    app.setApplicationName("LANa")
    app.setOrganizationName("LANa")
    app.setWindowIcon(app_icon())
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
