# LANa

Installer et administrer des serveurs de jeu depuis un panneau web, pensé pour de vieux Mac Intel, et fonctionnel sous macOS, Linux et Windows.
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

- **Python 3.9 ou plus récent**. Lancement : `lancer.command` (double-clic sous macOS, `./lancer.command` sous Linux), `python3 run.py`, ou `lancer.bat` (Windows). Le panneau s'ouvre sur http://localhost:8765.
- **Wine** pour les serveurs Windows (Enshrouded, Palworld, V Rising, Sons of the Forest) sous macOS et Linux ;
  inutile sous Windows, où les serveurs se lancent tels quels.
  macOS : MacPorts `sudo port install wine-stable` ou Homebrew `brew install --cask wine-stable`.
  Linux : le paquet `wine` de la distribution (ex. `sudo apt install wine64`), de préférence une version récente.
- **Java** pour Minecraft : rien à installer. Si la machine n'a pas le Java exigé par la version de Minecraft, LANa télécharge un JRE portable (Eclipse Temurin, ~50 Mo) dans `~/LANa/tools/java`, sans toucher au système.

LANa compare chaque jeu à la machine (RAM, disque, outils) et prévient avant d'installer.

## Jeux

| Jeu | État |
|---|---|
| Enshrouded | disponible, installation et administration complètes |
| Minecraft (Java) | disponible : dernière version stable de Mojang, mémoire de Java réglable, import de mondes `.zip` |
| V Rising | disponible (Wine) : installation, démarrage, réglages lus par le jeu, testés sur Mac Intel de 8 Go (environ 1,9 Go de RAM) |
| Palworld | disponible (Wine), **installation et configuration vérifiées, démarrage non testé** : 8 Go de RAM est son minimum et cette machine héberge déjà un autre serveur |
| Sons of the Forest | **expérimental sur Mac Intel avec Wine 11** : le serveur démarre et fait ses sauvegardes automatiques (constaté lancé à la main), avec des erreurs de shaders sans conséquence apparente, mais il a **planté en cours de partie**. Le démarrage via LANa n'est pas encore validé |

### Limite connue : sauvegarde à l'arrêt des serveurs Windows

## Joueurs

La page d'un serveur affiche les joueurs passés par lui : statut (en ligne depuis combien de temps, ou vu pour la dernière fois),
première connexion, nombre de sessions, temps de jeu, puis des statistiques globales (joueurs différents, temps cumulé, session moyenne
et plus longue, pic de joueurs simultanés, derniers événements). Un clic sur un joueur détaille sa fiche.

LANa lit les connexions dans le journal du serveur (aucun mod ni RCON) et garde l'historique dans `players.json` de l'instance.
Le suivi tourne tant que LANa tourne ; si LANa est fermé pendant que le serveur joue, les connexions sont rattrapées au retour
depuis le journal (heures du jour seulement : au-delà de 24 h, les dates sont approximatives). Quand le serveur s'arrête, les sessions ouvertes sont fermées.

| Jeu | Suivi | Statistiques en plus |
|---|---|---|
| Enshrouded | oui, format **vérifié sur un vrai journal** | — |
| Minecraft | oui, format standard | morts, monstres tués, distance, blocs minés, sauts, progrès, temps de jeu du monde et records, y compris pour les joueurs passés avant LANa |
| Palworld | oui, **format d'un modèle tiers, non vérifié** (avertissement affiché) | — |
| V Rising, Sons of the Forest | **non** : format de journal inconnu, aucune source fiable | — |

## Systèmes

| Système | État |
|---|---|
| macOS Intel | testé de bout en bout |
| Linux | **non testé** : même chemin que macOS (Wine, SteamCMD, signaux POSIX) ; la détection de la machine et les téléchargements de Java sont couverts par des tests unitaires |
| Windows | **non testé** : serveurs lancés sans Wine, arrêt par Ctrl+Pause puis `taskkill`, détection de la mémoire par l'API Windows ; les points à vérifier en priorité sont l'arrêt des serveurs et l'import de sauvegardes (renommage de dossiers) |

Sons of the Forest n'est signalé comme expérimental que sous macOS : le plantage constaté vient de Wine sur Mac.

Sous Wine, ni SIGTERM ni SIGINT ne font sauvegarder V Rising à l'arrêt (mesuré : aucun fichier écrit ; SIGINT bloque même l'arrêt 30 s). LANa archive la sauvegarde **telle qu'elle est sur disque** avant chaque arrêt, mais la progression depuis la dernière sauvegarde automatique du jeu peut être perdue.
Gardez donc un intervalle de sauvegarde automatique court (réglable dans chaque jeu). Une vraie commande de sauvegarde (RCON ou API REST selon le jeu) est la prochaine amélioration. Minecraft, lui, sauvegarde en quittant.

## Sauvegardes

Pour tous les jeux, depuis la page d'un serveur :

- **Sauvegarde automatique** à chaque arrêt, ou à la demande ; les 10 dernières archives `.tar.gz` sont gardées.
- **Exporter** la sauvegarde actuelle, ou **télécharger** une archive existante.
- **Importer** une archive LANa, ou un fichier au format propre au jeu (déclaré dans `save_import`).
  Le serveur doit être arrêté. Le fichier est vérifié avant d'écraser quoi que ce soit, et la sauvegarde actuelle est archivée d'abord.
  Les archives sont refusées si elles contiennent des liens, des chemins hors du dossier de sauvegarde, ou dépassent 4 Go décompressées.

## Ajouter un jeu

Un jeu est un fichier `games/<id>.json`, sans code Python. Il décrit :

- `install` : comment l'installer (`steamcmd` avec `appid`, `platform`, `check_file` ; ou `mojang` pour Minecraft) ; `write_files` = fichiers à créer à côté de l'exécutable ;
- `eula` : contrat de licence à faire accepter explicitement par l'utilisateur (`url`, `label`, fichier à écrire). LANa n'accepte jamais un contrat à sa place ;
- `run` : le runtime (`wine`, `java` ou `native`), la commande, le dossier de lancement, `env` (variables d'environnement) et `stop_signal` (`TERM` par défaut) ;
- `requirements` : RAM minimale et recommandée, disque, note affichée à l'utilisateur ;
- `ports`, `connect`, `savegame` (dossier sauvegardé) ;
- `save_import` : formats de fichier propres au jeu acceptés à l'import (`extensions`, `magic` = premiers octets attendus, `target` = nom du fichier dans le dossier de sauvegarde) ;
- `compat` : incompatibilité constatée en test (`level` `warn` ou `bad`, `note`). Avec `bad`, l'installation est refusée et la raison affichée ;
- `log_file` : journal du jeu s'il n'écrit pas sur la sortie standard ;
- `world_zip` : accepte l'import de mondes `.zip` (`marker` = fichier qui prouve que c'est un monde, ex. `level.dat`) ;
- `config` : fichier, format (`json`, `properties` ou `ue_options` pour la ligne `OptionSettings=(…)` d'Unreal), `seed_from` (fichier par défaut du jeu à copier comme point de départ) et `initial` (valeurs imposées par LANa ; le jeton `"{random}"` devient un mot de passe aléatoire) ;
- `fields` : les paramètres éditables. Types : `text`, `int`, `float`, `bool`, `enum`, `tags`,
  `minutes_ns` (minutes dans l'interface, nanosecondes dans le fichier) et `collection` (liste d'éléments).
  `key` est un chemin pointé dans le fichier de config (nom entier de la propriété pour `.properties`).
  Une clé qui commence par `lana:` est un réglage de LANa (ex. `lana:memory_mb`), gardé hors du fichier du jeu et utilisable dans la commande de lancement (`{memory_mb}`).

`games/enshrouded.json` sert de modèle.

## Tests

```bash
python3 -m unittest discover -s tests
```

## Structure

```
run.py            lanceur (lancer.bat sous Windows)
lana/             machine, games, config, runtime (Wine, SteamCMD, processus), system (différences macOS/Linux/Windows), instances, jobs, web
games/            une définition JSON par jeu
web/index.html    interface
tests/            tests unitaires (aucun ne lance Wine)
```

## Licence

LANa est distribuée sous licence MIT (voir `LICENSE`). Elle ne couvre que le code de LANa : SteamCMD, Java (Eclipse Temurin)
et les serveurs de jeu sont téléchargés chez l'utilisateur depuis leurs sources officielles et restent soumis à leurs propres conditions.

LANa n'est affiliée à aucun éditeur des jeux cités (Keen Games, Pocketpair, Stunlock Studios, Endnight Games, Mojang/Microsoft) ni à Valve.
Les noms des jeux sont des marques de leurs propriétaires.
