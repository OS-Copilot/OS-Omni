"""Evaluator: marker text appears in a11y tree or saved ODT content."""

from __future__ import annotations

import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


def _collect_strings(ui_nodes: Any) -> list[str]:
    out: list[str] = []
    if not isinstance(ui_nodes, list):
        return out
    for node in ui_nodes:
        if isinstance(node, dict):
            for key in ("text", "content_description", "content-desc"):
                raw = node.get(key)
                if raw is not None and str(raw).strip():
                    out.append(str(raw))
        else:
            for attr in ("text", "content_description"):
                raw = getattr(node, attr, None)
                if raw is not None and str(raw).strip():
                    out.append(str(raw))
    return out


class LibreOfficeViewerMarkEvaluator(BaseEvaluator):
    """PASS if expected marker appears in a11y tree or in saved ODT `content.xml`."""

    DEFAULT_FILENAME = "bench_read_by_viewer.odt"
    # Common places where LibreOffice Android saves user documents.
    DEFAULT_REMOTE_CANDIDATES = (
        "/sdcard/Documents",
        "/sdcard/Download",
        "/sdcard/Downloads",
        "/sdcard",
    )
    XML_NAMESPACES = {
        "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    }

    @classmethod
    def _find_remote_odt(
        cls,
        *,
        controller: Any,
        filename: str,
    ) -> str:
        """Return a remote file path if the ODT exists on device, else empty string."""
        if controller is None or not hasattr(controller, "execute_adb"):
            return ""

        # Fast path: direct candidate locations.
        for base in cls.DEFAULT_REMOTE_CANDIDATES:
            remote = f"{base.rstrip('/')}/{filename}"
            out = str(controller.execute_adb(["shell", "ls", remote]) or "").strip()
            if out == remote or out.endswith(filename):
                return remote

        # Fallback: recursive lookup under /sdcard (single-line first hit).
        lookup = (
            f"find /sdcard -type f -name '{filename}' 2>/dev/null | head -n 1"
        )
        out = str(controller.execute_adb(["shell", "sh", "-c", lookup]) or "").strip()
        if out.endswith(filename):
            return out
        return ""

    @staticmethod
    def _normalize_line(value: str) -> str:
        return " ".join(str(value or "").replace("\u00a0", " ").split())

    @classmethod
    def _extract_odt_text_lines(cls, local_path: Path) -> list[str]:
        try:
            with zipfile.ZipFile(local_path, "r") as zf:
                xml_bytes = zf.read("content.xml")
        except Exception:
            return []

        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError:
            return []

        lines: list[str] = []
        for para in root.findall(".//text:p", cls.XML_NAMESPACES):
            text = "".join(para.itertext())
            normalized = cls._normalize_line(text)
            if normalized:
                lines.append(normalized)
        return lines

    @classmethod
    def _check_local_odt_exact_marker(
        cls,
        *,
        local_path: Path,
        expected: str,
    ) -> tuple[bool, dict[str, Any]]:
        lines = cls._extract_odt_text_lines(local_path)
        if not lines:
            return False, {
                "line_count": 0,
                "lines_preview": [],
            }

        return lines == [expected], {
            "line_count": len(lines),
            "lines_preview": lines[:5],
        }

    @staticmethod
    def _local_odt_candidates(*, run_dir: Path | None, filename: str) -> list[Path]:
        candidates: list[Path] = []
        if run_dir is not None:
            candidates.append(run_dir / "_evaluator" / filename)
        else:
            candidates.append(Path.cwd() / "_evaluator" / filename)
        seen: set[Path] = set()
        unique: list[Path] = []
        for path in candidates:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            unique.append(path)
        return unique

    @classmethod
    def _pull_and_check_marker(
        cls,
        *,
        controller: Any,
        remote_path: str,
        expected: str,
        run_dir: Path | None,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Pull remote ODT, inspect body text lines, and report exact marker match + local path."""
        base_dir = Path(run_dir) if run_dir else Path.cwd()
        eval_dir = base_dir / "_evaluator"
        eval_dir.mkdir(parents=True, exist_ok=True)
        local_path = eval_dir / Path(remote_path).name
        if controller is None or not hasattr(controller, "execute_adb"):
            return False, str(local_path), {"line_count": 0, "lines_preview": []}

        try:
            controller.execute_adb(["pull", remote_path, str(local_path)])
        except Exception:
            return False, str(local_path), {"line_count": 0, "lines_preview": []}

        if not local_path.exists() or local_path.stat().st_size <= 0:
            return False, str(local_path), {"line_count": 0, "lines_preview": []}

        matched, details = cls._check_local_odt_exact_marker(
            local_path=local_path,
            expected=expected,
        )
        return matched, str(local_path), details

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        params = dict(context.get("params") or {})
        expected = str(params.get("expected_marker") or "READ_BY_VIEWER").strip()
        if not expected:
            return EvalResult(
                status=EvalStatus.ERROR,
                message="evaluation.params.expected_marker is empty",
            )

        final_observation = context.get("final_observation")
        controller = context.get("controller")
        if final_observation is None and controller is not None and hasattr(controller, "observe"):
            try:
                final_observation = controller.observe(include_ui_tree=True)
            except Exception:
                pass

        if final_observation is None:
            return EvalResult(
                status=EvalStatus.UNDETERMINED,
                message="No observation available",
            )

        filename = str(params.get("expected_filename") or self.DEFAULT_FILENAME).strip()
        run_dir_raw = context.get("run_dir")
        run_dir = Path(run_dir_raw) if run_dir_raw else None
        controller = context.get("controller")
        remote_path = self._find_remote_odt(controller=controller, filename=filename)
        if remote_path:
            found, local_path, odt_details = self._pull_and_check_marker(
                controller=controller,
                remote_path=remote_path,
                expected=expected,
                run_dir=run_dir,
            )
            if found:
                return EvalResult(
                    status=EvalStatus.PASS,
                    message=f"Marker {expected!r} is the only non-empty line in saved ODT content.xml",
                    metadata={
                        "marker": expected,
                        "expected_filename": filename,
                        "remote_path": remote_path,
                        "local_pulled_path": local_path,
                        **odt_details,
                    },
                )
            odt_failure_details = {
                "remote_path": remote_path,
                "local_pulled_path": local_path,
                **odt_details,
            }
        else:
            odt_failure_details = {
                "remote_path": "",
                "local_pulled_path": "",
                "line_count": 0,
                "lines_preview": [],
            }

        for local_candidate in self._local_odt_candidates(run_dir=run_dir, filename=filename):
            if not local_candidate.exists() or local_candidate.stat().st_size <= 0:
                continue
            found, odt_details = self._check_local_odt_exact_marker(
                local_path=local_candidate,
                expected=expected,
            )
            if found:
                return EvalResult(
                    status=EvalStatus.PASS,
                    message=f"Marker {expected!r} is the only non-empty line in saved ODT content.xml",
                    metadata={
                        "marker": expected,
                        "expected_filename": filename,
                        "remote_path": remote_path,
                        "local_pulled_path": str(local_candidate),
                        **odt_details,
                    },
                )
            odt_failure_details = {
                "remote_path": remote_path,
                "local_pulled_path": str(local_candidate),
                **odt_details,
            }

        ui_nodes = getattr(final_observation, "ui_nodes", []) or []
        haystack = "\n".join(_collect_strings(ui_nodes))

        return EvalResult(
            status=EvalStatus.FAIL,
            message=(
                f"Saved ODT {filename!r} does not contain exactly one non-empty line equal to {expected!r}"
            ),
            metadata={
                "marker": expected,
                "expected_filename": filename,
                "preview": haystack[:500],
                **odt_failure_details,
            },
        )
