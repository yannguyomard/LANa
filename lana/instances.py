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

from . import config, games, jobs, machine, paths, runtime

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
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
        base, n = game_id, 1
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

    def install(self, accept_eula=False):
        """Lance l'installation en arrière-plan ; retourne la tâche.

        Si le jeu impose un contrat de licence (`eula`), l'utilisateur doit l'avoir accepté explicitement :
        LANa n'accepte jamais un contrat à sa place.
        """
        game = self.game
        eula = game.get("eula")
        if eula and not accept_eula:
            raise InstanceError("Vous devez accepter le contrat de licence : %s" % eula["url"])
        verdict = machine.verdict(game["requirements"], [], machine.detect())
        if verdict["level"] == "bad":
            raise InstanceError(" ".join(verdict["messages"]))
        # Java est téléchargé automatiquement si absent ; les autres outils doivent déjà être là.
        missing = [t for t in games.needs(game) if t != "java" and not machine.find_tool(t)]
        if missing:
            raise InstanceError("Outil manquant : %s. Installez-le puis réessayez." % ", ".join(missing))

        def work(job):
            spec = game["install"]
            if game["run"]["runtime"] == "wine":
                runtime.init_prefix(self.prefix, job)
            extra = {}
            if spec["type"] == "steamcmd":
                runtime.steamcmd_install(game, self.server_dir, self.prefix, job)
            elif spec["type"] == "mojang":
                extra = runtime.mojang_install(game, self.server_dir, job)
                job.log("Serveur Minecraft %s installé." % extra["version"])
            else:
                raise RuntimeError("Type d'installation non géré : %s" % spec["type"])
            if not os.path.exists(os.path.join(self.server_dir, game["config"]["file"])):
                config.write_file(game, self.server_dir, config.initial_config(game))
                job.log("Configuration initiale créée.")
            if eula:
                with open(os.path.join(self.server_dir, eula["file"]), "w", encoding="utf-8") as fh:
                    fh.write(eula["content"])
                job.log("Contrat de licence accepté par l'utilisateur (%s)." % eula["url"])
            meta = self.meta()
            meta.update(extra)
            meta["installed"] = True
            self._save_meta(meta)
            job.log("Installation terminée.")

        return jobs.start("Installation de %s" % game["name"], work)

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
                raise InstanceError("Trop de mémoire allouée à Java (%s Mo) pour %s Go de RAM : laissez au moins 1,5 Go à macOS."
                                    % (settings["memory_mb"], ram))
            try:
                _procs[self.id] = runtime.start_process(self.game, self.server_dir, self.prefix, self.log_path,
                                                        settings=settings, java_min=self.meta().get("java_min", 0))
            except RuntimeError as ex:
                raise InstanceError(str(ex))
            self._set_pgid(_procs[self.id].pid)

    def stop(self, backup=True):
        with _lock(self.id):
            if not self.running():
                raise InstanceError("Le serveur est déjà arrêté")
            if backup and os.path.isdir(os.path.join(self.server_dir, self.game["savegame"])):
                self._backup_unlocked("avant-arret")
            if not runtime.stop_group(self._pgid(), self.game["run"]["runtime"], self.prefix):
                raise InstanceError("Le serveur ne s'est pas arrêté")

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
        if not os.path.exists(self.log_path):
            return ""
        with open(self.log_path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 60000))
            text = fh.read().decode("utf-8", "replace")
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
            out.append({"name": os.path.basename(path), "size_mb": round(os.path.getsize(path) / 2**20, 1)})
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

    def _extract_zip(self, path, top):
        dest = self._save_path()
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
