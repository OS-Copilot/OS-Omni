@'
import json
import pathlib
import sqlite3
import sys

app_dir = pathlib.Path(r"C:\Users\User\AppData\Roaming\oss.krtirtho\spotube")
prefs_path = app_dir / "shared_preferences.json"
db_path = app_dir / "db.sqlite"

if not prefs_path.exists():
    print("EVAL_RESULT:FAIL shared_preferences.json missing")
    sys.exit(1)

if not db_path.exists():
    print("EVAL_RESULT:FAIL db.sqlite missing")
    sys.exit(1)

shared = json.loads(prefs_path.read_text(encoding="utf-8"))
if shared.get("doneGettingStarted") is not True and shared.get("flutter.doneGettingStarted") is not True:
    print("EVAL_RESULT:FAIL doneGettingStarted not true")
    sys.exit(1)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
row = conn.execute(
    "select market, endless_playback from preferences_table order by id limit 1"
).fetchone()
conn.close()

if row is None:
    print("EVAL_RESULT:FAIL preferences row missing")
    sys.exit(1)

if row["market"] != "CA":
    print(f"EVAL_RESULT:FAIL market expected CA got {row['market']}")
    sys.exit(1)

if int(row["endless_playback"]) != 0:
    print(f"EVAL_RESULT:FAIL endless_playback expected 0 got {row['endless_playback']}")
    sys.exit(1)

print("EVAL_RESULT:PASS Spotube getting started updated for Canada with endless playback off")
'@ | py -3 -
