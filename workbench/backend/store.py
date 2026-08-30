from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from .normalize import AssetRegistry, scan_workspace


class WorkbenchStore:
    def __init__(self, repo_root: Path, result_roots: list[Path], refresh_interval_seconds: float = 2.0) -> None:
        self.repo_root = repo_root
        self.result_roots = result_roots
        self.refresh_interval_seconds = refresh_interval_seconds
        self._lock = threading.Lock()
        self._last_scan = 0.0
        self._workspace: dict[str, Any] | None = None
        self._run_details: dict[str, dict[str, Any]] = {}
        self._execution_details: dict[str, dict[str, Any]] = {}
        self._assets = AssetRegistry()

    def get_workspace(self, force_refresh: bool = False) -> dict[str, Any]:
        with self._lock:
            self._refresh(force_refresh=force_refresh)
            return self._workspace or {}

    def get_run(self, run_id: str, force_refresh: bool = False) -> dict[str, Any] | None:
        with self._lock:
            self._refresh(force_refresh=force_refresh)
            return self._run_details.get(run_id)

    def get_execution(self, execution_id: str, force_refresh: bool = False) -> dict[str, Any] | None:
        with self._lock:
            self._refresh(force_refresh=force_refresh)
            return self._execution_details.get(execution_id)

    def get_asset(self, asset_id: str, force_refresh: bool = False) -> dict[str, Any] | None:
        with self._lock:
            self._refresh(force_refresh=force_refresh)
            return self._assets.lookup(asset_id)

    def _refresh(self, force_refresh: bool) -> None:
        is_stale = (time.time() - self._last_scan) >= self.refresh_interval_seconds
        if self._workspace is not None and not force_refresh and not is_stale:
            return
        workspace, run_details, execution_details, assets = scan_workspace(self.repo_root, self.result_roots)
        self._workspace = workspace
        self._run_details = run_details
        self._execution_details = execution_details
        self._assets = assets
        self._last_scan = time.time()
