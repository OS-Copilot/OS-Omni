#!/usr/bin/env python3
"""Re-score saved Linux/Web run artifacts offline with the evaluators in the repo.

No model, VM or network is used. For each task directory of a finished run
(``results/<task_id>/`` with ``args.json``, ``result.json``, ``trajectory.jsonl``,
``screenshots/`` and ``end_state.tar.gz``) the tool

1. extracts ``end_state.tar.gz`` (the guest files under /home/user and /tmp that
   changed during the episode, archived after the original evaluation),
2. runs the task's evaluator in a child process with the Linux runner's own
   context building (``build_evaluator_context`` + ``with_task_binding``) and a
   controller whose ``run_python_script`` / ``run_bash_script`` execute the guest
   scripts locally inside ``bwrap``: the extracted tree is mounted at /home/user
   and /tmp, the network and the host's processes are unshared, the rest of the
   host is read-only, and every file access / connect() is traced with strace,
3. writes one JSON per task with the new status, the per-check comparison against
   the original result, the files the evaluator wanted but the end state lacks,
   the connections it attempted (live-state evaluators), and a localStorage
   freshness analysis (last LevelDB write in guest time, mapped to host time,
   against the agent's last state-changing steps).

Two code versions can be scored:
  current  - the repo working tree as it is now (the fixed evaluators);
  runtime  - an approximation of the code the run used: HEAD plus every
             uncommitted change whose file mtime precedes the task start. Scoring
             it is a replay check: when it reproduces the original checks, the end
             state holds the evidence the original evaluator read.
Both are snapshotted into the output directory first, so a whole run is scored
with one consistent code version, and the per-task JSON records the sha256 of
every repo file the evaluator imported.

Usage (cwd = repo root):
  python tools/rescore_end_state.py RESULTS_DIR [--task-id ID ...] [--out DIR]
         [--mode current|runtime|both] [--jobs N] [--label provisional]
Writes OUT/tasks/<task_id>.json, OUT/summary.json and OUT/summary.tsv;
OUT defaults to RESULTS_DIR/../rescore-<YYYYMMDD>.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

REPO = Path(__file__).resolve().parents[1]
# Python used to run the evaluators (needs the repo requirements); defaults to this interpreter.
DEFAULT_PYTHON = os.environ.get("OS_OMNI_RESCORE_PYTHON", sys.executable)
# Top-level repo entries an evaluator can import or read; the code snapshots copy only these.
CODE_ENTRIES = ("__init__.py", "core", "evaluators", "initializers", "platforms", "integrations",
                "services", "scripts", "configs", "executions", "tasks")
STRACE_CALLS = "openat,open,creat,stat,lstat,newfstatat,statx,access,faccessat,faccessat2,readlink,readlinkat,connect,execve"
GUEST_ROOTS = ("/home/user", "/tmp")
# pyautogui / shell calls that can change application state. moveTo, screenshot and sleep cannot.
MUTATING_ACTION = re.compile(
    r"\b(?:click|doubleClick|tripleClick|rightClick|middleClick|mouseDown|mouseUp|dragTo|dragRel|drag|"
    r"press|hotkey|keyDown|keyUp|write|typewrite|scroll|hscroll|vscroll)\s*\(|xdotool|subprocess|os\.system",
)


# --------------------------------------------------------------------------- helpers


def utc(value: Any) -> Optional[float]:
    """ISO-8601 text -> POSIX seconds (UTC)."""
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.timestamp()


def iso(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def task_relpath(path: Path, code_root: Path) -> Path:
    """The task file's path inside a checkout.

    A run records the absolute path in whichever checkout ran it (often another clone or worktree than
    this one), so anything outside REPO is re-rooted at its ``tasks/`` component when that file exists
    under ``code_root``.
    """
    if not path.is_absolute():
        return path
    if REPO in path.parents:
        return path.relative_to(REPO)
    parts = path.parts
    for i, part in enumerate(parts):
        if part == "tasks" and (code_root / Path(*parts[i:])).is_file():
            return Path(*parts[i:])
    return path


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def normalize_checks(metadata: Any) -> dict[str, Optional[bool]]:
    """Map check name -> passed for the check-list shapes the evaluators emit."""
    out: dict[str, Optional[bool]] = {}
    if not isinstance(metadata, Mapping):
        return out
    checks = metadata.get("checks")
    if isinstance(checks, Mapping):
        for name, value in checks.items():
            if isinstance(value, Mapping):
                value = value.get("passed", value.get("ok"))
            out[str(name)] = None if value is None else bool(value)
        return out
    if not isinstance(checks, list):
        return out
    for index, check in enumerate(checks):
        if not isinstance(check, Mapping):
            continue
        name = next((str(check[k]) for k in ("name", "check_id", "check", "id", "label") if check.get(k)), f"#{index}")
        while name in out:
            name += "'"
        value = next((check[k] for k in ("passed", "ok", "pass", "success") if k in check), None)
        out[name] = None if value is None else bool(value)
    return out


_TEMP_NAME = re.compile(r"(/tmp/[A-Za-z]\w*?_)[A-Za-z0-9_]{6,}(\.\w+)")


def canonical(value: Any) -> str:
    """JSON text for comparing evaluator metadata; random tempfile names are masked."""
    return _TEMP_NAME.sub(r"\1*\2", json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))


def metadata_diff(old: Any, new: Any, path: str = "", out: Optional[list] = None) -> list[str]:
    """Paths (with old | new values) where two metadata documents differ; at most 12."""
    out = [] if out is None else out
    if len(out) >= 12:
        return out
    if isinstance(old, Mapping) and isinstance(new, Mapping):
        for key in sorted(set(old) | set(new), key=str):
            metadata_diff(old.get(key), new.get(key), f"{path}.{key}", out)
    elif isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        for index, (a, b) in enumerate(zip(old, new)):
            metadata_diff(a, b, f"{path}[{index}]", out)
    elif canonical(old) != canonical(new):
        out.append(f"{path or '.'}: {canonical(old)[:120]} | {canonical(new)[:120]}")
    return out


def compare_checks(old: Mapping[str, Optional[bool]], new: Mapping[str, Optional[bool]]) -> dict[str, Any]:
    flips = [{"check": k, "old": old[k], "new": new[k]} for k in old if k in new and old[k] != new[k]]
    return {
        "same_names": sorted(old) == sorted(new),
        "flipped": flips,
        "dropped": [{"check": k, "old": old[k]} for k in old if k not in new],
        "added": [{"check": k, "new": new[k]} for k in new if k not in old],
        "old_failed": [k for k, v in old.items() if v is False],
        "new_failed": [k for k, v in new.items() if v is False],
    }


# --------------------------------------------------------------------------- run artifacts


def task_dirs(results: Path, task_ids: Iterable[str]) -> list[Path]:
    wanted = list(task_ids)
    if wanted:
        return [results / t for t in wanted]
    return sorted(p for p in results.iterdir() if p.is_dir() and (p / "result.json").is_file())


def extract_tree(task_dir: Path, dest: Path) -> dict[str, Any]:
    """Extract end_state.tar.gz once; return member stats (mtimes are guest clock)."""
    archive = task_dir / "end_state.tar.gz"
    info: dict[str, Any] = {"archive": str(archive), "present": archive.is_file()}
    if not archive.is_file():
        return info
    marker = dest / ".rescore-extracted.json"
    if marker.is_file():
        cached = read_json(marker)
        if isinstance(cached, dict) and cached.get("archive_sha256") == sha256_file(archive):
            return cached
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "home" / "user").mkdir(parents=True, exist_ok=True)
    (dest / "tmp").mkdir(parents=True, exist_ok=True)
    skipped, mtimes = [], {}
    with tarfile.open(archive) as tar:
        members = []
        for member in tar.getmembers():
            if not (member.isfile() or member.isdir()):
                skipped.append(member.name)
                continue
            if not member.name.startswith(("home/user/", "tmp/")):
                skipped.append(member.name)
                continue
            members.append(member)
            if member.isfile():
                mtimes[member.name] = member.mtime
        tar.extractall(dest, members=members, filter="data")
    info.update(archive_sha256=sha256_file(archive), files=len(mtimes), skipped=skipped, mtimes=mtimes)
    marker.write_text(json.dumps(info))
    return info


def guest_clock_offset(task_dir: Path, tree_info: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    """host = guest + offset. The end-state list is written in the guest after the episode
    ended (result.json ended_at) and before the archive reached the host (its mtime)."""
    guest = (tree_info.get("mtimes") or {}).get("tmp/os_omni_end_state.list")
    archive = task_dir / "end_state.tar.gz"
    ended = utc(result.get("ended_at"))
    if guest is None or ended is None or not archive.is_file():
        return {"known": False}
    low, high = ended - guest, archive.stat().st_mtime - guest
    return {"known": True, "low": low, "high": max(low, high), "uncertainty_s": round(max(0.0, high - low), 1)}


def load_steps(task_dir: Path) -> list[dict[str, Any]]:
    steps = []
    path = task_dir / "trajectory.jsonl"
    if not path.is_file():
        return steps
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        action = ((row.get("action_parse") or {}).get("action") or {})
        code = str(action.get("code") or "")
        steps.append({
            "step": row.get("step_index"),
            "end": utc(row.get("timestamp")),
            "type": action.get("type"),
            "mutating": action.get("type") == "python_code" and bool(MUTATING_ACTION.search(code)),
            "reflection": str((row.get("llm_reasoning") or {}).get("reflection") or "")[:300],
        })
    # The runner logs "[Step N] Action:" when it starts executing the action.
    log = task_dir / "runner.log"
    if log.is_file():
        starts = {}
        pattern = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\S* .*?\[Step (\d+)\] Action:")
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            match = pattern.match(line)
            if match:
                starts[int(match.group(2))] = utc(match.group(1).replace(" ", "T"))
        for step in steps:
            step["start"] = starts.get(step["step"])
    return steps


def leveldb_freshness(tree: Path, tree_info: Mapping[str, Any], offset: Mapping[str, Any],
                      steps: list[dict[str, Any]], result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Per Local Storage LevelDB in the end state: last write vs the agent's last mutating steps."""
    mtimes = tree_info.get("mtimes") or {}
    dirs: dict[str, list[float]] = {}
    for name, mtime in mtimes.items():
        if "/Local Storage/leveldb/" in name and not name.endswith(("/LOG", "/LOG.old", "/LOCK")):
            dirs.setdefault(name.rsplit("/", 1)[0], []).append(mtime)
    out = []
    started = utc(result.get("started_at"))
    for directory, values in sorted(dirs.items()):
        newest_guest = max(values)
        row: dict[str, Any] = {"dir": "/" + directory, "newest_write_guest": iso(newest_guest)}
        if offset.get("known"):
            write_low, write_high = newest_guest + offset["low"], newest_guest + offset["high"]
            row["newest_write_host"] = iso(write_low)
            if started is not None and write_high < started:
                row["note"] = "no write during the episode"
            # A step whose action ran entirely before the write is on disk; later ones may not be.
            after = [s for s in steps if s["mutating"] and (s.get("end") or 0) > write_low]
            row["mutating_steps_after_write"] = [s["step"] for s in after]
            row["mutating_steps_surely_after_write"] = [
                s["step"] for s in after if (s.get("start") or s.get("end") or 0) > write_high]
            row["unflushed_risk"] = bool(after)
            row["steps_after_write"] = [{"step": s["step"], "reflection": s["reflection"]} for s in after][:15]
            last_mut = max((s.get("end") or 0 for s in steps if s["mutating"]), default=None)
            row["last_mutating_step_host"] = iso(last_mut)
            if last_mut:
                row["gap_s"] = round(last_mut - write_low, 1)
        try:
            row["keys"] = _ls_keys(tree / directory)
        except Exception as exc:  # noqa: BLE001
            row["keys_error"] = f"{type(exc).__name__}: {exc}"
        out.append(row)
    return out


def _ls_keys(directory: Path) -> list[dict[str, Any]]:
    sys.path.insert(0, str(REPO))
    from evaluators.cua_review.platforms.linux.local_storage import storage_entries  # noqa: E402
    return [{"origin": origin[:80], "key": key, "chars": len(text)}
            for origin, key, text in sorted(storage_entries(str(directory)))][:40]


# --------------------------------------------------------------------------- code snapshots


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True).stdout


def changed_files() -> dict[str, str]:
    """Uncommitted paths (relative) -> porcelain status code."""
    out: dict[str, str] = {}
    entries = git("status", "--porcelain=v1", "-z", "--untracked-files=all").split(b"\0")
    i = 0
    while i < len(entries):
        entry = entries[i].decode("utf-8", "surrogateescape")
        i += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if code[0] in "RC":
            i += 1  # the rename source follows
        out[path] = code.strip() or code
    return out


def _copy_entries(src_root: Path, dest: Path) -> None:
    for entry in CODE_ENTRIES:
        src = src_root / entry
        if src.is_dir():
            shutil.copytree(src, dest / entry, symlinks=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "vmware_vm_data"))
        elif src.is_file():
            shutil.copy2(src, dest / entry)


def snapshot_current(out: Path) -> Path:
    dest = out / "code-current"
    if (dest / ".complete").is_file():
        return dest
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    _copy_entries(REPO, dest)
    (dest / ".complete").write_text(json.dumps({"copied_at": iso(time.time()), "head": git("rev-parse", "HEAD").decode().strip()}))
    return dest


def snapshot_runtime(out: Path, cutoff: float) -> tuple[Path, list[str]]:
    """Approximate the code a run used: the last commit before ``cutoff`` and, when that is HEAD,
    the uncommitted changes whose mtime precedes ``cutoff``."""
    base = git("rev-list", "-1", f"--before={int(cutoff)}", "HEAD").decode().strip() or "HEAD"
    head = git("rev-parse", "HEAD").decode().strip()
    changed = changed_files() if base == head else {}
    newer = sorted(p for p in changed if p.split("/", 1)[0] in CODE_ENTRIES
                   and (not (REPO / p).exists() or (REPO / p).stat().st_mtime >= cutoff))
    if base != head:
        newer = [f"<all changes after commit {base[:10]}>"]
    key = hashlib.sha1(json.dumps([base] + newer).encode()).hexdigest()[:10]
    dest = out / f"code-runtime-{key}"
    if (dest / ".complete").is_file():
        return dest, newer
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    entries = [e for e in CODE_ENTRIES if git("ls-tree", "--name-only", base, e).strip()]
    archive = subprocess.run(["git", "-C", str(REPO), "archive", base, *entries],
                             check=True, capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive, check=True)
    older = [p for p in changed if p not in newer and p.split("/", 1)[0] in CODE_ENTRIES and (REPO / p).is_file()]
    for rel in older:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, target)
    (dest / ".complete").write_text(json.dumps({"cutoff": iso(cutoff), "base_commit": base,
                                                "reverted_to_head_or_removed": newer,
                                                "kept_uncommitted": sorted(older)}, indent=1))
    return dest, newer


# --------------------------------------------------------------------------- strace


_STRACE_LINE = re.compile(r'^\d+\s+(\w+)\((.*)\)\s+=\s+(-?\d+|\?)(?:\s+(\w+))?')
_PATH_ARG = re.compile(r'"((?:[^"\\]|\\.)*)"')


def parse_strace(log_dir: Path) -> dict[str, Any]:
    missing: set[str] = set()
    read: set[str] = set()
    connects: list[str] = []
    execs: set[str] = set()
    for log in sorted(log_dir.glob("strace.*")):
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            match = _STRACE_LINE.match(line)
            if not match:
                continue
            call, args, ret, err = match.groups()
            if call == "connect":
                if "AF_INET" in args or "AF_INET6" in args:
                    port = re.search(r"htons\((\d+)\)", args)
                    addr = re.search(r'inet_(?:addr|pton)\((?:AF_INET6, )?"([^"]+)"', args)
                    connects.append(f"{addr.group(1) if addr else '?'}:{port.group(1) if port else '?'} -> {err or ret}")
                elif "AF_UNIX" in args:
                    path = _PATH_ARG.search(args)
                    if path and "nscd" not in path.group(1):  # libc's name-service cache probe
                        connects.append(f"unix:{path.group(1)} -> {err or ret}")
                continue
            path_match = _PATH_ARG.search(args)
            if not path_match:
                continue
            path = path_match.group(1)
            if call == "execve":
                execs.add(path)
                continue
            if not path.startswith(GUEST_ROOTS) or path.startswith("/tmp/helloworld_linux_runtime_"):
                continue
            if "__pycache__" in path or path == "/tmp/-":
                continue
            if err == "ENOENT":
                missing.add(path)
            elif ret not in ("-1",) and call in ("openat", "open"):
                read.add(path)
    # A path that was missing and later created by the script itself is not missing evidence.
    return {"missing": sorted(missing - read), "opened": sorted(read), "connects": sorted(set(connects)),
            "executables": sorted(execs)}


# --------------------------------------------------------------------------- worker (child process)


class SandboxController:
    """Executes evaluator guest scripts locally against an extracted end state.

    Mirrors platforms/linux/guest/runtime_server.py: /run_python writes the code to a
    file and runs python3 on it (stdout/stderr apart, return_code); /run_bash_script
    prepends "#!/bin/bash\\nset -e" and merges stderr into output (returncode).
    """

    def __init__(self, tree: Path, log_dir: Path, python: str) -> None:
        self.tree = tree
        self.log_dir = log_dir
        self.python = python
        self.calls: list[dict[str, Any]] = []
        self.counter = 0
        base = subprocess.run([python, "-I", "-c", "import sys; print(sys.base_prefix)"],
                              capture_output=True, text=True, check=True).stdout.strip()
        self.binds: list[str] = []
        if base.startswith("/home/"):
            self.binds += ["--ro-bind", base, base]
        venv_bin = str(Path(python).parent)
        shim = log_dir / "bin"
        shim.mkdir(parents=True, exist_ok=True)
        # A wrapper, not a symlink: a venv interpreter finds its pyvenv.cfg from the path it was started by.
        for name in ("python3", "python"):
            wrapper = shim / name
            wrapper.write_text(f'#!/bin/sh\nexec {python} "$@"\n')
            wrapper.chmod(0o755)
        self.path_env = f"/mnt/osomni_log/bin:{venv_bin}:/usr/local/bin:/usr/bin:/bin"

    def _sandbox(self, argv: list[str], timeout: float, cwd: str = "/tmp") -> subprocess.CompletedProcess:
        self.counter += 1
        cmd = [
            "bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
            "--tmpfs", "/home", *self.binds,
            "--bind", str(self.tree / "home" / "user"), "/home/user",
            "--bind", str(self.tree / "tmp"), "/tmp",
            "--tmpfs", "/mnt", "--bind", str(self.log_dir), "/mnt/osomni_log",
            "--unshare-net", "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--die-with-parent", "--new-session",
            "--clearenv", "--setenv", "HOME", "/home/user", "--setenv", "USER", "user", "--setenv", "LOGNAME", "user",
            "--setenv", "PATH", self.path_env, "--setenv", "LANG", "C.UTF-8", "--setenv", "TZ", "UTC",
            # The host's newer Pillow/numpy warn where the guest's do not; run_bash_script merges stderr.
            "--setenv", "PYTHONWARNINGS", "ignore",
            "--chdir", cwd,
            "strace", "-f", "-qq", "-s", "1024", "-e", f"trace={STRACE_CALLS}", "-e", "signal=none",
            "-o", f"/mnt/osomni_log/strace.{self.counter}", *argv,
        ]
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            return subprocess.CompletedProcess(cmd, -1, exc.stdout or "", f"TimeoutExpired after {timeout}s")

    def run_python_script(self, code: str, *, timeout: int = 30, **_: Any) -> dict[str, Any]:
        script = self.log_dir / f"script.{self.counter + 1}.py"
        script.write_text(code, encoding="utf-8")
        proc = self._sandbox(["python3", f"/mnt/osomni_log/{script.name}"], timeout=max(timeout, 60) * 2)
        self.calls.append({"method": "run_python_script", "n": self.counter, "rc": proc.returncode,
                           "stderr_tail": (proc.stderr or "")[-400:]})
        return {"status": "success" if proc.returncode == 0 else "error", "output": proc.stdout,
                "error": proc.stderr, "return_code": proc.returncode}

    def run_bash_script(self, script: str, *, timeout: int = 30, working_dir: Optional[str] = None, **_: Any) -> dict[str, Any]:
        body = script if script.startswith("#!/bin/bash") else f"#!/bin/bash\nset -e\n{script}\n"
        path = self.log_dir / f"script.{self.counter + 1}.sh"
        path.write_text(body, encoding="utf-8")
        proc = self._sandbox(["/bin/bash", f"/mnt/osomni_log/{path.name}"], timeout=max(timeout, 60) * 2,
                             cwd=working_dir if working_dir and str(working_dir).startswith(GUEST_ROOTS) else "/tmp")
        output = (proc.stdout or "") + (proc.stderr or "")
        self.calls.append({"method": "run_bash_script", "n": self.counter, "rc": proc.returncode,
                           "output_tail": output[-400:]})
        return {"status": "success" if proc.returncode == 0 else "error", "output": output, "error": "",
                "returncode": proc.returncode}

    def execute_command(self, command: Any, *, shell: bool = False, timeout: int = 120, **_: Any) -> dict[str, Any]:
        argv = ["/bin/bash", "-c", command] if isinstance(command, str) else [str(c) for c in command]
        proc = self._sandbox(argv, timeout=timeout)
        self.calls.append({"method": "execute_command", "n": self.counter, "rc": proc.returncode})
        return {"status": "success" if proc.returncode == 0 else "error", "output": proc.stdout,
                "stdout": proc.stdout, "stderr": proc.stderr, "returncode": proc.returncode}

    def _local(self, guest: str) -> Path:
        text = str(guest)
        for root, sub in (("/home/user", self.tree / "home" / "user"), ("/tmp", self.tree / "tmp")):
            if text == root or text.startswith(root + "/"):
                return sub / text[len(root):].lstrip("/")
        raise FileNotFoundError(f"{guest} is outside the archived guest roots")

    def get_file(self, file_path: str) -> bytes:
        self.calls.append({"method": "get_file", "path": str(file_path)})
        return self._local(file_path).read_bytes()

    def read_file(self, file_path: str, encoding: str = "utf-8") -> str:
        self.calls.append({"method": "read_file", "path": str(file_path)})
        return self._local(file_path).read_text(encoding=encoding)

    def __getattr__(self, name: str) -> Any:
        # observe(), screenshots, actions ... need the live VM.
        if name.startswith("__"):
            raise AttributeError(name)
        self.__dict__.setdefault("calls", []).append({"method": name, "unsupported": True})
        raise AttributeError(f"offline controller has no live-VM method {name!r}")


def _final_observation(task_dir: Path, result: Mapping[str, Any]) -> Any:
    from platforms.linux.runtime_env.controller import Observation  # noqa: E402

    saved = result.get("final_observation") or {}
    info = saved.get("addition_info") or {}
    shot = saved.get("screenshot_path")
    data = None
    if shot and (task_dir / shot).is_file():
        data = (task_dir / shot).read_bytes()
    return Observation(timestamp=str(result.get("ended_at") or ""), width=int(info.get("width") or 0),
                       height=int(info.get("height") or 0), ui_nodes=list(saved.get("a11y_tree") or []),
                       foreground_app=str(info.get("foreground_app") or ""),
                       foreground_bundle_id=str(info.get("foreground_bundle_id") or ""),
                       foreground_window=str(info.get("foreground_window") or ""), screenshot_data=data)


def worker(spec_path: Path) -> int:
    spec = json.loads(spec_path.read_text())
    code_root = Path(spec["code_root"])
    sys.path.insert(0, str(code_root))
    os.chdir(code_root)
    import logging
    logging.basicConfig(level=logging.WARNING)
    from core.evaluation import EvalResult, load_evaluator  # noqa: E402
    from core.evaluation.context import with_task_binding  # noqa: E402
    from core.specs.loader import _parse_task_spec, load_task_spec  # noqa: E402
    from platforms.linux.runners.evaluation import build_evaluator_context  # noqa: E402

    task_dir = Path(spec["task_dir"])
    args = read_json(task_dir / "args.json") or {}
    result = read_json(task_dir / "result.json") or {}
    original_path = Path(((args.get("task") or {}).get("path")) or "")
    if spec["task_source"] == "snapshot":
        task = _parse_task_spec((args.get("task") or {}).get("snapshot") or {}, original_path)
    else:
        # The same task file, inside the code snapshot being scored.
        task = load_task_spec(code_root / task_relpath(original_path, code_root))
    log_dir = Path(spec["log_dir"])
    controller = SandboxController(Path(spec["tree"]), log_dir, spec["python"])
    out: dict[str, Any] = {"task_source": spec["task_source"], "code_root": str(code_root),
                           "evaluator_id": task.evaluation.evaluator_id}
    started = time.time()
    try:
        evaluator = load_evaluator(task.evaluation.evaluator_id)
        out["requires_live_browser"] = bool(getattr(evaluator, "REQUIRES_LIVE_BROWSER", False))
        trajectory = task_dir / "trajectory.jsonl"
        context = build_evaluator_context(params=task.evaluation.params, controller=controller,
                                          final_observation=_final_observation(task_dir, result), run_dir=task_dir,
                                          trajectory_path=trajectory if trajectory.is_file() else None)
        context = with_task_binding(context, task)
        res = evaluator.evaluate(context)
        if not isinstance(res, EvalResult):
            raise TypeError(f"evaluate() returned {type(res)!r}")
        out.update(status=res.status.value, message=res.message, metadata=res.metadata)
    except Exception as exc:  # noqa: BLE001 - reported like the runner does
        import traceback
        out.update(status="ERROR", message=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc()[-3000:])
    out["seconds"] = round(time.time() - started, 1)
    out["controller_calls"] = controller.calls
    deps = {}
    for module in list(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if path and Path(path).resolve().is_relative_to(code_root.resolve()):
            rel = str(Path(path).resolve().relative_to(code_root.resolve()))
            deps[rel] = sha256_file(Path(path))
    out["code_files"] = dict(sorted(deps.items()))
    Path(spec["out"]).write_text(json.dumps(out, ensure_ascii=False, default=str, indent=1))
    return 0


# --------------------------------------------------------------------------- driver


def run_mode(task_dir: Path, tree: Path, code_root: Path, task_source: str, work: Path, python: str,
             timeout: float) -> dict[str, Any]:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    spec = {"code_root": str(code_root), "task_dir": str(task_dir), "task_source": task_source, "tree": str(tree),
            "log_dir": str(work), "python": python, "out": str(work / "result.json")}
    (work / "spec.json").write_text(json.dumps(spec))
    # The evaluators may write into the tree (exports, temp files); score on a private copy.
    proc = subprocess.run([python, "-I", str(Path(__file__).resolve()), "--worker", str(work / "spec.json")],
                          capture_output=True, text=True, timeout=timeout)
    out = read_json(work / "result.json") or {"status": "ERROR", "message": "worker produced no result",
                                              "worker_stderr": proc.stderr[-3000:]}
    out["access"] = parse_strace(work)
    return out


def rescore_task(task_dir: Path, out: Path, modes: list[str], python: str, timeout: float,
                 code: Mapping[str, Path]) -> dict[str, Any]:
    args = read_json(task_dir / "args.json") or {}
    result = read_json(task_dir / "result.json") or {}
    batch = read_json(task_dir / "batch_run.json") or {}
    task_id = result.get("task_id") or task_dir.name
    record: dict[str, Any] = {
        "task_id": task_id, "task_dir": str(task_dir), "platform": result.get("platform"),
        "started_at": result.get("started_at"), "ended_at": result.get("ended_at"),
        "steps_taken": result.get("steps_taken"),
        "task_path": (args.get("task") or {}).get("path"),
        "run_task_sha256": (batch.get("fingerprint") or {}).get("task_sha256"),
        "old": {"status": result.get("status"), "eval_status": (result.get("evaluation") or {}).get("status"),
                "message": (result.get("evaluation") or {}).get("message"),
                "checks": normalize_checks((result.get("evaluation") or {}).get("metadata"))},
    }
    tree_cache = out / "trees" / task_dir.name
    tree_info = extract_tree(task_dir, tree_cache)
    record["end_state"] = {k: v for k, v in tree_info.items() if k not in ("mtimes", "skipped")}
    record["end_state"]["skipped_members"] = len(tree_info.get("skipped") or [])
    if not tree_info.get("present"):
        record["error"] = "no end_state.tar.gz"
        return record
    offset = guest_clock_offset(task_dir, tree_info, result)
    record["guest_clock_offset"] = offset
    steps = load_steps(task_dir)
    record["localstorage_freshness"] = leveldb_freshness(tree_cache, tree_info, offset, steps, result)
    for mode in modes:
        # Each mode scores a private copy: evaluators may write exports or caches into the tree.
        scratch = out / "work" / task_dir.name / mode
        tree = scratch.parent / f"tree-{mode}"
        if tree.exists():
            shutil.rmtree(tree)
        shutil.copytree(tree_cache, tree, symlinks=True)
        source = "current" if mode == "current" else "snapshot"
        res = run_mode(task_dir, tree, code[mode], source, scratch, python, timeout)
        res["checks"] = normalize_checks(res.get("metadata"))
        res["vs_old"] = compare_checks(record["old"]["checks"], res["checks"])
        res["status_vs_old"] = f"{record['old']['status']}->{res.get('status')}"
        if mode == "runtime":
            old_md = (read_json(task_dir / "result.json") or {}).get("evaluation", {}).get("metadata")
            res["metadata_equal_original"] = canonical(res.get("metadata")) == canonical(old_md)
            res["metadata_diff_vs_original"] = metadata_diff(old_md, res.get("metadata"))
            same_checks = not res["vs_old"]["flipped"] and res["vs_old"]["same_names"]
            # Without a check list only identical metadata shows the replay read what the original read.
            res["replay_matches_original"] = (res.get("status") == record["old"]["eval_status"] and same_checks
                                              and (bool(record["old"]["checks"]) or res["metadata_equal_original"]))
        record[mode] = res
        shutil.rmtree(tree, ignore_errors=True)
    if "current" in record and "runtime" in record:
        runtime_missing = set(record["runtime"]["access"]["missing"])
        record["current"]["missing_not_in_replay"] = [p for p in record["current"]["access"]["missing"]
                                                      if p not in runtime_missing]
        record["current"]["vs_runtime"] = compare_checks(record["runtime"]["checks"], record["current"]["checks"])
    return record


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", nargs="?", type=Path, help="run results dir (contains <task_id>/ dirs)")
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--mode", choices=("current", "runtime", "both"), default="both")
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--python", default=DEFAULT_PYTHON)
    parser.add_argument("--timeout", type=float, default=900, help="seconds per evaluator run")
    parser.add_argument("--label", default="", help="free text stored in summary.json (e.g. provisional)")
    parser.add_argument("--reuse-code", action="store_true", help="reuse an existing code-current snapshot in --out")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        return worker(args.worker)
    if args.results is None:
        parser.error("RESULTS_DIR is required")
    results = args.results.resolve()
    out = (args.out or results.parent / f"rescore-{dt.date.today():%Y%m%d}").resolve()
    (out / "tasks").mkdir(parents=True, exist_ok=True)
    modes = ["current", "runtime"] if args.mode == "both" else [args.mode]
    dirs = task_dirs(results, args.task_id)

    current_root = out / "code-current"
    if "current" in modes and not (args.reuse_code and (current_root / ".complete").is_file()):
        if current_root.exists():
            shutil.rmtree(current_root)
        current_root = snapshot_current(out)
    runtime_roots: dict[str, tuple[Path, list[str]]] = {}
    plan = []
    for task_dir in dirs:
        result = read_json(task_dir / "result.json") or {}
        code: dict[str, Path] = {"current": current_root}
        if "runtime" in modes:
            cutoff = utc(result.get("started_at")) or time.time()
            key = iso(cutoff)
            if key not in runtime_roots:
                runtime_roots[key] = snapshot_runtime(out, cutoff)
            code["runtime"] = runtime_roots[key][0]
        plan.append((task_dir, code))

    def one(item):
        task_dir, code = item
        started = time.time()
        try:
            record = rescore_task(task_dir, out, modes, args.python, args.timeout, code)
        except Exception as exc:  # noqa: BLE001
            import traceback
            record = {"task_id": task_dir.name, "task_dir": str(task_dir), "error": f"{type(exc).__name__}: {exc}",
                      "traceback": traceback.format_exc()[-3000:]}
        record["rescored_at"] = iso(time.time())
        record["rescore_seconds"] = round(time.time() - started, 1)
        (out / "tasks" / f"{record['task_id']}.json").write_text(
            json.dumps(record, ensure_ascii=False, default=str, indent=1))
        line = (f"{record['task_id']}: old={record.get('old', {}).get('status')} "
                + " ".join(f"{m}={record.get(m, {}).get('status')}" for m in modes)
                + (" replay_match=%s" % record["runtime"].get("replay_matches_original") if "runtime" in record else ""))
        print(line, flush=True)
        return record

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        list(pool.map(one, plan))
    # The summary covers every task scored into OUT so far, not only this invocation's.
    records = [r for r in (read_json(p) for p in sorted((out / "tasks").glob("*.json"))) if isinstance(r, dict)]

    summary = {
        "label": args.label, "results": str(results), "out": str(out), "modes": modes, "created_at": iso(time.time()),
        "code_current": json.loads((current_root / ".complete").read_text()) if (current_root / ".complete").is_file() else None,
        "code_runtime": {k: {"root": str(v[0]), "reverted": v[1]} for k, v in runtime_roots.items()},
        "tasks": {r["task_id"]: {"old": r.get("old", {}).get("status"),
                                 **{m: r.get(m, {}).get("status") for m in modes},
                                 "replay_match": r.get("runtime", {}).get("replay_matches_original"),
                                 "error": r.get("error")} for r in records},
    }
    for mode in modes:
        summary[f"{mode}_pass"] = sum(1 for r in records if r.get(mode, {}).get("status") == "PASS")
    summary["old_pass"] = sum(1 for r in records if r.get("old", {}).get("status") == "PASS")
    summary["n"] = len(records)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    with (out / "summary.tsv").open("w") as handle:
        handle.write("task_id\told\t" + "\t".join(modes) + "\treplay_match\n")
        for task_id, row in summary["tasks"].items():
            handle.write("\t".join([task_id, str(row["old"])] + [str(row.get(m)) for m in modes]
                                   + [str(row.get("replay_match"))]) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k.endswith("_pass") or k == "n"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
