# LANa

Installer et administrer des serveurs de jeu (28 jeux) depuis un panneau web, pensé pour de vieux Mac Intel, et fonctionnel sous macOS, Linux et Windows.
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

## Android (Termux)

LANa tourne aussi sur un téléphone ou une tablette Android, dans [Termux](https://termux.dev) (à installer depuis F-Droid ou GitHub ; la version du Play Store n'est plus à jour).
Sur un processeur ARM (téléphone, Raspberry Pi), LANa ne propose que les serveurs qui y tournent. Les autres, compilés pour les processeurs x86, sont masqués par défaut ; un bouton du catalogue les affiche, avec la raison.

| Serveur | Sur Android | Ce qu'il faut dans Termux |
|---|---|---|
| Minecraft (Java), avec Fabric ou Paper | Java de Termux | `pkg install openjdk-21` |
| Mindustry | Java de Termux | `pkg install openjdk-21` |
| Luanti (ex-Minetest) | paquet Termux | `pkg install x11-repo` puis `pkg install luanti` |
| Terraria (TShock) | binaire Linux ARM64, lancé dans un Debian | `pkg install proot-distro` ; LANa installe Debian (`proot-distro install debian`), `libicu` et le runtime .NET 9 au premier serveur |

```bash
pkg install python openjdk-21 git        # openjdk-21 : Minecraft 1.20.5 et plus récent ; « pkg search openjdk » pour les autres
git clone https://github.com/yannguyomard/LANa.git
sh LANa/lancer-termux.sh                 # panneau : http://localhost:8765 dans le navigateur du téléphone
sh LANa/lancer-termux.sh --lan           # ou aussi depuis les autres appareils du wifi
```

- `lancer-termux.sh` garde le téléphone éveillé tant que LANa tourne (`termux-wake-lock`).
- Dans les réglages Android, retirez Termux de l'optimisation de la batterie, sinon le serveur s'arrête quand l'écran s'éteint.
- Coupez tout VPN et l'option qui combine Wi-Fi et données mobiles (« double canal » sur Oppo) : sinon les joueurs du réseau local ne reçoivent pas les réponses du serveur. Ce point a été constaté lors d'un essai de Sons of the Forest sous Winlator.
- Java n'est pas téléchargé automatiquement sous Android : les JRE publiés pour Linux ne fonctionnent pas sur Android. Il vient de Termux (`pkg install openjdk-21`).
- Les programmes Linux ARM habituels (glibc) ne se lancent pas directement sous Android ; LANa les fait tourner dans le Debian de proot-distro, avec le dossier de LANa visible au même chemin.

État : **non testé sur un téléphone**. Sur Mac Intel, Mindustry et Terraria (TShock) ont été installés, lancés, arrêtés et relancés par LANa ; la détection d'Android, du processeur ARM et la commande proot-distro sont couvertes par les tests unitaires.

## Jeux

| Jeu | État |
|---|---|
| Enshrouded | disponible, installation et administration complètes |
| Minecraft (Java) | disponible : dernière version stable de Mojang, mémoire de Java réglable, import de mondes `.zip` |
| V Rising | disponible (Wine) : installation, démarrage, réglages lus par le jeu, testés sur Mac Intel de 8 Go (environ 1,9 Go de RAM) |
| Palworld | disponible (Wine), **installation et configuration vérifiées, démarrage non testé** : 8 Go de RAM est son minimum et cette machine héberge déjà un autre serveur |
| Sons of the Forest | disponible (Wine) : fonctionne sur Mac Intel avec 4 joueurs (constaté). Un plantage en cours de partie a été observé une fois, sur une machine qui faisait aussi tourner un autre serveur |
| Terraria (TShock) | disponible, aussi sur processeur ARM : installation, création du monde, arrêt avec sauvegarde (`exit`) et reprise vérifiés sur Mac Intel. La création d'un monde prend plusieurs minutes sur une petite machine. Runtime .NET 9 installé automatiquement |
| Mindustry | disponible, aussi sur processeur ARM : installation, création de la partie, sauvegarde à l'arrêt et reprise vérifiées sur Mac Intel |
| Luanti (ex-Minetest) | disponible, aussi sur processeur ARM ; le moteur s'installe avec le gestionnaire de paquets (Termux, apt, Homebrew), LANa télécharge le jeu Minetest Game. **Démarrage non testé** (moteur absent de la machine de test) |

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

## Versions

Quand un jeu publie plusieurs versions, on peut en choisir une : à l'installation (« Autre version… » sur la carte du jeu), ou plus tard depuis la page du serveur.

- **Minecraft (Java)** : toutes les versions stables depuis la 1.2.5, d'après la liste officielle de Mojang.
- **Jeux Steam** : les branches publiques de l'éditeur, par exemple les anciennes alphas de 7 Days to Die, `legacy41` de Project Zomboid ou les versions d'avant les grandes mises à jour de Valheim et V Rising. Les branches à mot de passe ne sont pas proposées. La liste vient d'[api.steamcmd.net](https://www.steamcmd.net), un miroir public des informations de SteamCMD ; le téléchargement, lui, passe toujours par SteamCMD. Revenir à « Dernière version » installe la branche `public`.
- **open.mp** : les versions publiées sur GitHub.

La section n'apparaît que pour ces jeux, et la liste dit s'il n'existe qu'une seule version (Sons of the Forest, Palworld, Enshrouded…).
Un changement de version se fait serveur arrêté. La sauvegarde est d'abord archivée (`…-avant-version.tar.gz`), parce qu'un monde ouvert dans une version récente ne se charge pas toujours dans une plus ancienne.
La version choisie reste celle du serveur : « Réessayer » ou une réinstallation reprennent la même.

## Liste blanche (Minecraft)

Section « Liste blanche » de la page d'un serveur Minecraft :

- une case pour l'activer (`white-list` et `enforce-whitelist` dans `server.properties`) : seuls les joueurs de la liste peuvent entrer ;
- ajouter un joueur par son pseudo, avec les joueurs déjà venus sur le serveur proposés (`usercache.json`), ou le retirer ;
- serveur en ligne : le pseudo est vérifié auprès de Mojang, qui donne son identifiant ; serveur hors ligne (`online-mode=false`) : l'identifiant est calculé à partir du pseudo, comme le fait Minecraft ;
- serveur en marche : LANa passe par la console (`whitelist add …`), le changement s'applique sans redémarrage. Cela vaut pour un serveur démarré par cette version de LANa ; sinon, au prochain démarrage.

Le serveur Minecraft s'arrête désormais par sa commande `stop` (sauvegarde du monde comprise), puis par un signal s'il ne répond pas.

## Mods

Section « Mods » de la page d'un serveur, pour les jeux qui le permettent :

| Jeu | Source automatique | Chargeur installé par LANa | Ajout manuel |
|---|---|---|---|
| Minecraft (Java) | Modrinth (mods ou plugins compatibles avec la version installée) | Fabric (mods) ou Paper (plugins), au choix | `.jar` dans `mods/` ou `plugins/` |
| Valheim, V Rising | Thunderstore | BepInEx | `.dll` ou `.zip` dans `BepInEx/plugins/` |
| Rust | uMod | Oxide | `.cs` dans `oxide/plugins/` |
| Project Zomboid, ARK, Unturned | Workshop Steam (lien d'un objet ou d'une collection) | — (le serveur télécharge les objets au démarrage) | PZ : `.zip` dans `Zomboid/mods/` |

- **Simple** : chercher, cliquer « Installer ». Le chargeur et les dépendances s'installent tout seuls. Un mod se désactive d'une case, sans être supprimé, et un mod encore nécessaire à un autre ne peut pas être retiré. « Rechercher les mises à jour » met tout à jour d'un coup.
- **Avancé** : choisir la version d'un mod Minecraft, déposer ses propres fichiers (un `.zip` est décompressé), voir les fichiers posés par chaque mod, modifier les fichiers de réglages des mods (une copie `.bak` est gardée), corriger les identifiants de mods d'un objet du Workshop (Project Zomboid).
- **Fichiers copiés à la main** dans le dossier des mods (Finder, autre serveur) : ils apparaissent dans la liste et s'activent ou se retirent comme les autres.
- **Workshop** : LANa écrit les numéros dans la configuration du jeu (`WorkshopItems` et `Mods` pour Project Zomboid, avec le préfixe `\` de la Build 42 ; `ActiveMods` et `-automanagedmods` pour ARK ; `WorkshopDownloadConfig.json` pour Unturned). Les valeurs que vous y avez mises vous-même sont conservées. Steam ne permet pas de chercher dans le Workshop sans clé : la page propose un lien vers le Workshop, et on y copie le lien de l'objet.
- **Changement de version** (Minecraft) : le moteur Fabric ou Paper suit la nouvelle version ; les mods d'une autre version sont signalés par la recherche de mises à jour. Après une mise à jour de Rust, Oxide est réinstallé.
- **Moteur Minecraft** : Fabric télécharge ses bibliothèques au premier démarrage. Le monde est conservé d'un moteur à l'autre.

État : installation vérifiée contre les vrais services (Fabric, Paper, Modrinth avec dépendances, BepInEx et mods Thunderstore, Oxide, Workshop).
Pas encore vérifié : le chargement effectif des mods en jeu, surtout BepInEx sous Wine (LANa force le `winhttp.dll` de BepInEx avec `WINEDLLOVERRIDES`), et le téléchargement des objets du Workshop par les serveurs. uMod limite fortement le nombre de téléchargements : en cas de refus, réessayez une minute plus tard ou déposez le `.cs` à la main.

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
- **Sons of the Forest** : compressez le dossier de partie (ex. `0000000001`, dans `Saves/DedicatedServer/Multiplayer/`
  d'un autre serveur) et importez le `.zip` ; LANa le range dans l'emplacement de partie réglé (`SaveSlot`), sans toucher aux autres.

## Ajouter un jeu

Un jeu est un fichier `games/<id>.json`, sans code Python. Il décrit :

- `install` : comment l'installer, et `check_file` (fichier témoin d'une installation réussie) :
  - `steamcmd` avec `appid` (connexion anonyme), et au besoin `beta` (branche par défaut, remplacée par celle choisie dans l'interface) ou `mod` (jeux GoldSrc) ;
  - `download` avec `source` : `url` (adresses par plateforme), `github` (dernière version d'un dépôt ; clés `windows`, `linux`, `linux-arm64`, `mac`), `github_tag` (archive du dernier tag) ou `bedrock` ; `archive: "file"` si le téléchargement est le serveur lui-même (ex. un `.jar`), `dest` pour l'extraire dans un sous-dossier ; options `strip`, `keep` (fichiers de l'utilisateur à ne pas écraser), `executable`, `extras`, `archive: "nsis"` (installeur Windows silencieux) ;
  - `upload` : l'utilisateur dépose l'archive des fichiers serveur (`help` explique où la trouver) ;
  - `mojang` pour Minecraft (Java) ;
  - `write_files` = fichiers à créer à côté de l'exécutable, `make_dirs` = dossiers à créer ;
- `eula` : contrat de licence à faire accepter explicitement par l'utilisateur (`url`, `label`, fichier à écrire). LANa n'accepte jamais un contrat à sa place ;
- `run` : le runtime (`wine`, `java`, `native`, ou `tool` avec `tool` = programme installé sur la machine, ex. `luanti`), la commande, le dossier de lancement, `env` (variables d'environnement, `{server_dir}` remplacé par le dossier du serveur) et `stop_signal` (`TERM` par défaut) ; `stop_command` = commandes écrites dans la console pour un arrêt propre (ex. `exit` pour Terraria), `console_start` = commandes de console passées au lancement (Mindustry) ;
- `arm` : le serveur tourne aussi sur processeur ARM (`native` = programme de la machine ; `glibc` = binaire Linux ARM64, lancé sous Android dans un Debian proot-distro, avec `debian_packages`) ; `dotnet` = version du runtime .NET à installer (ex. `"9.0"`) ; `tool_help` = comment installer l'outil, par système ;
- `requirements` : RAM minimale et recommandée, disque, note affichée à l'utilisateur ;
- `ports`, `connect`, `savegame` (dossier sauvegardé) ;
- `save_import` : formats de fichier propres au jeu acceptés à l'import (`extensions`, `magic` = premiers octets attendus, `target` = nom du fichier dans le dossier de sauvegarde) ;
- variantes Linux : toute clé `nom_linux` (au premier niveau, dans `install` ou dans `config`) remplace `nom` quand le serveur tourne nativement sous Linux ; `run.linux` / `run.windows` remplacent la commande de lancement ;
- `compat` : incompatibilité constatée en test (`level` `warn` ou `bad`, `note`). Avec `bad`, l'installation est refusée et la raison affichée ;
- `log_file` : journal du jeu s'il n'écrit pas sur la sortie standard ;
- `whitelist` : liste blanche gérée par LANa (`file`, réglage `toggle` et `enforce`, commandes `console` add/remove/on/off) ;
- `mods` : gestion des mods (`provider` = `modrinth`, `thunderstore` avec `community` et `loader`, `umod` avec `game`, ou `workshop` avec `appid` et `targets`) ; `dir` et `extensions` pour l'ajout manuel, `config_dirs` pour les réglages modifiables, `verified` et `note` affichés à l'utilisateur ;
- `world_zip` : accepte l'import de mondes `.zip` (`marker` = fichier qui prouve que c'est un monde, ex. `level.dat` ; `into`, facultatif = sous-dossier de la sauvegarde où l'extraire, qui peut citer la config, ex. `DedicatedServer/Multiplayer/{SaveSlot:010d}` pour Sons of the Forest) ;
- `config` : fichier, format (`json`, `properties`, `ini` à sections avec des clés `[Section]Clé`, `cfg` pour les `server.cfg` de type Source/Quake (`prefix`, `quote`), `xml_props`, `xml_elements`, `arma` pour `clé = valeur;`, `none` si tout passe par la ligne de commande, ou `ue_options` pour la ligne `OptionSettings=(…)` d'Unreal) ; seules les lignes des réglages connus et modifiés sont réécrites ; `enforce` = réglages imposés même dans une config existante ; `seed_from` (fichier par défaut du jeu à copier comme point de départ) et `initial` (valeurs imposées par LANa ; le jeton `"{random}"` devient un mot de passe aléatoire) ;
- `fields` : les paramètres éditables. Types : `text`, `int`, `float`, `bool`, `enum`, `tags`,
  `minutes_ns` (minutes dans l'interface, nanosecondes dans le fichier) et `collection` (liste d'éléments).
  `key` est un chemin pointé dans le fichier de config (nom entier de la propriété pour `.properties`).
  Une clé qui commence par `lana:` est un réglage de LANa (ex. `lana:memory_mb`), gardé hors du fichier du jeu et utilisable dans la commande de lancement (`{memory_mb}`).
  `"advanced": true` range le réglage dans le mode avancé de l'appli de bureau (ports, performances, sauvegardes,
  administration…) ; les autres sont montrés à tout le monde, donc à garder compréhensibles par un débutant.

`games/enshrouded.json` sert de modèle.

## Tests

```bash
python3 -m unittest discover -s tests
```

## Structure

```
run.py            lanceur (lancer.bat sous Windows, lancer-termux.sh sous Android)
lana/             machine, games, config, runtime (Wine, SteamCMD, processus), system (différences macOS/Linux/Windows), instances, jobs, mods, players, upnp, versions, web, whitelist
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
