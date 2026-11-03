"""Pont entre l'appli de bureau et le moteur LANa (lana/), appelé directement, sans HTTP.

Toutes ces fonctions peuvent bloquer (disque, réseau, arrêt d'un serveur) : l'interface les appelle
depuis un fil d'arrière-plan (voir widgets.run_async).
"""
import os
import shutil
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lana import __version__, games, instances, jobs, paths, players, upnp, versions, web  # noqa: E402
from lana.instances import Instance, InstanceError  # noqa: E402,F401

VERSION = __version__
_installs = {}          # id du serveur -> tâche d'installation en cours ou finie (durée de vie de l'appli)
_services = threading.Event()


def start_services():
    """Suivi des joueurs et renouvellement UPnP, comme le panneau web."""
    if _services.is_set():
        return
    _services.set()
    os.makedirs(paths.INSTANCES_DIR, exist_ok=True)
    threading.Thread(target=players.track_forever, args=(instances.list_all,), daemon=True).start()
    threading.Thread(target=upnp.maintain_forever, args=(instances.list_all,), daemon=True).start()


def data_dir():
    return paths.HOME


# ---------- lecture ----------

def servers():
    out = []
    for inst in instances.list_all():
        try:
            out.append(_with_job(web.instance_payload(inst)))
        except Exception as ex:  # noqa: BLE001 - un serveur abîmé ne doit pas cacher les autres
            out.append({"id": inst.id, "name": inst.id, "game": "?", "installed": False, "running": False,
                        "broken": str(ex), "job": None})
    return out


def server(instance_id):
    return _with_job(web.instance_payload(Instance(instance_id)))


def _with_job(payload):
    job = _installs.get(payload["id"])
    payload["job"] = job.snapshot() if job else None
    return payload


def catalog():
    return web.games_payload()


def game(game_id):
    return games.get(game_id)


def startup_seconds(game_id):
    return games.run_spec(games.get(game_id)).get("startup_seconds", 30)


def version_options(game_id):
    return versions.available(games.get(game_id))


def log_tail(instance_id, lines=400):
    return Instance(instance_id).log_tail(lines)


def job(job_id):
    j = jobs.get(job_id)
    return j.snapshot() if j else None


# ---------- actions ----------

def create(game_id, name):
    return Instance.create(game_id, name.strip() or None).id


def install(instance_id, accept_eula=False, version=None):
    j = Instance(instance_id).install(accept_eula=accept_eula, version=version or None)
    _installs[instance_id] = j
    return j.snapshot()


def install_upload(instance_id, archive, accept_eula=False):
    Instance(instance_id).install_upload(archive, os.path.basename(archive), accept_eula=accept_eula)


def start(instance_id):
    Instance(instance_id).start()


def stop(instance_id):
    Instance(instance_id).stop()


def restart(instance_id):
    inst = Instance(instance_id)
    if inst.running():
        inst.stop()
    inst.start()


def delete(instance_id):
    inst = Instance(instance_id)
    if inst.running():
        raise InstanceError("Arrêtez le serveur avant de le supprimer")
    job = _installs.get(instance_id)
    if job and job.state == "running":
        raise InstanceError("Attendez la fin de l'installation avant de supprimer ce serveur")
    shutil.rmtree(inst.dir)
    _installs.pop(instance_id, None)


def running_servers():
    return [{"id": i.id, "name": i.meta().get("name", i.id)} for i in instances.list_all() if i.running()]
