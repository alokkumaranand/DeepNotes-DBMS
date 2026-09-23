"""Schema version 1. Fresh application DB only; no implicit prototype import."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS structures(
 id INTEGER PRIMARY KEY, created_at REAL NOT NULL, reason TEXT NOT NULL,
 based_on INTEGER REFERENCES structures(id), high_water INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS classes(
 version INTEGER NOT NULL REFERENCES structures(id), id TEXT NOT NULL,
 name TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(version,id));
CREATE VIRTUAL TABLE IF NOT EXISTS catalog_search USING fts5(version UNINDEXED, class_id UNINDEXED, text);
CREATE TABLE IF NOT EXISTS entries(
 id INTEGER PRIMARY KEY, content TEXT NOT NULL, source_url TEXT NOT NULL DEFAULT '',
 source_title TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, session_id TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS entries_session ON entries(session_id,id);
CREATE TABLE IF NOT EXISTS guidance(
 id INTEGER PRIMARY KEY, scope TEXT NOT NULL CHECK(scope IN ('entry','class','global')),
 target_id TEXT, content TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS guidance_scope ON guidance(scope,target_id,id);
CREATE TABLE IF NOT EXISTS jobs(
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('organize','structure')),
 entry_id INTEGER REFERENCES entries(id), version INTEGER NOT NULL REFERENCES structures(id),
 revision INTEGER, state TEXT NOT NULL DEFAULT 'pending'
 CHECK(state IN ('pending','running','completed','failed','superseded')),
 attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL,
 owner TEXT, error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(state,available_at,id);
CREATE UNIQUE INDEX IF NOT EXISTS organize_job_unique ON jobs(entry_id,version,revision) WHERE kind='organize';
CREATE UNIQUE INDEX IF NOT EXISTS one_structure_job ON jobs(kind) WHERE kind='structure' AND state='pending';
CREATE TABLE IF NOT EXISTS process_lease(id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS runs(
 id INTEGER PRIMARY KEY, job_id INTEGER REFERENCES jobs(id), interaction_id INTEGER,
 step TEXT NOT NULL, status TEXT NOT NULL, model TEXT NOT NULL,
 payload TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS interpretations(
 version INTEGER NOT NULL REFERENCES structures(id), entry_id INTEGER NOT NULL REFERENCES entries(id),
 revision INTEGER NOT NULL, payload TEXT NOT NULL, origin_version INTEGER NOT NULL,
 inherited INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(version,entry_id));
CREATE TABLE IF NOT EXISTS assignments(
 version INTEGER NOT NULL, entry_id INTEGER NOT NULL REFERENCES entries(id), class_id TEXT NOT NULL,
 PRIMARY KEY(version,entry_id,class_id), FOREIGN KEY(version,class_id) REFERENCES classes(version,id));
CREATE INDEX IF NOT EXISTS assignments_class ON assignments(version,class_id,entry_id);
CREATE VIRTUAL TABLE IF NOT EXISTS entry_search USING fts5(version UNINDEXED, entry_id UNINDEXED, text);
CREATE TABLE IF NOT EXISTS concepts(id TEXT PRIMARY KEY, name TEXT NOT NULL, class_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mentions(
 version INTEGER NOT NULL REFERENCES structures(id), entry_id INTEGER NOT NULL REFERENCES entries(id),
 concept_id TEXT NOT NULL REFERENCES concepts(id), PRIMARY KEY(version,entry_id,concept_id));
CREATE INDEX IF NOT EXISTS mentions_concept ON mentions(version,concept_id,entry_id);
CREATE TABLE IF NOT EXISTS relations(
 version INTEGER NOT NULL REFERENCES structures(id), entry_id INTEGER NOT NULL REFERENCES entries(id),
 source TEXT NOT NULL REFERENCES concepts(id), target TEXT NOT NULL REFERENCES concepts(id),
 relation TEXT NOT NULL, evidence TEXT NOT NULL, inferred INTEGER NOT NULL,
 PRIMARY KEY(version,entry_id,source,target,relation));
CREATE TABLE IF NOT EXISTS interactions(
 id INTEGER PRIMARY KEY, question TEXT NOT NULL, created_at REAL NOT NULL,
 version INTEGER NOT NULL REFERENCES structures(id), status TEXT NOT NULL DEFAULT 'running',
 answer TEXT, reference_data TEXT, metadata TEXT, error TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS interaction_search USING fts5(interaction_id UNINDEXED, text);
"""
