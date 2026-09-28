"""Long-running tasks (downloads, installs) run in a thread; the UI polls their progress.

Only one job runs at a time: installs stop and restart servers, and two of them at once would fight.
"""
import itertools
import threading
import time
import traceback

_ids = itertools.count(1)
_jobs: dict[int, "Job"] = {}
_lock = threading.Lock()
KEEP_DONE = 600   # seconds a finished job stays visible to the UI poll


class Job:
    def __init__(self, title: str):
        self.id = next(_ids)
        self.title = title
        self.message = "Starting"
        self.progress = None      # 0..1, or None when unknown
        self.done = False
        self.error = None
        self.result = None
        self.finished = 0.0

    def update(self, message: str | None = None, progress: float | None = None):
        if message is not None:
            self.message = message
        self.progress = progress

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "message": self.message, "progress": self.progress,
                "done": self.done, "error": self.error, "result": self.result}


def start(title: str, fn, *args) -> dict:
    """Run fn(job, *args) in a background thread. Raises if another job is still running."""
    with _lock:
        busy = next((j for j in _jobs.values() if not j.done), None)
        if busy:
            raise RuntimeError(f"Wait for \"{busy.title}\" to finish first")
        job = Job(title)
        _jobs[job.id] = job

    def run():
        try:
            job.result = fn(job, *args)
            job.update("Done", 1)
        except Exception as e:
            traceback.print_exc()
            job.error = str(e) or e.__class__.__name__
        finally:
            job.finished = time.time()
            job.done = True

    threading.Thread(target=run, daemon=True, name=f"job-{job.id}").start()
    return job.as_dict()


def listing() -> list[dict]:
    now = time.time()
    with _lock:
        for jid in [j.id for j in _jobs.values() if j.done and now - j.finished > KEEP_DONE]:
            del _jobs[jid]
        return [j.as_dict() for j in _jobs.values()]
