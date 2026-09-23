"""Single leased worker. SQL owns the queue; the Event only reduces latency."""
import threading
import uuid
from .models import public_error


class Worker:
    def __init__(self, store, pipelines, settings):
        self.store, self.pipelines, self.settings = store, pipelines, settings
        self.owner = str(uuid.uuid4())
        self.stop_event = threading.Event()
        self.wakeup = threading.Event()
        self.thread = None
        self.last_error = None

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def start(self):
        self.store.acquire_worker(self.owner, self.settings.lease_seconds)
        self.thread = threading.Thread(target=self._loop, name="deepnotes-organizer", daemon=True)
        self.thread.start()

    def notify(self):
        self.wakeup.set()

    def tick(self):
        self.store.renew_worker(self.owner, self.settings.lease_seconds)
        job = self.store.claim_job(self.owner, self.settings.max_attempts)
        if not job:
            return False
        try:
            self.pipelines.run_job(job, self.owner)
            self.last_error = None
        except Exception as exc:
            self.last_error = public_error(exc)
            self.store.record_run("commit_or_pipeline", "failed", self.pipelines.model.name, {"error": self.last_error}, job_id=job["id"])
            self.store.fail_job(job, self.owner, self.last_error, self.settings.max_attempts, self.settings.retry_seconds)
        return True

    def _loop(self):
        try:
            while not self.stop_event.is_set():
                self.wakeup.clear()
                if not self.tick():
                    self.wakeup.wait(self.settings.poll_seconds)
        except Exception as exc:
            self.last_error = public_error(exc)
        finally:
            self.store.release_worker(self.owner)

    def stop(self):
        self.stop_event.set()
        self.wakeup.set()
        if self.thread:
            self.thread.join(timeout=self.settings.timeout + 15)
        # If a provider call outlives shutdown, keep the lease until expiry.
        # A live old thread cannot commit after a replacement takes ownership.
