"""Helpers for seeding and validating Flow app state in an iOS simulator."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

from platforms.ios.runtime_env.simulator_manager import get_app_data_container_path


DEFAULT_BUNDLE_ID = "mn.flow.flow"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FLOW_REPO_PATH = "platforms/ios/flow_benchmark"
FLOW_REPO_PATH_ENV_VARS = ("HELLOWORLD_FLOW_REPO_PATH", "FLOW_REPO_PATH")
DEFAULT_SUBDIRECTORY = "__debug"
BENCHMARK_JSON_PREFIX = "__FLOW_BENCHMARK_JSON__"
DEFAULT_FLUTTER_TEST_TIMEOUT = "5m"
PUB_GET_TIMEOUT_SECONDS = 180


def resolve_flow_repo_path(flow_repo_path: str | Path | None = None) -> Path:
    """Resolve Flow helper paths relative to this repository."""

    raw_path = str(flow_repo_path or "").strip()
    if not raw_path:
        for env_var in FLOW_REPO_PATH_ENV_VARS:
            raw_path = os.environ.get(env_var, "").strip()
            if raw_path:
                break
    if not raw_path:
        raw_path = DEFAULT_FLOW_REPO_PATH

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


class IOSFlowStore:
    """Bridge into Flow's own Dart/ObjectBox tooling for benchmark state setup."""

    def __init__(
        self,
        *,
        flow_repo_path: str | Path | None = None,
        bundle_id: str = DEFAULT_BUNDLE_ID,
        app_support_directory: str | Path,
        data_container_path: str | Path | None = None,
        subdirectory: str = DEFAULT_SUBDIRECTORY,
    ) -> None:
        self.flow_repo_path = resolve_flow_repo_path(flow_repo_path)
        self.bundle_id = str(bundle_id or DEFAULT_BUNDLE_ID).strip() or DEFAULT_BUNDLE_ID
        self.app_support_directory = Path(app_support_directory).expanduser().resolve()
        self.data_container_path = (
            Path(data_container_path).expanduser().resolve()
            if data_container_path is not None
            else self.app_support_directory.parent.parent
        )
        self.subdirectory = str(subdirectory or DEFAULT_SUBDIRECTORY).strip() or DEFAULT_SUBDIRECTORY

    @classmethod
    def from_simulator(
        cls,
        udid: str,
        *,
        bundle_id: str = DEFAULT_BUNDLE_ID,
        flow_repo_path: str | Path | None = None,
        subdirectory: str = DEFAULT_SUBDIRECTORY,
    ) -> "IOSFlowStore":
        data_container_path = Path(get_app_data_container_path(udid, bundle_id)).expanduser().resolve()
        app_support_directory = data_container_path / "Library" / "Application Support"
        return cls(
            flow_repo_path=flow_repo_path,
            bundle_id=bundle_id,
            app_support_directory=app_support_directory,
            data_container_path=data_container_path,
            subdirectory=subdirectory,
        )

    def seed(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        return self._run_tool("seed", spec)

    def assert_state(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        result = self._run_tool("assert-state", spec)
        if str(result.get("status") or "").lower() != "fail":
            return result

        summary = result.get("summary")
        if not isinstance(summary, Mapping):
            return result

        relaxed_result = _assert_state_against_summary(spec, summary)
        if str(relaxed_result.get("status") or "").lower() == "pass":
            relaxed_result["message"] = (
                "Flow ObjectBox state matches expectations with normalized descriptions"
            )
            relaxed_result["original_failures"] = result.get("failures") or []
        return relaxed_result


    def summary(self, spec: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._run_tool("summary", spec or {})

    def clear_saved_state(self) -> None:
        candidates = [
            self.data_container_path
            / "Library"
            / "Saved Application State"
            / f"{self.bundle_id}.savedState",
            self.data_container_path
            / "Library"
            / "SplashBoard"
            / "Snapshots"
            / f"sceneID:{self.bundle_id}-default",
            self.data_container_path
            / "Library"
            / "SplashBoard"
            / "Snapshots"
            / f"{self.bundle_id} - {{DEFAULT GROUP}}",
        ]
        for candidate in candidates:
            if candidate.exists():
                shutil.rmtree(candidate, ignore_errors=True)

    def _run_tool(self, command: str, spec: Mapping[str, Any]) -> dict[str, Any]:
        if not self.flow_repo_path.exists():
            raise FileNotFoundError(
                "Flow benchmark helper path does not exist: "
                f"{self.flow_repo_path}. Install the helper at this path or set "
                "HELLOWORLD_FLOW_REPO_PATH/FLOW_REPO_PATH."
            )
        self._ensure_flutter_dependencies()
        self._ensure_objectbox_library()

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(spec, handle, ensure_ascii=False, indent=2)
            spec_path = Path(handle.name)

        try:
            proc = subprocess.run(
                [
                    "flutter",
                    "test",
                    "test/benchmark_flow_state_test.dart",
                    "--timeout",
                    DEFAULT_FLUTTER_TEST_TIMEOUT,
                    "--reporter",
                    "compact",
                    f"--dart-define=FLOW_BENCHMARK_COMMAND={command}",
                    f"--dart-define=FLOW_BENCHMARK_SPEC={spec_path}",
                    f"--dart-define=FLOW_BENCHMARK_CUSTOM_DIRECTORY={self.app_support_directory}",
                    f"--dart-define=FLOW_BENCHMARK_SUBDIRECTORY={self.subdirectory}",
                ],
                cwd=str(self.flow_repo_path),
                capture_output=True,
                text=True,
                timeout=240,
                check=False,
            )
        finally:
            spec_path.unlink(missing_ok=True)

        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()

        payload: dict[str, Any] | None = None
        if stdout:
            for line in reversed(stdout.splitlines()):
                line = line.strip()
                if not line:
                    continue
                if line.startswith(BENCHMARK_JSON_PREFIX):
                    line = line[len(BENCHMARK_JSON_PREFIX) :].strip()
                try:
                    candidate = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(candidate, dict):
                    payload = candidate
                    break

        if payload is None:
            raise RuntimeError(
                f"Flow benchmark tool produced no JSON output for '{command}'.\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )

        if proc.returncode != 0 and str(payload.get("status") or "").lower() not in {"fail", "pass"}:
            raise RuntimeError(
                f"Flow benchmark tool failed for '{command}' with code {proc.returncode}: "
                f"{payload.get('message') or stderr or stdout}"
            )

        return payload

    def _ensure_objectbox_library(self) -> None:
        target_dir = self.flow_repo_path / "lib"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "libobjectbox.dylib"

        source_candidates = [
            self.flow_repo_path
            / "ios"
            / "ObjectBoxLocal"
            / "ObjectBox.xcframework"
            / "macos-arm64_x86_64"
            / "ObjectBox.framework"
            / "Versions"
            / "A"
            / "ObjectBox",
            self.flow_repo_path
            / "build"
            / "macos"
            / "Build"
            / "Products"
            / "Debug"
            / "ObjectBox.framework"
            / "Versions"
            / "A"
            / "ObjectBox",
        ]
        source_path = next((candidate for candidate in source_candidates if candidate.exists()), None)
        if source_path is None:
            raise FileNotFoundError("Could not locate Flow's macOS ObjectBox binary for benchmark helper")

        # The vendored framework's top-level link was flattened into a text
        # file. Bind the helper directly to its actual versioned binary.
        if target_path.is_symlink():
            if target_path.resolve() == source_path.resolve():
                return
            target_path.unlink()
        elif target_path.exists():
            return

        try:
            target_path.symlink_to(source_path)
        except FileExistsError:
            pass

    def _ensure_flutter_dependencies(self) -> None:
        package_config = self.flow_repo_path / ".dart_tool" / "package_config.json"
        if package_config.exists():
            return

        proc = subprocess.run(
            ["flutter", "pub", "get"],
            cwd=str(self.flow_repo_path),
            capture_output=True,
            text=True,
            timeout=PUB_GET_TIMEOUT_SECONDS,
            check=False,
        )
        if proc.returncode != 0:
            stdout = (proc.stdout or "").strip()
            stderr = (proc.stderr or "").strip()
            raise RuntimeError(
                "Failed to run `flutter pub get` for Flow benchmark helper "
                f"at {self.flow_repo_path}.\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )


def _assert_state_against_summary(
    spec: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Mirror Flow's benchmark assertion while tolerating note-only punctuation drift."""

    failures: list[str] = []
    observed_accounts = {
        _string(account.get("name")): account
        for account in _coerce_mapping_list(summary.get("accounts"))
    }
    observed_transactions = _coerce_mapping_list(summary.get("transactions"))

    for expectation in _coerce_mapping_list(spec.get("present_transactions")):
        matched = any(
            _transaction_matches(transaction, expectation)
            for transaction in observed_transactions
        )
        if not matched:
            serialized = json.dumps(expectation, separators=(",", ":"))
            failures.append(f"missing transaction {serialized}")

    for title in _coerce_text_list(spec.get("absent_titles")):
        present = any(
            _string(transaction.get("title")) == title
            for transaction in observed_transactions
        )
        if present:
            failures.append(f"unexpected title still present: {title}")

    account_balances = spec.get("account_balances")
    if isinstance(account_balances, Mapping):
        for account_name, expected_balance in account_balances.items():
            observed = observed_accounts.get(_string(account_name))
            if observed is None:
                failures.append(f"missing account {account_name}")
                continue
            actual_balance = _round_money(observed.get("balance"))
            wanted_balance = _round_money(expected_balance)
            if actual_balance != wanted_balance:
                failures.append(
                    f"account {account_name} balance expected {wanted_balance} but got {actual_balance}"
                )

    transaction_count = spec.get("transaction_count")
    if transaction_count is not None:
        actual_count = len(observed_transactions)
        expected_count = int(str(transaction_count))
        if actual_count != expected_count:
            failures.append(
                f"transaction count expected {transaction_count} but got {actual_count}"
            )

    return {
        "status": "pass" if not failures else "fail",
        "message": (
            "Flow ObjectBox state matches expectations"
            if not failures
            else "Flow ObjectBox state does not match expectations"
        ),
        "failures": failures,
        "summary": summary,
    }


def _transaction_matches(
    observed: Mapping[str, Any],
    expectation: Mapping[str, Any],
) -> bool:
    for key in (
        "type",
        "amount",
        "title",
        "description",
        "account",
        "category",
        "to_account",
        "from_account",
    ):
        expected = expectation.get(key)
        if expected is None:
            continue
        actual = observed.get(key)
        if key == "amount":
            if _round_money(actual) != _round_money(expected):
                return False
        elif key == "description":
            if _normalize_note_text(actual) != _normalize_note_text(expected):
                return False
        elif _string(actual) != _string(expected):
            return False

    if "is_pending" in expectation and observed.get("is_pending") != expectation.get(
        "is_pending"
    ):
        return False
    return True


def _normalize_note_text(value: Any) -> str:
    text = _string(value).replace("\\.", ".")
    text = " ".join(text.split())
    if text.endswith("."):
        text = text[:-1].rstrip()
    return text


def _round_money(value: Any) -> float:
    return round(float(value or 0), 2)


def _string(value: Any) -> str:
    return str(value or "").strip()


def _coerce_mapping_list(raw: Any) -> list[Mapping[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _coerce_text_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    for item in raw:
        text = _string(item)
        if text:
            values.append(text)
    return values
