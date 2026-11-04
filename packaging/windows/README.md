# LANa pour Windows

Version portable de l'appli de bureau : un zip à décompresser, rien à installer.

```
LANa\
  LANa.exe        lanceur (C#, compilé par le csc.exe du .NET Framework 4 présent sur tous les Windows)
  python\         Python « embeddable » officiel + PySide6 réduit (QtCore, QtGui, QtWidgets, QtSvg)
  app\            lana\, games\, desktop\ (sans le panneau web ni les tests)
  LISEZMOI.txt
```

## Fabriquer

```
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

Résultat : `packaging\windows\build\LANa-<version>-windows-x64.zip` (environ 71 Mo décompressé). Il faut un Python
3.9+ avec pip sur la machine de fabrication, seulement pour télécharger les roues PySide6 ; le Python embarqué et
les roues sont gardés dans `build\cache`. Le script essaie ensuite l'appli avec ce Python et ce PySide6 réduits
(`smoke_test.py` : la fenêtre se construit, la traduction française de Qt se charge).

## Le lanceur

`LANa.exe` lance `python\python.exe -m desktop` dans une console cachée : les serveurs de jeu en héritent (aucune
fenêtre noire) et LANa peut leur envoyer Ctrl+Pause pour les arrêter proprement. La sortie de l'appli va dans
`%USERPROFILE%\LANa\appli.log` ; si l'appli s'arrête en erreur dans les 6 premières secondes, le lanceur l'affiche.

## Antivirus

Le lanceur n'est pas signé. Bitdefender l'a mis en quarantaine juste après sa compilation (2026-11-04), puis a
continué de bloquer les emplacements où il l'avait trouvé : un petit exécutable inconnu qui lance un programme sans
fenêtre est un profil surveillé. Les utilisateurs de Bitdefender risquent donc de voir LANa.exe supprimé.
Pistes : signaler le faux positif à l'éditeur de l'antivirus, et signer l'exécutable (certificat de signature
de code, ou SignPath, gratuit pour les projets libres).

Pour fabriquer malgré tout : exclure `packaging\windows\build` de l'analyse (antivirus et surveillance des
comportements). Le paquet est assemblé dans `build\sortie\` ; un ancien emplacement resté bloqué par l'antivirus
peut être supprimé après un redémarrage.
