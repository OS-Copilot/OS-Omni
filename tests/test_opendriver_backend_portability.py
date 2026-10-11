"""Portability checks for the vendored openDriver backend.

Static source checks (always run) plus an opt-live scratch boot on an
ephemeral non-4320 port against a temp copy of the backend (skipped when
node/npm is unavailable). No simulator, GUI, Appium, GreenMail, or live
backend use; the vendored tree itself is never started or mutated.
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
VENDORED = REPO / "services" / "opendriver_backend"
BACKEND = VENDORED / "backend"
SRC = BACKEND / "src"
SERVER_JS = SRC / "server.js"

REQUIRED_FILES = [
    "backend/src/server.js",
    "backend/src/domain.js",
    "backend/src/database/store.js",
    "backend/src/database/seed.js",
    "backend/package.json",
    "backend/package-lock.json",
    "backend/README.md",
    "backend/.env.example",
    "backend/test/domain.test.js",
    "shared-docs/API.md",
    "LICENSE.upstream",
    "PROVENANCE.md",
]

# Canonical HTTP surface the iOS tasks depend on (from server.js / API.md).
REQUIRED_ROUTES = [
    "/health",
    "/dev/reset",
    "/config/bootstrap",
    "/auth/login",
    "/rides/request",
    "/rides/active",
    "/rides/history",
    "/payments/refunds",
    "/support/tickets",
    "/driver/payouts",
]

LIVE_PORT = 4331  # fixed scratch port; live :4320 is owned by root, never used.


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_required_files_present() -> None:
    missing = [name for name in REQUIRED_FILES if not (VENDORED / name).is_file()]
    assert not missing, f"missing vendored files: {missing}"


def test_no_runtime_artifacts_vendored() -> None:
    banned = ["node_modules", "tile-cache", "road-graphs", "route-cache",
              "search-index", "opendriver-db.json", ".env", "dist", ".tvm"]
    hits = [b for b in banned if (BACKEND / b).exists() or (BACKEND / "data" / b).exists()]
    assert not hits, f"runtime artifacts must not be vendored: {hits}"


def test_package_manifest() -> None:
    manifest = json.loads(_read_text(BACKEND / "package.json"))
    assert manifest["name"] == "opendriver-backend"
    assert manifest["main"] == "src/server.js"
    assert manifest["scripts"]["start"] == "node src/server.js"
    assert manifest["scripts"]["seed"].startswith("node ")
    assert set(manifest["dependencies"]) == {"jpeg-js"}


def test_store_persistence_contract() -> None:
    store = _read_text(SRC / "database" / "store.js")
    assert "opendriver-db.json" in store
    assert "DATA_DIR" in store and "DB_PATH" in store
    assert "schemaVersion" in store and "resetDb" in store
    assert "< 16" in store  # stale schemas trigger reseed


def test_seed_baseline_contract() -> None:
    seed = _read_text(SRC / "database" / "seed.js")
    assert "schemaVersion: 16" in seed
    assert "createSeedData" in seed
    assert "rider@example.com" in seed
    # Baseline FAIL: task answers are not seeded.
    for literal in ("Fare review", "Blue umbrella", "Rear seat"):
        assert literal not in seed, f"seed must not contain task answer {literal!r}"


def test_canonical_routes_present() -> None:
    server = _read_text(SERVER_JS)
    missing = [route for route in REQUIRED_ROUTES if route not in server]
    assert not missing, f"routes missing from server.js: {missing}"
    assert 'url.pathname === "/dev/reset" && req.method === "POST"' in server
    assert "store.resetDb()" in server


def _wait_for_health(base: str, timeout_s: float = 60.0) -> None:
    deadline = time.time() + timeout_s
    last_error = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/health", timeout=3) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001 - probe loop
            last_error = str(exc)
        time.sleep(0.5)
    raise AssertionError(f"scratch backend never healthy at {base}: {last_error}")


@pytest.mark.skipif(shutil.which("node") is None or shutil.which("npm") is None,
                    reason="node/npm unavailable")
def test_scratch_backend_boots_resets_and_serves(tmp_path: Path) -> None:
    scratch = tmp_path / "od-backend"
    shutil.copytree(BACKEND, scratch, ignore=shutil.ignore_patterns("data"))
    subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=scratch,
                   check=True, capture_output=True, timeout=300)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", LIVE_PORT))  # fail fast if the scratch port is taken
    env = dict(__import__("os").environ, PORT=str(LIVE_PORT), HOST="127.0.0.1")
    proc = subprocess.Popen(["node", "src/server.js"], cwd=scratch, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        base = f"http://127.0.0.1:{LIVE_PORT}"
        _wait_for_health(base)
        reset_req = urllib.request.Request(base + "/dev/reset", method="POST")
        with urllib.request.urlopen(reset_req, timeout=10) as response:
            payload = json.load(response)
        assert payload["data"]["reset"] is True
        assert payload["data"]["meta"]["schemaVersion"] == 16
        with urllib.request.urlopen(base + "/config/bootstrap", timeout=10) as response:
            bootstrap = json.load(response)
        assert len(bootstrap["data"]["serviceCities"]) == 20
        assert (scratch / "data" / "opendriver-db.json").is_file()
    finally:
        proc.terminate()
        proc.wait(timeout=15)
    assert proc.returncode is not None  # own test process stopped
