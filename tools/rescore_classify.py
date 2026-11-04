#!/usr/bin/env python3
"""Decide per task whether an offline re-score (tools/rescore_end_state.py) is valid.

For every task record in RESCORE_DIR/tasks/*.json the validity rule is applied:

1. The instruction the agent saw (args.json task snapshot) must equal the current YAML's.
2. The environment must be unchanged: initializer id/params, and every repo file the
   initializer imports, must be identical between the run-time code snapshot
   (code-runtime-*) and the scored one (code-current). A changed initializer file
   counts as an environment change unless a reviewed file note says it has no effect
   for this task (impact "none", or "if_init_param:<name>" and the task lacks <name>).
3. The evidence the current evaluator needs must be in the saved artifacts:
   the offline evaluator must not error, must not need the live VM (DevTools / app
   HTTP APIs / observe()), must not miss files the run-time evaluator found, the
   replay of the run-time evaluator must reproduce the original checks (or the
   mismatch must be explained), and the Chrome Local Storage it read must not have
   missed the agent's last state-changing steps (unflushed writes).
Classes: UNCHANGED (nothing relevant changed; the old result stands), RESCORE_VALID
(old -> new status), NEEDS_RERUN (reason), NEEDS_REVIEW (a changed file or an evidence
risk has no manual note yet). Manual notes (tools/rescore_manual_notes.json) record
per-file impact judgements (pinned to the file's sha256, so a later edit re-opens the
review) and per-task judgements for the cases the rules cannot settle.

Usage: python tools/rescore_classify.py RESCORE_DIR [--notes tools/rescore_manual_notes.json RUN_NOTES.json ...]
Writes RESCORE_DIR/classification.json and RESCORE_DIR/classification.md.
"""

from __future__ import annotations

import os
import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Optional

REPO = Path(__file__).resolve().parents[1]
# Python used to run the evaluators (needs the repo requirements); defaults to this interpreter.
DEFAULT_PYTHON = os.environ.get("OS_OMNI_RESCORE_PYTHON", sys.executable)
HARNESS_FILES = ("platforms/linux/runners/evaluation.py", "platforms/linux/runners/base_episode.py",
                 "platforms/linux/runners/episode.py", "platforms/linux/guest/runtime_server.py",
                 "platforms/linux/runtime_env/controller.py", "scripts/run_linux_qemu_batch.py")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def sha(path: Path) -> Optional[str]:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _module_file(root: Path, module: str) -> Optional[Path]:
    base = root.joinpath(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def static_deps(roots: list[Path], module: str) -> list[str]:
    """Repo files a module needs, following its own import statements (any depth), but not the
    side imports of package __init__ files: initializers/linux/__init__.py imports every Linux
    initializer, which a given initializer class does not use. Resolved in each root; union."""
    import ast  # noqa: PLC0415

    found: set[str] = set()
    for root in roots:
        todo, seen = [module], set()
        while todo:
            name = todo.pop()
            if name in seen:
                continue
            seen.add(name)
            path = _module_file(root, name)
            if path is None:
                continue
            found.add(str(path.relative_to(root)))
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            package = name if path.name == "__init__.py" else name.rpartition(".")[0]
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    todo.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        parts = package.split(".")
                        base = ".".join(parts[: len(parts) - node.level + 1] if node.level > 1 else parts)
                        target = f"{base}.{node.module}" if node.module else base
                    else:
                        target = node.module or ""
                    for alias in node.names:
                        sub = f"{target}.{alias.name}"
                        if _module_file(root, sub) is not None:
                            todo.append(sub)
                        else:
                            todo.append(target)
    # The importing packages' __init__ files are recorded only when they define what is imported.
    return sorted(found)


def content_changed(files: list[str], root_a: Path, root_b: Path) -> list[str]:
    return sorted(f for f in files if sha(root_a / f) != sha(root_b / f))


def load_yaml(path: Path) -> dict[str, Any]:
    import yaml  # noqa: PLC0415 - venv dependency
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def file_note(notes: Mapping[str, Any], rel: str, current_root: Path) -> Optional[dict[str, Any]]:
    note = (notes.get("files") or {}).get(rel)
    if not isinstance(note, Mapping):
        return None
    pinned = note.get("sha256")
    if pinned and pinned != sha(current_root / rel):
        return {"impact": "unreviewed", "note": f"file changed after its note was written ({rel})"}
    return dict(note)


def classify(rec: Mapping[str, Any], notes: Mapping[str, Any], python: str) -> dict[str, Any]:
    task_id = rec["task_id"]
    task_note = dict(((notes.get("tasks") or {}).get(task_id)) or {})
    out: dict[str, Any] = {"task_id": task_id, "old": (rec.get("old") or {}).get("status"), "reasons": [],
                           "flags": [], "manual": task_note.get("why") or ""}
    if rec.get("error") or "current" not in rec:
        out.update(cls="NEEDS_REVIEW", new=None)
        out["reasons"].append(f"offline scoring did not run: {rec.get('error')}")
        return out
    current, runtime = rec["current"], rec.get("runtime") or {}
    current_root, runtime_root = Path(current["code_root"]), Path(runtime.get("code_root") or "")
    args = read_json(Path(rec["task_dir"]) / "args.json") or {}
    snapshot = (args.get("task") or {}).get("snapshot") or {}
    task_path = Path((args.get("task") or {}).get("path") or "")
    rel_task = task_path.relative_to(REPO) if REPO in task_path.parents else task_path
    now = load_yaml(current_root / rel_task)

    # 1. instruction -------------------------------------------------------------
    out["instruction_changed"] = snapshot.get("instruction") != now.get("instruction")
    # 2. environment ---------------------------------------------------------------
    init_then, init_now = snapshot.get("init") or {}, now.get("init") or {}
    env: list[str] = []
    if init_then.get("initializer_id") != init_now.get("initializer_id"):
        env.append(f"initializer {init_then.get('initializer_id')} -> {init_now.get('initializer_id')}")
    if (init_then.get("params") or {}) != (init_now.get("params") or {}):
        changed_keys = sorted(k for k in set(init_then.get("params") or {}) | set(init_now.get("params") or {})
                              if (init_then.get("params") or {}).get(k) != (init_now.get("params") or {}).get(k))
        env.append(f"initializer params changed: {changed_keys}")
    unreviewed: list[str] = []
    init_modules = {str(x.get("initializer_id") or "").partition(":")[0] for x in (init_then, init_now)} - {""}
    if init_modules and runtime_root.is_dir():
        deps = sorted({f for m in init_modules for f in static_deps([runtime_root, current_root], m)})
        changed = content_changed(deps, runtime_root, current_root)
        out["initializer_files_changed"] = changed
        params_now = init_now.get("params") or {}
        for rel in changed:
            note = file_note(notes, rel, current_root)
            impact = (note or {}).get("impact", "unreviewed")
            if impact == "none":
                continue
            if impact == "env_when":
                when = note.get("when") or {}
                ids = {init_then.get("initializer_id"), init_now.get("initializer_id")}
                params = {**(init_then.get("params") or {}), **params_now}
                steps = {str(step.get("type")) for step in (params.get("steps") or []) if isinstance(step, Mapping)}
                if not (ids & set(when.get("initializer_ids") or []) or set(params) & set(when.get("init_params") or [])
                        or steps & set(when.get("init_step_types") or [])):
                    continue
                env.append(f"{rel}: {note.get('note')}")
            elif impact == "env":
                env.append(f"{rel}: {note.get('note')}")
            else:
                unreviewed.append(rel)
    if task_note.get("env_unaffected"):
        out["flags"].append(f"env change judged irrelevant: {task_note['env_unaffected']}")
        env = []
    out["environment_changes"] = env
    # 3. evaluator change -----------------------------------------------------------
    eval_then, eval_now = snapshot.get("evaluation") or {}, now.get("evaluation") or {}
    eval_changes: list[str] = []
    if eval_then.get("evaluator_id") != eval_now.get("evaluator_id"):
        eval_changes.append("evaluator id")
    if (eval_then.get("params") or {}) != (eval_now.get("params") or {}):
        keys = sorted(k for k in set(eval_then.get("params") or {}) | set(eval_now.get("params") or {})
                      if (eval_then.get("params") or {}).get(k) != (eval_now.get("params") or {}).get(k))
        eval_changes.append(f"evaluator params {keys}")
    eval_modules = {str(x.get("evaluator_id") or "").partition(":")[0] for x in (eval_then, eval_now)} - {""}
    eval_deps = sorted({f for m in eval_modules for f in static_deps([runtime_root, current_root], m)})
    code_changed = content_changed(eval_deps, runtime_root, current_root) if runtime_root.is_dir() else []
    out["evaluator_files"] = eval_deps
    harness_changed = content_changed(list(HARNESS_FILES), runtime_root, current_root) if runtime_root.is_dir() else []
    for rel in code_changed:
        if rel in HARNESS_FILES:
            continue
        note = file_note(notes, rel, current_root)
        if (note or {}).get("impact") == "none":
            out["flags"].append(f"{rel} changed without a scoring effect: {note.get('note')}")
            continue
        eval_changes.append(rel)
    out["evaluator_changes"] = eval_changes
    out["harness_changes"] = harness_changed

    # 4. evidence --------------------------------------------------------------------
    evidence: list[str] = []
    access = current.get("access") or {}
    inet = [c for c in access.get("connects") or [] if not c.startswith("unix:")]
    live_methods = [c["method"] for c in current.get("controller_calls") or [] if c.get("unsupported")]
    carried = list(task_note.get("live_checks_carried") or [])
    if current.get("status") == "ERROR":
        evidence.append(f"offline evaluator ERROR: {str(current.get('message'))[:160]}")
    runtime_inet = {c for c in (runtime.get("access") or {}).get("connects") or [] if not c.startswith("unix:")}
    new_inet = [c for c in inet if c not in runtime_inet]
    # Live endpoints the run-time evaluator also probed are harmless when its offline replay reproduced
    # the original result: the original's probes changed nothing either (e.g. a LevelDB fallback).
    if (inet and not runtime.get("replay_matches_original")) or new_inet or live_methods:
        what = ", ".join(inet + live_methods)
        if carried:
            out["flags"].append(f"live-only checks carried over from the original run: {carried} ({what})")
        else:
            evidence.append(f"needs live VM state ({what})")
    missing_new = current.get("missing_not_in_replay") or []
    if missing_new:
        if task_note.get("missing_ok"):
            out["flags"].append(f"files absent offline judged irrelevant: {task_note['missing_ok']}")
        else:
            evidence.append(f"evaluator reads files absent from end state: {missing_new[:4]}")
    if runtime and not runtime.get("replay_matches_original"):
        explained = task_note.get("replay_mismatch")
        flips = (runtime.get("vs_old") or {}).get("flipped") or []
        read_dirs = [row for row in rec.get("localstorage_freshness") or []
                     if any(p.startswith(row["dir"] + "/") for p in (access.get("opened") or []))]
        if (not explained and flips and all(f["old"] is False and f["new"] is True for f in flips)
                and runtime.get("status") != "ERROR" and read_dirs
                and not any(row.get("unflushed_risk") for row in read_dirs)):
            # Chrome committed after the original evaluator read the store and before the archive was
            # taken; no state-changing step followed that commit, so the archive is the final state.
            explained = ("archive fresher than the evaluation-time read (checks "
                         f"{[f['check'] for f in flips]} False->True; no mutating step after the last write)")
        if explained:
            out["flags"].append(f"replay mismatch explained: {explained}")
        else:
            evidence.append(f"replay of the run-time evaluator differs from the original ({runtime.get('status')}, "
                            f"flipped {[f['check'] for f in flips][:4]})")
    # Evaluators that replay a document's LevelDB history (process checks) see fewer versions when
    # Chrome compacted the store between the original evaluation and the archive.
    old_md = ((read_json(Path(rec["task_dir"]) / "result.json") or {}).get("evaluation") or {}).get("metadata") or {}
    hist_old, hist_now = old_md.get("history_version_count"), (runtime.get("metadata") or {}).get("history_version_count")
    if isinstance(hist_old, int) and isinstance(hist_now, int) and hist_now < hist_old:
        if task_note.get("history_ok"):
            out["flags"].append(f"history versions {hist_old}->{hist_now} judged irrelevant: {task_note['history_ok']}")
        else:
            evidence.append(f"LevelDB compacted after the evaluation: {hist_old} document versions then, {hist_now} in the archive")
    opened = access.get("opened") or []
    stale = []
    for row in rec.get("localstorage_freshness") or []:
        if row.get("unflushed_risk") and any(p.startswith(row["dir"] + "/") for p in opened):
            stale.append(f"{row['dir'].split('/.config/')[-1]}: last write {row.get('newest_write_host')}, "
                         f"mutating steps after it {row.get('mutating_steps_after_write')}")
    out["stale_storage"] = stale
    if stale:
        if task_note.get("stale_ok"):
            out["flags"].append(f"unflushed-storage risk judged harmless: {task_note['stale_ok']}")
        else:
            evidence.append("Local Storage may miss the last steps (Chrome had not flushed): " + "; ".join(stale))
    out["evidence_problems"] = evidence

    # 5. decision ---------------------------------------------------------------------
    new = current.get("status")
    if carried and new != "ERROR":
        failing = [c for c, v in (current.get("checks") or {}).items() if v is False and c not in carried]
        old_checks = (rec.get("old") or {}).get("checks") or {}
        new = "FAIL" if failing or not all(old_checks.get(c) for c in carried) else "PASS"
        out["flags"].append(f"status derived from offline checks + carried live checks; failing: {failing}")
    out["offline_status"] = current.get("status")
    if task_note.get("class"):
        out.update(cls=task_note["class"], new=task_note.get("new", new if task_note["class"] == "RESCORE_VALID" else None))
        out["reasons"].append("manual: " + str(task_note.get("why") or ""))
    elif out["instruction_changed"]:
        out.update(cls="NEEDS_RERUN", new=None)
        out["reasons"].append("instruction changed")
    elif env:
        out.update(cls="NEEDS_RERUN", new=None)
        out["reasons"].append("environment changed: " + "; ".join(env))
    elif unreviewed:
        out.update(cls="NEEDS_REVIEW", new=None)
        out["reasons"].append(f"initializer files changed without a reviewed note: {unreviewed}")
    elif not eval_changes:
        if stale and not task_note.get("stale_ok"):
            out.update(cls="NEEDS_RERUN", new=None)
            out["reasons"].append("old result read unflushed Local Storage (the harness now flushes); the archive has the same stale copy")
        else:
            out.update(cls="UNCHANGED", new=out["old"])
            out["reasons"].append("instruction, environment and evaluator unchanged since the run")
            if current.get("status") != out["old"] and not evidence:
                out["flags"].append(f"offline score {current.get('status')} differs from the old result")
    elif evidence:
        out.update(cls="NEEDS_RERUN" if task_note.get("evidence_final", True) else "NEEDS_REVIEW", new=None)
        out["reasons"].append("evidence incomplete: " + " | ".join(evidence))
    else:
        out.update(cls="RESCORE_VALID", new=new)
        out["reasons"].append("evaluator changed (" + ", ".join(eval_changes[:3]) + "); end state holds its evidence")
    flips = (current.get("vs_old") or {}).get("flipped") or []
    out["check_flips_vs_old"] = [f"{f['check']}: {f['old']}->{f['new']}" for f in flips][:12]
    out["checks_dropped"] = [d["check"] for d in (current.get("vs_old") or {}).get("dropped") or []][:12]
    out["new_failed_checks"] = (current.get("vs_old") or {}).get("new_failed", [])[:12]
    return out


def render_md(rows: list[dict[str, Any]], summary: Mapping[str, Any]) -> str:
    lines = [f"# Offline re-score classification ({summary['label'] or 'unlabelled'})", "",
             f"Rescore dir: `{summary['rescore_dir']}`  ", f"Classified: {summary['created_at']}", "",
             "| class | n |", "|---|---|"]
    for cls, n in sorted(summary["counts"].items()):
        lines.append(f"| {cls} | {n} |")
    lines += ["", f"Old score: {summary['old_pass']}/{summary['n']}. Re-scored (UNCHANGED + RESCORE_VALID, "
              f"NEEDS_RERUN kept at old status): {summary['new_pass_keep_old']}/{summary['n']}; "
              f"PASS among the {summary['n_settled']} settled tasks: {summary['new_pass_settled']}.", "",
              "| task | old | class | new | reason / flags |", "|---|---|---|---|---|"]
    for row in rows:
        why = "; ".join(row["reasons"])
        if row["flags"]:
            why += " [" + "; ".join(row["flags"]) + "]"
        lines.append(f"| {row['task_id']} | {row['old']} | {row['cls']} | {row.get('new') or ''} | {why.replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("rescore_dir", type=Path)
    parser.add_argument("--notes", type=Path, nargs="+", default=[REPO / "tools" / "rescore_manual_notes.json"],
                        help="notes files, merged in order (repo file notes plus per-run notes kept next to a run)")
    parser.add_argument("--python", default=DEFAULT_PYTHON)
    args = parser.parse_args(argv)
    notes_all: dict = {"files": {}, "runs": {}}
    for notes_path in args.notes:
        part = read_json(notes_path) or {}
        notes_all["files"].update(part.get("files") or {})
        for run, tasks in (part.get("runs") or {}).items():
            notes_all["runs"].setdefault(run, {}).update(tasks)
    summary_in = read_json(args.rescore_dir / "summary.json") or {}
    results = str(summary_in.get("results") or "")
    notes = {"files": notes_all.get("files") or {}, "tasks": ((notes_all.get("runs") or {}).get(results) or {})}
    rows = []
    for path in sorted((args.rescore_dir / "tasks").glob("*.json")):
        rec = read_json(path)
        if isinstance(rec, dict):
            rows.append(classify(rec, notes, args.python))
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["cls"]] = counts.get(row["cls"], 0) + 1
    settled = [r for r in rows if r["cls"] in ("UNCHANGED", "RESCORE_VALID")]
    summary = {
        "label": summary_in.get("label") or "", "rescore_dir": str(args.rescore_dir), "results": results,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "n": len(rows),
        "counts": counts, "old_pass": sum(r["old"] == "PASS" for r in rows), "n_settled": len(settled),
        "new_pass_settled": sum(r.get("new") == "PASS" for r in settled),
        "new_pass_keep_old": sum((r.get("new") if r in settled else r["old"]) == "PASS" for r in rows),
        "flips": [f"{r['task_id']}: {r['old']}->{r['new']}" for r in settled if r.get("new") != r["old"]],
        "needs_rerun": {r["task_id"]: "; ".join(r["reasons"]) for r in rows if r["cls"] == "NEEDS_RERUN"},
        "needs_review": {r["task_id"]: "; ".join(r["reasons"]) for r in rows if r["cls"] == "NEEDS_REVIEW"},
        "code_current": summary_in.get("code_current"),
    }
    (args.rescore_dir / "classification.json").write_text(json.dumps({"summary": summary, "tasks": rows},
                                                                      ensure_ascii=False, indent=1))
    (args.rescore_dir / "classification.md").write_text(render_md(rows, summary))
    print(json.dumps({k: summary[k] for k in ("n", "counts", "old_pass", "n_settled", "new_pass_settled",
                                              "new_pass_keep_old", "flips")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
