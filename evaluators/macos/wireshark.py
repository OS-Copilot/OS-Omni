"""Evaluate exported Wireshark artifacts on macOS."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent
from typing import Any, Mapping, Sequence

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus

_SCAN_ARTIFACTS_SCRIPT = r'''
import json
import os
import time
from pathlib import Path

params = json.loads(__PARAMS_JSON__)
artifacts = list(params.get("artifacts") or [])
poll_attempts = max(1, int(params.get("poll_attempts") or 10))
poll_interval_ms = max(0, int(params.get("poll_interval_ms") or 500))
result = {
    "status": "fail",
    "message": "Wireshark artifact checks failed",
    "artifacts": [],
    "failures": [],
}

if not artifacts:
    result["status"] = "error"
    result["message"] = "Wireshark evaluator requires at least one artifact"
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0)


def _as_text_list(value):
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


for attempt in range(1, poll_attempts + 1):
    attempt_failures = []
    attempt_artifacts = []

    for raw_spec in artifacts:
        spec = dict(raw_spec or {})
        kind = str(spec.get("kind") or "file").strip().lower()
        raw_path = str(spec.get("path") or "").strip()
        entry = {
            "kind": kind,
            "path": raw_path,
        }

        if not raw_path:
            attempt_failures.append("artifact path is required")
            attempt_artifacts.append(entry)
            continue

        path = Path(os.path.expanduser(raw_path))
        entry["resolved_path"] = str(path)

        if kind == "file":
            entry["exists"] = path.is_file()
            if not entry["exists"]:
                attempt_failures.append(f"missing file: {path}")
                attempt_artifacts.append(entry)
                continue

            size = path.stat().st_size
            min_bytes = int(spec.get("min_bytes") or 1)
            entry["size"] = size
            entry["min_bytes"] = min_bytes
            if size < min_bytes:
                attempt_failures.append(
                    f"file too small: {path} ({size} bytes < {min_bytes})"
                )

            text_contains = _as_text_list(spec.get("text_contains"))
            if text_contains:
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except Exception as exc:
                    attempt_failures.append(f"failed to read text from {path}: {exc}")
                else:
                    missing = [needle for needle in text_contains if needle not in text]
                    entry["text_contains"] = text_contains
                    if missing:
                        attempt_failures.append(
                            f"text markers missing in {path}: {missing}"
                        )

        elif kind == "dir":
            entry["exists"] = path.is_dir()
            if not entry["exists"]:
                attempt_failures.append(f"missing directory: {path}")
                attempt_artifacts.append(entry)
                continue

            file_count = sum(1 for item in path.rglob("*") if item.is_file())
            min_file_count = int(spec.get("min_file_count") or 1)
            entry["file_count"] = file_count
            entry["min_file_count"] = min_file_count
            if file_count < min_file_count:
                attempt_failures.append(
                    f"directory has too few files: {path} ({file_count} < {min_file_count})"
                )
        else:
            attempt_failures.append(f"unsupported artifact kind '{kind}' for {path}")

        attempt_artifacts.append(entry)

    result["attempt"] = attempt
    result["artifacts"] = attempt_artifacts
    result["failures"] = attempt_failures

    if not attempt_failures:
        break

    if attempt < poll_attempts and poll_interval_ms > 0:
        time.sleep(poll_interval_ms / 1000.0)

if result["failures"]:
    result["status"] = "fail"
    result["message"] = "; ".join(result["failures"])
else:
    result["status"] = "pass"
    result["message"] = "Wireshark artifacts match expected outputs"

print(json.dumps(result, ensure_ascii=False))
'''


class WiresharkArtifactEvaluator(BaseEvaluator):
    """Verify Wireshark exports such as pcapng files, text reports, and object folders."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        run_dir_raw = context.get("run_dir")

        if controller is None or not hasattr(controller, "run_python_script"):
            return EvalResult(
                status=EvalStatus.ERROR,
                message="controller.run_python_script is required",
            )

        artifacts = list(params.get("artifacts") or [])
        if not artifacts:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="Wireshark evaluator requires artifacts",
            )

        script = dedent(_SCAN_ARTIFACTS_SCRIPT).replace(
            "__PARAMS_JSON__",
            repr(json.dumps({"artifacts": artifacts}, ensure_ascii=False)),
        )

        try:
            result = controller.run_python_script(script, timeout=int(params.get("timeout", 90) or 90))
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"Wireshark evaluation failed: {exc}")

        payload_raw = result.get("stdout") or result.get("output") or ""
        try:
            payload = json.loads(payload_raw)
        except Exception:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="Wireshark evaluator returned non-JSON output",
                metadata={"runtime_result": result},
            )

        local_copies: dict[str, str] = {}
        if run_dir_raw and hasattr(controller, "get_file"):
            eval_dir = Path(run_dir_raw) / "_evaluator"
            eval_dir.mkdir(parents=True, exist_ok=True)
            for artifact in artifacts:
                if str(artifact.get("kind") or "file").strip().lower() != "file":
                    continue
                remote_path = str(artifact.get("path") or "").strip()
                if not remote_path:
                    continue
                try:
                    file_bytes = controller.get_file(remote_path)
                except Exception:
                    continue
                local_path = eval_dir / Path(remote_path).name
                try:
                    local_path.write_bytes(file_bytes)
                except OSError:
                    continue
                local_copies[remote_path] = str(local_path)

        payload["local_copies"] = local_copies
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
            message=str(payload.get("message") or "Wireshark evaluation completed"),
            metadata=payload,
        )


def _observation_value(observation: Any, key: str) -> Any:
    if isinstance(observation, Mapping):
        return observation.get(key)
    return getattr(observation, key, None)


def _as_nonempty_str_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _probe_wireshark_group1_checkboxes(
    controller: Any,
    *,
    window_title_substrings: Sequence[str],
    labels: Sequence[str],
    timeout: int = 20,
) -> dict[str, dict[str, str]]:
    if controller is None:
        return {}

    requested_windows = [item for item in _as_nonempty_str_list(window_title_substrings)]
    requested_labels = [item for item in _as_nonempty_str_list(labels)]
    if not requested_windows or not requested_labels:
        return {}

    def _python_probe_script() -> str:
        payload_literal = repr(
            json.dumps(
                {
                    "window_title_substrings": requested_windows,
                    "labels": requested_labels,
                },
                ensure_ascii=False,
            )
        )
        lines = [
            "import json",
            "import subprocess",
            "",
            f"payload = json.loads({payload_literal})",
            "results = {}",
            "",
            "def applescript_literal(raw: str) -> str:",
            "    return '\"' + raw.replace('\\\\', '\\\\\\\\').replace('\"', '\\\\\"') + '\"'",
            "",
            "for window_substring in payload.get(\"window_title_substrings\", []):",
            "    label_values = {}",
            "    for label in payload.get(\"labels\", []):",
            "        applescript = f'''",
            "tell application \"System Events\"",
            "  tell process \"Wireshark\"",
            "    try",
            "      set targetWindow to first window whose name contains {applescript_literal(window_substring)}",
            "      tell group 1 of targetWindow",
            "        repeat with cb in every checkbox",
            "          if (name of cb as text) is {applescript_literal(label)} then",
            "            return value of cb as text",
            "          end if",
            "        end repeat",
            "      end tell",
            "    end try",
            "    return \"\"",
            "  end tell",
            "end tell",
            "'''",
            "        proc = subprocess.run(",
            "            [\"osascript\"],",
            "            input=applescript,",
            "            capture_output=True,",
            "            text=True,",
            "            check=False,",
            "            timeout=8,",
            "        )",
            "        label_values[str(label)] = (",
            "            proc.stdout.strip()",
            "            if proc.returncode == 0",
            "            else \"\"",
            "        )",
            "    results[str(window_substring)] = label_values",
            "",
            "print(json.dumps(results, ensure_ascii=False))",
        ]
        return "\n".join(lines) + "\n"

    def _parse_probe_result(result: Any) -> dict[str, dict[str, str]] | None:
        if not isinstance(result, Mapping):
            return None

        status_name = str(result.get("status") or "").strip().lower()
        returncode = result.get("returncode")
        if status_name == "error" or (isinstance(returncode, int) and returncode != 0):
            return None

        payload_raw = result.get("stdout") or result.get("output") or ""
        try:
            payload = json.loads(payload_raw)
        except Exception:
            return None

        normalized: dict[str, dict[str, str]] = {}
        if not isinstance(payload, Mapping):
            return None
        for raw_window, raw_label_map in payload.items():
            window_key = str(raw_window).strip()
            if not window_key or not isinstance(raw_label_map, Mapping):
                continue
            label_map: dict[str, str] = {}
            for raw_label, raw_value in raw_label_map.items():
                label_key = str(raw_label).strip()
                if not label_key:
                    continue
                label_map[label_key] = str(raw_value or "").strip()
            normalized[window_key] = label_map
        return normalized

    result = None
    if hasattr(controller, "run_bash_script"):
        bash_lines = ["set -e", "python3 - <<'PY'"]
        bash_lines.append(_python_probe_script().rstrip())
        bash_lines.append("PY")
        try:
            result = controller.run_bash_script("\n".join(bash_lines) + "\n", timeout=timeout)
        except Exception:
            result = None
        else:
            normalized = _parse_probe_result(result)
            if normalized is not None:
                return normalized

    if hasattr(controller, "run_python_script"):
        try:
            result = controller.run_python_script(_python_probe_script(), timeout=timeout)
        except Exception:
            return {}
    elif result is None:
        return {}

    normalized = _parse_probe_result(result)
    return normalized or {}


def _probe_wireshark_combobox_texts(
    controller: Any,
    *,
    window_title_queries: Sequence[str],
    timeout: int = 20,
) -> dict[str, list[dict[str, str]]]:
    if controller is None:
        return {}

    requested_queries = [item for item in _as_nonempty_str_list(window_title_queries)]
    if not requested_queries:
        return {}

    def _python_probe_script() -> str:
        payload_literal = repr(json.dumps({"window_title_queries": requested_queries}, ensure_ascii=False))
        lines = [
            "import json",
            "import subprocess",
            "",
            f"payload = json.loads({payload_literal})",
            "results = {}",
            "",
            "def applescript_literal(raw: str) -> str:",
            "    return '\"' + raw.replace('\\\\', '\\\\\\\\').replace('\"', '\\\\\"') + '\"'",
            "",
            "for window_query in payload.get(\"window_title_queries\", []):",
            "    applescript = f'''",
            "tell application \"System Events\"",
            "  tell process \"Wireshark\"",
            "    set targetWindow to missing value",
            "    repeat with w in every window",
            "      try",
            "        if (name of w as text) is {applescript_literal(window_query)} then",
            "          set targetWindow to w",
            "          exit repeat",
            "        end if",
            "      end try",
            "    end repeat",
            "    if targetWindow is missing value then",
            "      try",
            "        set targetWindow to first window whose name contains {applescript_literal(window_query)}",
            "      end try",
            "    end if",
            "    if targetWindow is missing value then",
            "      return \"\"",
            "    end if",
            "    set outputLines to {}",
            "    repeat with cb in every combo box of targetWindow",
            "      set comboName to \"\"",
            "      set comboValue to \"\"",
            "      try",
            "        set comboName to (name of cb as text)",
            "      end try",
            "      try",
            "        set comboValue to (value of cb as text)",
            "      end try",
            "      set end of outputLines to comboName & \"|\" & comboValue",
            "    end repeat",
            "    set AppleScript's text item delimiters to linefeed",
            "    set joinedOutput to outputLines as text",
            "    set AppleScript's text item delimiters to \"\"",
            "    return joinedOutput",
            "  end tell",
            "end tell",
            "'''",
            "    proc = subprocess.run(",
            "        [\"osascript\"],",
            "        input=applescript,",
            "        capture_output=True,",
            "        text=True,",
            "        check=False,",
            "        timeout=8,",
            "    )",
            "    entries = []",
            "    if proc.returncode == 0:",
            "        for raw_line in proc.stdout.splitlines():",
            "            line = raw_line.strip()",
            "            if not line:",
            "                continue",
            "            if \"|\" in line:",
            "                combo_name, combo_value = line.split(\"|\", 1)",
            "            else:",
            "                combo_name, combo_value = line, \"\"",
            "            entries.append({\"name\": combo_name.strip(), \"value\": combo_value.strip()})",
            "    results[str(window_query)] = entries",
            "",
            "print(json.dumps(results, ensure_ascii=False))",
        ]
        return "\n".join(lines) + "\n"

    def _parse_probe_result(result: Any) -> dict[str, list[dict[str, str]]] | None:
        if not isinstance(result, Mapping):
            return None

        status_name = str(result.get("status") or "").strip().lower()
        returncode = result.get("returncode")
        if status_name == "error" or (isinstance(returncode, int) and returncode != 0):
            return None

        payload_raw = result.get("stdout") or result.get("output") or ""
        try:
            payload = json.loads(payload_raw)
        except Exception:
            return None

        if not isinstance(payload, Mapping):
            return None

        normalized: dict[str, list[dict[str, str]]] = {}
        for raw_query, raw_entries in payload.items():
            query_key = str(raw_query).strip()
            if not query_key or not isinstance(raw_entries, Sequence) or isinstance(raw_entries, (str, bytes, bytearray)):
                continue
            entries: list[dict[str, str]] = []
            for raw_entry in raw_entries:
                if not isinstance(raw_entry, Mapping):
                    continue
                combo_name = str(raw_entry.get("name") or "").strip()
                combo_value = str(raw_entry.get("value") or "").strip()
                if combo_value.lower() == "missing value":
                    combo_value = ""
                if not combo_name and not combo_value:
                    continue
                entries.append({"name": combo_name, "value": combo_value})
            normalized[query_key] = entries
        return normalized

    result = None
    if hasattr(controller, "run_bash_script"):
        bash_lines = ["set -e", "python3 - <<'PY'"]
        bash_lines.append(_python_probe_script().rstrip())
        bash_lines.append("PY")
        try:
            result = controller.run_bash_script("\n".join(bash_lines) + "\n", timeout=timeout)
        except Exception:
            result = None
        else:
            normalized = _parse_probe_result(result)
            if normalized is not None:
                return normalized

    if hasattr(controller, "run_python_script"):
        try:
            result = controller.run_python_script(_python_probe_script(), timeout=timeout)
        except Exception:
            return {}
    elif result is None:
        return {}

    normalized = _parse_probe_result(result)
    return normalized or {}


def _probe_wireshark_all_combobox_texts(
    controller: Any,
    *,
    timeout: int = 20,
) -> list[dict[str, str]]:
    if controller is None:
        return []

    script = "\n".join(
        [
            "import json",
            "import subprocess",
            "",
            "applescript = '''",
            "tell application \"System Events\"",
            "  tell process \"Wireshark\"",
            "    set outputLines to {}",
            "    repeat with w in every window",
            "      set windowName to \"\"",
            "      try",
            "        set windowName to (name of w as text)",
            "      end try",
            "      repeat with cb in every combo box of w",
            "        set comboName to \"\"",
            "        set comboValue to \"\"",
            "        try",
            "          set comboName to (name of cb as text)",
            "        end try",
            "        try",
            "          set comboValue to (value of cb as text)",
            "        end try",
            "        set end of outputLines to windowName & tab & comboName & tab & comboValue",
            "      end repeat",
            "    end repeat",
            "    set AppleScript's text item delimiters to linefeed",
            "    set joinedOutput to outputLines as text",
            "    set AppleScript's text item delimiters to \"\"",
            "    return joinedOutput",
            "  end tell",
            "end tell",
            "'''",
            "proc = subprocess.run(",
            "    [\"osascript\"],",
            "    input=applescript,",
            "    capture_output=True,",
            "    text=True,",
            "    check=False,",
            "    timeout=8,",
            ")",
            "entries = []",
            "if proc.returncode == 0:",
            "    for raw_line in proc.stdout.splitlines():",
            "        line = raw_line.strip()",
            "        if not line:",
            "            continue",
            "        parts = line.split(\"\\t\")",
            "        while len(parts) < 3:",
            "            parts.append(\"\")",
            "        window_name, combo_name, combo_value = parts[:3]",
            "        if combo_value.strip().lower() == \"missing value\":",
            "            combo_value = \"\"",
            "        entries.append({",
            "            \"window\": window_name.strip(),",
            "            \"name\": combo_name.strip(),",
            "            \"value\": combo_value.strip(),",
            "        })",
            "print(json.dumps(entries, ensure_ascii=False))",
            "",
        ]
    )

    def _parse_result(result: Any) -> list[dict[str, str]] | None:
        if not isinstance(result, Mapping):
            return None
        status_name = str(result.get("status") or "").strip().lower()
        returncode = result.get("returncode")
        if status_name == "error" or (isinstance(returncode, int) and returncode != 0):
            return None
        payload_raw = result.get("stdout") or result.get("output") or ""
        try:
            payload = json.loads(payload_raw)
        except Exception:
            return None
        if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes, bytearray)):
            return None
        normalized: list[dict[str, str]] = []
        for raw_entry in payload:
            if not isinstance(raw_entry, Mapping):
                continue
            window_name = str(raw_entry.get("window") or "").strip()
            combo_name = str(raw_entry.get("name") or "").strip()
            combo_value = str(raw_entry.get("value") or "").strip()
            if not window_name and not combo_name and not combo_value:
                continue
            normalized.append(
                {
                    "window": window_name,
                    "name": combo_name,
                    "value": combo_value,
                }
            )
        return normalized

    result = None
    if hasattr(controller, "run_bash_script"):
        bash_lines = ["set -e", "python3 - <<'PY'", script.rstrip(), "PY"]
        try:
            result = controller.run_bash_script("\n".join(bash_lines) + "\n", timeout=timeout)
        except Exception:
            result = None
        else:
            parsed = _parse_result(result)
            if parsed is not None:
                return parsed

    if hasattr(controller, "run_python_script"):
        try:
            result = controller.run_python_script(script, timeout=timeout)
        except Exception:
            return []
    elif result is None:
        return []

    parsed = _parse_result(result)
    return parsed or []


def _probe_wireshark_window_texts(
    controller: Any,
    *,
    window_title_queries: Sequence[str],
    timeout: int = 20,
) -> dict[str, list[str]]:
    if controller is None:
        return {}

    requested_queries = [item for item in _as_nonempty_str_list(window_title_queries)]
    if not requested_queries:
        return {}

    def _python_probe_script() -> str:
        payload_literal = repr(json.dumps({"window_title_queries": requested_queries}, ensure_ascii=False))
        lines = [
            "import json",
            "import subprocess",
            "",
            f"payload = json.loads({payload_literal})",
            "results = {}",
            "",
            "def applescript_literal(raw: str) -> str:",
            "    return '\"' + raw.replace('\\\\', '\\\\\\\\').replace('\"', '\\\\\"') + '\"'",
            "",
            "for window_query in payload.get(\"window_title_queries\", []):",
            "    applescript = f'''",
            "tell application \"System Events\"",
            "  tell process \"Wireshark\"",
            "    set targetWindow to missing value",
            "    repeat with w in every window",
            "      try",
            "        if (name of w as text) is {applescript_literal(window_query)} then",
            "          set targetWindow to w",
            "          exit repeat",
            "        end if",
            "      end try",
            "    end repeat",
            "    if targetWindow is missing value then",
            "      try",
            "        set targetWindow to first window whose name contains {applescript_literal(window_query)}",
            "      end try",
            "    end if",
            "    if targetWindow is missing value then",
            "      return \"\"",
            "    end if",
            "    set outputLines to {}",
            "    repeat with st in every static text of targetWindow",
            "      try",
            "        set end of outputLines to (value of st as text)",
            "      end try",
            "    end repeat",
            "    repeat with grp in every group of targetWindow",
            "      try",
            "        if (value of grp) is not missing value then",
            "          set end of outputLines to (value of grp as text)",
            "        end if",
            "      end try",
            "      try",
            "        if (name of grp) is not missing value then",
            "          set end of outputLines to (name of grp as text)",
            "        end if",
            "      end try",
            "    end repeat",
            "    set AppleScript's text item delimiters to linefeed",
            "    set joinedOutput to outputLines as text",
            "    set AppleScript's text item delimiters to \"\"",
            "    return joinedOutput",
            "  end tell",
            "end tell",
            "'''",
            "    proc = subprocess.run(",
            "        [\"osascript\"],",
            "        input=applescript,",
            "        capture_output=True,",
            "        text=True,",
            "        check=False,",
            "        timeout=8,",
            "    )",
            "    values = []",
            "    if proc.returncode == 0:",
            "        for raw_line in proc.stdout.splitlines():",
            "            line = raw_line.strip()",
            "            if line:",
            "                values.append(line)",
            "    results[str(window_query)] = values",
            "",
            "print(json.dumps(results, ensure_ascii=False))",
        ]
        return "\n".join(lines) + "\n"

    def _parse_probe_result(result: Any) -> dict[str, list[str]] | None:
        if not isinstance(result, Mapping):
            return None
        status_name = str(result.get("status") or "").strip().lower()
        returncode = result.get("returncode")
        if status_name == "error" or (isinstance(returncode, int) and returncode != 0):
            return None
        payload_raw = result.get("stdout") or result.get("output") or ""
        try:
            payload = json.loads(payload_raw)
        except Exception:
            return None
        if not isinstance(payload, Mapping):
            return None
        normalized: dict[str, list[str]] = {}
        for raw_query, raw_values in payload.items():
            query_key = str(raw_query).strip()
            if not query_key or not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes, bytearray)):
                continue
            normalized[query_key] = [str(item).strip() for item in raw_values if str(item).strip()]
        return normalized

    result = None
    if hasattr(controller, "run_bash_script"):
        bash_lines = ["set -e", "python3 - <<'PY'"]
        bash_lines.append(_python_probe_script().rstrip())
        bash_lines.append("PY")
        try:
            result = controller.run_bash_script("\n".join(bash_lines) + "\n", timeout=timeout)
        except Exception:
            result = None
        else:
            normalized = _parse_probe_result(result)
            if normalized is not None:
                return normalized

    if hasattr(controller, "run_python_script"):
        try:
            result = controller.run_python_script(_python_probe_script(), timeout=timeout)
        except Exception:
            return {}
    elif result is None:
        return {}

    normalized = _parse_probe_result(result)
    return normalized or {}


class WiresharkObservationEvaluator(BaseEvaluator):
    """Verify Wireshark UI state from the final observation."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        observation = context.get("final_observation")

        refresh_observation = bool(params.get("refresh_observation", True))
        if refresh_observation and controller is not None and hasattr(controller, "observe"):
            observation = controller.observe(include_ui_tree=True, include_screenshot_data=False)
        elif observation is None and controller is not None and hasattr(controller, "observe"):
            observation = controller.observe(include_ui_tree=True, include_screenshot_data=False)

        if observation is None:
            return EvalResult(status=EvalStatus.ERROR, message="final_observation or controller.observe is required")

        ui_nodes = list(_observation_value(observation, "ui_nodes") or [])
        if not ui_nodes:
            return EvalResult(status=EvalStatus.FAIL, message="Wireshark observation did not include ui_nodes")

        required_window_titles = [
            str(item).strip()
            for item in list(params.get("required_window_titles") or [])
            if str(item).strip()
        ]
        required_window_title_substrings = [
            str(item).strip()
            for item in list(params.get("required_window_title_substrings") or [])
            if str(item).strip()
        ]
        foreground_window_title_substring = str(params.get("foreground_window_title_substring") or "").strip()
        required_texts = [
            str(item).strip()
            for item in list(params.get("required_texts") or [])
            if str(item).strip()
        ]
        required_exact_values = [
            str(item).strip()
            for item in list(params.get("required_exact_values") or [])
            if str(item).strip()
        ]
        checkbox_values = {
            str(key).strip(): str(value).strip()
            for key, value in dict(params.get("checkbox_values") or {}).items()
            if str(key).strip()
        }
        checkbox_value_counts = {
            str(key).strip(): {
                "value": str((value or {}).get("value") or "").strip(),
                "min_matches": int((value or {}).get("min_matches") or 1),
            }
            for key, value in dict(params.get("checkbox_value_counts") or {}).items()
            if str(key).strip()
        }
        scripted_checkbox_windows = _as_nonempty_str_list(params.get("scripted_checkbox_windows"))
        scripted_combobox_texts = {
            str(key).strip(): _as_nonempty_str_list(value)
            for key, value in dict(params.get("scripted_combobox_texts") or {}).items()
            if str(key).strip()
        }
        scripted_combobox_any_texts = _as_nonempty_str_list(params.get("scripted_combobox_any_texts"))
        scripted_window_texts = {
            str(key).strip(): _as_nonempty_str_list(value)
            for key, value in dict(params.get("scripted_window_texts") or {}).items()
            if str(key).strip()
        }
        expected_filter = str(params.get("filter_text") or "").strip()

        failures: list[str] = []
        matched_windows: list[str] = []
        matched_window_substrings: list[str] = []
        matched_texts: list[str] = []
        matched_exact_values: list[str] = []
        matched_checkboxes: dict[str, str] = {}
        matched_checkbox_counts: dict[str, int] = {}
        scripted_checkbox_results: dict[str, dict[str, str]] = {}
        scripted_combobox_results: dict[str, list[dict[str, str]]] = {}
        scripted_combobox_any_results: list[dict[str, str]] = []
        scripted_window_text_results: dict[str, list[str]] = {}

        def _node_text(node: Mapping[str, Any]) -> str:
            return str(node.get("text") or "").strip()

        def _node_value(node: Mapping[str, Any]) -> str:
            return str(node.get("value") or "").strip()

        if scripted_checkbox_windows and (checkbox_values or checkbox_value_counts):
            scripted_checkbox_results = _probe_wireshark_group1_checkboxes(
                controller,
                window_title_substrings=scripted_checkbox_windows,
                labels=list({*checkbox_values.keys(), *checkbox_value_counts.keys()}),
            )
        if scripted_combobox_texts:
            scripted_combobox_results = _probe_wireshark_combobox_texts(
                controller,
                window_title_queries=list(scripted_combobox_texts.keys()),
            )
        if scripted_combobox_any_texts:
            scripted_combobox_any_results = _probe_wireshark_all_combobox_texts(
                controller,
            )
        if scripted_window_texts:
            scripted_window_text_results = _probe_wireshark_window_texts(
                controller,
                window_title_queries=list(scripted_window_texts.keys()),
            )

        foreground_window_title = next(
            (
                _node_text(node)
                for node in ui_nodes
                if isinstance(node, Mapping) and str(node.get("type") or "").strip() == "AXWindow"
            ),
            "",
        )

        for title in required_window_titles:
            if any(_node_text(node) == title for node in ui_nodes if isinstance(node, Mapping)):
                matched_windows.append(title)
            else:
                failures.append(f"missing window title: {title}")

        for title_substring in required_window_title_substrings:
            if any(title_substring in _node_text(node) for node in ui_nodes if isinstance(node, Mapping)):
                matched_window_substrings.append(title_substring)
            else:
                failures.append(f"missing window title substring: {title_substring}")

        if foreground_window_title_substring and foreground_window_title_substring not in foreground_window_title:
            failures.append(
                f"foreground window mismatch: expected substring {foreground_window_title_substring!r}, observed {foreground_window_title!r}"
            )

        if expected_filter:
            filter_match = False
            for node in ui_nodes:
                if not isinstance(node, Mapping):
                    continue
                node_text = _node_text(node)
                node_value = _node_value(node)
                role = str(node.get("roleDescription") or "").strip().lower()
                node_type = str(node.get("type") or "").strip().lower()
                if (
                    (node_text == expected_filter or node_value == expected_filter)
                    and (role in {"combo box", "text field"} or node_type in {"axcombobox", "axtextfield"})
                ):
                    filter_match = True
                    break
            if not filter_match:
                failures.append(f"display filter not visible as '{expected_filter}'")

        for text in required_texts:
            if any(
                text in _node_text(node) or text in _node_value(node)
                for node in ui_nodes
                if isinstance(node, Mapping)
            ):
                matched_texts.append(text)
            elif any(
                text in value
                for values in scripted_window_text_results.values()
                for value in values
            ):
                matched_texts.append(text)
            else:
                failures.append(f"missing text marker: {text}")

        for exact_value in required_exact_values:
            if any(
                _node_text(node) == exact_value or _node_value(node) == exact_value
                for node in ui_nodes
                if isinstance(node, Mapping)
            ):
                matched_exact_values.append(exact_value)
            else:
                failures.append(f"missing exact value: {exact_value}")

        for label, expected_value in checkbox_values.items():
            matched = None
            for node in ui_nodes:
                if not isinstance(node, Mapping):
                    continue
                if _node_text(node) != label:
                    continue
                role = str(node.get("roleDescription") or "").strip().lower()
                node_type = str(node.get("type") or "").strip().lower()
                if role != "checkbox" and node_type != "axcheckbox":
                    continue
                matched = str(node.get("value") or "").strip()
                if matched == expected_value:
                    matched_checkboxes[label] = matched
                    break
            if matched != expected_value and scripted_checkbox_results:
                for label_map in scripted_checkbox_results.values():
                    scripted_value = str(label_map.get(label) or "").strip()
                    if scripted_value == expected_value:
                        matched_checkboxes[label] = scripted_value
                        matched = scripted_value
                        break
            if matched is None:
                failures.append(f"missing checkbox: {label}")
            elif matched != expected_value:
                failures.append(f"checkbox mismatch for {label}: expected {expected_value}, observed {matched}")

        for label, spec in checkbox_value_counts.items():
            expected_value = str(spec.get("value") or "").strip()
            min_matches = max(1, int(spec.get("min_matches") or 1))
            observation_count = 0
            for node in ui_nodes:
                if not isinstance(node, Mapping):
                    continue
                if _node_text(node) != label:
                    continue
                role = str(node.get("roleDescription") or "").strip().lower()
                node_type = str(node.get("type") or "").strip().lower()
                if role != "checkbox" and node_type != "axcheckbox":
                    continue
                if _node_value(node) == expected_value:
                    observation_count += 1
            scripted_count = 0
            if scripted_checkbox_results:
                for label_map in scripted_checkbox_results.values():
                    if str(label_map.get(label) or "").strip() == expected_value:
                        scripted_count += 1
            count = max(observation_count, scripted_count)
            matched_checkbox_counts[label] = count
            if count < min_matches:
                failures.append(
                    f"checkbox count mismatch for {label}: expected at least {min_matches} with value {expected_value}, observed {count}"
                )

        for window_query, expected_texts in scripted_combobox_texts.items():
            observed_entries = scripted_combobox_results.get(window_query) or []
            observed_texts = {
                text
                for entry in observed_entries
                for text in (str(entry.get("name") or "").strip(), str(entry.get("value") or "").strip())
                if text
            }
            for expected_text in expected_texts:
                if expected_text not in observed_texts:
                    failures.append(
                        f"scripted combobox text missing for {window_query}: expected {expected_text!r}, observed {sorted(observed_texts)!r}"
                    )

        if scripted_combobox_any_texts:
            observed_any_texts = {
                text
                for entry in scripted_combobox_any_results
                for text in (
                    str(entry.get("window") or "").strip(),
                    str(entry.get("name") or "").strip(),
                    str(entry.get("value") or "").strip(),
                )
                if text
            }
            for expected_text in scripted_combobox_any_texts:
                if expected_text not in observed_any_texts:
                    failures.append(
                        f"scripted combobox text missing globally: expected {expected_text!r}, observed {sorted(observed_any_texts)!r}"
                    )

        for window_query, expected_texts in scripted_window_texts.items():
            observed_values = scripted_window_text_results.get(window_query) or []
            for expected_text in expected_texts:
                if not any(expected_text in value for value in observed_values):
                    failures.append(
                        f"scripted window text missing for {window_query}: expected {expected_text!r}, observed {observed_values!r}"
                    )

        status = EvalStatus.PASS if not failures else EvalStatus.FAIL
        message = "Wireshark UI state matches expected observation" if not failures else "; ".join(failures)
        return EvalResult(
            status=status,
            message=message,
            metadata={
                "required_window_titles": required_window_titles,
                "required_window_title_substrings": required_window_title_substrings,
                "foreground_window_title_substring": foreground_window_title_substring,
                "foreground_window_title": foreground_window_title,
                "required_texts": required_texts,
                "required_exact_values": required_exact_values,
                "matched_windows": matched_windows,
                "matched_window_substrings": matched_window_substrings,
                "matched_texts": matched_texts,
                "matched_exact_values": matched_exact_values,
                "checkbox_values": checkbox_values,
                "checkbox_value_counts": checkbox_value_counts,
                "matched_checkboxes": matched_checkboxes,
                "matched_checkbox_counts": matched_checkbox_counts,
                "scripted_checkbox_windows": scripted_checkbox_windows,
                "scripted_checkbox_results": scripted_checkbox_results,
                "scripted_combobox_texts": scripted_combobox_texts,
                "scripted_combobox_results": scripted_combobox_results,
                "scripted_combobox_any_texts": scripted_combobox_any_texts,
                "scripted_combobox_any_results": scripted_combobox_any_results,
                "scripted_window_texts": scripted_window_texts,
                "scripted_window_text_results": scripted_window_text_results,
                "filter_text": expected_filter,
                "refresh_observation": refresh_observation,
                "foreground_app": _observation_value(observation, "foreground_app"),
                "foreground_bundle_id": _observation_value(observation, "foreground_bundle_id"),
            },
        )
