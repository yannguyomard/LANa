"""Serveurs installés : un dossier par instance dans ~/LANa/instances/<id>/."""
import glob
import json
import os
import re
import shutil
import tarfile
import threading
import time
import zipfile

from . import config, games, jobs, machine, mods, paths, runtime, system, upnp, versions

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
KEEP_BACKUPS = 10
LANA_PREFIX = "lana:"
MAX_IMPORT_BYTES = 4 * 2**30   # taille maximale d'une sauvegarde importée, une fois décompressée
_procs = {}      # id -> Popen, pour récupérer les processus enfants terminés
_locks = {}      # id -> Lock, une opération de cycle de vie à la fois par serveur


class InstanceError(Exception):
    """Erreur destinée à être affichée telle quelle à l'utilisateur."""


def _lock(instance_id):
    return _locks.setdefault(instance_id, threading.Lock())


class Instance:
    def __init__(self, instance_id):
        if not ID_RE.match(instance_id):
            raise InstanceError("Identifiant de serveur invalide")
        self.id = instance_id
        self.dir = os.path.join(paths.INSTANCES_DIR, instance_id)
        self.server_dir = os.path.join(self.dir, "server")
        self.prefix = os.path.join(self.dir, "prefix")
        self.backup_dir = os.path.join(self.dir, "backups")
        self.log_path = os.path.join(self.dir, "logs", "server.log")
        self.meta_path = os.path.join(self.dir, "instance.json")
        self.state_path = os.path.join(self.dir, "state.json")

    # ---------- méta ----------

    def exists(self):
        return os.path.exists(self.meta_path)

    def meta(self):
        if not self.exists():
            raise InstanceError("Serveur introuvable")
        with open(self.meta_path, encoding="utf-8") as fh:
            return json.load(fh)

    def _save_meta(self, meta):
        with open(self.meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh)

    @property
    def game(self):
        return games.get(self.meta()["game"])

    # ---------- état du processus ----------

    def _pgid(self):
        try:
            with open(self.state_path) as fh:
                return json.load(fh).get("pgid")
        except (OSError, ValueError):
            return None

    def _set_pgid(self, pgid):
        with open(self.state_path, "w") as fh:
            json.dump({"pgid": pgid, "started": time.time()}, fh)

    def running(self):
        proc = _procs.get(self.id)
        if proc is not None:
            proc.poll()  # récupère le processus s'il s'est terminé
        pgid = self._pgid()
        return bool(pgid) and runtime.group_alive(pgid)

    def status(self):
        meta = self.meta()
        out = {"id": self.id, "game": meta["game"], "name": meta.get("name", self.id),
               "installed": meta.get("installed", False), "running": False}
        if out["installed"]:
            out["running"] = self.running()
        return out

    # ---------- création et installation ----------

    @classmethod
    def create(cls, game_id, name=None):
        game = games.get(game_id)
        base, n = game_id.replace("_", "-"), 1   # identifiant de serveur : lettres, chiffres et tirets
        instance_id = base
        while os.path.exists(os.path.join(paths.INSTANCES_DIR, instance_id)):
            n += 1
            instance_id = "%s-%d" % (base, n)
        inst = cls(instance_id)
        os.makedirs(inst.dir)
        with open(inst.meta_path, "w", encoding="utf-8") as fh:
            json.dump({"game": game_id, "name": name or game["name"], "installed": False,
                       "created": time.time()}, fh)
        return inst

    def _check_installable(self, accept_eula):
        game = self.game
        eula = game.get("eula")
        if eula and not accept_eula:
            raise InstanceError("Vous devez accepter le contrat de licence : %s" % eula["url"])
        verdict = machine.verdict(game["requirements"], [], machine.detect(), games.cpu_compat(game) or game.get("compat"))
        if verdict["level"] == "bad":
            raise InstanceError(" ".join(verdict["messages"]))
        # Java est téléchargé automatiquement si absent ; les autres outils doivent déjà être là.
        missing = [t for t in games.needs(game) if t != "java" and not machine.find_tool(t)]
        if missing:
            how = game.get("tool_help", {})
            hint = how.get("android" if system.IS_ANDROID else "mac" if system.IS_MAC else "windows" if system.IS_WINDOWS else "linux", "")
            raise InstanceError("Outil manquant : %s. %s" % (", ".join(missing), hint or "Installez-le puis réessayez."))

    def install(self, accept_eula=False, version=None):
        """Lance l'installation en arrière-plan ; retourne la tâche.

        Si le jeu impose un contrat de licence (`eula`), l'utilisateur doit l'avoir accepté explicitement :
        LANa n'accepte jamais un contrat à sa place. Les jeux à fichiers fournis par l'utilisateur
        (`install.type == "upload"`) s'installent avec `install_upload`.
        `version` : version choisie (voir versions.py) ; sinon celle déjà retenue pour ce serveur, ou la dernière.
        """
        game = self.game
        self._check_installable(accept_eula)
        spec = game["install"]
        if spec["type"] == "upload":
            raise InstanceError("Ce jeu s'installe en déposant l'archive de ses fichiers serveur : %s" % spec.get("help", ""))
        if version:
            try:
                version = versions.check(game, version)
            except versions.VersionError as ex:
                raise InstanceError(str(ex))
            # Retenue dès maintenant : « Réessayer » et les mises à jour reprennent la même version.
            self._save_meta(dict(self.meta(), version=version))
        else:
            version = self.meta().get("version")

        def work(job):
            if system.uses_wine(games.run_spec(game)["runtime"]):
                runtime.init_prefix(self.prefix, job)
            if games.uses_proot(game):
                runtime.ensure_debian(job, game.get("debian_packages", []))
            if game.get("dotnet"):
                runtime.ensure_dotnet(game["dotnet"], job)
            extra = {}
            if spec["type"] == "steamcmd":
                runtime.steamcmd_install(game, self.server_dir, self.prefix, job, branch=version)
            elif spec["type"] == "mojang":
                extra = runtime.mojang_install(game, self.server_dir, job, version=version)
                job.log("Serveur Minecraft %s installé." % extra["version"])
            elif spec["type"] == "download":
                extra = runtime.download_install(game, self.server_dir, self.prefix, job, version=version)
                if games.run_spec(game)["runtime"] == "java":   # serveur Java hors Mojang (ex. Mindustry)
                    runtime.ensure_java(spec.get("java_min", 17), job)
                    extra["java_min"] = spec.get("java_min", 17)
            else:
                raise RuntimeError("Type d'installation non géré : %s" % spec["type"])
            self._finish_install(job.log, extra, accept_eula)
            mods.after_install(self, job)

        return jobs.start("Installation de %s" % game["name"], work)

    def change_version(self, version, accept_eula=False):
        """Installe une autre version sur un serveur arrêté, après avoir archivé sa sauvegarde ; retourne la tâche."""
        with _lock(self.id):
            if self.running():
                raise InstanceError("Arrêtez le serveur avant de changer de version")
            if os.path.exists(self._save_path()):
                self._backup_unlocked("avant-version")
        return self.install(accept_eula=accept_eula, version=version)

    def _finish_install(self, log, extra, accept_eula):
        """Après la copie des fichiers du jeu : configuration initiale, fichiers attendus, contrat, état."""
        game, spec = self.game, self.game["install"]
        cfg = game["config"]
        if cfg["format"] != "none" and not os.path.exists(os.path.join(self.server_dir, cfg["file"])):
            config.write_initial(game, self.server_dir)
            log("Configuration initiale créée.")
        if cfg.get("enforce"):   # réglages indispensables à LANa, même dans une config fournie (ex. écouter le réseau)
            data = config.read_file(game, self.server_dir)
            if any(data.get(k) != v for k, v in cfg["enforce"].items()):
                data.update(cfg["enforce"])
                config.write_file(game, self.server_dir, data)
                log("Réglages réseau ajustés : %s." % ", ".join("%s=%s" % kv for kv in cfg["enforce"].items()))
        for name, content in spec.get("write_files", {}).items():   # fichiers que le jeu attend à côté de l'exécutable
            path = os.path.join(self.server_dir, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
        for folder in spec.get("make_dirs", []):
            os.makedirs(os.path.join(self.server_dir, folder), exist_ok=True)
        eula = game.get("eula")
        if eula and accept_eula:
            with open(os.path.join(self.server_dir, eula["file"]), "w", encoding="utf-8") as fh:
                fh.write(eula["content"])
            log("Contrat de licence accepté par l'utilisateur (%s)." % eula["url"])
        meta = self.meta()
        meta.update(extra)
        meta["installed"] = True
        self._save_meta(meta)
        log("Installation terminée.")

    def install_upload(self, tmp_path, filename, accept_eula=False):
        """Installe un serveur à partir de l'archive de ses fichiers, fournie par l'utilisateur (zip ou tar)."""
        game, spec = self.game, self.game["install"]
        if spec["type"] != "upload":
            raise InstanceError("Ce jeu s'installe automatiquement")
        self._check_installable(accept_eula)
        if not (zipfile.is_zipfile(tmp_path) or tarfile.is_tarfile(tmp_path)):
            raise InstanceError("Format non reconnu : déposez une archive .zip ou .tar.gz des fichiers serveur")
        staging = os.path.join(self.dir, "upload")
        shutil.rmtree(staging, ignore_errors=True)
        os.makedirs(staging)
        try:
            try:
                runtime._safe_extract(tmp_path, staging)
            except (RuntimeError, tarfile.TarError, zipfile.BadZipFile) as ex:
                raise InstanceError("Archive refusée : %s" % ex)
            # Les fichiers peuvent être à la racine de l'archive ou dans un dossier : on cherche le fichier témoin.
            found = None
            for root, _dirs, files in os.walk(staging):
                if os.path.basename(spec["check_file"]) in files and os.path.exists(os.path.join(root, os.path.basename(spec["check_file"]))):
                    base = root[:len(root) - len(os.path.dirname(spec["check_file"]))] if os.path.dirname(spec["check_file"]) else root
                    if os.path.exists(os.path.join(base, spec["check_file"])):
                        found = base
                        break
            if not found:
                raise InstanceError("L'archive « %s » ne contient pas %s" % (filename, spec["check_file"]))
            os.makedirs(self.server_dir, exist_ok=True)
            runtime._merge_tree(found, self.server_dir, set(spec.get("keep", [])))
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        for rel in spec.get("executable", []):
            path = os.path.join(self.server_dir, rel)
            if os.path.exists(path):
                os.chmod(path, os.stat(path).st_mode | 0o755)
        self._finish_install(lambda _line: None, {"source": filename}, accept_eula)
        return "Fichiers serveur installés"

    # ---------- démarrage et arrêt ----------

    def start(self):
        with _lock(self.id):
            if not self.meta().get("installed"):
                raise InstanceError("Ce serveur n'est pas encore installé")
            if self.running():
                raise InstanceError("Le serveur tourne déjà")
            settings = self._run_settings()
            ram = machine.detect()["ram_gb"]
            if ram and settings.get("memory_mb", 0) / 1024 > ram - 1.5:
                raise InstanceError("Trop de mémoire allouée à Java (%s Mo) pour %s Go de RAM : laissez au moins 1,5 Go au système."
                                    % (settings["memory_mb"], ram))
            try:
                _procs[self.id] = runtime.start_process(self.game, self.server_dir, self.prefix, self.log_path,
                                                        settings=settings, java_min=self.meta().get("java_min", 0),
                                                        overrides=mods.launch_overrides(self))
            except RuntimeError as ex:
                raise InstanceError(str(ex))
            self._set_pgid(_procs[self.id].pid)
        upnp.poke()

    def stop(self, backup=True):
        with _lock(self.id):
            if not self.running():
                raise InstanceError("Le serveur est déjà arrêté")
            run = games.run_spec(self.game)
            # Serveur qui sauvegarde sur commande (Terraria, Mindustry) : on la lui envoie, puis on archive le monde à jour.
            if run.get("stop_command") and runtime.send_console(self.log_path, run["stop_command"]):
                for _ in range(run.get("stop_wait", 60)):
                    if not self.running():
                        break
                    time.sleep(1)
            if backup and os.path.isdir(os.path.join(self.server_dir, self.game["savegame"])):
                self._backup_unlocked("avant-arret")
            if self.running() and not runtime.stop_group(self._pgid(), system.uses_wine(run["runtime"]), self.prefix,
                                      sig=runtime.stop_signal(run.get("stop_signal", "TERM"))):
                raise InstanceError("Le serveur ne s'est pas arrêté")
        upnp.poke()

    # ---------- ports ----------

    def ports(self):
        """Ports du serveur d'après sa config : [{"label", "proto", "port"}]."""
        values = self.read_config()
        return [{"label": p["label"], "proto": p["proto"], "port": int(values[p["from"]]) + p["offset"]}
                for p in self.game.get("ports", [])]

    def upnp_enabled(self):
        return self.meta().get("upnp", True)

    def set_upnp(self, enabled):
        self._save_meta(dict(self.meta(), upnp=bool(enabled)))
        upnp.poke()

    # ---------- config ----------

    # Les champs dont la clé commence par "lana:" sont des réglages de LANa (ex. mémoire de Java),
    # gardés dans instance.json et non dans le fichier de config du jeu.

    def _run_settings(self):
        defaults = {f["key"][len(LANA_PREFIX):]: f["default"] for f in self.game["fields"] if f["key"].startswith(LANA_PREFIX)}
        defaults.update(self.meta().get("settings", {}))
        return defaults

    def read_config(self):
        game = self.game
        data = config.read_file(game, self.server_dir)
        for key, value in self._run_settings().items():
            data[LANA_PREFIX + key] = value
        return config.to_ui(game, data)

    def write_config(self, values):
        game = self.game
        updated = config.apply_ui(game, config.read_file(game, self.server_dir), values)
        settings = {k[len(LANA_PREFIX):]: updated.pop(k) for k in [k for k in updated if k.startswith(LANA_PREFIX)]}
        config.write_file(game, self.server_dir, updated)
        meta = self.meta()
        meta["settings"] = settings
        self._save_meta(meta)

    # ---------- journal ----------

    def log_tail(self, lines=120):
        # Certains jeux écrivent leur journal dans un fichier plutôt que sur la sortie standard.
        own = self.game.get("log_file")
        path = os.path.join(self.server_dir, own) if own else None
        if not (path and os.path.exists(path)):
            path = self.log_path
        if not os.path.exists(path):
            return ""
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 60000))
            text = fh.read().decode("utf-8", "replace")
        text = ANSI.sub("", text)   # codes de couleur des consoles (Mindustry…)
        kept = [l for l in text.splitlines() if "[mvk-info]" not in l]
        return "\n".join(kept[-lines:])

    # ---------- sauvegardes ----------

    def _save_path(self):
        return os.path.join(self.server_dir, self.game["savegame"])

    def _backup_unlocked(self, label, prune=True):
        src = self._save_path()
        if not os.path.exists(src):
            raise InstanceError("Aucune sauvegarde à copier pour l'instant")
        os.makedirs(self.backup_dir, exist_ok=True)
        label = re.sub(r"[^a-z0-9-]", "", str(label).lower())[:20] or "manuelle"  # le libellé finit dans un nom de fichier
        name = "%s-%s.tar.gz" % (time.strftime("%Y%m%d-%H%M%S"), label)
        with tarfile.open(os.path.join(self.backup_dir, name), "w:gz") as tar:
            tar.add(src, arcname=os.path.basename(src))
        if prune:
            self._prune_backups()
        return name

    def _prune_backups(self):
        for old in sorted(glob.glob(os.path.join(self.backup_dir, "*.tar.gz")))[:-KEEP_BACKUPS]:
            os.remove(old)

    def backup(self, label="manuelle"):
        with _lock(self.id):
            return self._backup_unlocked(label)

    def backups(self):
        out = []
        for path in sorted(glob.glob(os.path.join(self.backup_dir, "*.tar.gz")), reverse=True):
            out.append({"name": os.path.basename(path), "size_mb": round(os.path.getsize(path) / 2**20, 1), "path": path})
        return out

    def backup_path(self, name):
        """Chemin d'une archive de ce serveur (le nom ne peut pas sortir du dossier des sauvegardes)."""
        path = os.path.join(self.backup_dir, os.path.basename(name))
        if not name.endswith(".tar.gz") or not os.path.isfile(path):
            raise InstanceError("Sauvegarde introuvable")
        return path

    def import_formats(self):
        """Formats de fichier acceptés à l'import : celui du jeu (s'il en a un) et l'archive LANa."""
        formats = [{"label": f["label"], "extensions": f["extensions"]} for f in self.game.get("save_import", [])]
        if self.game.get("world_zip"):
            formats.append({"label": self.game["world_zip"]["label"], "extensions": [".zip"]})
        formats.append({"label": "Archive LANa", "extensions": [".tar.gz"]})
        return formats

    def _replace_save(self, install):
        """Archive la sauvegarde actuelle, puis exécute install(). Le serveur doit être arrêté."""
        if self.running():
            raise InstanceError("Arrêtez le serveur avant de modifier sa sauvegarde")
        if os.path.exists(self._save_path()):
            # Pas d'élagage avant la fin : l'archive qu'on restaure pourrait être la plus ancienne.
            self._backup_unlocked("avant-import", prune=False)
        install()
        self._prune_backups()

    def restore(self, name):
        with _lock(self.id):
            path = self.backup_path(name)
            self._check_archive(path)
            self._replace_save(lambda: self._extract_archive(path))

    # ---------- import ----------

    def _check_archive(self, path):
        """Valide une archive avant d'y toucher : une seule racine attendue, fichiers et dossiers
        réguliers uniquement (ni liens ni fichiers spéciaux), aucun chemin hors du dossier, taille bornée."""
        root = os.path.basename(self.game["savegame"])
        total = 0
        try:
            with tarfile.open(path) as tar:
                members = tar.getmembers()
        except (tarfile.TarError, OSError, EOFError):
            raise InstanceError("Archive illisible ou corrompue")
        if not members:
            raise InstanceError("Archive vide")
        for m in members:
            parts = m.name.split("/")
            if m.name.startswith("/") or ".." in parts or parts[0] != root:
                raise InstanceError("Archive invalide : « %s » n'est pas dans « %s »" % (m.name, root))
            if not (m.isreg() or m.isdir()):
                raise InstanceError("Archive invalide : « %s » n'est pas un fichier ordinaire" % m.name)
            total += m.size
        if total > MAX_IMPORT_BYTES:
            raise InstanceError("Archive trop volumineuse une fois décompressée")

    @staticmethod
    def _zip_entries(zf):
        """Entrées utiles d'un zip, sans les fichiers parasites que macOS ajoute."""
        return [i for i in zf.infolist() if not i.filename.startswith("__MACOSX/") and not i.filename.endswith(".DS_Store")]

    def _check_zip(self, path, marker):
        """Valide un monde en .zip et retourne le préfixe à retirer (le dossier qui contient `marker`).

        Même exigences que pour les archives LANa : aucun lien, aucun chemin hors du dossier, taille bornée.
        """
        try:
            zf = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError):
            raise InstanceError("Fichier .zip illisible ou corrompu")
        with zf:
            entries = self._zip_entries(zf)
            names = [i.filename for i in entries]
            tops = [n[:-len(marker)] for n in names if n == marker or (n.endswith("/" + marker) and n.count("/") == 1)]
            if not tops:
                raise InstanceError("Ce .zip ne ressemble pas à un monde : « %s » est introuvable à sa racine" % marker)
            top = tops[0]
            total = 0
            for info in entries:
                parts = info.filename.split("/")
                if info.filename.startswith("/") or ".." in parts:
                    raise InstanceError("Archive invalide : « %s »" % info.filename)
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise InstanceError("Archive invalide : « %s » est un lien" % info.filename)
                if not info.filename.startswith(top):
                    raise InstanceError("Archive invalide : « %s » est hors du monde" % info.filename)
                total += info.file_size
            if total > MAX_IMPORT_BYTES:
                raise InstanceError("Archive trop volumineuse une fois décompressée")
        return top

    def _zip_dest(self):
        """Dossier où extraire un monde .zip : la sauvegarde, ou le sous-dossier `into` (qui peut citer la config,
        ex. « DedicatedServer/Multiplayer/{SaveSlot:010d} »)."""
        into = self.game["world_zip"].get("into")
        if not into:
            return self._save_path()
        values = {k: v for k, v in self.read_config().items() if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k)}
        rel = into.format(**values)
        parts = rel.replace("\\", "/").split("/")
        if rel.startswith("/") or ".." in parts or "" in parts:
            raise InstanceError("Dossier d'import invalide : %s" % rel)
        return os.path.join(self._save_path(), *parts)

    def _extract_zip(self, path, top):
        dest = self._zip_dest()
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        elif os.path.exists(dest):
            os.remove(dest)
        os.makedirs(dest)
        base = os.path.realpath(dest)
        with zipfile.ZipFile(path) as zf:
            for info in self._zip_entries(zf):
                rel = info.filename[len(top):]
                if not rel:
                    continue
                target = os.path.realpath(os.path.join(base, rel))
                if target != base and not target.startswith(base + os.sep):
                    raise InstanceError("Archive invalide : « %s »" % info.filename)
                if info.is_dir():
                    os.makedirs(target, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)

    def _extract_archive(self, path):
        dest = self._save_path()
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        elif os.path.exists(dest):
            os.remove(dest)
        with tarfile.open(path) as tar:
            tar.extractall(os.path.dirname(dest))

    def import_save(self, tmp_path, filename):
        """Importe un fichier envoyé par l'utilisateur : archive LANa ou format propre au jeu."""
        with _lock(self.id):
            name = filename.lower()
            if name.endswith((".tar.gz", ".tgz")):
                self._check_archive(tmp_path)
                self._replace_save(lambda: self._extract_archive(tmp_path))
                return "Archive importée"
            if name.endswith(".zip") and self.game.get("world_zip"):
                top = self._check_zip(tmp_path, self.game["world_zip"]["marker"])
                self._replace_save(lambda: self._extract_zip(tmp_path, top))
                return "Monde importé"
            for fmt in self.game.get("save_import", []):
                if not name.endswith(tuple(fmt["extensions"])):
                    continue
                with open(tmp_path, "rb") as fh:
                    head = fh.read(len(fmt["magic"]))
                if head != fmt["magic"].encode("latin-1"):
                    raise InstanceError("Ce fichier n'est pas une sauvegarde %s valide" % self.game["name"])
                target = os.path.join(self._save_path(), fmt["target"])

                def install():
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.copyfile(tmp_path, target)
                self._replace_save(install)
                return "%s importé" % fmt["label"]
            accepted = ", ".join(e for f in self.import_formats() for e in f["extensions"])
            raise InstanceError("Format non reconnu. Formats acceptés : %s" % accepted)


def list_all():
    if not os.path.isdir(paths.INSTANCES_DIR):
        return []
    out = []
    for name in sorted(os.listdir(paths.INSTANCES_DIR)):
        inst = Instance(name) if ID_RE.match(name) else None
        if inst and inst.exists():
            out.append(inst)
    return out
