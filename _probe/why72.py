import sqlite3, sys, json
db = sys.argv[1]
job = int(sys.argv[2])
c = sqlite3.connect('file:%s?mode=ro' % db, uri=True)
c.row_factory = sqlite3.Row
row = c.execute("select payload from runs where job_id=? and step='organize' order by id desc limit 1", (job,)).fetchone()
p = json.loads(row['payload'])
raw = p.get('raw_output') or ''
print('RAW LENGTH:', len(raw))
print('TAIL 300:', repr(raw[-300:]))
print('PARSE:', end=' ')
try:
    obj = json.loads(raw)
    print('valid JSON; keys =', list(obj.keys()))
    print('  class_ids:', obj.get('class_ids'))
    print('  concepts :', obj.get('concepts'))
    print('  relations:', len(obj.get('relations') or []))
except Exception as e:
    print('INVALID JSON ->', e)

print('\n--- re-validate against the app contracts ---')
sys.path.insert(0, r'C:\My library\MyProjects\DeepNotesDBMS\DeepNotes')
try:
    from deepnotes.contracts import Interpretation
    Interpretation.model_validate_json(raw)
    print('Interpretation contract: OK')
except Exception as e:
    print('Interpretation contract FAILED:', type(e).__name__, str(e)[:1500])

# Now simulate the pipeline's evidence check for this entry.
ent = c.execute("select id,content from entries where id=2").fetchone()
content = ent['content']
try:
    obj = json.loads(raw)
except Exception:
    obj = {}
print('\n--- evidence substring check against entry 2 ---')
for rel in (obj.get('relations') or []):
    for ev in (rel.get('evidence') or []):
        ok = ev.get('excerpt') in content
        print('  entry_id=%r in_sources=%s  excerpt_ok=%s  %r' % (
            ev.get('entry_id'), ev.get('entry_id') in (1, 2), ok, ev.get('excerpt')[:90]))
