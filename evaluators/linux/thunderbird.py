"""Thunderbird task evaluator for Linux."""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import tempfile
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class ThunderbirdTaskEvaluator(BaseEvaluator):
    """Evaluate Thunderbird tasks that use OSWorld-style rule payloads."""

    DEFAULT_TIMEOUT = 30

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        if controller is None:
            return EvalResult(status=EvalStatus.ERROR, message="controller is required")

        params = dict(context.get("params") or {})
        payload = dict(params.get("osworld_evaluator") or {})
        func = str(payload.get("func") or "").strip()
        if not func:
            return EvalResult(status=EvalStatus.ERROR, message="evaluation.params.osworld_evaluator.func is required")

        timeout = int(payload.get("timeout", self.DEFAULT_TIMEOUT) or self.DEFAULT_TIMEOUT)

        try:
            cache_files = self._run_postconfig(controller, payload.get("postconfig"), timeout=timeout)
            metadata = {"func": func}
            if func == "infeasible":
                return EvalResult(
                    status=EvalStatus.PASS,
                    message="Task is marked infeasible by evaluator configuration",
                    metadata=metadata,
                )
            result_payload = self._resolve_result_payload(
                controller,
                context=context,
                result_spec=payload.get("result"),
                cache_files=cache_files,
                timeout=timeout,
            )
            expected = dict(payload.get("expected") or {})
            metadata["result_payload"] = self._metadata_preview(result_payload)
            if func == "check_list":
                self._check_list(result_payload, expected)
            elif func == "check_csv":
                self._check_csv(result_payload, expected)
            elif func == "check_json":
                self._check_json(result_payload, expected)
            elif func == "run_sqlite3":
                self._run_sqlite3(result_payload, expected)
            elif func == "check_thunderbird_prefs":
                self._check_thunderbird_prefs(result_payload, expected)
            elif func == "check_thunderbird_filter":
                self._check_thunderbird_filter(result_payload, expected)
            elif func == "check_accessibility_tree":
                self._check_accessibility_tree(result_payload, expected)
            else:
                return EvalResult(status=EvalStatus.ERROR, message=f"unsupported thunderbird evaluator func: {func}")
        except AssertionError as exc:
            return EvalResult(status=EvalStatus.FAIL, message=str(exc), metadata=metadata)
        except Exception as exc:
            return EvalResult(
                status=EvalStatus.ERROR,
                message=f"{type(exc).__name__}: {exc}",
                metadata={"func": func},
            )

        return EvalResult(status=EvalStatus.PASS, message="Thunderbird evaluation passed", metadata=metadata)

    @staticmethod
    def _run_postconfig(controller: Any, raw_steps: Any, *, timeout: int) -> dict[str, str]:
        cache_files: dict[str, str] = {}
        if not isinstance(raw_steps, list):
            return cache_files

        for step in raw_steps:
            if not isinstance(step, Mapping):
                continue
            step_type = str(step.get("type") or "").strip()
            parameters = dict(step.get("parameters") or {})

            if step_type == "sleep":
                seconds = float(parameters.get("seconds", 0.0) or 0.0)
                if seconds > 0:
                    controller.run_bash_script(f"sleep {seconds}", timeout=max(5, int(seconds) + 5))
                continue

            if step_type == "download":
                for item in parameters.get("files") or []:
                    if not isinstance(item, Mapping):
                        continue
                    url = str(item.get("url") or "").strip()
                    path = str(item.get("path") or "").strip()
                    if url and path:
                        controller.download_file(url, path, overwrite=True)
                continue

            if step_type in {"execute", "command"}:
                command = parameters.get("command")
                if not command:
                    raise ValueError(f"{step_type} postconfig step requires parameters.command")
                shell = bool(parameters.get("shell", False))
                result = controller.execute_command(command, shell=shell, timeout=max(timeout, 30))
                returncode = int(result.get("returncode", -1))
                if returncode != 0:
                    output = str(result.get("output", "")).strip()
                    error = str(result.get("error", "")).strip()
                    raise RuntimeError(output or error or f"postconfig {step_type} failed with exit code {returncode}")
                stdout_path = str(parameters.get("stdout") or "").strip()
                if stdout_path:
                    cache_files[stdout_path] = str(result.get("output", ""))
                continue

            if step_type == "close_window":
                ThunderbirdTaskEvaluator._close_window(controller, parameters)
                continue

            raise ValueError(f"unsupported postconfig step type: {step_type}")

        return cache_files

    @staticmethod
    def _close_window(controller: Any, parameters: Mapping[str, Any]) -> None:
        window_name = str(parameters.get("window_name") or "").strip()
        if not window_name:
            raise ValueError("close_window step requires parameters.window_name")
        strict = bool(parameters.get("strict", False))
        by_class = bool(parameters.get("by_class", False))
        escaped = json.dumps(window_name)
        mode = "class" if by_class else "name"
        match = "==" if strict else "in"
        script = f"""python3 - <<'PY'
import json
import subprocess

window_name = json.loads({json.dumps(escaped)})
strict = {json.dumps(strict)}
by_class = {json.dumps(by_class)}
lines = subprocess.run(["wmctrl", "-lx"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False).stdout.splitlines()
window_ids = []
for line in lines:
    parts = line.split(None, 4)
    if len(parts) < 5:
        continue
    window_id, _, wm_class, _, title = parts
    haystack = wm_class if by_class else title
    matched = haystack == window_name if strict else window_name in haystack
    if matched:
        window_ids.append(window_id)
for window_id in window_ids:
    subprocess.run(["wmctrl", "-ic", window_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
print(json.dumps({{"closed": len(window_ids), "mode": {json.dumps(mode)}, "match": {json.dumps(match)}}}))
PY"""
        controller.run_bash_script(script, timeout=20)

    def _resolve_result_payload(
        self,
        controller: Any,
        *,
        context: Mapping[str, Any],
        result_spec: Any,
        cache_files: Mapping[str, str],
        timeout: int,
    ) -> Any:
        del timeout
        spec = dict(result_spec or {})
        result_type = str(spec.get("type") or "").strip()
        if result_type == "cache_file":
            path = str(spec.get("path") or "").strip()
            if not path:
                raise ValueError("cache_file result requires path")
            if path not in cache_files:
                raise FileNotFoundError(f"cache_file not found in postconfig outputs: {path}")
            return str(cache_files[path])
        if result_type == "vm_file":
            path = str(spec.get("path") or "").strip()
            if not path:
                raise ValueError("vm_file result requires path")
            return controller.get_file(path)
        if result_type == "accessibility_tree":
            final_observation = context.get("final_observation")
            ui_nodes = list(getattr(final_observation, "ui_nodes", []) or [])
            foreground_app = str(getattr(final_observation, "foreground_app", "") or "")
            foreground_window = str(getattr(final_observation, "foreground_window", "") or "")
            if not ui_nodes:
                observation = controller.observe(include_ui_tree=True, include_screenshot_data=False)
                ui_nodes = list(getattr(observation, "ui_nodes", []) or [])
                foreground_app = str(getattr(observation, "foreground_app", "") or "")
                foreground_window = str(getattr(observation, "foreground_window", "") or "")
            return {
                "ui_nodes": ui_nodes,
                "foreground_app": foreground_app,
                "foreground_window": foreground_window,
            }
        raise ValueError(f"unsupported result type: {result_type}")

    @staticmethod
    def _metadata_preview(payload: Any) -> Any:
        if isinstance(payload, bytes):
            return {"bytes": len(payload)}
        if isinstance(payload, str):
            return payload[:2000]
        if isinstance(payload, Mapping):
            preview = dict(payload)
            if "ui_nodes" in preview and isinstance(preview["ui_nodes"], list):
                preview["ui_nodes"] = preview["ui_nodes"][:20]
                preview["ui_node_count"] = len(payload.get("ui_nodes", []))
            return preview
        return payload

    @staticmethod
    def _expect_rule(expected: Mapping[str, Any]) -> Mapping[str, Any] | list[Any]:
        if str(expected.get("type") or "") != "rule":
            raise ValueError("expected.type must be rule")
        rules = expected.get("rules")
        if not isinstance(rules, Mapping) and not isinstance(rules, list):
            raise ValueError("expected.rules must be a mapping or list")
        return rules

    def _check_list(self, payload: Any, expected: Mapping[str, Any]) -> None:
        text = self._decode_text(payload)
        rules = self._expect_rule(expected)
        if isinstance(rules, list):
            expect_patterns = [str(item) for item in rules]
            unexpect_patterns: list[str] = []
        else:
            expect_patterns = [str(item) for item in rules.get("expect") or []]
            unexpect_patterns = [str(item) for item in rules.get("unexpect") or []]
        for pattern in expect_patterns:
            assert re.search(pattern, text, re.MULTILINE), f"expected pattern not found: {pattern}"
        for pattern in unexpect_patterns:
            assert not re.search(pattern, text, re.MULTILINE), f"unexpected pattern matched: {pattern}"

    def _check_csv(self, payload: Any, expected: Mapping[str, Any]) -> None:
        text = self._decode_text(payload)
        rows = list(csv.DictReader(io.StringIO(text)))
        rules = self._expect_rule(expected)
        if not isinstance(rules, Mapping):
            raise ValueError("check_csv expected.rules must be a mapping")
        for item in rules.get("expect") or []:
            assert self._csv_has_row(rows, item), f"expected CSV row not found: {item}"
        for item in rules.get("unexpect") or []:
            assert not self._csv_has_row(rows, item), f"unexpected CSV row found: {item}"

    @staticmethod
    def _csv_has_row(rows: list[dict[str, str]], raw_expected: Any) -> bool:
        if not isinstance(raw_expected, Mapping):
            return False
        expected = {str(key): str(value) for key, value in raw_expected.items()}
        for row in rows:
            if all(str(row.get(key, "")) == value for key, value in expected.items()):
                return True
        return False

    def _check_json(self, payload: Any, expected: Mapping[str, Any]) -> None:
        text = self._decode_text(payload)
        data = json.loads(text)
        rules = self._expect_rule(expected)
        if not isinstance(rules, Mapping):
            raise ValueError("check_json expected.rules must be a mapping")
        for item in rules.get("expect") or []:
            assert isinstance(item, Mapping), f"invalid JSON expectation: {item!r}"
            key_path = item.get("key")
            method = str(item.get("method") or "eq")
            ref = item.get("ref")
            value = self._lookup_key_path(data, key_path)
            self._match_scalar(value, method, ref, label="JSON value")
        for item in rules.get("unexpect") or []:
            assert isinstance(item, Mapping), f"invalid JSON unexpectation: {item!r}"
            key_path = item.get("key")
            method = str(item.get("method") or "eq")
            ref = item.get("ref")
            value = self._lookup_key_path(data, key_path)
            try:
                self._match_scalar(value, method, ref, label="JSON value")
            except AssertionError:
                continue
            raise AssertionError(f"unexpected JSON value matched at {key_path}: {value!r}")

    def _run_sqlite3(self, payload: Any, expected: Mapping[str, Any]) -> None:
        if not isinstance(payload, (bytes, bytearray)):
            raise ValueError("run_sqlite3 requires vm_file bytes payload")
        rules = self._expect_rule(expected)
        if not isinstance(rules, Mapping):
            raise ValueError("run_sqlite3 expected.rules must be a mapping")
        sql = str(rules.get("sql") or "").strip()
        if not sql:
            raise ValueError("run_sqlite3 expected.rules.sql is required")
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=True) as handle:
            handle.write(bytes(payload))
            handle.flush()
            con = sqlite3.connect(handle.name)
            try:
                row = con.execute(sql).fetchone()
            finally:
                con.close()
        value = row[0] if row else None
        assert bool(value), f"SQL assertion returned falsy value: {value!r}"

    def _check_thunderbird_prefs(self, payload: Any, expected: Mapping[str, Any]) -> None:
        text = self._decode_text(payload)
        prefs = self._parse_thunderbird_prefs(text)
        rules = self._expect_rule(expected)
        if not isinstance(rules, Mapping):
            raise ValueError("check_thunderbird_prefs expected.rules must be a mapping")
        for key, matcher in (rules.get("expect") or {}).items():
            value = prefs.get(str(key))
            self._match_rule_object(value, matcher, label=f"pref {key}")
        for key, matcher in (rules.get("unexpect") or {}).items():
            value = prefs.get(str(key))
            try:
                self._match_rule_object(value, matcher, label=f"pref {key}")
            except AssertionError:
                continue
            raise AssertionError(f"unexpected preference matched: {key}")

    def _check_thunderbird_filter(self, payload: Any, expected: Mapping[str, Any]) -> None:
        text = self._decode_text(payload)
        filters = self._parse_thunderbird_filters(text)
        rules = self._expect_rule(expected)
        if not isinstance(rules, Mapping):
            raise ValueError("check_thunderbird_filter expected.rules must be a mapping")
        for item in rules.get("expect") or []:
            assert self._has_matching_filter(filters, item), f"expected filter not found: {item}"
        for item in rules.get("unexpect") or []:
            assert not self._has_matching_filter(filters, item), f"unexpected filter found: {item}"

    def _check_accessibility_tree(self, payload: Any, expected: Mapping[str, Any]) -> None:
        if not isinstance(payload, Mapping):
            raise ValueError("check_accessibility_tree requires accessibility tree payload")
        ui_nodes = list(payload.get("ui_nodes") or [])
        foreground_app = str(payload.get("foreground_app") or "")
        rules = self._expect_rule(expected)
        if not isinstance(rules, list):
            raise ValueError("check_accessibility_tree expected.rules must be a list")
        haystacks = []
        for node in ui_nodes:
            if not isinstance(node, Mapping):
                continue
            haystacks.append(
                {
                    "type": str(node.get("type") or ""),
                    "text": str(node.get("text") or ""),
                    "selector": str(node.get("selector") or ""),
                }
            )

        for item in rules:
            if not isinstance(item, Mapping):
                continue
            if "xpath" in item:
                xpath = str(item.get("xpath") or "")
                for token in self._extract_xpath_contains_tokens(xpath):
                    assert self._tree_contains_text(haystacks, token), f"accessibility tree missing token: {token}"
                app_names = re.findall(r"@name='([^']+)'", xpath)
                for app_name in app_names:
                    if app_name:
                        assert app_name.lower() in foreground_app.lower() or self._tree_contains_text(haystacks, app_name), (
                            f"foreground app mismatch for accessibility check: {app_name}"
                        )
            for selector_expr in item.get("selectors") or []:
                selector_text = str(selector_expr or "")
                names = re.findall(r'name=\"([^\"]+)\"', selector_text)
                for name in names:
                    assert self._tree_contains_text(haystacks, name), f"accessibility selector missing text: {name}"
                app_names = re.findall(r"application\\[name=([^\\]]+)\\]", selector_text)
                for app_name in app_names:
                    assert app_name.lower() in foreground_app.lower() or self._tree_contains_text(haystacks, app_name), (
                        f"foreground app mismatch for selector check: {app_name}"
                    )

    @staticmethod
    def _decode_text(payload: Any) -> str:
        if isinstance(payload, bytes):
            return payload.decode("utf-8", errors="replace")
        if isinstance(payload, str):
            return payload
        raise ValueError(f"expected text payload, got {type(payload)!r}")

    @staticmethod
    def _lookup_key_path(data: Any, key_path: Any) -> Any:
        if not isinstance(key_path, list) or not key_path:
            raise ValueError(f"invalid JSON key path: {key_path!r}")
        current = data
        for key in key_path:
            if isinstance(current, Mapping):
                current = current[key]
            elif isinstance(current, list):
                current = current[int(key)]
            else:
                raise KeyError(key)
        return current

    @staticmethod
    def _match_scalar(value: Any, method: str, ref: Any, *, label: str) -> None:
        if method == "eq":
            assert value == ref, f"{label} expected {ref!r}, got {value!r}"
            return
        flags = 0
        if method == "re.S":
            flags = re.S
            method = "re"
        if method == "re":
            assert re.search(str(ref), str(value), flags), f"{label} does not match /{ref}/: {value!r}"
            return
        raise ValueError(f"unsupported matcher method: {method}")

    @classmethod
    def _match_rule_object(cls, value: Any, raw_matcher: Any, *, label: str) -> None:
        if not isinstance(raw_matcher, Mapping):
            raise ValueError(f"invalid matcher for {label}: {raw_matcher!r}")
        method = str(raw_matcher.get("method") or "eq")
        ref = raw_matcher.get("ref")
        cls._match_scalar(value, method, ref, label=label)

    @staticmethod
    def _parse_thunderbird_prefs(text: str) -> dict[str, Any]:
        prefs: dict[str, Any] = {}
        pattern = re.compile(r'user_pref\("(?P<key>[^"]+)",\s*(?P<value>.+?)\);\s*$')
        for line in text.splitlines():
            match = pattern.search(line.strip())
            if not match:
                continue
            key = match.group("key")
            raw_value = match.group("value").strip()
            prefs[key] = ThunderbirdTaskEvaluator._parse_pref_value(raw_value)
        return prefs

    @staticmethod
    def _parse_pref_value(raw_value: str) -> Any:
        if raw_value == "true":
            return True
        if raw_value == "false":
            return False
        if raw_value.startswith('"') and raw_value.endswith('"'):
            return json.loads(raw_value)
        try:
            return int(raw_value)
        except ValueError:
            pass
        try:
            return float(raw_value)
        except ValueError:
            pass
        return raw_value

    @staticmethod
    def _parse_thunderbird_filters(text: str) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key == "name" and current:
                filters.append(current)
                current = {}
            if key == "condition":
                current.setdefault("condition", []).append(value)
            else:
                current[key] = value
        if current:
            filters.append(current)
        return filters

    @staticmethod
    def _has_matching_filter(filters: list[dict[str, Any]], raw_expected: Any) -> bool:
        if not isinstance(raw_expected, Mapping):
            return False
        for item in filters:
            matched = True
            for key, value in raw_expected.items():
                if key == "condition":
                    actual_conditions = list(item.get("condition") or [])
                    expected_conditions = [str(entry) for entry in value] if isinstance(value, list) else [str(value)]
                    if actual_conditions != expected_conditions:
                        matched = False
                        break
                    continue
                if str(item.get(str(key))) != str(value):
                    matched = False
                    break
            if matched:
                return True
        return False

    @staticmethod
    def _extract_xpath_contains_tokens(xpath: str) -> list[str]:
        tokens = re.findall(r"contains\((?:text\(\)|@name), '([^']+)'\)", xpath)
        return [token for token in tokens if token]

    @staticmethod
    def _tree_contains_text(nodes: list[dict[str, str]], needle: str) -> bool:
        needle_lower = needle.lower()
        for node in nodes:
            haystack = " ".join([node.get("type", ""), node.get("text", ""), node.get("selector", "")]).lower()
            if needle_lower in haystack:
                return True
        return False


class ThunderbirdUnifiedInboxEvaluator(BaseEvaluator):
    """Validate both smart-folder persistence and visible unified-inbox UI state."""

    DEFAULT_PROFILE_DIR = "/home/user/.thunderbird/t5q2a5hp.default-release"

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        if controller is None or not hasattr(controller, "get_file"):
            return EvalResult(status=EvalStatus.ERROR, message="controller.get_file is required")

        params = dict(context.get("params") or {})
        profile_dir = str(params.get("profile_dir") or self.DEFAULT_PROFILE_DIR).strip()
        xulstore_path = f"{profile_dir.rstrip('/')}/xulstore.json"

        try:
            payload = controller.get_file(xulstore_path)
            text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
            data = json.loads(text)
            mode = ThunderbirdTaskEvaluator._lookup_key_path(
                data,
                ["chrome://messenger/content/messenger.xhtml", "folderTree", "mode"],
            )
            assert re.search(r"\bsmart\b", str(mode)), f"folderTree.mode does not match smart: {mode!r}"

            final_observation = context.get("final_observation")
            ui_nodes = list(getattr(final_observation, "ui_nodes", []) or [])
            foreground_app = str(getattr(final_observation, "foreground_app", "") or "")
            if not ui_nodes and hasattr(controller, "observe"):
                observation = controller.observe(include_ui_tree=True, include_screenshot_data=False)
                ui_nodes = list(getattr(observation, "ui_nodes", []) or [])
                foreground_app = str(getattr(observation, "foreground_app", "") or "")

            haystacks = []
            for node in ui_nodes:
                if not isinstance(node, Mapping):
                    continue
                haystacks.append(
                    {
                        "type": str(node.get("type") or ""),
                        "text": str(node.get("text") or ""),
                        "selector": str(node.get("selector") or ""),
                    }
                )

            assert "thunderbird" in foreground_app.lower(), f"foreground app is not Thunderbird: {foreground_app!r}"
            assert ThunderbirdTaskEvaluator._tree_contains_text(haystacks, "Smart Folders"), (
                "accessibility tree missing Smart Folders"
            )
            assert ThunderbirdTaskEvaluator._tree_contains_text(haystacks, "Inbox"), (
                "accessibility tree missing Inbox"
            )
        except AssertionError as exc:
            return EvalResult(status=EvalStatus.FAIL, message=str(exc))
        except Exception as exc:
            return EvalResult(status=EvalStatus.ERROR, message=f"{type(exc).__name__}: {exc}")

        return EvalResult(status=EvalStatus.PASS, message="Thunderbird unified inbox evaluation passed")
