"""Deterministic regression tests. No network calls or prototype data access."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from deepnotes.api import create_app
from deepnotes.config import Settings
from deepnotes.contracts import StructureProposal
from deepnotes.models import DemoModel, CloudModel, ModelUnavailable
from deepnotes.pipelines import Pipelines, validate_catalog
from deepnotes.storage import Store, fts_query
from deepnotes.worker import Worker


FEEDBACK = {"id": "feedback", "name": "Feedback", "description": "Feedback about DeepNotes, its behavior and improvements.", "aliases": ["application suggestions"], "parent_id": None, "routing_hints": "User comments on the note application."}


def interpretation(class_id="unclassified"):
    return {"summary": "Java has a type system.", "intent": "learning", "class_ids": [class_id], "concepts": ["Java", "type system"], "relations": [], "rationale": "A learning note.", "clarification": ""}


class ScriptedModel(DemoModel):
    name = "scripted-test-model"

    def __init__(self, outputs=None):
        self.outputs = outputs or {}
        self.contexts = []

    def generate(self, step, system, context, schema):
        self.contexts.append((step, context))
        if step not in self.outputs:
            return super().generate(step, system, context, schema)
        value = self.outputs[step]
        if callable(value):
            value = value(context)
        if isinstance(value, Exception):
            raise value
        return (value if isinstance(value, str) else json.dumps(value)), {"test": True}


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "test.sqlite3")
        self.store.initialize()
        self.owner = "test-worker"
        self.store.acquire_worker(self.owner, 120)

    def tearDown(self):
        self.store.release_worker(self.owner)
        self.temp.cleanup()

    def claim(self):
        return self.store.claim_job(self.owner, 3)


class StorageTests(StoreCase):
    def test_capture_is_atomic_and_immediately_searchable(self):
        entry = self.store.create_entry("Java generics preserve type safety.")
        self.assertEqual(entry["status"], "pending")
        self.assertEqual(self.store.search("generics", [], 1)[0]["id"], entry["id"])
        self.assertEqual(len(self.store.jobs()), 1)
        with patch.object(Store, "_enqueue_entry", side_effect=RuntimeError("simulated")):
            with self.assertRaises(RuntimeError):
                self.store.create_entry("Must roll back")
        self.assertEqual(len(self.store.entries()), 1)
        self.assertFalse(self.store.search("rollback", [], 1))

    def test_sessions_break_after_thirty_minutes(self):
        a = self.store.create_entry("first", now=100)
        b = self.store.create_entry("second", now=1800)
        c = self.store.create_entry("third", now=3600)
        self.assertEqual(a["session_id"], b["session_id"])
        self.assertNotEqual(b["session_id"], c["session_id"])
        self.assertEqual(len(self.store.entry_context(b["id"])["preceding_context_only"]), 1)
        self.assertFalse(self.store.entry_context(c["id"])["preceding_context_only"])

    def test_context_is_three_preceding_not_future_entries(self):
        notes = [self.store.create_entry(str(i), now=100 + i) for i in range(6)]
        context = self.store.entry_context(notes[4]["id"])
        self.assertEqual([n["id"] for n in context["preceding_context_only"]], [2, 3, 4])

    def test_duplicate_safe_completion_and_restart_persistence(self):
        entry = self.store.create_entry("Java has a type system.")
        job = self.claim()
        self.assertTrue(self.store.complete_organization(job, self.owner, interpretation()))
        self.assertFalse(self.store.complete_organization(job, self.owner, interpretation()))
        second = Store(self.store.path)
        second.initialize()
        self.assertEqual(second.get_entry(entry["id"])["status"], "completed")
        with second.connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM mentions").fetchone()[0], 2)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_retry_and_exhausted_failures(self):
        self.store.create_entry("Retry me")
        for attempt in range(1, 4):
            job = self.claim()
            self.assertEqual(job["attempts"], attempt)
            self.store.fail_job(job, self.owner, "test failure", 3, 0)
        self.assertEqual(self.store.jobs()[0]["state"], "failed")
        self.store.retry_job(job["id"])
        self.assertEqual(self.claim()["attempts"], 1)

    def test_worker_lock_and_crash_recovery_fence(self):
        self.store.create_entry("Survive interruption")
        job = self.claim()
        with self.assertRaises(RuntimeError):
            self.store.acquire_worker("other", 120)
        with self.store.connection(True) as conn:
            conn.execute("UPDATE process_lease SET expires_at=0")
        self.store.acquire_worker("replacement", 120)
        self.assertFalse(self.store.complete_organization(job, self.owner, interpretation()))
        resumed = self.store.claim_job("replacement", 3)
        self.assertEqual(resumed["id"], job["id"])
        self.assertEqual(resumed["attempts"], 2)
        self.store.release_worker("replacement")

    def test_entry_guidance_invalidates_old_job_and_is_scoped(self):
        a = self.store.create_entry("Make it nicer")
        b = self.store.create_entry("Unrelated physics")
        job = self.claim()
        gid = self.store.add_guidance("entry", str(a["id"]), "This is feedback about DeepNotes.")
        self.assertFalse(self.store.complete_organization(job, self.owner, interpretation()))
        self.assertEqual(self.store.get_entry(a["id"])["revision"], 2)
        self.assertEqual(self.store.get_entry(b["id"])["revision"], 1)
        self.assertEqual(self.store.applicable_guidance(a["id"])["items"][0]["id"], gid)
        self.assertFalse(self.store.applicable_guidance(b["id"])["items"])
        self.assertTrue(any(j["kind"] == "structure" for j in self.store.jobs()))

    def test_global_guidance_requeues_all_and_budget_is_visible(self):
        self.store.create_entry("One")
        self.store.create_entry("Two")
        for _ in range(4):
            self.store.add_guidance("global", None, "x" * 4000)
        self.assertTrue(self.store.applicable_guidance()["truncated"])
        self.assertTrue(all(e["revision"] == 5 for e in self.store.entries()))
        self.assertEqual(sum(j["kind"] == "structure" and j["state"] == "pending" for j in self.store.jobs()), 1)

    def test_auto_trigger_and_manual_requests_coalesce(self):
        for i in range(4):
            self.store.create_entry(str(i))
        a, b = self.store.queue_structure(), self.store.queue_structure()
        self.assertEqual(a, b)
        self.assertEqual(sum(j["kind"] == "structure" for j in self.store.jobs()), 1)

    def test_publication_reprocesses_and_fences_stale_work(self):
        entry = self.store.create_entry("Java has a type system.")
        job = self.claim()
        classes = self.store.catalog()["classes"] + [FEEDBACK]
        version = self.store.publish(classes, "Add feedback", 1)
        self.assertEqual(version, 2)
        self.assertFalse(self.store.complete_organization(job, self.owner, interpretation()))
        replacement = self.claim()
        self.assertEqual(replacement["version"], 2)
        self.assertTrue(self.store.complete_organization(replacement, self.owner, interpretation("feedback")))
        self.assertEqual(self.store.get_entry(entry["id"])["interpretation"]["class_ids"], ["feedback"])

    def test_rollback_is_new_version_with_search_snapshot(self):
        entry = self.store.create_entry("Java has a type system.")
        self.store.complete_organization(self.claim(), self.owner, interpretation())
        self.store.publish(self.store.catalog()["classes"] + [FEEDBACK], "Feedback", 1)
        result = interpretation("feedback")
        result["summary"] = "rollbackuniqueterm"
        self.store.complete_organization(self.claim(), self.owner, result)
        self.assertTrue(self.store.search("rollbackuniqueterm", [], 2))
        self.assertFalse(self.store.search("rollbackuniqueterm", [], 1))
        version = Pipelines(self.store, DemoModel()).rollback(1)
        self.assertEqual(version, 3)
        self.assertFalse(self.store.search("rollbackuniqueterm", [], 3))
        self.assertTrue(self.store.search("rollbackuniqueterm", [], 2))
        view = self.store.get_entry(entry["id"])
        self.assertTrue(view["interpretation"]["inherited"])
        self.assertEqual(view["interpretation"]["origin_version"], 1)
        self.assertEqual(view["content"], "Java has a type system.")

    def test_class_removal_normalizes_inherited_assignments(self):
        entry = self.store.create_entry("Application feedback")
        self.store.publish(self.store.catalog()["classes"] + [FEEDBACK], "Add", 1)
        self.store.complete_organization(self.claim(), self.owner, interpretation("feedback"))
        self.store.publish(self.store.catalog(1)["classes"], "Remove", 1)
        self.assertEqual(self.store.get_entry(entry["id"])["interpretation"]["class_ids"], ["unclassified"])
        with self.store.connection() as conn:
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_fts_input_is_not_executable_syntax(self):
        self.store.create_entry("Java language")
        self.assertTrue(self.store.search('Java OR "; DROP TABLE entries; --', [], 1))
        self.assertEqual(len(self.store.entries()), 1)
        self.assertEqual(fts_query('"*()'), "")

    def test_generated_interactions_are_not_note_evidence(self):
        iid, _ = self.store.begin_interaction("uniqueghostword")
        self.store.finish_interaction(iid, "uniqueghostword is generated", {"notes": []}, {})
        self.assertFalse(self.store.search("uniqueghostword", [], 1))
        self.assertEqual(len(self.store.interactions("uniqueghostword")), 1)

    def test_structure_noop_covers_snapshot_not_later_entries(self):
        for i in range(4):
            self.store.create_entry(str(i))
        while True:
            job = self.claim()
            if job["kind"] == "structure":
                break
            self.store.complete_organization(job, self.owner, interpretation())
        self.store.create_entry("arrived after snapshot")
        self.store.complete_review(job, self.owner, 4)
        with self.store.connection() as conn:
            self.assertEqual(conn.execute("SELECT value FROM settings WHERE key='review_high_water'").fetchone()[0], "4")


class PipelineTests(StoreCase):
    def test_organizer_validates_source_excerpts(self):
        self.store.create_entry("Java has a type system.")
        result = interpretation()
        result["relations"] = [{"source": "Java", "target": "type system", "relation": "related_to", "evidence": [{"entry_id": 1, "excerpt": "invented excerpt"}], "inferred": True}]
        pipeline = Pipelines(self.store, ScriptedModel({"organize": result}))
        with self.assertRaises(ValueError):
            pipeline.organize(self.claim(), self.owner)
        self.assertIsNone(self.store.get_entry(1)["interpretation"])

    def test_valid_evidence_and_multiple_relations_persist(self):
        self.store.create_entry("Java has a type system.")
        result = interpretation()
        evidence = [{"entry_id": 1, "excerpt": "Java has a type system."}]
        result["relations"] = [{"source": "Java", "target": "type system", "relation": kind, "evidence": evidence, "inferred": True} for kind in ("related_to", "supports")]
        Pipelines(self.store, ScriptedModel({"organize": result})).organize(self.claim(), self.owner)
        with self.store.connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0], 2)

    def test_meta_catalog_and_explicit_context_reach_both_agents(self):
        self.store.create_entry("Make feedback easier")
        self.store.add_guidance("global", None, "Feedback concerns the DeepNotes application.")
        model = ScriptedModel()
        pipeline = Pipelines(self.store, model)
        pipeline.organize(self.claim(), self.owner)
        pipeline.answer("feedback")
        for step, context in model.contexts:
            if step in ("organize", "plan"):
                self.assertIn("overview", context["catalog"])
                self.assertTrue(context["guidance"]["items"])

    def test_entry_clarification_reaches_structure_review(self):
        self.store.create_entry("This interface needs improvement")
        gid = self.store.add_guidance("entry", "1", "This is feedback about DeepNotes.")
        model = ScriptedModel({"structure": {"upserts": [FEEDBACK], "remove_ids": [], "rationale": "Feedback context", "support_entry_ids": [1], "support_guidance_ids": [gid]}})
        pipeline = Pipelines(self.store, model)
        pipeline.organize(self.claim(), self.owner)
        pipeline.restructure(self.claim(), self.owner)
        self.assertIn("feedback", [c["id"] for c in self.store.catalog()["classes"]])
        structure_context = next(c for s, c in model.contexts if s == "structure")
        self.assertEqual(structure_context["guidance"]["items"][0]["scope"], "entry")

    def test_answer_empty_database_and_persisted_references(self):
        output = {"answer": "Java is a programming language.", "coverage": "none", "general_knowledge": True, "explanation": "General model knowledge; no saved evidence.", "cited_entry_ids": []}
        response = Pipelines(self.store, ScriptedModel({"answer": output})).answer("What is Java?")
        self.assertEqual(response["answer"], output["answer"])
        self.assertTrue(response["references"]["general_knowledge"])
        self.assertFalse(response["references"]["live_web"])
        self.assertEqual(self.store.interactions()[0]["references"], response["references"])

    def test_invalid_citation_fails_and_is_recorded(self):
        self.store.create_entry("Java language")
        output = {"answer": "A claim", "coverage": "sufficient", "general_knowledge": False, "explanation": "Saved notes", "cited_entry_ids": [999]}
        with self.assertRaises(ValueError):
            Pipelines(self.store, ScriptedModel({"answer": output})).answer("Java")
        history = self.store.interactions()[0]
        self.assertEqual(history["status"], "failed")
        self.assertIsNone(history["answer"])

    def test_planning_failure_still_uses_indexed_fallback_and_postprocessor(self):
        self.store.create_entry("Java is a language")
        model = ScriptedModel({"plan": "not-json"})
        response = Pipelines(self.store, model).answer("Java")
        self.assertEqual(response["references"]["notes"][0]["id"], 1)
        self.assertIsNotNone(self.store.interactions()[0]["metadata"]["planning_error"])
        self.assertEqual([s for s, _ in model.contexts], ["plan", "answer"])

    def test_catalog_rejects_cycles_unknown_evidence_and_reserved_changes(self):
        current = self.store.catalog()["classes"]
        bad = {**FEEDBACK, "parent_id": "feedback"}
        for changes in (
            {"upserts": [bad], "support_entry_ids": [1]},
            {"upserts": [FEEDBACK], "support_entry_ids": [999]},
            {"remove_ids": ["unclassified"], "support_entry_ids": [1]},
        ):
            proposal = StructureProposal(rationale="test", **changes)
            with self.assertRaises(ValueError):
                validate_catalog(current, proposal, [1], [])

    def test_worker_marks_validation_failure_retryable(self):
        self.store.create_entry("Test note")
        settings = Settings(db_path=self.store.path, retry_seconds=0)
        model = ScriptedModel({"organize": "not-json"})
        worker = Worker(self.store, Pipelines(self.store, model), settings)
        worker.owner = self.owner
        self.assertTrue(worker.tick())
        self.assertEqual(self.store.jobs()[0]["state"], "pending")
        self.assertIsNone(self.store.get_entry(1)["interpretation"])
        self.assertIn("validation", worker.last_error)

    def test_missing_credentials_does_not_prevent_saving(self):
        self.store.create_entry("Stored without a key")
        model = CloudModel(Settings(api_key="", db_path=self.store.path))
        with self.assertRaises(ModelUnavailable):
            Pipelines(self.store, model).answer("A question")
        self.assertEqual(len(self.store.entries()), 1)
        self.assertEqual(self.store.interactions()[0]["status"], "failed")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        settings = Settings(db_path=Path(self.temp.name) / "api.sqlite3", demo_mode=True)
        self.app = create_app(settings, start_worker=False)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def test_original_code_indentation_is_preserved(self):
        original = "    if ready:\n        learn()\n\n"
        result = self.client.post("/api/entries", json={"content": original})
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json()["content"], original)
        self.assertEqual(self.client.get("/api/entries").json()["items"][0]["content"], original)

    def test_full_capture_query_guidance_history_contract(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        saved = self.client.post("/api/entries", json={"content": "Java type system", "source_url": "https://example.com/java"})
        self.assertEqual(saved.status_code, 201)
        eid = saved.json()["id"]
        context = self.client.post("/api/guidance", json={"scope": "entry", "target_id": str(eid), "content": "Lecture notes"})
        self.assertEqual(context.status_code, 201)
        answer = self.client.post("/api/queries", json={"question": "Java"})
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertTrue(answer.json()["answer"])
        self.assertIn("references", answer.json())
        self.assertEqual(len(self.client.get("/api/interactions").json()["items"]), 1)
        self.assertTrue(self.client.get("/api/status").json()["demo_mode"])
        queued = self.client.post("/api/structure/reorganize", json={})
        self.assertEqual(queued.status_code, 200)

    def test_validation_local_security_and_no_destructive_reset(self):
        self.assertEqual(self.client.post("/api/entries", json={"content": " "}).status_code, 422)
        self.assertEqual(self.client.post("/api/entries", json={"content": "X", "source_url": "javascript:alert(1)"}).status_code, 422)
        self.assertEqual(self.client.post("/api/entries", json={"content": "X"}, headers={"Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/entries", content="x", headers={"Content-Type": "text/plain"}).status_code, 415)
        self.assertEqual(self.client.get("/api/status", headers={"Host": "evil.example"}).status_code, 400)
        self.assertEqual(self.client.post("/reset", json={}).status_code, 405)

    def test_live_worker_processes_and_stops(self):
        self.client.__exit__(None, None, None)
        settings = Settings(db_path=Path(self.temp.name) / "thread.sqlite3", demo_mode=True, poll_seconds=0.01)
        self.app = create_app(settings)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.client.post("/api/entries", json={"content": "Worker note"})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.client.get("/api/entries").json()["items"][0]["status"] == "completed":
                break
            threading.Event().wait(0.02)
        else:
            self.fail("Worker did not complete in time")
        worker = self.app.state.worker
        self.client.__exit__(None, None, None)
        self.assertFalse(worker.running)
        # Reenter so teardown owns a matching context.
        self.app = create_app(settings, start_worker=False)
        self.client = TestClient(self.app)
        self.client.__enter__()


if __name__ == "__main__":
    unittest.main()
