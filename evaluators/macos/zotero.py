"""Evaluate macOS Zotero tasks via the local Zotero SQLite library."""

from __future__ import annotations

import json
from textwrap import dedent
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus

_SCAN_SCRIPT = r'''
import json
import os
import shutil
import sqlite3
import tempfile
from collections import defaultdict
from pathlib import Path

params = json.loads(__PARAMS_JSON__)
db_path = Path(os.path.expanduser(str(params.get("db_path") or "~/Zotero/zotero.sqlite")))
required_collections = [str(name).strip() for name in params.get("required_collections") or [] if str(name).strip()]
required_items = [dict(item or {}) for item in params.get("required_items") or [] if isinstance(item, dict)]
forbidden_collections = [str(name).strip() for name in params.get("forbidden_collections") or [] if str(name).strip()]
forbidden_titles = [str(title).strip() for title in params.get("forbidden_titles") or [] if str(title).strip()]
text_artifacts = [dict(item or {}) for item in params.get("text_artifacts") or [] if isinstance(item, dict)]

result = {
    "status": "fail",
    "message": "Zotero checks failed",
    "db_path": str(db_path),
    "required_collections": required_collections,
    "required_items": required_items,
    "forbidden_collections": forbidden_collections,
    "forbidden_titles": forbidden_titles,
    "text_artifacts": text_artifacts,
}

if not db_path.exists():
    result["message"] = f"zotero.sqlite missing: {db_path}"
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0)

workdir = Path(tempfile.mkdtemp(prefix="zotero-eval-"))
local_db = workdir / "zotero.sqlite"
shutil.copy2(db_path, local_db)
for suffix in ("-wal", "-shm"):
    sidecar = db_path.with_name(db_path.name + suffix)
    if sidecar.exists():
        shutil.copy2(sidecar, workdir / ("zotero.sqlite" + suffix))

try:
    conn = sqlite3.connect(local_db)
    conn.row_factory = sqlite3.Row
except Exception as exc:
    result["status"] = "error"
    result["message"] = f"failed to open copied zotero db: {exc}"
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0)

cur = conn.cursor()


def table_exists(name):
    row = cur.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def normalize(text):
    return " ".join(str(text or "").split()).strip().lower()


def qall(sql, args=()):
    return [dict(row) for row in cur.execute(sql, args).fetchall()]


required_tables = [
    "collections",
    "items",
    "collectionItems",
    "itemData",
    "itemDataValues",
]
missing_tables = [name for name in required_tables if not table_exists(name)]
if missing_tables:
    result["status"] = "error"
    result["message"] = f"missing Zotero tables: {missing_tables}"
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0)

collection_rows = qall("SELECT collectionID, collectionName FROM collections")
collection_name_by_id = {int(row["collectionID"]): str(row["collectionName"] or "") for row in collection_rows}
collections_normalized = {normalize(name): name for name in collection_name_by_id.values() if normalize(name)}

field_table = "fieldsCombined" if table_exists("fieldsCombined") else "fields"
title_field_row = cur.execute(
    f"SELECT fieldID FROM {field_table} WHERE fieldName='title' LIMIT 1"
).fetchone()
if title_field_row is None:
    result["status"] = "error"
    result["message"] = "title field missing from Zotero schema"
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0)

title_field_id = int(title_field_row["fieldID"])
if table_exists("itemTypes"):
    item_title_rows = qall(
        """
        SELECT i.itemID, it.typeName AS item_type, idv.value AS title
        FROM items i
        LEFT JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
        JOIN itemData idata ON idata.itemID = i.itemID AND idata.fieldID = ?
        JOIN itemDataValues idv ON idv.valueID = idata.valueID
        WHERE idv.value IS NOT NULL AND trim(idv.value) != ''
        """,
        (title_field_id,),
    )
else:
    item_title_rows = qall(
        """
        SELECT i.itemID, '' AS item_type, idv.value AS title
        FROM items i
        JOIN itemData idata ON idata.itemID = i.itemID AND idata.fieldID = ?
        JOIN itemDataValues idv ON idv.valueID = idata.valueID
        WHERE idv.value IS NOT NULL AND trim(idv.value) != ''
        """,
        (title_field_id,),
    )

collections_by_item = defaultdict(list)
for row in qall("SELECT collectionID, itemID FROM collectionItems"):
    item_id = int(row["itemID"])
    collection_name = collection_name_by_id.get(int(row["collectionID"]))
    if collection_name:
        collections_by_item[item_id].append(collection_name)

creators_by_item = defaultdict(list)
if table_exists("itemCreators") and table_exists("creators"):
    for row in qall(
        """
        SELECT ic.itemID, c.firstName, c.lastName, c.fieldMode
        FROM itemCreators ic
        JOIN creators c ON c.creatorID = ic.creatorID
        ORDER BY ic.itemID, ic.orderIndex
        """
    ):
        first = str(row.get("firstName") or "").strip()
        last = str(row.get("lastName") or "").strip()
        full = " ".join(part for part in (first, last) if part).strip() or last or first
        if full:
            creators_by_item[int(row["itemID"])].append(full)

raw_tags_by_item = defaultdict(list)
if table_exists("itemTags") and table_exists("tags"):
    for row in qall(
        """
        SELECT it.itemID, t.name
        FROM itemTags it
        JOIN tags t ON t.tagID = it.tagID
        ORDER BY it.itemID, t.name
        """
    ):
        tag_name = str(row.get("name") or "").strip()
        if tag_name:
            raw_tags_by_item[int(row["itemID"])] .append(tag_name)

notes_by_item = defaultdict(list)
if table_exists("itemNotes"):
    for row in qall("SELECT itemID, parentItemID, note, title FROM itemNotes"):
        note_text = str(row.get("note") or "").strip() or str(row.get("title") or "").strip()
        if note_text:
            notes_by_item[int(row["itemID"])] .append(note_text)
        parent_item_id = row.get("parentItemID")
        if parent_item_id is not None:
            parent_item_id = int(parent_item_id)
            if note_text:
                notes_by_item[parent_item_id].append(note_text)

items = []
for row in item_title_rows:
    item_id = int(row["itemID"])
    title = str(row.get("title") or "").strip()
    if not title:
        continue
    items.append(
        {
            "itemID": item_id,
            "title": title,
            "item_type": str(row.get("item_type") or ""),
            "collections": sorted(set(collections_by_item.get(item_id, []))),
            "creators": creators_by_item.get(item_id, []),
            "tags": sorted(set(raw_tags_by_item.get(item_id, []))),
            "notes": notes_by_item.get(item_id, []),
        }
    )

items_by_title = defaultdict(list)
for item in items:
    items_by_title[normalize(item["title"])].append(item)

failures = []
for collection_name in required_collections:
    if normalize(collection_name) not in collections_normalized:
        failures.append(f"missing collection: {collection_name}")

for collection_name in forbidden_collections:
    if normalize(collection_name) in collections_normalized:
        failures.append(f"forbidden collection present: {collection_name}")

for title in forbidden_titles:
    if normalize(title) in items_by_title:
        failures.append(f"forbidden item present: {title}")

item_matches = {}
for spec in required_items:
    title = str(spec.get("title") or "").strip()
    if not title:
        failures.append("required item missing title in evaluator params")
        continue

    expected_collections = [str(name).strip() for name in spec.get("collections") or [] if str(name).strip()]
    forbidden_item_collections = [str(name).strip() for name in spec.get("forbidden_collections") or [] if str(name).strip()]
    expected_creators = [str(name).strip() for name in spec.get("creators") or [] if str(name).strip()]
    expected_tags = [str(name).strip() for name in spec.get("tags") or [] if str(name).strip()]
    expected_note_contains = [str(text).strip() for text in spec.get("note_contains") or [] if str(text).strip()]
    expected_item_type = str(spec.get("item_type") or spec.get("type") or "").strip()

    matches = []
    for item in items_by_title.get(normalize(title), []):
        type_ok = True if not expected_item_type else normalize(item.get("item_type")) == normalize(expected_item_type)
        collection_ok = all(normalize(name) in {normalize(v) for v in item["collections"]} for name in expected_collections)
        forbidden_collection_ok = all(
            normalize(name) not in {normalize(v) for v in item["collections"]}
            for name in forbidden_item_collections
        )
        creator_ok = all(
            any(normalize(expected) in normalize(observed) for observed in item["creators"])
            for expected in expected_creators
        )
        tag_ok = all(normalize(name) in {normalize(v) for v in item["tags"]} for name in expected_tags)
        note_ok = all(
            any(normalize(needle) in normalize(observed) for observed in item["notes"])
            for needle in expected_note_contains
        )
        if type_ok and collection_ok and forbidden_collection_ok and creator_ok and tag_ok and note_ok:
            matches.append(item)

    item_matches[title] = matches
    if not matches:
        problems = []
        if expected_collections:
            problems.append(f"collections={expected_collections}")
        if forbidden_item_collections:
            problems.append(f"forbidden_collections={forbidden_item_collections}")
        if expected_creators:
            problems.append(f"creators={expected_creators}")
        if expected_tags:
            problems.append(f"tags={expected_tags}")
        if expected_note_contains:
            problems.append(f"note_contains={expected_note_contains}")
        if expected_item_type:
            problems.append(f"item_type={expected_item_type}")
        suffix = f" ({', '.join(problems)})" if problems else ""
        failures.append(f"missing Zotero item: {title}{suffix}")

artifact_results = []
for item in text_artifacts:
    path = Path(os.path.expanduser(str(item.get("path") or "")))
    entry = {"path": str(path), "exists": path.exists()}
    content = ""
    if path.exists():
        try:
            content = path.read_text(encoding="utf-8")
            entry["content"] = content
        except Exception as exc:
            entry["error"] = str(exc)
            failures.append(f"failed to read text artifact {path}: {exc}")
    else:
        failures.append(f"expected text artifact to exist: {path}")
    if path.exists() and "equals" in item:
        expected = str(item.get("equals") or "")
        if content != expected:
            failures.append(f"text artifact mismatch for {path}")
    if path.exists() and "contains" in item:
        needle = str(item.get("contains") or "")
        if needle not in content:
            failures.append(f"expected text artifact {path} to contain {needle!r}")
    artifact_results.append(entry)

result["observed_collections"] = sorted(collections_normalized.values(), key=lambda value: value.lower())
result["observed_items"] = items
result["matched_items"] = {
    title: matches
    for title, matches in item_matches.items()
}
result["text_artifact_results"] = artifact_results

if failures:
    result["status"] = "fail"
    result["message"] = "; ".join(failures)
else:
    result["status"] = "pass"
    result["message"] = "required Zotero collections and items found"

conn.close()
print(json.dumps(result, ensure_ascii=False))
'''


class ZoteroLibraryEvaluator(BaseEvaluator):
    """Evaluate Zotero library state on macOS via the local SQLite store."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "run_python_script"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.run_python_script is required")

        script = dedent(_SCAN_SCRIPT).replace(
            "__PARAMS_JSON__",
            repr(json.dumps(params, ensure_ascii=False)),
        )
        try:
            result = controller.run_python_script(script, timeout=int(params.get("timeout", 90) or 90))
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"Zotero evaluation failed: {exc}")

        payload_raw = result.get("stdout") or result.get("output") or ""
        try:
            payload = json.loads(payload_raw)
        except Exception:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="Zotero evaluator returned non-JSON output",
                metadata={"runtime_result": result},
            )

        status_name = str(payload.get("status") or "").strip().lower()
        eval_status = (
            EvalStatus.PASS
            if status_name == "pass"
            else EvalStatus.FAIL
            if status_name == "fail"
            else EvalStatus.ERROR
        )
        return EvalResult(
            status=eval_status,
            message=str(payload.get("message") or "Zotero evaluation completed"),
            metadata=payload,
        )
