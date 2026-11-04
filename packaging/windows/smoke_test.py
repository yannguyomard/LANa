"""Essai du paquet : avec le Python embarqué et le PySide6 réduit, l'appli s'importe et sa fenêtre se construit
(sans s'afficher). Lancé par build.ps1 avec LANA_HOME pointant vers un dossier jetable."""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
from desktop import __main__ as entry, style  # noqa: E402
from desktop.window import MainWindow  # noqa: E402

if not entry.french_qt(app).isEmpty():
    print("Traduction française de Qt : ok")
style.apply(app)
window = MainWindow()
window.setAttribute(Qt.WA_DontShowOnScreen)
window.show()
app.processEvents()
window.closing_ok = True
window.close()
print("Essai de la fenêtre : ok")
