# LANa

Installer et administrer des serveurs de jeu depuis un panneau web, pensé pour de vieux Mac Intel.
Aucune dépendance Python à installer : la bibliothèque standard suffit (Python 3.9 ou plus récent).

## Lancer

```bash
python3 run.py            # panneau sur http://localhost:8765
python3 run.py --lan      # accessible depuis le réseau local (jamais sur Internet : pas de chiffrement)
```

Au premier lancement, LANa affiche l'identifiant (`admin`) et un mot de passe généré, aussi
enregistré dans `~/LANa/auth.json`. Les serveurs installés vivent dans `~/LANa/instances/`
(variable `LANA_HOME` pour déplacer ce dossier).

## Prérequis

- **Wine** pour les serveurs Windows (Enshrouded, et plus tard Palworld, V Rising, Sons of the Forest).
  Installation conseillée : MacPorts `sudo port install wine-stable` ou Homebrew `brew install --cask wine-stable`.
- **Java** pour Minecraft (à venir).

LANa compare chaque jeu à la machine (RAM, disque, outils) et prévient avant d'installer.

## Jeux

| Jeu | État |
|---|---|
| Enshrouded | disponible, installation et administration complètes |
| Minecraft | prochaine étape |
| Sons of the Forest, V Rising, Palworld | à venir (Windows via Wine ; Palworld demande beaucoup de RAM) |

## Sauvegardes

Pour tous les jeux, depuis la page d'un serveur :

- **Sauvegarde automatique** à chaque arrêt, ou à la demande ; les 10 dernières archives `.tar.gz` sont gardées.
- **Exporter** la sauvegarde actuelle, ou **télécharger** une archive existante.
- **Importer** une archive LANa, ou un fichier au format propre au jeu (déclaré dans `save_import`).
  Le serveur doit être arrêté. Le fichier est vérifié avant d'écraser quoi que ce soit, et la sauvegarde actuelle est archivée d'abord.
  Les archives sont refusées si elles contiennent des liens, des chemins hors du dossier de sauvegarde, ou dépassent 4 Go décompressées.

## Ajouter un jeu

Un jeu est un fichier `games/<id>.json`, sans code Python. Il décrit :

- `install` : comment l'installer (`steamcmd` avec `appid`, `platform`, `check_file`) ;
- `run` : le runtime (`wine`, `java` ou `native`), la commande et le dossier de lancement ;
- `requirements` : RAM minimale et recommandée, disque, note affichée à l'utilisateur ;
- `ports`, `connect`, `savegame` (dossier sauvegardé) ;
- `save_import` : formats de fichier propres au jeu acceptés à l'import (`extensions`, `magic` = premiers octets attendus, `target` = nom du fichier dans le dossier de sauvegarde) ;
- `config` : fichier, format, et config `initial` (le jeton `"{random}"` devient un mot de passe aléatoire) ;
- `fields` : les paramètres éditables. Types : `text`, `int`, `float`, `bool`, `enum`, `tags`,
  `minutes_ns` (minutes dans l'interface, nanosecondes dans le fichier) et `collection` (liste d'éléments).
  `key` est un chemin pointé dans le fichier de config.

`games/enshrouded.json` sert de modèle.

## Tests

```bash
python3 -m unittest discover -s tests
```

## Structure

```
run.py            lanceur
lana/             machine, games, config, runtime (Wine, SteamCMD, processus), instances, jobs, web
games/            une définition JSON par jeu
web/index.html    interface
tests/            tests unitaires (aucun ne lance Wine)
```
