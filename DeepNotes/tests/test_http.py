"""Real loopback HTTP smoke test with Uvicorn and a deterministic model."""
from contextlib import contextmanager
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

import httpx
import uvicorn
from deepnotes.api import create_app
from deepnotes.config import Settings


@contextmanager
def serve(settings):
    app = create_app(settings)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        if not server.started:
            raise AssertionError("HTTP server failed to start")
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5, trust_env=False) as client:
            yield client, app
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()
        if thread.is_alive():
            raise AssertionError("HTTP server did not shut down")


class NetworkSmokeTests(unittest.TestCase):
    def test_http_capture_context_answer_and_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Settings(db_path=Path(folder) / "http.sqlite3", demo_mode=True, poll_seconds=0.01)
            with serve(settings) as (client, app):
                page = client.get("/")
                self.assertEqual(page.status_code, 200)
                self.assertIn("References & related notes", page.text)
                self.assertIn("frame-ancestors 'none'", page.headers["content-security-policy"])
                saved = client.post("/api/entries", json={"content": "Java learning note"})
                self.assertEqual(saved.status_code, 201)
                eid = saved.json()["id"]
                self.assertEqual(client.post("/api/guidance", json={"scope": "entry", "target_id": str(eid), "content": "This was from a lecture"}).status_code, 201)
                self.assertEqual(client.post("/api/structure/reorganize", json={}).status_code, 200)
                answer = client.post("/api/queries", json={"question": "Java"})
                self.assertEqual(answer.status_code, 200, answer.text)
                self.assertEqual(answer.json()["references"]["notes"][0]["id"], eid)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if client.get("/api/entries").json()["items"][0]["status"] == "completed":
                        break
                    threading.Event().wait(0.02)
                else:
                    self.fail("Worker did not complete")
            self.assertFalse(app.state.worker.running)
            with serve(settings) as (client, _):
                self.assertEqual(client.get("/api/entries").json()["items"][0]["id"], eid)
                self.assertEqual(len(client.get("/api/interactions").json()["items"]), 1)
                self.assertEqual(client.get("/api/status").json()["jobs"]["failed"], 0)
