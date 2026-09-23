"""SQLite repository. Write transactions never contain model/network calls."""
from contextlib import closing, contextmanager
import hashlib
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path

from .schema import SCHEMA


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def fts_query(text):
    # Quote tokens so input is data, never FTS syntax. Empty searches are allowed.
    words = list(dict.fromkeys(re.findall(r"[^\W_]+", text.lower(), re.UNICODE)))[:24]
    return " OR ".join('"' + word + '"' for word in words if len(word) > 1)


def source_excerpt(content, query, budget=4000):
    """Select a bounded ORIGINAL passage near matches, never a generated summary."""
    if len(content) <= budget:
        return content, 0
    terms = re.findall(r"[^\W_]+", query.casefold(), re.UNICODE)[:24]
    folded = content.casefold()
    starts = {0}
    for term in terms:
        if len(term) > 2:
            index = folded.find(term)
            if index >= 0:
                starts.add(max(0, min(len(content) - budget, index - budget // 3)))
    start = max(starts, key=lambda pos: (sum(term in folded[pos:pos + budget] for term in set(terms) if len(term) > 2), pos))
    return content[start:start + budget], start


class Store:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connection(self, write=False):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError("Unsupported database version; do not downgrade this database")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.execute("PRAGMA user_version=1")
        with self.connection(True) as conn:
            if not conn.execute("SELECT 1 FROM settings WHERE key='active_version'").fetchone():
                conn.execute("INSERT INTO structures(id,created_at,reason) VALUES(1,?,'Initial structure')", (time.time(),))
                self._put_class(conn, 1, {"id": "unclassified", "name": "Unclassified", "description": "Material not yet assigned to a useful section.", "aliases": [], "parent_id": None, "routing_hints": "Use when existing sections do not fit."})
                conn.execute("INSERT INTO settings VALUES('active_version','1')")
                conn.execute("INSERT INTO settings VALUES('review_high_water','0')")

    @staticmethod
    def _active(conn):
        return int(conn.execute("SELECT value FROM settings WHERE key='active_version'").fetchone()[0])

    def active_version(self):
        with self.connection() as conn:
            return self._active(conn)

    @staticmethod
    def _put_class(conn, version, item):
        conn.execute("INSERT INTO classes VALUES(?,?,?,?)", (version, item["id"], item["name"], dump(item)))
        text = " ".join([item["name"], item["description"], " ".join(item.get("aliases", [])), item.get("routing_hints", "")])
        conn.execute("INSERT INTO catalog_search VALUES(?,?,?)", (version, item["id"], text))

    @staticmethod
    def _enqueue_entry(conn, entry_id, version, revision):
        now = time.time()
        conn.execute("INSERT OR IGNORE INTO jobs(kind,entry_id,version,revision,available_at,created_at,updated_at) VALUES('organize',?,?,?,?,?,?)", (entry_id, version, revision, now, now, now))
        return conn.execute("SELECT id FROM jobs WHERE kind='organize' AND entry_id=? AND version=? AND revision=?", (entry_id, version, revision)).fetchone()[0]

    @staticmethod
    def _enqueue_structure(conn, version):
        pending = conn.execute("SELECT id FROM jobs WHERE kind='structure' AND state='pending'").fetchone()
        if pending:
            return pending[0]
        now = time.time()
        return conn.execute("INSERT INTO jobs(kind,version,available_at,created_at,updated_at) VALUES('structure',?,?,?,?)", (version, now, now, now)).lastrowid

    @staticmethod
    def _auto_structure(conn):
        count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        reviewed = int(conn.execute("SELECT value FROM settings WHERE key='review_high_water'").fetchone()[0])
        threshold = max(4, 1 << max(0, reviewed.bit_length()))
        if count >= threshold or count - reviewed >= 32:
            Store._enqueue_structure(conn, Store._active(conn))

    def create_entry(self, content, source_url="", source_title="", now=None):
        now = time.time() if now is None else now
        with self.connection(True) as conn:
            previous = conn.execute("SELECT session_id,created_at FROM entries ORDER BY id DESC LIMIT 1").fetchone()
            session = previous["session_id"] if previous and 0 <= now - previous["created_at"] < 1800 else str(uuid.uuid4())
            eid = conn.execute("INSERT INTO entries(content,source_url,source_title,created_at,session_id) VALUES(?,?,?,?,?)", (content, source_url, source_title, now, session)).lastrowid
            conn.execute("INSERT INTO entry_search VALUES(?,?,?)", (self._active(conn), eid, content + " " + source_title))
            self._enqueue_entry(conn, eid, self._active(conn), 1)
            self._auto_structure(conn)
        return self.get_entry(eid)

    def get_entry(self, entry_id):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
            if not row:
                raise KeyError("Entry not found")
            return self._entry_view(conn, row, self._active(conn))

    @staticmethod
    def _entry_view(conn, row, version):
        item = dict(row)
        result = conn.execute("SELECT * FROM interpretations WHERE entry_id=? AND version=?", (row["id"], version)).fetchone()
        item["interpretation"] = None
        if result:
            item["interpretation"] = {**json.loads(result["payload"]), "inherited": bool(result["inherited"]), "origin_version": result["origin_version"]}
        job = conn.execute("SELECT state FROM jobs WHERE entry_id=? AND version=? AND revision=?", (row["id"], version, row["revision"])).fetchone()
        item["status"] = job[0] if job else ("completed" if result else "pending")
        return item

    def entries(self, limit=30, offset=0):
        with self.connection() as conn:
            version = self._active(conn)
            return [self._entry_view(conn, row, version) for row in conn.execute("SELECT * FROM entries ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))]

    def add_guidance(self, scope, target_id, content):
        with self.connection(True) as conn:
            version = self._active(conn)
            if scope == "entry":
                if not conn.execute("SELECT 1 FROM entries WHERE id=?", (target_id,)).fetchone():
                    raise KeyError("Entry not found")
                ids = [int(target_id)]
            elif scope == "class":
                if not conn.execute("SELECT 1 FROM classes WHERE version=? AND id=?", (version, target_id)).fetchone():
                    raise KeyError("Class not found in active structure")
                ids = [r[0] for r in conn.execute("SELECT entry_id FROM assignments WHERE version=? AND class_id=?", (version, target_id))]
            else:
                ids = [r[0] for r in conn.execute("SELECT id FROM entries")]
            gid = conn.execute("INSERT INTO guidance(scope,target_id,content,created_at) VALUES(?,?,?,?)", (scope, target_id, content, time.time())).lastrowid
            for eid in ids:
                conn.execute("UPDATE entries SET revision=revision+1 WHERE id=?", (eid,))
                revision = conn.execute("SELECT revision FROM entries WHERE id=?", (eid,)).fetchone()[0]
                conn.execute("UPDATE jobs SET state='superseded' WHERE entry_id=? AND state IN ('pending','running')", (eid,))
                self._enqueue_entry(conn, eid, version, revision)
            # Even entry-only clarification can inform a future class definition,
            # without turning that clarification into globally applicable guidance.
            self._enqueue_structure(conn, version)
            return gid

    def guidance(self, limit=100):
        with self.connection() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM guidance ORDER BY id DESC LIMIT ?", (limit,))]

    def applicable_guidance(self, entry_id=None, class_ids=(), entry_ids=()):
        with self.connection() as conn:
            placeholders = ",".join("?" for _ in class_ids) or "NULL"
            entries = [str(eid) for eid in entry_ids] + ([str(entry_id)] if entry_id is not None else [])
            entry_slots = ",".join("?" for _ in entries) or "NULL"
            rows = conn.execute(f"SELECT * FROM guidance WHERE scope='global' OR (scope='entry' AND target_id IN ({entry_slots})) OR (scope='class' AND target_id IN ({placeholders})) ORDER BY id DESC LIMIT 101", (*entries, *class_ids)).fetchall()
            selected, used = [], 0
            for row in rows:
                if used + len(row["content"]) > 12000 or len(selected) >= 20:
                    break
                selected.append(dict(row))
                used += len(row["content"])
            return {"items": selected, "truncated": len(selected) < len(rows)}

    def catalog(self, version=None):
        with self.connection() as conn:
            version = version or self._active(conn)
            classes = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM classes WHERE version=? ORDER BY id", (version,))]
            if not classes:
                raise KeyError("Structure version not found")
            versions = [dict(r) for r in conn.execute("SELECT * FROM structures ORDER BY id DESC LIMIT 100")]
            return {"version": version, "classes": classes, "versions": versions}

    def catalog_context(self, text, version):
        catalog = self.catalog(version)["classes"]
        terms = fts_query(text)
        ids = []
        if terms:
            with self.connection() as conn:
                ids = [r[0] for r in conn.execute("SELECT class_id FROM catalog_search WHERE catalog_search MATCH ? AND version=? ORDER BY rank LIMIT 12", (terms, version))]
        if not ids:
            ids = [item["id"] for item in catalog[:12]]
        return {"version": version,
                "overview": [{"id": c["id"], "name": c["name"], "parent_id": c.get("parent_id"), "description": c["description"][:160]} for c in catalog],
                "details": [c for c in catalog if c["id"] in ids]}

    def assigned_classes(self, entry_ids, version):
        if not entry_ids:
            return []
        slots = ",".join("?" for _ in entry_ids)
        with self.connection() as conn:
            return [r[0] for r in conn.execute(f"SELECT DISTINCT class_id FROM assignments WHERE version=? AND entry_id IN ({slots})", (version, *entry_ids))]

    def entry_context(self, entry_id):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
            if not row:
                raise KeyError("Entry not found")
            neighbors = [dict(r) for r in conn.execute("SELECT * FROM entries WHERE session_id=? AND id<? ORDER BY id DESC LIMIT 3", (row["session_id"], entry_id))]
            for neighbor in neighbors:
                neighbor["content"] = neighbor["content"][:3000]
            return {"current": dict(row), "preceding_context_only": list(reversed(neighbors))}

    def structure_sample(self, version=None):
        with self.connection() as conn:
            version = version or self._active(conn)
            recent = conn.execute("SELECT * FROM entries ORDER BY id DESC LIMIT 16").fetchall()
            unclassified = conn.execute("SELECT e.* FROM entries e WHERE NOT EXISTS(SELECT 1 FROM assignments a WHERE a.version=? AND a.entry_id=e.id AND a.class_id!='unclassified') ORDER BY e.id LIMIT 16", (version,)).fetchall()
            reviewed = int(conn.execute("SELECT value FROM settings WHERE key='review_high_water'").fetchone()[0])
            count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            # Rotate older samples deterministically between reviews; no RANDOM() full sort.
            older = conn.execute("SELECT * FROM entries ORDER BY id LIMIT 8 OFFSET ?", (reviewed % max(count, 1),)).fetchall()
            notes = {r["id"]: {**dict(r), "content": r["content"][:2000]} for r in [*recent, *unclassified, *older]}
            selected = list(notes.values())[:40]
            for note in selected:
                row = conn.execute("SELECT payload FROM interpretations WHERE version=? AND entry_id=?", (version, note["id"])).fetchone()
                if row:
                    derived = json.loads(row[0])
                    note["interpretation"] = {"summary": derived["summary"][:600], "intent": derived["intent"], "class_ids": derived["class_ids"]}
            counts = {r[0]: r[1] for r in conn.execute("SELECT class_id,COUNT(*) FROM assignments WHERE version=? GROUP BY class_id", (version,))}
            return {"entries": selected, "class_counts": counts, "high_water": count, "sampled": len(selected) < count, "version": version}

    def queue_structure(self):
        with self.connection(True) as conn:
            return self._enqueue_structure(conn, self._active(conn))

    def acquire_worker(self, owner, lease_seconds):
        now = time.time()
        with self.connection(True) as conn:
            lock = conn.execute("SELECT * FROM process_lease WHERE id=1").fetchone()
            if lock and lock["expires_at"] > now and lock["owner"] != owner:
                raise RuntimeError("Another DeepNotes worker owns this database; run one API process")
            conn.execute("INSERT OR REPLACE INTO process_lease VALUES(1,?,?)", (owner, now + lease_seconds))
            self._recover_jobs(conn, now)
            conn.execute("UPDATE interactions SET status='failed',error='Interrupted query; please ask again' WHERE status='running'")

    @staticmethod
    def _recover_jobs(conn, now):
        if conn.execute("SELECT 1 FROM jobs WHERE kind='structure' AND state='pending'").fetchone():
            conn.execute("UPDATE jobs SET state='superseded',error='Interrupted review replaced by queued successor' WHERE kind='structure' AND state='running'")
        conn.execute("UPDATE jobs SET state='pending',owner=NULL,available_at=?,error='Interrupted attempt recovered' WHERE state='running'", (now,))

    def renew_worker(self, owner, lease_seconds):
        with self.connection(True) as conn:
            lock = conn.execute("SELECT * FROM process_lease WHERE id=1 AND owner=?", (owner,)).fetchone()
            if not lock:
                raise RuntimeError("Worker lease lost")
            now = time.time()
            if lock["expires_at"] <= now:
                # Laptop sleep can expire our lease without another process taking it.
                # Recover only while ownership is still ours under the write lock.
                self._recover_jobs(conn, now)
            conn.execute("UPDATE process_lease SET expires_at=? WHERE id=1 AND owner=?", (now + lease_seconds, owner))

    def release_worker(self, owner):
        with self.connection(True) as conn:
            conn.execute("DELETE FROM process_lease WHERE owner=?", (owner,))

    @staticmethod
    def _owns(conn, job, owner):
        return bool(conn.execute("SELECT 1 FROM jobs j JOIN process_lease l ON l.id=1 WHERE j.id=? AND j.state='running' AND j.owner=? AND l.owner=? AND l.expires_at>?", (job["id"], owner, owner, time.time())).fetchone())

    def claim_job(self, owner, max_attempts):
        with self.connection(True) as conn:
            if not conn.execute("SELECT 1 FROM process_lease WHERE owner=? AND expires_at>?", (owner, time.time())).fetchone():
                raise RuntimeError("Worker lease lost")
            conn.execute("UPDATE jobs SET state='failed',error='Attempt limit reached after interruption' WHERE state='pending' AND attempts>=?", (max_attempts,))
            row = conn.execute("SELECT * FROM jobs WHERE state='pending' AND available_at<=? ORDER BY id LIMIT 1", (time.time(),)).fetchone()
            if not row:
                return None
            # A coalesced structure request always reviews the newest published version.
            version = self._active(conn) if row["kind"] == "structure" else row["version"]
            conn.execute("UPDATE jobs SET state='running',owner=?,attempts=attempts+1,version=?,updated_at=? WHERE id=?", (owner, version, time.time(), row["id"]))
            return dict(conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())

    def fail_job(self, job, owner, error, max_attempts, retry_seconds):
        with self.connection(True) as conn:
            if not self._owns(conn, job, owner):
                return
            state = "failed" if job["attempts"] >= max_attempts else "pending"
            # Coalesce a failed structure retry if a follow-up request already exists.
            if job["kind"] == "structure" and state == "pending" and conn.execute("SELECT 1 FROM jobs WHERE kind='structure' AND state='pending'").fetchone():
                state = "superseded"
            conn.execute("UPDATE jobs SET state=?,error=?,available_at=?,updated_at=? WHERE id=?", (state, error, time.time() + retry_seconds * 2 ** (job["attempts"] - 1), time.time(), job["id"]))

    def retry_job(self, job_id):
        with self.connection(True) as conn:
            job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                raise KeyError("Job not found")
            if job["state"] != "failed":
                raise ValueError("Only failed jobs may be retried")
            active = self._active(conn)
            if job["kind"] == "structure":
                conn.execute("UPDATE jobs SET state='superseded' WHERE id=?", (job_id,))
                return self._enqueue_structure(conn, active)
            revision = conn.execute("SELECT revision FROM entries WHERE id=?", (job["entry_id"],)).fetchone()[0]
            if job["version"] != active or job["revision"] != revision:
                conn.execute("UPDATE jobs SET state='superseded' WHERE id=?", (job_id,))
                current_id = self._enqueue_entry(conn, job["entry_id"], active, revision)
                conn.execute("UPDATE jobs SET state='pending',attempts=0,error=NULL,available_at=? WHERE id=? AND state='failed'", (time.time(), current_id))
                return current_id
            conn.execute("UPDATE jobs SET state='pending',attempts=0,error=NULL,available_at=? WHERE id=?", (time.time(), job_id))
            return job_id

    def record_run(self, step, status, model, payload, job_id=None, interaction_id=None):
        with self.connection(True) as conn:
            conn.execute("INSERT INTO runs(job_id,interaction_id,step,status,model,payload,created_at) VALUES(?,?,?,?,?,?,?)", (job_id, interaction_id, step, status, model, dump(payload), time.time()))

    @staticmethod
    def _concept_id(scope, name):
        return hashlib.sha256((scope + ":" + name.casefold().strip()).encode()).hexdigest()[:32]

    def complete_organization(self, job, owner, result):
        with self.connection(True) as conn:
            if not self._owns(conn, job, owner):
                return False
            entry = conn.execute("SELECT * FROM entries WHERE id=?", (job["entry_id"],)).fetchone()
            if self._active(conn) != job["version"] or entry["revision"] != job["revision"]:
                conn.execute("UPDATE jobs SET state='superseded' WHERE id=?", (job["id"],))
                self._enqueue_entry(conn, entry["id"], self._active(conn), entry["revision"])
                return False
            version, eid = job["version"], entry["id"]
            conn.execute("INSERT OR REPLACE INTO interpretations VALUES(?,?,?,?,?,0)", (version, eid, entry["revision"], dump(result), version))
            for table in ("assignments", "mentions", "relations"):
                conn.execute(f"DELETE FROM {table} WHERE version=? AND entry_id=?", (version, eid))
            for cid in result["class_ids"]:
                conn.execute("INSERT OR IGNORE INTO assignments VALUES(?,?,?)", (version, eid, cid))
            scope = sorted(result["class_ids"])[0]
            keys = {}
            for name in result["concepts"]:
                key = self._concept_id(scope, name)
                keys[name] = key
                conn.execute("INSERT OR IGNORE INTO concepts VALUES(?,?,?)", (key, name, scope))
                conn.execute("INSERT OR IGNORE INTO mentions VALUES(?,?,?)", (version, eid, key))
            for rel in result["relations"]:
                conn.execute("INSERT OR REPLACE INTO relations VALUES(?,?,?,?,?,?,?)", (version, eid, keys[rel["source"]], keys[rel["target"]], rel["relation"], dump(rel["evidence"]), int(rel["inferred"])))
            conn.execute("DELETE FROM entry_search WHERE version=? AND entry_id=?", (version, eid))
            conn.execute("INSERT INTO entry_search VALUES(?,?,?)", (version, eid, " ".join([entry["content"], entry["source_title"], result["summary"], result["intent"], " ".join(result["concepts"])])))
            conn.execute("UPDATE jobs SET state='completed',error=NULL,updated_at=? WHERE id=?", (time.time(), job["id"]))
            return True

    def publish(self, classes, reason, high_water, job=None, owner=None, restore_from=None):
        with self.connection(True) as conn:
            old = self._active(conn)
            if job and (not self._owns(conn, job, owner) or old != job["version"]):
                if self._owns(conn, job, owner):
                    conn.execute("UPDATE jobs SET state='superseded' WHERE id=?", (job["id"],))
                return None
            outstanding_review = conn.execute("SELECT 1 FROM jobs WHERE kind='structure' AND state='running' AND id!=?", (job["id"] if job else -1,)).fetchone()
            if outstanding_review:
                conn.execute("UPDATE jobs SET state='superseded',error='Review replaced after structure transition' WHERE kind='structure' AND state='running' AND id!=?", (job["id"] if job else -1,))
            source = restore_from or old
            old_classes = {r["id"]: json.loads(r["payload"]) for r in conn.execute("SELECT * FROM classes WHERE version=?", (old,))}
            new_classes = {c["id"]: c for c in classes}
            changed = {cid for cid in old_classes.keys() | new_classes.keys() if old_classes.get(cid) != new_classes.get(cid)}
            version = conn.execute("INSERT INTO structures(created_at,reason,based_on,high_water) VALUES(?,?,?,?)", (time.time(), reason, old, high_water)).lastrowid
            for item in classes:
                self._put_class(conn, version, item)
            conn.execute("INSERT INTO interpretations SELECT ?,entry_id,revision,payload,origin_version,inherited FROM interpretations WHERE version=?", (version, source))
            conn.execute("INSERT INTO assignments SELECT ?,a.entry_id,a.class_id FROM assignments a JOIN classes c ON c.version=? AND c.id=a.class_id WHERE a.version=?", (version, version, source))
            for table, columns in (("mentions", "entry_id,concept_id"), ("relations", "entry_id,source,target,relation,evidence,inferred")):
                conn.execute(f"INSERT INTO {table} SELECT ?,{columns} FROM {table} WHERE version=?", (version, source))
            affected = set()
            if restore_from or new_classes.keys() - old_classes.keys():
                affected = {r[0] for r in conn.execute("SELECT id FROM entries")}
            else:
                for cid in changed | {"unclassified"}:
                    affected.update(r[0] for r in conn.execute("SELECT entry_id FROM assignments WHERE version=? AND class_id=?", (old, cid)))
                affected.update(r[0] for r in conn.execute("SELECT id FROM entries WHERE id NOT IN (SELECT entry_id FROM interpretations WHERE version=?)", (version,)))
                affected.update(r[0] for r in conn.execute("SELECT entry_id FROM jobs WHERE kind='organize' AND state IN ('pending','running','failed')"))
            # Removed class references in inherited payloads are normalized immediately.
            for row in conn.execute("SELECT entry_id,payload FROM interpretations WHERE version=?", (version,)).fetchall():
                payload = json.loads(row["payload"])
                payload["class_ids"] = [cid for cid in payload["class_ids"] if cid in new_classes] or ["unclassified"]
                conn.execute("UPDATE interpretations SET payload=? WHERE version=? AND entry_id=?", (dump(payload), version, row["entry_id"]))
                for cid in payload["class_ids"]:
                    conn.execute("INSERT OR IGNORE INTO assignments VALUES(?,?,?)", (version, row["entry_id"], cid))
            conn.execute("UPDATE settings SET value=? WHERE key='active_version'", (str(version),))
            if outstanding_review:
                self._enqueue_structure(conn, version)
            if not restore_from:
                conn.execute("UPDATE settings SET value=? WHERE key='review_high_water'", (str(high_water),))
            conn.execute("UPDATE jobs SET state='superseded' WHERE kind='organize' AND state IN ('pending','running')")
            for eid in affected:
                revision = conn.execute("SELECT revision FROM entries WHERE id=?", (eid,)).fetchone()[0]
                conn.execute("UPDATE interpretations SET inherited=1 WHERE version=? AND entry_id=?", (version, eid))
                self._enqueue_entry(conn, eid, version, revision)
            # Search projection follows the active interpretation, including after rollback.
            conn.execute("INSERT INTO entry_search SELECT ?,e.id,e.content || ' ' || e.source_title || ' ' || COALESCE(i.payload,'') FROM entries e LEFT JOIN interpretations i ON i.entry_id=e.id AND i.version=?", (version, version))
            if job:
                conn.execute("UPDATE jobs SET state='completed',error=NULL,updated_at=? WHERE id=?", (time.time(), job["id"]))
            self._auto_structure(conn)
            return version

    def complete_review(self, job, owner, high_water):
        with self.connection(True) as conn:
            if not self._owns(conn, job, owner):
                return
            if self._active(conn) != job["version"]:
                conn.execute("UPDATE jobs SET state='superseded' WHERE id=?", (job["id"],))
                return
            conn.execute("UPDATE settings SET value=? WHERE key='review_high_water'", (str(high_water),))
            conn.execute("UPDATE jobs SET state='completed',error=NULL WHERE id=?", (job["id"],))
            self._auto_structure(conn)

    def search(self, text, class_ids, version, limit=12):
        terms = fts_query(text)
        with self.connection() as conn:
            lexical, classified, graph = [], [], []
            if terms:
                lexical = [r[0] for r in conn.execute("SELECT entry_id FROM entry_search WHERE entry_search MATCH ? AND version=? ORDER BY rank LIMIT ?", (terms, version, limit))]
            for cid in class_ids:
                classified.extend(r[0] for r in conn.execute("SELECT entry_id FROM assignments WHERE version=? AND class_id=? ORDER BY entry_id DESC LIMIT 6", (version, cid)))
            seed_ids = list(dict.fromkeys(lexical + classified))[:24]
            if seed_ids:
                slots = ",".join("?" for _ in seed_ids)
                graph = [r[0] for r in conn.execute(f"""WITH seed_concepts AS (
                    SELECT concept_id FROM mentions WHERE version=? AND entry_id IN ({slots})
                ), expanded AS (
                    SELECT concept_id FROM seed_concepts
                    UNION SELECT r.target FROM relations r JOIN seed_concepts s ON s.concept_id=r.source WHERE r.version=?
                    UNION SELECT r.source FROM relations r JOIN seed_concepts s ON s.concept_id=r.target WHERE r.version=?
                ) SELECT DISTINCT m.entry_id FROM mentions m JOIN expanded x ON x.concept_id=m.concept_id
                  WHERE m.version=? AND m.entry_id NOT IN ({slots}) ORDER BY m.entry_id DESC LIMIT 6""",
                    (version, *seed_ids, version, version, version, *seed_ids))]
            # Reserve candidate slots so a full lexical pool cannot starve graph routing.
            class_extra = [eid for eid in dict.fromkeys(classified) if eid not in lexical][:max(1, limit // 4)]
            graph_extra = [eid for eid in graph if eid not in class_extra][:max(1, limit // 4)]
            primary = lexical[:max(1, limit - len(class_extra) - len(graph_extra))]
            selected = list(dict.fromkeys(primary + class_extra + graph_extra + lexical + classified + graph))[:limit]
            notes = []
            for eid in selected:
                row = conn.execute("SELECT * FROM entries WHERE id=?", (eid,)).fetchone()
                if row:
                    # Bounded excerpts; references preserve exactly what the answer saw.
                    item = dict(row)
                    item["content"], item["excerpt_offset"] = source_excerpt(item["content"], text)
                    item["excerpted"] = len(item["content"]) < len(row["content"])
                    notes.append(item)
            return notes

    def begin_interaction(self, question):
        with self.connection(True) as conn:
            version = self._active(conn)
            iid = conn.execute("INSERT INTO interactions(question,created_at,version) VALUES(?,?,?)", (question, time.time(), version)).lastrowid
            conn.execute("INSERT INTO interaction_search VALUES(?,?)", (iid, question))
            return iid, version

    def finish_interaction(self, iid, answer, references, metadata):
        with self.connection(True) as conn:
            conn.execute("UPDATE interactions SET status='completed',answer=?,reference_data=?,metadata=? WHERE id=?", (answer, dump(references), dump(metadata), iid))
            question = conn.execute("SELECT question FROM interactions WHERE id=?", (iid,)).fetchone()[0]
            conn.execute("DELETE FROM interaction_search WHERE interaction_id=?", (iid,))
            conn.execute("INSERT INTO interaction_search VALUES(?,?)", (iid, question + " " + answer))

    def fail_interaction(self, iid, error):
        with self.connection(True) as conn:
            conn.execute("UPDATE interactions SET status='failed',error=? WHERE id=?", (error, iid))

    def interactions(self, query="", limit=20):
        with self.connection() as conn:
            terms = fts_query(query)
            if terms:
                rows = conn.execute("SELECT i.* FROM interaction_search s JOIN interactions i ON i.id=s.interaction_id WHERE interaction_search MATCH ? ORDER BY i.id DESC LIMIT ?", (terms, limit))
            else:
                rows = conn.execute("SELECT * FROM interactions ORDER BY id DESC LIMIT ?", (limit,))
            items = []
            for row in rows:
                item = dict(row)
                item["references"] = json.loads(item.pop("reference_data") or "null")
                item["metadata"] = json.loads(item["metadata"] or "null")
                items.append(item)
            return items

    def jobs(self, limit=30):
        with self.connection() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))]

    def status(self):
        with self.connection() as conn:
            counts = {key: 0 for key in ("pending", "running", "completed", "failed", "superseded")}
            counts.update({r[0]: r[1] for r in conn.execute("SELECT state,COUNT(*) FROM jobs GROUP BY state")})
            return {"jobs": counts, "active_version": self._active(conn)}
