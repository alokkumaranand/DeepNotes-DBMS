"""Failure cases found during independent review, preserved as regressions."""
import asyncio
import json
import time
from unittest.mock import patch
import unittest
import httpx

from deepnotes.config import Settings
from deepnotes.models import CloudModel, ModelUnavailable, DemoModel
from deepnotes.pipelines import Pipelines
from test_system import StoreCase, ScriptedModel, interpretation, FEEDBACK


class ReviewRegressions(StoreCase):
    def test_recovery_coalesces_running_and_pending_structure_jobs(self):
        first = self.store.queue_structure()
        claimed = self.claim()
        self.assertEqual(claimed["id"], first)
        successor = self.store.queue_structure()
        self.assertNotEqual(first, successor)
        with self.store.connection(True) as conn:
            conn.execute("UPDATE process_lease SET expires_at=0")
        self.store.acquire_worker("replacement", 120)
        jobs = {j["id"]: j for j in self.store.jobs()}
        self.assertEqual(jobs[first]["state"], "superseded")
        self.assertEqual(jobs[successor]["state"], "pending")
        self.store.release_worker("replacement")

    def test_same_owner_recovers_after_laptop_sleep(self):
        self.store.create_entry("Resume after sleep")
        interrupted = self.claim()
        with self.store.connection(True) as conn:
            conn.execute("UPDATE process_lease SET expires_at=0")
        self.store.renew_worker(self.owner, 120)
        recovered = self.claim()
        self.assertEqual(recovered["id"], interrupted["id"])
        self.assertEqual(recovered["attempts"], 2)

    def test_lost_owner_cannot_renew_after_takeover(self):
        with self.store.connection(True) as conn:
            conn.execute("UPDATE process_lease SET expires_at=0")
        self.store.acquire_worker("replacement", 120)
        with self.assertRaises(RuntimeError):
            self.store.renew_worker(self.owner, 120)
        self.store.release_worker("replacement")

    def test_retry_old_failure_requeues_current_failure(self):
        self.store.create_entry("Java")
        old = self.claim()
        self.store.fail_job(old, self.owner, "failure", 1, 0)
        self.store.publish(self.store.catalog()["classes"] + [FEEDBACK], "test", 1)
        current = self.claim()
        self.store.fail_job(current, self.owner, "failure", 1, 0)
        self.assertEqual(self.store.retry_job(old["id"]), current["id"])
        claimed = self.claim()
        self.assertEqual(claimed["id"], current["id"])
        self.assertEqual(claimed["attempts"], 1)

    def test_long_note_returns_matching_original_passage(self):
        text = "irrelevant prefix " * 600 + "the specialquasar is bright"
        self.store.create_entry(text)
        note = self.store.search("specialquasar", [], 1)[0]
        self.assertIn("specialquasar", note["content"])
        self.assertTrue(note["excerpted"])
        self.assertGreater(note["excerpt_offset"], 0)
        self.assertEqual(note["content"], text[note["excerpt_offset"]:note["excerpt_offset"] + 4000])

    def test_bad_valid_plan_cannot_erase_original_query_terms(self):
        self.store.create_entry("specialquasar is bright")
        model = ScriptedModel({"plan": {"terms": ["bad noise unrelated irrelevant" for _ in range(12)], "class_ids": [], "intent": "off target"}})
        answer = Pipelines(self.store, model).answer("specialquasar")
        self.assertEqual(answer["references"]["notes"][0]["id"], 1)

    def test_composer_receives_entry_clarification(self):
        self.store.create_entry("Java exercise")
        self.store.add_guidance("entry", "1", "This refers to a programming exercise, not coffee.")
        model = ScriptedModel()
        Pipelines(self.store, model).answer("Java")
        context = next(c for step, c in model.contexts if step == "answer")
        self.assertTrue(any(g["scope"] == "entry" for g in context["guidance"]["items"]))

    def test_class_guidance_not_lost_outside_detail_matches(self):
        classes = [{**FEEDBACK, "id": f"a{i:02}", "name": f"Section {i}"} for i in range(13)]
        self.store.publish(self.store.catalog()["classes"] + classes, "many sections", 0)
        self.store.create_entry("Java")
        self.store.complete_organization(self.claim(), self.owner, interpretation("a12"))
        self.store.add_guidance("class", "a12", "These entries concern the feedback project.")
        model = ScriptedModel({"organize": interpretation("a12")})
        pipelines = Pipelines(self.store, model)
        pipelines.organize(self.claim(), self.owner)
        pipelines.answer("Java")
        organize = next(c for step, c in model.contexts if step == "organize")
        answer = next(c for step, c in model.contexts if step == "answer")
        self.assertNotIn("a12", [c["id"] for c in organize["catalog"]["details"]])
        for context in (organize, answer):
            self.assertTrue(any(g["target_id"] == "a12" for g in context["guidance"]["items"]))

    def test_graph_candidates_survive_full_lexical_pool(self):
        for i in range(12):
            self.store.create_entry(f"needle lexical note {i}")
        linked = self.store.create_entry("Related material without the keyword")
        while job := self.claim():
            if job["kind"] == "structure":
                self.store.complete_review(job, self.owner, 13)
            else:
                result = interpretation()
                result["concepts"] = ["Shared topic"]
                self.store.complete_organization(job, self.owner, result)
        notes = self.store.search("needle", [], 1, limit=12)
        self.assertEqual(len(notes), 12)
        self.assertIn(linked["id"], [n["id"] for n in notes])

    def test_rollback_preserves_explicit_inflight_review_intent(self):
        self.store.create_entry("One note below threshold")
        self.store.complete_organization(self.claim(), self.owner, interpretation())
        self.store.queue_structure()
        review = self.claim()
        self.assertEqual(review["kind"], "structure")
        current = Pipelines(self.store, DemoModel()).rollback(1)
        self.store.complete_review(review, self.owner, 1)
        pending = [j for j in self.store.jobs() if j["kind"] == "structure" and j["state"] == "pending"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["version"], current)


class TransportBoundsTests(unittest.TestCase):
    def test_overall_deadline_cancels_slow_stream(self):
        class Slow(httpx.AsyncByteStream):
            closed = False
            async def __aiter__(self):
                for _ in range(100):
                    await asyncio.sleep(0.01)
                    yield b" "
            async def aclose(self):
                self.closed = True
        stream = Slow()
        transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
        real_client = httpx.AsyncClient
        model = CloudModel(Settings(api_key="test", timeout=0.05))
        start = time.monotonic()
        with patch("deepnotes.models.httpx.AsyncClient", side_effect=lambda **kw: real_client(transport=transport, **kw)):
            with self.assertRaisesRegex(ModelUnavailable, "timed out"):
                model.generate("answer", "test", {}, {})
        self.assertLess(time.monotonic() - start, 1)
        self.assertTrue(stream.closed)

    def test_stream_limit_stops_before_reading_rest(self):
        class Large(httpx.AsyncByteStream):
            chunks = 0
            closed = False
            async def __aiter__(self):
                for _ in range(10):
                    self.chunks += 1
                    yield b"x" * 1_000_000
            async def aclose(self):
                self.closed = True
        stream = Large()
        transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
        real_client = httpx.AsyncClient
        model = CloudModel(Settings(api_key="test"))
        with patch("deepnotes.models.httpx.AsyncClient", side_effect=lambda **kw: real_client(transport=transport, **kw)):
            with self.assertRaisesRegex(ModelUnavailable, "size limit"):
                model.generate("answer", "test", {}, {})
        self.assertEqual(stream.chunks, 3)
        self.assertTrue(stream.closed)

    def test_cloud_adapter_accepts_compatible_json_and_tracks_usage(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": [{"message": {"content": '{"answer":"ok"}'}}], "usage": {"total_tokens": 10}}))
        real_client = httpx.AsyncClient
        with patch("deepnotes.models.httpx.AsyncClient", side_effect=lambda **kw: real_client(transport=transport, **kw)):
            raw, usage = CloudModel(Settings(api_key="test")).generate("answer", "test", {}, {})
        self.assertEqual(json.loads(raw)["answer"], "ok")
        self.assertEqual(usage["total_tokens"], 10)
