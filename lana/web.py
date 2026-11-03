"""Serveur web de LANa : API JSON + interface. Bibliothèque standard uniquement."""
import base64
import hmac
import json
import os
import re
import secrets
import shutil
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, games, instances, jobs, machine, paths, players, system, upnp, versions
from .instances import Instance, InstanceError

ROUTE_INSTANCE = re.compile(r"^/api/instances/([a-z0-9-]+)(?:/([a-z-]+))?$")
ROUTE_JOB = re.compile(r"^/api/jobs/([0-9a-f]+)$")
ROUTE_VERSIONS = re.compile(r"^/api/games/([a-z0-9_]+)/versions$")
ROUTE_DOWNLOAD = re.compile(r"^/api/instances/([a-z0-9-]+)/backups/([A-Za-z0-9._-]+)$")
# Fichiers de l'interface (polices…) : noms simples uniquement, sans « .. » possible, et types en liste blanche.
ROUTE_STATIC = re.compile(r"^/static/((?:[a-z0-9_-]+/)*[a-z0-9_-]+(\.[a-z0-9]+))$")
STATIC_TYPES = {".woff2": "font/woff2", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".js": "text/javascript; charset=utf-8"}


def static_file(url_path):
    """(chemin, type) d'un fichier de web/static demandé par l'interface, ou None s'il est refusé ou absent."""
    match = ROUTE_STATIC.match(url_path)
    if not match or match.group(2) not in STATIC_TYPES:
        return None
    base = os.path.realpath(os.path.join(paths.WEB_DIR, "static"))
    full = os.path.realpath(os.path.join(base, match.group(1)))
    if not full.startswith(base + os.sep) or not os.path.isfile(full):
        return None
    return full, STATIC_TYPES[match.group(2)]
MAX_UPLOAD_BYTES = 1024 * 2**20   # 1 Go : une sauvegarde de jeu est bien plus petite


def load_auth():
    """Identifiants du panneau ; créés au premier lancement. Retourne (auth, créé_maintenant)."""
    if os.path.exists(paths.AUTH_FILE):
        with open(paths.AUTH_FILE) as fh:
            return json.load(fh), False
    auth = {"user": "admin", "password": secrets.token_urlsafe(12)}
    os.makedirs(paths.HOME, exist_ok=True)
    fd = os.open(paths.AUTH_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(auth, fh)
    return auth, True


def games_payload():
    mach = machine.detect()
    out = []
    for game in games.load_all().values():
        spec = game["install"]
        out.append({"id": game["id"], "name": game["name"], "requirements": game["requirements"],
                    "eula": game.get("eula"), "install_type": spec["type"],
                    "install_help": spec.get("help", ""), "family": game.get("family", ""),
                    "untested": bool(game.get("untested")), "wine": "wine" in games.needs(game),
                    "versions": versions.kind(game),
                    "verdict": machine.verdict(game["requirements"], games.needs(game), mach, game.get("compat"))})
    return out


def instance_payload(inst):
    game = inst.game
    out = inst.status()
    out["fields"] = game["fields"]
    out["requirements"] = game["requirements"]
    out["eula"] = game.get("eula")
    spec = game["install"]
    out["install_type"] = spec["type"]
    out["install_help"] = spec.get("help", "")
    out["versions"] = versions.kind(game)
    out["version"] = inst.meta().get("version", "")
    tracking = game.get("players")
    out["players_tracking"] = {"verified": tracking.get("verified", False), "note": tracking.get("note", "")} if tracking else None
    if out["installed"]:
        values = inst.read_config()
        out["values"] = values
        ip = system.lan_ip()
        out["ports"] = inst.ports()
        out["upnp"] = upnp.status(inst)
        # Les clés à point ou à deux-points ne sont pas utilisables dans un format : réglages LANa sous leur nom court.
        names = {k: v for k, v in values.items() if "." not in k and ":" not in k}
        names.update({k[len("lana:"):]: v for k, v in values.items() if k.startswith("lana:")})
        # Clés à point (json imbriqué) utilisables sous forme soulignée : network.port -> {network_port}
        names.update({k.replace(".", "_"): v for k, v in values.items() if "." in k and ":" not in k and "[" not in k})
        out["connect"] = game.get("connect", "").format(lan_ip=ip or "?", **names)
        wan = out["upnp"]["external_ip"]
        out["connect_wan"] = game.get("connect", "").format(lan_ip=wan, **names) if wan and out["upnp"]["state"] == "ok" else ""
        out["backups"] = inst.backups()
        out["save_path"] = inst._save_path()
        out["backup_dir"] = inst.backup_dir
        out["import_formats"] = inst.import_formats()
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "LANa/" + __version__
    auth = None

    def log_message(self, *args):
        pass

    # ---------- utilitaires ----------

    def authed(self):
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
        except ValueError:
            return False
        return hmac.compare_digest(user, self.auth["user"]) & hmac.compare_digest(pw, self.auth["password"])

    def reply(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def json(self, obj, code=200):
        self.reply(code, json.dumps(obj, ensure_ascii=False))

    def fail(self, message, code=400):
        self.json({"ok": False, "message": message}, code)

    def send_file(self, path):
        """Envoie un fichier en téléchargement, par blocs (une archive peut peser plusieurs centaines de Mo)."""
        self.send_response(200)
        self.send_header("Content-Type", "application/gzip")
        self.send_header("Content-Length", str(os.path.getsize(path)))
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % os.path.basename(path))
        self.end_headers()
        with open(path, "rb") as fh:
            shutil.copyfileobj(fh, self.wfile, 1 << 20)

    def send_static(self, path, ctype):
        with open(path, "rb") as fh:
            raw = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        self.wfile.write(raw)

    def receive_upload(self, dest):
        """Écrit le corps de la requête dans dest, en refusant ce qui dépasse la limite."""
        length = int(self.headers.get("Content-Length", 0))
        if not 0 < length <= MAX_UPLOAD_BYTES:
            raise InstanceError("Fichier vide ou trop volumineux (limite %d Mo)" % (MAX_UPLOAD_BYTES // 2**20))
        remaining = length
        with open(dest, "wb") as fh:
            while remaining:
                chunk = self.rfile.read(min(remaining, 1 << 20))
                if not chunk:
                    raise InstanceError("Envoi interrompu")
                fh.write(chunk)
                remaining -= len(chunk)

    def instance(self, instance_id):
        inst = Instance(instance_id)
        inst.meta()  # lève InstanceError si absent
        return inst

    # ---------- GET ----------

    def do_GET(self):
        if not self.authed():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="LANa"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        path = self.path.split("?")[0]
        try:
            if path == "/":
                with open(os.path.join(paths.WEB_DIR, "index.html"), "rb") as fh:
                    return self.reply(200, fh.read(), "text/html")
            asset = static_file(path)
            if asset:
                return self.send_static(*asset)
            if path == "/api/machine":
                return self.json(dict(machine.detect(), version=__version__))
            if path == "/api/games":
                return self.json(games_payload())
            if path == "/api/instances":
                return self.json([i.status() for i in instances.list_all()])
            download = ROUTE_DOWNLOAD.match(path)
            if download:
                inst = self.instance(download.group(1))
                return self.send_file(inst.backup_path(download.group(2)))
            wanted = ROUTE_VERSIONS.match(path)
            if wanted:
                try:
                    return self.json({"ok": True, "versions": versions.available(games.get(wanted.group(1)))})
                except KeyError as ex:
                    return self.fail(str(ex), 404)
                except versions.VersionError as ex:
                    return self.fail(str(ex), 502)
            job = ROUTE_JOB.match(path)
            if job:
                found = jobs.get(job.group(1))
                return self.json(found.snapshot()) if found else self.fail("Tâche introuvable", 404)
            match = ROUTE_INSTANCE.match(path)
            if match:
                inst = self.instance(match.group(1))
                if match.group(2) is None:
                    return self.json(instance_payload(inst))
                if match.group(2) == "log":
                    return self.reply(200, inst.log_tail(), "text/plain")
                if match.group(2) == "players":
                    found = players.report(inst) if inst.meta().get("installed") else None
                    if found is None:
                        return self.fail("Le suivi des joueurs n'est pas disponible pour ce serveur", 404)
                    return self.json(found)
            self.fail("Introuvable", 404)
        except InstanceError as ex:
            self.fail(str(ex), 404)

    # ---------- POST ----------

    def do_POST(self):
        if not self.authed():
            return self.fail("Authentification requise", 401)
        # Anti-CSRF : un formulaire d'un autre site ne peut pas poser cet en-tête.
        if self.headers.get("X-LANa") != "1":
            return self.fail("Requête refusée", 403)
        path = self.path.split("?")[0]
        upload = ROUTE_INSTANCE.match(path)
        if upload and upload.group(2) == "import":
            # Corps binaire (le fichier lui-même), pas du JSON.
            return self.handle_import(upload.group(1))
        if upload and upload.group(2) == "server-files":
            return self.handle_server_files(upload.group(1))
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except ValueError:
            return self.fail("JSON invalide")
        try:
            self.route_post(path, body)
        except InstanceError as ex:
            self.fail(str(ex))
        except (ValueError, KeyError, TypeError) as ex:
            self.fail("Non enregistré : %s" % ex)

    def handle_import(self, instance_id):
        try:
            inst = self.instance(instance_id)
            if inst.running():  # on refuse avant de recevoir le fichier
                raise InstanceError("Arrêtez le serveur avant d'importer une sauvegarde")
            filename = urllib.parse.unquote(self.headers.get("X-Filename", ""))
            tmp = os.path.join(inst.dir, "import.tmp")
            try:
                self.receive_upload(tmp)
                message = inst.import_save(tmp, os.path.basename(filename))
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
            self.json({"ok": True, "message": message + ". L'ancienne sauvegarde est archivée."})
        except InstanceError as ex:
            self.fail(str(ex))

    def handle_server_files(self, instance_id):
        """Installation d'un jeu dont l'utilisateur fournit lui-même les fichiers serveur (archive)."""
        try:
            inst = self.instance(instance_id)
            filename = urllib.parse.unquote(self.headers.get("X-Filename", ""))
            accept = self.headers.get("X-Accept-Eula") == "1"
            tmp = os.path.join(inst.dir, "server-files.tmp")
            try:
                self.receive_upload(tmp)
                message = inst.install_upload(tmp, os.path.basename(filename), accept_eula=accept)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
            self.json({"ok": True, "message": message})
        except InstanceError as ex:
            self.fail(str(ex))

    def route_post(self, path, body):
        if path == "/api/instances":
            game = games.get(body.get("game", ""))
            inst = Instance.create(game["id"], body.get("name"))
            if game["install"]["type"] == "upload":   # l'installation se fera au dépôt de l'archive
                return self.json({"ok": True, "id": inst.id, "job": None})
            try:
                job = inst.install(accept_eula=body.get("accept_eula") is True, version=body.get("version") or None)
            except InstanceError:
                shutil.rmtree(inst.dir, ignore_errors=True)
                raise
            return self.json({"ok": True, "id": inst.id, "job": job.id})
        match = ROUTE_INSTANCE.match(path)
        if not match or not match.group(2):
            return self.fail("Introuvable", 404)
        inst, action = self.instance(match.group(1)), match.group(2)
        if action == "install":
            return self.json({"ok": True, "job": inst.install(accept_eula=body.get("accept_eula") is True).id})
        if action == "version":
            job = inst.change_version(body["version"], accept_eula=body.get("accept_eula") is True)
            return self.json({"ok": True, "job": job.id})
        if action == "start":
            inst.start()
            return self.json({"ok": True, "message": "Démarrage lancé (environ %s secondes)" % games.run_spec(inst.game).get("startup_seconds", 30)})
        if action == "stop":
            inst.stop()
            return self.json({"ok": True, "message": "Serveur arrêté, sauvegarde faite"})
        if action == "restart":
            if inst.running():
                inst.stop()
            inst.start()
            return self.json({"ok": True, "message": "Redémarrage lancé"})
        if action == "config":
            inst.write_config(body["values"])
            if body.get("restart") and inst.running():
                inst.stop()
                inst.start()
                return self.json({"ok": True, "message": "Configuration enregistrée, serveur redémarré"})
            note = " Redémarrez le serveur pour l'appliquer." if inst.running() else ""
            return self.json({"ok": True, "message": "Configuration enregistrée." + note})
        if action == "upnp":
            inst.set_upnp(body["enabled"] is True)
            return self.json({"ok": True, "message": "Ouverture automatique des ports %s" % ("activée" if body["enabled"] is True else "désactivée")})
        if action == "backup":
            name = inst.backup(body.get("label", "manuelle"))
            return self.json({"ok": True, "message": "Sauvegarde créée : %s" % name, "name": name})
        if action == "restore":
            inst.restore(body["name"])
            return self.json({"ok": True, "message": "Sauvegarde restaurée"})
        if action == "delete":
            if inst.running():
                raise InstanceError("Arrêtez le serveur avant de le supprimer")
            shutil.rmtree(inst.dir)
            return self.json({"ok": True, "message": "Serveur supprimé"})
        self.fail("Action inconnue", 404)


def serve(host, port):
    Handler.auth, created = load_auth()
    if created:
        print("Identifiants créés — utilisateur : %s  mot de passe : %s" % (Handler.auth["user"], Handler.auth["password"]))
        print("(ils sont aussi dans %s)" % paths.AUTH_FILE)
    print("LANa %s sur http://%s:%d" % (__version__, "localhost" if host == "127.0.0.1" else host, port))
    threading.Thread(target=players.track_forever, args=(instances.list_all,), daemon=True).start()
    threading.Thread(target=upnp.maintain_forever, args=(instances.list_all,), daemon=True).start()
    ThreadingHTTPServer((host, port), Handler).serve_forever()
