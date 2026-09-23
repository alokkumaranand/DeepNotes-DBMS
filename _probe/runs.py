import sqlite3, sys, json
db = sys.argv[1]
job = int(sys.argv[2]) if len(sys.argv) > 2 else None
c = sqlite3.connect('file:%s?mode=ro' % db, uri=True)
c.row_factory = sqlite3.Row
sql = "select id,job_id,interaction_id,step,status,model,payload,created_at from runs"
args = ()
if job:
    sql += " where job_id=?"
    args = (job,)
sql += " order by id desc limit 12"
for r in c.execute(sql, args):
    d = dict(r)
    try:
        p = json.loads(d.pop('payload'))
    except Exception:
        p = d.pop('payload')
    print('=' * 90)
    print('run', d)
    if isinstance(p, dict):
        if 'error' in p:
            print('  ERROR:', p['error'])
        if p.get('raw_output'):
            print('  RAW OUTPUT (first 1500):')
            print('   ', p['raw_output'][:1500].replace('\n', '\n    '))
        if 'output' in p:
            print('  OUTPUT:', json.dumps(p['output'])[:600])
