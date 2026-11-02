# LANa

Installer et administrer des serveurs de jeu (25 jeux) depuis un panneau web, pensé pour de vieux Mac Intel, et fonctionnel sous macOS, Linux et Windows.
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
| Sons of the Forest | disponible (Wine) : fonctionne sur Mac Intel avec 4 joueurs (constaté). Un plantage en cours de partie a été observé une fois, sur une machine qui faisait aussi tourner un autre serveur |

### Jeux ajoutés, à tester

Les jeux suivants sont décrits d'après la documentation officielle et les données de Steam (identifiants et
exécutables vérifiés à la source), **sans avoir encore été essayés en conditions réelles** : l'interface les marque
« à tester ». Sous macOS et Linux, les serveurs Windows tournent sous Wine (étiquette « Wine »), sans garantie.

| Jeu | Installation | Réglages | Particularité |
|---|---|---|---|
| Counter-Strike 2 | SteamCMD (730) | `server.cfg` | ~60 Go ; jeton GSLT pour être visible sur Internet |
| Counter-Strike 1.6 | SteamCMD (90, mod cstrike) | `server.cfg` | |
| Counter-Strike: Source | SteamCMD (232330) | `server.cfg` | |
| Team Fortress 2 | SteamCMD (232250) | `server.cfg` | |
| Left 4 Dead 2 | SteamCMD (222860) | `server.cfg` | |
| Garry's Mod | SteamCMD (4020) | `server.cfg` | mode de jeu et collection Workshop au lancement |
| ARK: Survival Evolved | SteamCMD (376030) | `GameUserSettings.ini` | carte, ports et joueurs au lancement |
| ARK: Survival Ascended | SteamCMD (2430930) | `GameUserSettings.ini` | Windows seulement, 12 Go de RAM minimum |
| Rust | SteamCMD (258550) | `server.cfg` + lancement | carte, graine, taille et RCON au lancement |
| Project Zomboid | SteamCMD (380870) | `Zomboid/Server/lana.ini` | **démarrage vérifié sur Mac Intel (Wine)** ; mot de passe administrateur obligatoire ; mémoire de Java réglable (3 Go par défaut, le script officiel en réserve 16) |
| Valheim | SteamCMD (896660) | lancement | mot de passe d'au moins 5 caractères |
| Unturned | SteamCMD (1110390) | `Commands.dat` | jeton GSLT pour un serveur Internet |
| 7 Days to Die | SteamCMD (294420) | `serverconfig.xml` | |
| Dark and Light | SteamCMD (630230) | `GameUserSettings.ini` | Windows seulement ; nom de session sans espace |
| Quake Live | SteamCMD (349090) | `server.cfg` | |
| VEIN | SteamCMD (2131400) | `Game.ini` | |
| Minecraft (Bedrock) | téléchargement Mojang | `server.properties` | contrat de licence à accepter |
| GTA SA multijoueur (SA-MP) | open.mp (GitHub) | `config.json` | serveur moderne compatible SA-MP 0.3.7 |
| Multi Theft Auto: San Andreas | Linux : archive officielle ; Windows et macOS : installeur MTA silencieux | `mtaserver.conf` | |
| RAGE Multiplayer | **archive fournie par l'utilisateur** | `conf.json` | le site de RAGE MP refuse les téléchargements automatisés |

Non disponibles : **Hell Let Loose** (pas de serveur public : réservé à des hébergeurs sous licence), **Atlas**
(serveur en grille qui exige une base Redis et un éditeur de grille), et les serveurs qui demandent une authentification,
retirés volontairement : **DayZ** et **Arma 3** (compte Steam possédant le jeu), **FiveM** et **RedM** (compte Cfx.re et
clé de licence), **The Isle** (identifiants Epic Online Services).

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

## Ports et UPnP

Quand un serveur démarre, LANa demande à la box d'ouvrir ses ports (UPnP) et la page du serveur affiche l'adresse à donner aux joueurs extérieurs. Quand le serveur s'arrête, les ports sont refermés.
C'est actif par défaut pour tous les serveurs, avec une case « UPnP » par serveur pour le désactiver.

- **Bail d'une heure** : chaque redirection est renouvelée toutes les 10 minutes. Un serveur arrêté hors de LANa ne laisse donc pas de ports ouverts indéfiniment.
- **Box sans UPnP** : si la box ne répond pas, ou si l'UPnP y est désactivé, la page le dit et donne la liste des ports à ouvrir à la main.
- **Adresse non publique** : si l'adresse de la box n'est pas une adresse Internet, la page prévient que les joueurs extérieurs ne pourront pas se connecter. Cela arrive avec un double routeur ou un fournisseur qui partage les adresses (CGNAT).
- **Port déjà pris** : si un port est déjà redirigé vers une autre machine, LANa ne l'écrase pas et le signale.
- **Panneau d'administration** : le port de LANa lui-même n'est jamais ouvert sur Internet.

Vérifié sur une box MiniUPnPd (IGD 2) : ouverture au démarrage, fermeture par la case, adresse Internet relevée.

## Systèmes

| Système | État |
|---|---|
| macOS Intel | testé de bout en bout |
| Linux | **non testé** : même chemin que macOS (Wine, SteamCMD, signaux POSIX) ; la détection de la machine et les téléchargements de Java sont couverts par des tests unitaires |
| Windows | **non testé** : serveurs lancés sans Wine, arrêt par Ctrl+Pause puis `taskkill`, détection de la mémoire par l'API Windows ; les points à vérifier en priorité sont l'arrêt des serveurs et l'import de sauvegardes (renommage de dossiers) |


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

- `install` : comment l'installer, et `check_file` (fichier témoin d'une installation réussie) :
  - `steamcmd` avec `appid` (connexion anonyme), et au besoin `beta` (branche) ou `mod` (jeux GoldSrc) ;
  - `download` avec `source` : `url` (adresses par plateforme), `github` (dernière version d'un dépôt) ou `bedrock` ; options `strip`, `keep` (fichiers de l'utilisateur à ne pas écraser), `executable`, `extras`, `archive: "nsis"` (installeur Windows silencieux) ;
  - `upload` : l'utilisateur dépose l'archive des fichiers serveur (`help` explique où la trouver) ;
  - `mojang` pour Minecraft (Java) ;
  - `write_files` = fichiers à créer à côté de l'exécutable, `make_dirs` = dossiers à créer ;
- `eula` : contrat de licence à faire accepter explicitement par l'utilisateur (`url`, `label`, fichier à écrire). LANa n'accepte jamais un contrat à sa place ;
- `run` : le runtime (`wine`, `java` ou `native`), la commande, le dossier de lancement, `env` (variables d'environnement) et `stop_signal` (`TERM` par défaut) ;
- `requirements` : RAM minimale et recommandée, disque, note affichée à l'utilisateur ;
- `ports`, `connect`, `savegame` (dossier sauvegardé) ;
- `save_import` : formats de fichier propres au jeu acceptés à l'import (`extensions`, `magic` = premiers octets attendus, `target` = nom du fichier dans le dossier de sauvegarde) ;
- variantes Linux : toute clé `nom_linux` (au premier niveau, dans `install` ou dans `config`) remplace `nom` quand le serveur tourne nativement sous Linux ; `run.linux` / `run.windows` remplacent la commande de lancement ;
- `compat` : incompatibilité constatée en test (`level` `warn` ou `bad`, `note`). Avec `bad`, l'installation est refusée et la raison affichée ;
- `log_file` : journal du jeu s'il n'écrit pas sur la sortie standard ;
- `world_zip` : accepte l'import de mondes `.zip` (`marker` = fichier qui prouve que c'est un monde, ex. `level.dat`) ;
- `config` : fichier, format (`json`, `properties`, `ini` à sections avec des clés `[Section]Clé`, `cfg` pour les `server.cfg` de type Source/Quake (`prefix`, `quote`), `xml_props`, `xml_elements`, `arma` pour `clé = valeur;`, `none` si tout passe par la ligne de commande, ou `ue_options` pour la ligne `OptionSettings=(…)` d'Unreal) ; seules les lignes des réglages connus et modifiés sont réécrites ; `enforce` = réglages imposés même dans une config existante ; `seed_from` (fichier par défaut du jeu à copier comme point de départ) et `initial` (valeurs imposées par LANa ; le jeton `"{random}"` devient un mot de passe aléatoire) ;
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
lana/             machine, games, config, runtime (Wine, SteamCMD, processus), system (différences macOS/Linux/Windows), instances, jobs, players, upnp, web
games/            une définition JSON par jeu
web/index.html    interface
tests/            tests unitaires (aucun ne lance Wine)
```

## Licence

LANa est distribuée sous licence MIT (voir `LICENSE`). Elle ne couvre que le code de LANa : SteamCMD, Java (Eclipse Temurin)
et les serveurs de jeu sont téléchargés chez l'utilisateur depuis leurs sources officielles et restent soumis à leurs propres conditions.

Les polices de l'interface (Space Grotesk, Inter, JetBrains Mono, dans `web/static/fonts/`) sont sous licence
SIL Open Font License 1.1 ; leur licence est jointe à côté de chaque fichier. Elles sont servies par LANa elle-même :
l'interface ne charge rien depuis Internet.

LANa n'est affiliée à aucun éditeur des jeux cités (Keen Games, Pocketpair, Stunlock Studios, Endnight Games, Mojang/Microsoft) ni à Valve.
Les noms des jeux sont des marques de leurs propriétaires.
