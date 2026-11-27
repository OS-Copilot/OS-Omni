"""Probe Qwen3.8-max transport without starting a VM or executing model actions."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import httpx
from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.llm.llm_client import _load_model_parameters, _resolve_credentials
from core.llm.model_registry import ModelRegistry
from core.llm.errors import LLMClientError
from core.llm.providers.base import ProviderRequest, _redact_inline_images
from core.llm.providers.openai_adapter import OpenAIAdapter
from core.llm.providers.utils import image_path_to_data_url, resolve_chat_completions_url
from core.llm.providers.utils import extract_openai_text_content
from core.llm.types import ImagePart, Message, TextPart

MODELS = ("qwen3_8_max_low", "qwen3_8_max_no_thinking")


def load_profile(path: Path | None) -> None:
    load_dotenv(ROOT / ".env", override=False)
    if path is not None:
        if not path.is_file():
            raise ValueError(f"Environment profile not found: {path}")
        for key, value in dotenv_values(path).items():
            if value or key == "HELLOWORLD_WINDOWS_VM_PASSWORD":
                os.environ[key] = value or ""


def restore_images(payload: dict, image_root: Path, jpeg_quality: int) -> dict:
    """Restore only image digests present in a locally recorded request."""
    restored = copy.deepcopy(payload)
    references = []
    for message in restored.get("messages", []):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if part.get("type") == "image_url":
                holder = part["image_url"]
                if isinstance(holder.get("url"), dict):
                    references.append(holder)
    needed = {holder["url"]["inline_image_sha256"] for holder in references}
    found = {}
    for path in image_root.rglob("*"):
        if not needed - found.keys():
            break
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        uri = image_path_to_data_url(str(path), jpeg_quality=jpeg_quality)
        digest = hashlib.sha256(uri.encode()).hexdigest()
        if digest in needed:
            found[digest] = uri
    if needed - found.keys():
        raise ValueError("Cannot restore all request images from the selected image root")
    for holder in references:
        holder["url"] = found[holder["url"]["inline_image_sha256"]]
    return restored


def validate_replay(payload: dict, spec) -> None:
    expected = {
        "model": spec.model_name,
        "reasoning_effort": spec.metadata["reasoning_effort"],
        "enable_thinking": spec.metadata["enable_thinking"],
        "max_completion_tokens": spec.max_output_tokens,
        "stream": True,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"Replay {key} does not match the selected model preset")
    if "reasoning" in payload:
        raise ValueError("Replay contains a generic reasoning object; use the matching original setup")


def summarize_response(data: dict) -> dict:
    choices = data.get("choices") or []
    reasoning_chars = sum(
        len((choice.get("message") or {}).get("reasoning_content") or "")
        for choice in choices
    )
    return {
        "response_model": data.get("model"),
        "finish_reasons": [choice.get("finish_reason") for choice in choices],
        "raw_reasoning_characters": reasoning_chars,
        "response_content_characters": sum(len(extract_openai_text_content(
            (choice.get("message") or {}).get("content")
        ) or "") for choice in choices),
        "usage": data.get("usage"),
    }


def run_probes(adapter, spec, credentials, cases) -> list[dict]:
    """Run bounded diagnostics. Each case is (name, messages-or-exact-payload)."""
    results = []
    url = resolve_chat_completions_url(credentials.base_url)
    for name, value in cases:
        start = time.monotonic()
        request = None
        if isinstance(value, dict):
            payload = value
            validate_replay(payload, spec)
        else:
            request = ProviderRequest(
                model_spec=spec, credentials=credentials, messages=value,
                response_mode="json_text", parameters=_load_model_parameters(spec),
                timeout_seconds=180,
            )
            payload = adapter._build_payload(request)
        record = {"case": name, "url": url, "request": _redact_inline_images(payload),
                  "actions_executed": False, "automatic_retries": 0}
        try:
            if request is not None:
                response = adapter.invoke(request)
                data = response.raw_response or {}
            else:
                data = adapter._request_json(url, credentials.api_key, payload, 180)
            record.update(summarize_response(data))
            if spec.metadata["enable_thinking"] is False and record["raw_reasoning_characters"]:
                raise ValueError("Provider returned reasoning_content with thinking disabled")
            record["success"] = bool(record["response_content_characters"]) and all(
                reason == "stop" for reason in record["finish_reasons"]
            )
        except Exception as exc:
            record.update(success=False, error_type=type(exc).__name__,
                          error=str(exc).replace(credentials.api_key, "[REDACTED]"),
                          details=str(getattr(exc, "details", {})).replace(
                              credentials.api_key, "[REDACTED]"
                          )[:1200])
        record["seconds"] = round(time.monotonic() - start, 3)
        results.append(record)
        if not record["success"]:
            break
    return results


def make_cases(case: str, screenshot: Path | None, image_history: int) -> list:
    selected = ["text", "single", "multi"] if case == "all" else [case]
    cases = []
    for name in selected:
        user = Message("user", [TextPart("Reply exactly OK.")])
        if name != "text":
            if screenshot is None or not screenshot.is_file():
                raise ValueError("Screenshot cases require an existing --screenshot")
            user = Message("user", [
                TextPart("Name two visible applications in the current screenshot."),
                ImagePart(str(screenshot.resolve())),
            ])
        messages = [user]
        if name == "multi":
            prior_parts = [TextPart("Inspect the previous screenshot before describing the next one.")]
            if image_history:
                prior_parts.append(ImagePart(str(screenshot.resolve())))
            messages = [Message("user", prior_parts),
                        Message("assistant", [TextPart("I will inspect the current screenshot next.")]), user]
        cases.append((name, messages))
    return cases


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--model", choices=MODELS, default=MODELS[0])
    parser.add_argument("--case", choices=("text", "single", "multi", "all"), default="all")
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--image-history-window", choices=(0, 1), type=int, default=0)
    parser.add_argument("--replay-log", type=Path)
    parser.add_argument("--exchange-index", type=int, default=-1,
                        help="Zero-based exchange index; -1 selects the last recorded request")
    parser.add_argument("--image-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        output = args.output or ROOT / "artifacts" / "qwen38" / f"probe-{time.time_ns()}.json"
        if output.resolve().exists():
            raise ValueError("Output already exists; choose a new filename to preserve evidence")
        load_profile(args.env_file)
        spec = ModelRegistry.load(str(ROOT / "configs/models.yaml")).get(args.model)
        credentials = _resolve_credentials(spec)
        if args.replay_log:
            events = [json.loads(line) for line in args.replay_log.read_text(
                encoding="utf-8"
            ).splitlines() if line.strip()]
            event = events[args.exchange_index]
            url = resolve_chat_completions_url(credentials.base_url)
            if event.get("url") != url:
                raise ValueError("Replay URL differs from the configured endpoint")
            payload = restore_images(event["request"], args.image_root or args.replay_log.parent,
                                     spec.metadata["image_jpeg_quality"])
            cases = [("replay", payload)]
        else:
            cases = make_cases(args.case, args.screenshot, args.image_history_window)
        with httpx.Client(trust_env=False) as client:
            adapter = OpenAIAdapter(client=client)
            adapter.transient_retry_attempts = 0
            results = run_probes(adapter, spec, credentials, cases)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"output": str(output), "results": [
            {key: value for key, value in result.items() if key != "request"}
            for result in results
        ]}, ensure_ascii=True))
        return 0 if len(results) == len(cases) and all(r["success"] for r in results) else 1
    except (ValueError, KeyError, IndexError, OSError, LLMClientError) as exc:
        print(f"Probe setup error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
