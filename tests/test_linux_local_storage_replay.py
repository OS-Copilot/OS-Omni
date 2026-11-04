"""Chrome Local Storage (LevelDB) reader: the newest write of a key wins by sequence number.

Every LevelDB record carries the sequence number of its write: a write-ahead-log batch stores the
sequence of its first operation, and a sorted-table (.ldb) entry has the internal key
``user_key + fixed64(sequence << 8 | type)`` (type 1 = put, 0 = deletion).  A table lists the versions
of a key newest first, and the file numbers do not order the data: a table written by a later
compaction can hold older versions than a level-0 table flushed before it, and a log that was not yet
removed can be older than the table it was flushed to.  The fixtures below are real .log / .ldb files
whose read order differs from the write order.
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from evaluators.cua_review.evaluators.linux import openslide_leveldb
from evaluators.cua_review.platforms.linux import local_storage

KEY = "osomni.doc.v1"
_BLOCK = 32768
_MAGIC = 0xDB4775248B80FB57
PUT, DELETE = 1, 0


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _user_key(name: str = KEY, origin: str = "file://") -> bytes:
    return b"_" + origin.encode("utf-8") + b"\x00\x01" + name.encode("utf-8")


def _value(document) -> bytes:
    return b"\x01" + json.dumps(document).encode("utf-8")


def _log(batches) -> bytes:
    """A write-ahead log: ``batches`` is ``[(first_sequence, [(type, user_key, value), ...]), ...]``.

    Records are fragmented across 32 KiB blocks (FIRST / MIDDLE / LAST) the way LevelDB writes them.
    """
    out = bytearray()
    for sequence, operations in batches:
        payload = bytearray(struct.pack("<QI", sequence, len(operations)))
        for kind, user_key, value in operations:
            payload += bytes([kind]) + _varint(len(user_key)) + user_key
            if kind == PUT:
                payload += _varint(len(value)) + value
        payload = bytes(payload)
        first = True
        while True:
            left = _BLOCK - len(out) % _BLOCK
            if left <= 7:
                out += b"\x00" * left
                continue
            fragment, payload = payload[: left - 7], payload[left - 7:]
            kind = (1 if not payload else 2) if first else (4 if not payload else 3)
            out += struct.pack("<IHB", 0, len(fragment), kind) + fragment
            first = False
            if not payload:
                break
    return bytes(out)


def _snappy_literals(data: bytes) -> bytes:
    """A valid raw Snappy stream made of literal runs only."""
    out = bytearray(_varint(len(data)))
    for start in range(0, len(data), 65536):
        chunk = data[start:start + 65536]
        if len(chunk) <= 60:
            out.append((len(chunk) - 1) << 2)
        else:
            out.append(61 << 2)
            out += struct.pack("<H", len(chunk) - 1)
        out += chunk
    return bytes(out)


def _block(entries, restart_interval: int = 4) -> bytes:
    out = bytearray()
    restarts = []
    previous = b""
    for index, (key, value) in enumerate(entries):
        if index % restart_interval == 0:
            restarts.append(len(out))
            shared = 0
        else:
            shared = 0
            while shared < min(len(previous), len(key)) and previous[shared] == key[shared]:
                shared += 1
        out += _varint(shared) + _varint(len(key) - shared) + _varint(len(value)) + key[shared:] + value
        previous = key
    for offset in restarts or [0]:
        out += struct.pack("<I", offset)
    out += struct.pack("<I", len(restarts or [0]))
    return bytes(out)


def _table(rows, *, compress: bool = False, entries_per_block: int = 2) -> bytes:
    """A sorted table: ``rows`` is ``[(user_key, sequence, type, value), ...]`` in any order.

    The entries are written in LevelDB's internal-key order (user key ascending, sequence
    descending), so a key's newest version comes first.
    """
    ordered = sorted(rows, key=lambda row: (row[0], -row[1]))
    internal = [(key + struct.pack("<Q", (sequence << 8) | kind), value) for key, sequence, kind, value in ordered]
    out = bytearray()
    index = []

    def put(block: bytes) -> tuple[int, int]:
        if compress:
            body, kind = _snappy_literals(block), 1
        else:
            body, kind = block, 0
        offset = len(out)
        out.extend(body + bytes([kind]) + b"\x00\x00\x00\x00")  # trailer: type + (unchecked) crc32c
        return offset, len(body)

    for start in range(0, len(internal), entries_per_block):
        chunk = internal[start:start + entries_per_block]
        offset, size = put(_block(chunk))
        index.append((chunk[-1][0], _varint(offset) + _varint(size)))
    meta_offset, meta_size = put(_block([]))
    index_offset, index_size = put(_block(index, restart_interval=1))
    handles = _varint(meta_offset) + _varint(meta_size) + _varint(index_offset) + _varint(index_size)
    out += handles + b"\x00" * (40 - len(handles)) + struct.pack("<Q", _MAGIC)
    return bytes(out)


def _doc(n: int) -> dict:
    return {"n": n, "body": "generation %d " % n + "x" * 64}


def _texts(history) -> list:
    return [None if row["text"] is None else json.loads(row["text"])["n"] for row in history["versions"]]


READERS = [
    pytest.param(local_storage, id="platforms.linux.local_storage"),
    pytest.param(openslide_leveldb, id="openslide_leveldb"),
]


def test_fixture_round_trips_through_the_table_reader(tmp_path):
    rows = [(_user_key(), 3, PUT, _value(_doc(3))), (_user_key("other"), 9, DELETE, b"")]
    (tmp_path / "000005.ldb").write_bytes(_table(rows, compress=True))
    read = list(local_storage._table_records(tmp_path / "000005.ldb"))
    assert [(key, seq, kind) for key, seq, kind, _ in read] == [(_user_key(), 3, PUT), (_user_key("other"), 9, DELETE)]


@pytest.mark.parametrize("module", READERS)
@pytest.mark.parametrize("compress", [False, True])
def test_flushed_table_with_several_versions_ends_on_the_newest(module, compress, tmp_path):
    # A memtable flush (e.g. the log converted to a table when Chrome reopens the store) keeps every
    # version of the key; the table lists them newest first.
    rows = [(_user_key(), seq, PUT, _value(_doc(seq))) for seq in (11, 12, 13)]
    rows.append((_user_key("unrelated"), 14, PUT, _value({"n": -1})))
    (tmp_path / "000007.ldb").write_bytes(_table(rows, compress=compress))

    assert module.read_state(str(tmp_path), KEY)["n"] == 13
    history = module.replay_history(str(tmp_path), KEY)
    assert _texts(history) == [11, 12, 13]
    assert history["errors"] == []
    assert history["versions"][-1]["source"].endswith("000007.ldb")


@pytest.mark.parametrize("module", READERS)
def test_compaction_output_with_a_higher_file_number_holds_older_data(module, tmp_path):
    # 000005.ldb: level-0 table flushed after the write at seq 40.  000009.ldb: a later level-1 -> 2
    # compaction output that still carries the seq-10 version.  Name order is not write order.
    (tmp_path / "000005.ldb").write_bytes(_table([(_user_key(), 40, PUT, _value(_doc(40)))]))
    (tmp_path / "000009.ldb").write_bytes(_table([(_user_key(), 10, PUT, _value(_doc(10))),
                                                   (_user_key("zz"), 11, PUT, _value({"n": 0}))], compress=True))

    assert module.read_state(str(tmp_path), KEY)["n"] == 40
    history = module.replay_history(str(tmp_path), KEY)
    assert _texts(history) == [10, 40]
    assert history["versions"][-1]["source"].endswith("000005.ldb")
    assert [Path(path).name for path in history["sources"]] == ["000005.ldb", "000009.ldb"]


@pytest.mark.parametrize("module", READERS)
def test_table_newer_than_a_leftover_log(module, tmp_path):
    # A log whose writes were already flushed to a table and that is still on disk.
    (tmp_path / "000003.log").write_bytes(_log([(1, [(PUT, _user_key(), _value(_doc(1)))]),
                                                (2, [(PUT, _user_key(), _value(_doc(2)))])]))
    (tmp_path / "000004.ldb").write_bytes(_table([(_user_key(), seq, PUT, _value(_doc(seq))) for seq in (1, 2, 5)]))

    assert module.read_state(str(tmp_path), KEY)["n"] == 5
    assert _texts(module.replay_history(str(tmp_path), KEY)) == [1, 2, 5]


@pytest.mark.parametrize("module", READERS)
def test_log_writes_interleave_with_table_versions_by_sequence(module, tmp_path):
    big = {"n": 30, "body": "y" * 80_000}  # spans three log blocks
    (tmp_path / "000010.ldb").write_bytes(_table([(_user_key(), seq, PUT, _value(_doc(seq))) for seq in (20, 21)]))
    (tmp_path / "000011.log").write_bytes(_log([
        (30, [(PUT, _user_key(), _value(big))]),
        (31, [(PUT, _user_key("noise"), _value({"n": 0})), (PUT, _user_key(), _value(_doc(32)))]),
    ]))
    assert module.read_state(str(tmp_path), KEY)["n"] == 32
    history = module.replay_history(str(tmp_path), KEY)
    assert _texts(history) == [20, 21, 30, 32]
    assert [Path(row["source"]).name for row in history["versions"]] == ["000010.ldb", "000010.ldb", "000011.log", "000011.log"]


@pytest.mark.parametrize("module", READERS)
def test_deletions_are_respected_in_logs_and_tables(module, tmp_path):
    (tmp_path / "000004.ldb").write_bytes(_table([(_user_key(), 7, PUT, _value(_doc(7)))]))
    (tmp_path / "000006.ldb").write_bytes(_table([(_user_key(), 3, PUT, _value(_doc(3)))]))
    (tmp_path / "000008.log").write_bytes(_log([(9, [(DELETE, _user_key(), b"")])]))

    assert module.read_state(str(tmp_path), KEY) is None
    assert module.storage_entries(str(tmp_path)) == []
    assert _texts(module.replay_history(str(tmp_path), KEY)) == [3, 7, None]

    # Written again after the deletion.
    (tmp_path / "000008.log").write_bytes(_log([(9, [(DELETE, _user_key(), b"")]),
                                                (10, [(PUT, _user_key(), _value(_doc(10)))])]))
    assert module.read_state(str(tmp_path), KEY)["n"] == 10
    assert _texts(module.replay_history(str(tmp_path), KEY)) == [3, 7, None, 10]


@pytest.mark.parametrize("module", READERS)
def test_table_deletion_shadows_an_older_table_put(module, tmp_path):
    (tmp_path / "000012.ldb").write_bytes(_table([(_user_key(), 50, DELETE, b"")]))
    (tmp_path / "000013.ldb").write_bytes(_table([(_user_key(), 44, PUT, _value(_doc(44)))]))
    assert module.read_state(str(tmp_path), KEY) is None
    assert _texts(module.replay_history(str(tmp_path), KEY)) == [44, None]


@pytest.mark.parametrize("module", READERS)
def test_origin_filter_and_longest_origin_reading(module, tmp_path):
    (tmp_path / "000003.ldb").write_bytes(_table([
        (_user_key(origin="http://127.0.0.1:8080"), 5, PUT, _value(_doc(5))),
        (_user_key(origin="http://127.0.0.1:8080"), 2, PUT, _value(_doc(2))),
        (_user_key(origin="http://localhost:9000"), 4, PUT, _value({"n": 4})),
    ]))
    assert _texts(module.replay_history(str(tmp_path), KEY, "8080")) == [2, 5]
    assert _texts(module.replay_history(str(tmp_path), KEY, "9000")) == [4]
    assert module.read_state(str(tmp_path), KEY, "8080")["n"] == 5


@pytest.mark.parametrize("module", READERS)
def test_missing_key_and_missing_store(module, tmp_path):
    (tmp_path / "000003.log").write_bytes(_log([(1, [(PUT, _user_key("other"), _value({"n": 1}))])]))
    assert module.replay_history(str(tmp_path), KEY)["versions"] == []
    empty = module.replay_history(str(tmp_path / "absent"), KEY)
    assert empty == {"versions": [], "sources": [], "errors": []}


def test_unreadable_file_is_reported_and_the_rest_is_replayed(tmp_path):
    (tmp_path / "000004.ldb").write_bytes(_table([(_user_key(), 4, PUT, _value(_doc(4)))]))
    corrupt = bytearray(_table([(_user_key(), 9, PUT, _value(_doc(9)))], compress=True))
    corrupt[0] = 0x7F  # the Snappy length prefix no longer matches
    (tmp_path / "000005.ldb").write_bytes(bytes(corrupt))
    history = local_storage.replay_history(str(tmp_path), KEY)
    assert _texts(history) == [4]
    assert len(history["errors"]) == 1 and history["errors"][0].startswith("000005.ldb")


def test_guest_program_reads_the_newest_version(tmp_path):
    """The reader as evaluators ship it to the guest (LOCAL_STORAGE_SOURCE in a fresh interpreter)."""
    (tmp_path / "000005.ldb").write_bytes(_table([(_user_key(), seq, PUT, _value(_doc(seq))) for seq in (1, 2, 3)],
                                                 compress=True))
    (tmp_path / "000009.ldb").write_bytes(_table([(_user_key(), 0, PUT, _value(_doc(0)))]))
    script = local_storage.LOCAL_STORAGE_SOURCE + (
        "\n_h = replay_history(%r, %r)\nprint(json.dumps({'last': json.loads(_h['versions'][-1]['text'])['n'],"
        " 'state': read_state(%r, %r)['n']}))\n" % (str(tmp_path), KEY, str(tmp_path), KEY))
    done = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {"last": 3, "state": 3}


def test_openzotero_final_state_is_the_newest_generation(tmp_path):
    from evaluators.linux import openzotero_toolbenchx_reliability_review_snapshot2 as toolbench

    key = "openzotero.localState.v1"
    rows = [(_user_key(key), seq, PUT, _value({"generation": seq})) for seq in (100, 101, 102)]
    (tmp_path / "000020.ldb").write_bytes(_table(rows, compress=True))
    done = subprocess.run([sys.executable, "-I", "-c", toolbench.read_script(str(tmp_path))],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    observed = json.loads(done.stdout)
    assert observed["state"] == {"generation": 102}
    assert observed["version_count"] == 3


def test_openslide_history_ends_on_the_newest_deck_generation(tmp_path):
    key = openslide_leveldb.LOCAL_STORAGE_KEY
    decks = {seq: [{"id": "deck-1", "title": "draft" if seq < 3 else "final", "slides": [], "seq": seq}]
             for seq in (1, 2, 3)}
    (tmp_path / "000004.ldb").write_bytes(_table([(_user_key(key), seq, PUT, _value(decks[seq])) for seq in decks]))
    history = openslide_leveldb.read_history(str(tmp_path))
    assert [version["decks"][0]["seq"] for version in history["versions"]] == [1, 2, 3]
    found, count = openslide_leveldb.final_deck_versions(history, "final")
    assert count == 1 and [deck["seq"] for deck in found] == [1, 2, 3]


def test_both_reader_copies_stay_identical():
    """openslide_leveldb ships its own copy of the reader to the guest; it must not drift."""
    def body(source: str, name: str) -> str:
        start = source.index("\ndef %s(" % name)
        end = source.find("\ndef ", start + 1)
        return source[start:end]

    for name in ("_file_rows", "read_records", "_entry_parts", "replay_history", "decode_value", "read_state"):
        assert body(local_storage.LOCAL_STORAGE_SOURCE, name) == body(openslide_leveldb._READER, name), name


# --- Evaluators whose guest programs scanned the raw .log/.ldb bytes -------------------------------
#
# A document larger than one 32 KiB log block is split by block headers, so a byte scan cannot parse
# it; the programs now read the store through the shared reader and scan only when it finds nothing.

import os  # noqa: E402

import yaml  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


class _GuestHome:
    """Runs the evaluator's bash program locally with /home/user mapped to a scratch guest home."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self.scripts: list[str] = []

    def run_bash_script(self, script, timeout=60):
        script = script.replace("/home/user/", str(self.home) + "/").replace("DEVTOOLS_PORT = 9222", "DEVTOOLS_PORT = 9")
        self.scripts.append(script)
        env = dict(os.environ, HOME=str(self.home))
        done = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, timeout=timeout, env=env)
        return {"returncode": done.returncode, "stdout": done.stdout, "stderr": done.stderr, "output": done.stdout}


def _params(name: str) -> dict:
    return dict(yaml.safe_load((REPO / "tasks/v1/web" / name).read_text(encoding="utf-8"))["evaluation"]["params"])


def _food_state(coupons, padding: int = 70_000) -> dict:
    return {"claimedCoupons": coupons, "filters": {"q": "", "cuisine": "All", "sort": "recommended"},
            "createdOrders": [], "tickets": [], "menuAvailability": {"seed-%d" % i: True for i in range(padding // 20)}}


@pytest.mark.parametrize("module_name", ["openfood_qa02_s2_ops", "openfood_qa03_s2_ops",
                                         "openfood_qa04_snap2_deep_dish_status_reorder"])
def test_openfood_reads_a_state_split_across_log_blocks(module_name, tmp_path):
    import importlib

    module = importlib.import_module("evaluators.linux." + module_name)
    params = _params(module_name + ".yaml")
    coupon = str(params.get("coupon_code") or "WELCOME12").upper()
    store = tmp_path / ".config/osomni-openapps/launch-openfood/Default/Local Storage/leveldb"
    store.mkdir(parents=True)
    key = _user_key("openfood-static-state-v1")
    (store / "000021.log").write_bytes(_log([(5, [(PUT, key, _value(_food_state([])))]),
                                             (6, [(PUT, key, _value(_food_state([coupon])))])]))

    guest = _GuestHome(tmp_path)
    result = module.OpenFoodWorkflowEvaluator().evaluate({"params": params, "controller": guest})
    assert "def replay_history" in guest.scripts[-1] and module.LOCAL_STORAGE_READER_LINE not in guest.scripts[-1]
    assert result.message != "OpenFood verifier output is not readable", result.metadata
    evidence = result.metadata["evidence"]
    assert evidence["diagnostics"]["state_reader"] == "leveldb"
    assert evidence["state"]["claimedCoupons"] == [coupon]
    assert evidence["source_path"].endswith("000021.log")

    # The byte scan alone (reader line left as a comment) finds no parseable state in the same store.
    raw = module.OpenFoodWorkflowEvaluator._script(params).replace("def replay_history(", "def _unused_replay_history(")
    done = _GuestHome(tmp_path).run_bash_script(raw)
    assert done["returncode"] != 0 and "state not found" in done["stderr"]


@pytest.mark.parametrize("module_name", ["opentwitter_control_trail", "opentwitter_community_handoff_snap1"])
def test_opentwitter_static_read_parses_the_stored_document(module_name, tmp_path):
    import importlib

    module = importlib.import_module("evaluators.linux." + module_name)
    params = _params(module_name + ".yaml")
    marker = module.OpenTwitterStateEvaluator._expected_text_markers(params)[0]
    def document(liked, posts):
        # The released app's schema (opentwitter.localState.v7): per-account lists under userStateByHandle.
        return {
            "session": {"loggedIn": True, "user": {"handle": "alex"}},
            "users": [{"handle": "alex", "bio": "bio"}, {"handle": "mateo", "bio": ""}],
            "userStateByHandle": {
                "alex": {"likedPostIds": liked, "bookmarkedPostIds": [], "following": ["mateo"], "followers": [],
                         "messages": [{"handle": "mateo", "text": "hi", "outbound": True}], "notifications": []},
                "mateo": {"likedPostIds": ["seed-1"]},
            },
            "posts": posts,
        }

    seeds = [{"id": "seed-%d" % i, "authorHandle": "mateo", "text": "seed post %d" % i} for i in range(1500)]
    newest = document(["p-new"], [{"id": "p-new", "authorHandle": "alex", "text": marker}] + seeds)
    store = tmp_path / ".config/osomni-openapps/launch-opentwitter/Default/Local Storage/leveldb"
    store.mkdir(parents=True)
    key = _user_key("opentwitter.localState.v7")  # the released app's key; the script names v2
    (store / "000005.ldb").write_bytes(_table([(key, 3, PUT, _value(document([], seeds)))], compress=True))
    (store / "000006.log").write_bytes(_log([(4, [(PUT, key, _value(newest))])]))

    guest = _GuestHome(tmp_path)
    state = module.OpenTwitterStateEvaluator._fetch_static_state(guest, timeout=15, params=params)
    assert "def replay_history" in guest.scripts[-1]
    assert state["likedPostIds"] == ["p-new"]
    assert state["following"] == ["mateo"] and state["messages"][0]["text"] == "hi"
    assert [post["id"] for post in state["posts"][:1]] == ["p-new"] and len(state["posts"]) == 1501
    assert state["posts"][0]["liked"] is True and state["currentUser"]["handle"] == "alex"
