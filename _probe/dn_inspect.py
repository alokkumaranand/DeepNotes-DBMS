import sqlite3, sys
db = sys.argv[1]
c = sqlite3.connect(db)
c.row_factory = sqlite3.Row
names = [r[0] for r in c.execute("select name from sqlite_master where type='table' order by name")]
print("TABLES:")
for n in names:
    try:
        k = c.execute('select count(*) from "%s"' % n).fetchone()[0]
    except Exception as e:
        k = "ERR %s" % e
    print("  %-28s %s" % (n, k))

print("\nENTRIES:")
try:
    for r in c.execute("select id, substr(content,1,70) t, source_title, status, created_at from entries order by id desc limit 15"):
        print("  ", dict(r))
except Exception as e:
    print("  ", e)

print("\nCLASSES:")
try:
    for r in c.execute("select id, name, substr(description,1,60) d from catalog_classes limit 40"):
        print("  ", dict(r))
except Exception as e:
    print("  ", e)

print("\nJOBS:")
try:
    for r in c.execute("select id, kind, status, attempts, substr(coalesce(last_error,''),1,80) e from jobs order by id desc limit 20"):
        print("  ", dict(r))
except Exception as e:
    print("  ", e)
