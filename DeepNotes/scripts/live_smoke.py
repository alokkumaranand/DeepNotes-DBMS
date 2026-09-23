"""Opt-in provider check using synthetic samples in a temporary database only."""
import argparse
from pathlib import Path
import tempfile

from deepnotes.config import Settings
from deepnotes.models import CloudModel, public_error
from deepnotes.pipelines import Pipelines
from deepnotes.storage import Store


def main():
    parser = argparse.ArgumentParser(description="Send synthetic note/context samples to the configured cloud model. May incur provider charges; never uses your notes database.")
    parser.add_argument("--confirm-send-sample", action="store_true", help="Explicitly allow external model calls with synthetic samples")
    args = parser.parse_args()
    if not args.confirm_send_sample:
        parser.error("Pass --confirm-send-sample to authorize the provider calls")
    settings = Settings.from_env()
    model = CloudModel(settings)
    if not model.configured:
        parser.error("Configure LLM_API_KEY in DeepNotes/.env first")
    with tempfile.TemporaryDirectory(prefix="deepnotes-live-") as directory:
        store = Store(Path(directory) / "smoke.sqlite3")
        store.initialize()
        store.acquire_worker("live-smoke", settings.lease_seconds)
        pipelines = Pipelines(store, model)
        try:
            store.create_entry("Java generics let classes and methods use type parameters.")
            job = store.claim_job("live-smoke", 1)
            pipelines.organize(job, "live-smoke")
            if store.get_entry(1)["status"] != "completed":
                raise RuntimeError("Organizer did not complete")
            result = pipelines.answer("What did I save about Java generics?")
            if not result["references"]["notes"]:
                raise RuntimeError("Sample note was not retrieved")
            store.renew_worker("live-smoke", settings.lease_seconds)
            store.queue_structure()
            job = store.claim_job("live-smoke", 1)
            pipelines.restructure(job, "live-smoke")
            if next(j for j in store.jobs() if j["id"] == job["id"])["state"] != "completed":
                raise RuntimeError("Structural review did not complete")
            print("PASS: organizer, query planner, answer composer, and structural review returned valid outputs.")
            print("Sample answer (review its quality yourself):")
            print(result["answer"])
            print("Coverage:", result["references"]["coverage"])
            print("This is a connectivity/contract check, not a broad quality evaluation.")
        except Exception as exc:
            print("FAIL:", public_error(exc))
            return 1
        finally:
            store.release_worker("live-smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
