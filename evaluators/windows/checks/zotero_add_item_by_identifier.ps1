Stop-Process -Name zotero -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
@'
import os, glob, sqlite3, shutil, tempfile

# Zotero stores its data in a SQLite DB called zotero.sqlite.
zotero_dirs = [
    os.path.expandvars(r'%USERPROFILE%\Zotero'),
    os.path.expandvars(r'%APPDATA%\Zotero\Zotero\Profiles'),
    r'C:\Users\User\Zotero',
]

found = False
target_doi = '10.1038/nature14539'
inspected = []

for base in zotero_dirs:
    exists = os.path.exists(base)
    inspected.append((base, exists))
    if not exists:
        continue
    for db in glob.glob(os.path.join(base, '**', 'zotero.sqlite'), recursive=True):
        try:
            with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as tmp:
                tmp_path = tmp.name
            shutil.copyfile(db, tmp_path)
            conn = sqlite3.connect(tmp_path)
            cursor = conn.execute(
                'SELECT value FROM itemDataValues WHERE value LIKE ?',
                (f'%{target_doi}%',)
            )
            for row in cursor:
                found = True
                break
            conn.close()
            os.unlink(tmp_path)
        except Exception as e:
            print('sqlite error on', db, ':', e)
        if found:
            break
    if found:
        break

print('inspected:', inspected)
if found:
    print('EVAL_RESULT:PASS DOI item found')
else:
    print('EVAL_RESULT:FAIL DOI item not added to library')
'@ | py -3 -W ignore -
