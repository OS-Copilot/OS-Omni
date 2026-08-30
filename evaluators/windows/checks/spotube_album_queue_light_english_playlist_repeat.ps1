@'
import json
import pathlib
import sqlite3
import sys

app_dir = pathlib.Path(r"C:\Users\User\AppData\Roaming\oss.krtirtho\spotube")
prefs_path = app_dir / "shared_preferences.json"
db_path = app_dir / "db.sqlite"

if not prefs_path.exists() or not db_path.exists():
    print("EVAL_RESULT:FAIL Spotube state files missing")
    sys.exit(1)

shared = json.loads(prefs_path.read_text(encoding="utf-8"))
if shared.get("doneGettingStarted") is not True and shared.get("flutter.doneGettingStarted") is not True:
    print("EVAL_RESULT:FAIL doneGettingStarted not true")
    sys.exit(1)

volume = shared.get("volume")
if not isinstance(volume, (int, float)):
    print(f"EVAL_RESULT:FAIL volume missing or invalid: {volume}")
    sys.exit(1)

if volume < 0.30 or volume > 0.50:
    print(f"EVAL_RESULT:FAIL volume expected around 0.40 got {volume}")
    sys.exit(1)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
row = conn.execute(
    """
    select market, endless_playback, theme_mode, normalize_audio, locale, album_color_sync, cache_music
    from preferences_table
    order by id limit 1
    """
).fetchone()

if row is None:
    print("EVAL_RESULT:FAIL preferences row missing")
    sys.exit(1)

expected = {
    "market": "US",
    "endless_playback": 0,
    "theme_mode": "light",
    "normalize_audio": 1,
    "album_color_sync": 0,
    "cache_music": 0,
}

for key, value in expected.items():
    actual = row[key]
    if actual != value:
        print(f"EVAL_RESULT:FAIL {key} expected {value} got {actual}")
        sys.exit(1)

if '"languageCode":"en"' not in row["locale"]:
    print(f"EVAL_RESULT:FAIL locale expected English got {row['locale']}")
    sys.exit(1)

state_row = conn.execute(
    """
    select playing, loop_mode, shuffled, tracks, current_index
    from audio_player_state_table
    order by id limit 1
    """
).fetchone()
conn.close()

if state_row is None:
    print("EVAL_RESULT:FAIL audio player state missing")
    sys.exit(1)

if state_row["loop_mode"] != "loop":
    print(f"EVAL_RESULT:FAIL loop_mode expected loop got {state_row['loop_mode']}")
    sys.exit(1)

if state_row["shuffled"] != 0:
    print(f"EVAL_RESULT:FAIL shuffled expected 0 got {state_row['shuffled']}")
    sys.exit(1)

try:
    tracks = json.loads(state_row["tracks"])
except Exception as exc:
    print(f"EVAL_RESULT:FAIL could not parse tracks json: {exc}")
    sys.exit(1)

current_index = state_row["current_index"]
if not isinstance(current_index, int) or current_index < 0 or current_index >= len(tracks):
    print(f"EVAL_RESULT:FAIL invalid current_index {current_index}")
    sys.exit(1)

current_track = tracks[current_index]
current_name = current_track.get("name")
current_artists = ", ".join(artist.get("name", "") for artist in current_track.get("artists", []))

if current_name != "Vandalize":
    print(f"EVAL_RESULT:FAIL current track expected Vandalize got {current_name}")
    sys.exit(1)

if "ONE OK ROCK" not in current_artists:
    print(f"EVAL_RESULT:FAIL current artist expected ONE OK ROCK got {current_artists}")
    sys.exit(1)

queue_names = [track.get("name") for track in tracks]
required_queue_tracks = [
    "Save Yourself",
    "Renegades",
    "Wasted Nights",
    "Stand Out Fit In",
    "We are",
    "Taking Off",
    "The Beginning",
]
for name in required_queue_tracks:
    if name not in queue_names:
        print(f"EVAL_RESULT:FAIL queue missing {name}")
        sys.exit(1)

print("EVAL_RESULT:PASS Spotube English light album queue configured")
'@ | py -3 -
