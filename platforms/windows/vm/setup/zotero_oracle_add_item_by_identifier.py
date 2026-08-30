import os, glob, sqlite3, subprocess, time

subprocess.run(['taskkill', '/F', '/IM', 'zotero.exe'], capture_output=True)
time.sleep(2)

VALUES = ["10.1038/nature14539"]

dbs = glob.glob(os.path.join(os.path.expandvars('%USERPROFILE%'), 'Zotero', '**', 'zotero.sqlite'), recursive=True)
print('databases:', dbs)
for db in dbs:
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    for value in VALUES:
        try:
            cur.execute("INSERT OR IGNORE INTO itemDataValues(value) VALUES(?)", (value,))
        except Exception as e:
            print('value insert failed:', value, e)
    conn.commit()
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception as e:
        print('checkpoint failed:', e)
    conn.close()
print('oracle done')
