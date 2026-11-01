"""Serveurs installés : un dossier par instance dans ~/LANa/instances/<id>/."""
import glob
import json
import os
import re
import shutil
import tarfile
import threading
import time

from . import config, games, jobs, machine, paths, runtime

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
KEEP_BACKUPS = 10
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

    def install(self):
        """Lance l'installation en arrière-plan ; retourne la tâche."""
        game = self.game
        verdict = machine.verdict(game["requirements"], [], machine.detect())
        if verdict["level"] == "bad":
            raise InstanceError(" ".join(verdict["messages"]))
        missing = [t for t in games.needs(game) if not machine.find_tool(t)]
        if missing:
            raise InstanceError("Outil manquant : %s. Installez-le puis réessayez." % ", ".join(missing))

        def work(job):
            spec = game["install"]
            if game["run"]["runtime"] == "wine":
                runtime.init_prefix(self.prefix, job)
            if spec["type"] == "steamcmd":
                runtime.steamcmd_install(game, self.server_dir, self.prefix, job)
            else:
                raise RuntimeError("Type d'installation non géré : %s" % spec["type"])
            if not os.path.exists(os.path.join(self.server_dir, game["config"]["file"])):
                config.write_file(game, self.server_dir, config.initial_config(game))
                job.log("Configuration initiale créée.")
            meta = self.meta()
            meta["installed"] = True
            with open(self.meta_path, "w", encoding="utf-8") as fh:
                json.dump(meta, fh)
            job.log("Installation terminée.")

        return jobs.start("Installation de %s" % game["name"], work)

    # ---------- démarrage et arrêt ----------

    def start(self):
        with _lock(self.id):
            if not self.meta().get("installed"):
                raise InstanceError("Ce serveur n'est pas encore installé")
            if self.running():
                raise InstanceError("Le serveur tourne déjà")
            _procs[self.id] = runtime.start_process(self.game, self.server_dir, self.prefix, self.log_path)
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

    def read_config(self):
        game = self.game
        return config.to_ui(game, config.read_file(game, self.server_dir))

    def write_config(self, values):
        game = self.game
        current = config.read_file(game, self.server_dir)
        config.write_file(game, self.server_dir, config.apply_ui(game, current, values))

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
