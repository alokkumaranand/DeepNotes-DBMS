import sqlite3, sys, json
db = sys.argv[1] if len(sys.argv) > 1 else 'data/deepnotes.sqlite3'
c = sqlite3.connect(db); c.row_factory = sqlite3.Row

def dump(title, sql):
    print('--- %s ---' % title)
    try:
        for r in c.execute(sql):
            print(json.dumps(dict(r), ensure_ascii=False)[:600])
    except Exception as e:
        print('  ERR', e)

dump('entries', 'select id,source_title,source_url,created_at,substr(content,1,300) content from entries order by id')
dump('structures', 'select * from structures order by id')
dump('classes', 'select version,id,name,substr(payload,1,300) payload from classes order by version,id')
dump('jobs', 'select id,kind,entry_id,version,state,attempts,substr(coalesce(error,""),1,200) error from jobs order by id')
dump('interactions', 'select id,question,status,substr(coalesce(answer,""),1,300) answer from interactions order by id')
dump('guidance', 'select * from guidance order by id')
dump('settings', 'select * from settings')
dump('process_lease', 'select * from process_lease')
