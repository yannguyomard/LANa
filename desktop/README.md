# LANa — appli de bureau

Même moteur que le panneau web (`lana/`, appelé directement, sans HTTP), dans une fenêtre Qt (PySide6).
Pensée pour un utilisateur sans connaissances techniques ; le **mode avancé** (Préférences) montre le reste.

```
pip install -r desktop/requirements.txt
python -m desktop            # depuis la racine du dépôt
```

Données : les mêmes que le panneau web (`~/LANa`, ou `LANA_HOME`). Pour essayer sans toucher à ses vrais serveurs :
`LANA_HOME=/chemin/demo python -m desktop`. Une seule fenêtre LANa à la fois (verrou `appli.lock` dans ce dossier).

| Fichier | Rôle |
|---|---|
| `core.py` | pont vers `lana/` (lecture, installation, démarrage, arrêt…), appelé en arrière-plan |
| `window.py` | fenêtre, barre du haut, préférences, actions, fermeture (arrêter ou laisser tourner les serveurs) |
| `home.py` | « Mes serveurs » : une carte par serveur, état et bouton principal |
| `wizard.py` | « Nouveau serveur » : jeu, nom (+ version en mode avancé, contrat de licence), installation |
| `server.py` | page d'un serveur : adresses à partager, journal (mode avancé) |
| `style.py`, `widgets.py` | thème LANa, travail en arrière-plan, logo, pastille d'état |

Pas encore fait : réglages, sauvegardes, joueurs, mods, liste blanche, UPnP par serveur, paquet Windows,
verrou commun avec le panneau web (les deux interfaces ne doivent pas tourner en même temps).
