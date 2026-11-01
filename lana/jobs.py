"""Tâches longues (installation…) exécutées en arrière-plan, avec un journal consultable."""
import threading
import time
import uuid

_jobs = {}
_lock = threading.Lock()


class Job:
    def __init__(self, title):
        self.id = uuid.uuid4().hex[:10]
        self.title = title
        self.state = "running"  # running | done | error
        self.lines = []
        self.started = time.time()

    def log(self, line):
        self.lines.append(line.rstrip())
        del self.lines[:-400]

    def snapshot(self):
        return {"id": self.id, "title": self.title, "state": self.state, "lines": self.lines[-60:]}


def start(title, func):
    """Lance func(job) dans un thread ; une exception passe la tâche en erreur."""
    job = Job(title)
    with _lock:
        _jobs[job.id] = job

    def run():
        try:
            func(job)
            job.state = "done"
        except Exception as ex:  # noqa: BLE001 - toute erreur doit remonter à l'interface
            job.log("ERREUR : %s" % ex)
            job.state = "error"

    threading.Thread(target=run, daemon=True).start()
    return job


def get(job_id):
    return _jobs.get(job_id)
