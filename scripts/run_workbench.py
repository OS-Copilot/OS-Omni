#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workbench.backend.server import run_server
from workbench.backend.store import WorkbenchStore


HOST = "127.0.0.1"
PORT = 8765


def main() -> None:
    workbench_root = REPO_ROOT / "workbench"
    frontend_root = workbench_root / "frontend"
    result_roots = [REPO_ROOT / "results"]
    store = WorkbenchStore(
        repo_root=REPO_ROOT,
        result_roots=result_roots,
    )
    print(f"Benchmark Workbench running on http://{HOST}:{PORT}")
    print("Scanning roots:")
    for root in result_roots:
        print(f"  - {root}")
    run_server(host=HOST, port=PORT, store=store, frontend_root=frontend_root)


if __name__ == "__main__":
    main()
