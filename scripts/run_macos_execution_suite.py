#!/usr/bin/env python3
"""Run a curated macOS execution suite serially with stable stdin isolation."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "results" / "full_runs"
DEFAULT_PREFLIGHT_CMD = [sys.executable, str(REPO_ROOT / "scripts" / "run_benchmark.py")]
DEFAULT_RUNNER_CMD = [sys.executable, "-m", "platforms.macos.host.cli"]
MODELS_CONFIG_PATH = REPO_ROOT / "configs" / "models.yaml"


@dataclass(frozen=True)
class SuiteRunResult:
    run_dir: Path
    state: str
    execution_count: int
    failure_count: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value).strip("_") or "suite"


def load_suite_manifest(path: Path) -> tuple[Path, list[Path], dict]:
    source_path = path.expanduser()
    if not source_path.is_absolute():
        source_path = REPO_ROOT / source_path
    source_path = source_path.resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"suite manifest not found: {source_path}")

    payload = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"suite manifest must be a mapping: {source_path}")

    raw_executions = payload.get("executions")
    if not isinstance(raw_executions, list) or not raw_executions:
        raise ValueError(f"suite manifest must contain a non-empty executions list: {source_path}")

    execution_paths: list[Path] = []
    base_dir = source_path.parent
    for item in raw_executions:
        exec_path = Path(str(item))
        if not exec_path.is_absolute():
            base_candidate = (base_dir / exec_path).resolve()
            repo_candidate = (REPO_ROOT / exec_path).resolve()
            exec_path = base_candidate if base_candidate.exists() else repo_candidate
        if not exec_path.exists():
            raise FileNotFoundError(f"execution file not found: {exec_path}")
        execution_paths.append(exec_path)

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    return source_path, execution_paths, metadata


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML mapping expected: {path}")
    return payload


def _load_model_specs() -> dict[str, Mapping[str, Any]]:
    payload = _load_yaml_mapping(MODELS_CONFIG_PATH)
    raw_models = payload.get("models")
    if not isinstance(raw_models, Mapping):
        return {}
    return {str(key): value for key, value in raw_models.items() if isinstance(value, Mapping)}


def _looks_like_oracle_model(model_id: str, model_specs: Mapping[str, Mapping[str, Any]]) -> bool:
    normalized = str(model_id or "").strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    if "oracle" in lowered:
        return True
    spec = model_specs.get(normalized)
    if not isinstance(spec, Mapping):
        return False
    provider = str(spec.get("provider") or "").strip().lower()
    model_name = str(spec.get("model_name") or "").strip().lower()
    base_url = str(spec.get("base_url") or "").strip().lower()
    metadata = spec.get("metadata")
    fields = [provider, model_name, base_url]
    if isinstance(metadata, Mapping):
        fields.extend(str(metadata.get(key) or "").strip().lower() for key in ("oracle_model", "execution_style"))
    return any("oracle" in field for field in fields if field)


def _materialize_execution_files(
    *,
    execution_paths: Sequence[Path],
    destination_dir: Path,
    model_override: str | None,
    forbid_oracle_models: bool,
    model_specs: Mapping[str, Mapping[str, Any]],
) -> list[tuple[Path, Path, tuple[str, ...]]]:
    destination_dir.mkdir(parents=True, exist_ok=True)
    materialized: list[tuple[Path, Path, tuple[str, ...]]] = []

    for index, source_path in enumerate(execution_paths, start=1):
        payload = _load_yaml_mapping(source_path)
        raw_models = payload.get("models")
        if not isinstance(raw_models, list) or not raw_models:
            raise ValueError(f"execution file must contain a non-empty models list: {source_path}")

        if model_override:
            effective_models = [model_override]
            payload["models"] = effective_models
        else:
            effective_models = [str(item).strip() for item in raw_models if str(item).strip()]
            payload["models"] = effective_models

        if not effective_models:
            raise ValueError(f"execution file resolved to an empty models list: {source_path}")

        oracle_models = [model_id for model_id in effective_models if _looks_like_oracle_model(model_id, model_specs)]
        if forbid_oracle_models and oracle_models:
            joined = ", ".join(oracle_models)
            raise ValueError(f"oracle models are not allowed in this suite run: {source_path} -> {joined}")

        runtime_path = destination_dir / f"{index:02d}_{source_path.name}"
        runtime_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        materialized.append((source_path, runtime_path, tuple(effective_models)))

    return materialized


def _write_status(path: Path, fields: dict[str, object]) -> None:
    lines = [f"{key}={value}" for key, value in fields.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_log(log_path: Path, message: str) -> None:
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def _preflight_execution(execution_path: Path, *, preflight_cmd: Sequence[str], preflight_log: Path) -> None:
    with preflight_log.open("a", encoding="utf-8") as handle:
        handle.write(f"=== PREFLIGHT {execution_path} ===\n")
        handle.flush()
        completed = subprocess.run(
            [*preflight_cmd, "--execution", str(execution_path)],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(f"preflight failed for {execution_path} with rc={completed.returncode}")


def run_suite(
    *,
    suite_path: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    continue_on_failure: bool = True,
    preflight: bool = True,
    preflight_only: bool = False,
    preflight_cmd: Sequence[str] = DEFAULT_PREFLIGHT_CMD,
    runner_cmd: Sequence[str] = DEFAULT_RUNNER_CMD,
    model_override: str | None = None,
    forbid_oracle_models: bool = False,
) -> SuiteRunResult:
    source_path, execution_paths, metadata = load_suite_manifest(suite_path)

    suite_name = _safe_name(source_path.stem)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_root.expanduser().resolve() / f"{suite_name}_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    model_specs = _load_model_specs()
    materialized = _materialize_execution_files(
        execution_paths=execution_paths,
        destination_dir=run_dir / "executions",
        model_override=model_override,
        forbid_oracle_models=forbid_oracle_models,
        model_specs=model_specs,
    )
    effective_execution_paths = [runtime_path for _, runtime_path, _ in materialized]

    executions_path = run_dir / "executions.txt"
    executions_path.write_text(
        "\n".join(str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path) for path in execution_paths)
        + "\n",
        encoding="utf-8",
    )
    effective_executions_path = run_dir / "effective_executions.txt"
    effective_executions_path.write_text(
        "\n".join(str(path) for path in effective_execution_paths) + "\n",
        encoding="utf-8",
    )
    preflight_log = run_dir / "preflight.log"
    master_log = run_dir / "master.log"
    status_path = run_dir / "status.txt"
    summary_path = run_dir / "execution_summary.tsv"
    manifest_copy = run_dir / source_path.name
    manifest_copy.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
    effective_manifest = run_dir / f"{source_path.stem}.effective.yaml"
    effective_manifest.write_text(
        yaml.safe_dump(
            {
                "executions": [str(path) for path in effective_execution_paths],
                "metadata": {
                    **metadata,
                    "source_suite": str(source_path),
                    "model_override": model_override,
                    "forbid_oracle_models": forbid_oracle_models,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    mapping_path = run_dir / "execution_model_mapping.tsv"
    with mapping_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["index", "source_execution", "effective_execution", "models"])
        for index, (source_execution, effective_execution, models) in enumerate(materialized, start=1):
            writer.writerow([index, str(source_execution), str(effective_execution), ",".join(models)])

    started_at = _utc_now()
    _write_status(
        status_path,
        {
            "RUN_ID": run_dir.name,
            "SUITE_PATH": source_path,
            "STARTED_AT": started_at,
            "STATE": "preflighting" if preflight else "running",
            "EXECUTIONS_TOTAL": len(execution_paths),
            "MODEL_OVERRIDE": model_override or "",
            "FORBID_ORACLE_MODELS": str(forbid_oracle_models).lower(),
        },
    )
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["index", "execution", "effective_execution", "models", "rc", "started_at_utc", "ended_at_utc", "log"])

    _append_log(master_log, f"[{datetime.now().strftime('%F %T')}] suite started: {source_path}")
    if metadata.get("description"):
        _append_log(master_log, f"[{datetime.now().strftime('%F %T')}] suite description: {metadata['description']}")
    if model_override:
        _append_log(master_log, f"[{datetime.now().strftime('%F %T')}] model override: {model_override}")
    if forbid_oracle_models:
        _append_log(master_log, f"[{datetime.now().strftime('%F %T')}] oracle models forbidden: true")

    if preflight:
        for execution_path in effective_execution_paths:
            _preflight_execution(execution_path, preflight_cmd=preflight_cmd, preflight_log=preflight_log)
        if preflight_only:
            ended_at = _utc_now()
            _write_status(
                status_path,
                {
                    "RUN_ID": run_dir.name,
                    "SUITE_PATH": source_path,
                    "STARTED_AT": started_at,
                    "ENDED_AT": ended_at,
                    "STATE": "preflight_ok",
                    "EXECUTIONS_TOTAL": len(execution_paths),
                    "EXECUTIONS": 0,
                    "FAILURES": 0,
                    "MODEL_OVERRIDE": model_override or "",
                    "FORBID_ORACLE_MODELS": str(forbid_oracle_models).lower(),
                },
            )
            _append_log(master_log, f"[{datetime.now().strftime('%F %T')}] suite preflight complete")
            return SuiteRunResult(run_dir=run_dir, state="preflight_ok", execution_count=0, failure_count=0)
        _write_status(
            status_path,
            {
                "RUN_ID": run_dir.name,
                "SUITE_PATH": source_path,
                "STARTED_AT": started_at,
                "STATE": "running",
                "EXECUTIONS_TOTAL": len(execution_paths),
                "MODEL_OVERRIDE": model_override or "",
                "FORBID_ORACLE_MODELS": str(forbid_oracle_models).lower(),
            },
        )

    failures = 0
    executed = 0
    for index, (source_execution_path, execution_path, models) in enumerate(materialized, start=1):
        executed = index
        started = _utc_now()
        execution_log = run_dir / f"{index:02d}_{execution_path.stem}.log"
        rel_execution = (
            str(source_execution_path.relative_to(REPO_ROOT))
            if source_execution_path.is_relative_to(REPO_ROOT)
            else str(source_execution_path)
        )
        rel_effective_execution = (
            str(execution_path.relative_to(REPO_ROOT))
            if execution_path.is_relative_to(REPO_ROOT)
            else str(execution_path)
        )
        rel_log = str(execution_log.relative_to(REPO_ROOT)) if execution_log.is_relative_to(REPO_ROOT) else str(execution_log)
        _append_log(
            master_log,
            f"[{datetime.now().strftime('%F %T')}] >>> [{index}] START {rel_execution} -> {rel_effective_execution} models={','.join(models)}",
        )

        with execution_log.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(
                [*runner_cmd, "--execution", str(execution_path)],
                cwd=REPO_ROOT,
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )

        ended = _utc_now()
        with summary_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow([index, rel_execution, rel_effective_execution, ",".join(models), completed.returncode, started, ended, rel_log])

        if completed.returncode != 0:
            failures += 1
            _append_log(
                master_log,
                f"[{datetime.now().strftime('%F %T')}] !!! [{index}] FAIL rc={completed.returncode} {rel_execution} models={','.join(models)} (log: {rel_log})",
            )
            if not continue_on_failure:
                break
        else:
            _append_log(
                master_log,
                f"[{datetime.now().strftime('%F %T')}] <<< [{index}] OK   {rel_execution} models={','.join(models)}",
            )

    ended_at = _utc_now()
    state = "success" if failures == 0 and executed == len(execution_paths) else "finished_with_failures"
    _write_status(
        status_path,
        {
            "RUN_ID": run_dir.name,
            "SUITE_PATH": source_path,
            "STARTED_AT": started_at,
            "ENDED_AT": ended_at,
            "STATE": state,
            "EXECUTIONS_TOTAL": len(execution_paths),
            "EXECUTIONS": executed,
            "FAILURES": failures,
            "MODEL_OVERRIDE": model_override or "",
            "FORBID_ORACLE_MODELS": str(forbid_oracle_models).lower(),
        },
    )
    _append_log(
        master_log,
        f"[{datetime.now().strftime('%F %T')}] suite ended: state={state} executions={executed} failures={failures}",
    )
    return SuiteRunResult(run_dir=run_dir, state=state, execution_count=executed, failure_count=failures)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        required=True,
        help="Suite manifest path.",
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT.relative_to(REPO_ROOT)),
        help="Directory to store suite runs. Defaults to results/full_runs.",
    )
    parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="Abort the suite after the first failing execution.",
    )
    parser.add_argument(
        "--no-preflight",
        action="store_true",
        help="Skip per-execution preflight validation.",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Validate every execution in the suite and stop before launching benchmark runs.",
    )
    parser.add_argument(
        "--model-override",
        help="Rewrite every execution in the suite to use exactly this model id before preflight/run.",
    )
    parser.add_argument(
        "--forbid-oracle-models",
        action="store_true",
        help="Fail fast if any effective execution still resolves to an oracle model.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = run_suite(
            suite_path=Path(args.suite),
            output_root=Path(args.output_root),
            continue_on_failure=not args.stop_on_failure,
            preflight=not args.no_preflight,
            preflight_only=args.preflight_only,
            model_override=args.model_override,
            forbid_oracle_models=args.forbid_oracle_models,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"RUN_DIR={result.run_dir}")
    print(f"STATE={result.state}")
    print(f"EXECUTIONS={result.execution_count}")
    print(f"FAILURES={result.failure_count}")
    return 0 if result.failure_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
