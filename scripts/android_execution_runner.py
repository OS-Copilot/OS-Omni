from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _strip_inline_comment(value: str) -> str:
    quote: str | None = None
    for index, char in enumerate(value):
        if char in {"'", '"'}:
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
        elif char == "#" and quote is None and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value.strip()


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_dotenv_file(path: Path) -> None:
    if not path.is_file():
        print(f"[env] skipped missing {path}", file=sys.stderr)
        return

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ[key] = _unquote(_strip_inline_comment(value))


def sanitize_network_env() -> None:
    if os.environ.get("HELLOWORLD_KEEP_PROXY", "").strip().lower() in {"1", "true", "yes"}:
        print("[env] keeping proxy environment because HELLOWORLD_KEEP_PROXY is set")
        return

    removed = [key for key in PROXY_ENV_KEYS if os.environ.pop(key, None)]
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    if removed:
        print(f"[env] cleared proxy variables: {', '.join(removed)}")


def configure_provider_retries() -> None:
    os.environ.setdefault("HELLOWORLD_LLM_PROVIDER_RETRY_ATTEMPTS", "5")
    os.environ.setdefault("HELLOWORLD_LLM_PROVIDER_RETRY_DELAY_SECONDS", "2")


def _resolve_model_name(root: Path, model_id: str) -> str:
    try:
        import yaml

        payload = yaml.safe_load((root / "configs" / "models.yaml").read_text(encoding="utf-8")) or {}
        spec = (payload.get("models") or {}).get(model_id) or {}
        model_name = str(spec.get("model_name") or "").strip()
        if model_name:
            return model_name
    except Exception:
        pass
    return "gpt-5.4"


def _chat_completions_url(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _provider_probe(root: Path, *, model_id: str = "gpt5_4", timeout_seconds: int = 45) -> None:
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not base_url or not api_key:
        print("[preflight] skipped: OPENAI_BASE_URL or OPENAI_API_KEY is missing")
        return

    payload: dict[str, Any] = {
        "model": _resolve_model_name(root, model_id),
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "max_completion_tokens": 16,
    }
    request = urllib.request.Request(
        _chat_completions_url(base_url),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout_seconds) as response:
        if response.status >= 400:
            raise RuntimeError(f"HTTP {response.status}")
        response.read(1024)


def wait_for_provider(root: Path, *, attempts: int = 8, delay_seconds: int = 8) -> None:
    for attempt in range(1, attempts + 1):
        try:
            _provider_probe(root)
            print(f"[preflight] provider reachable on attempt {attempt}/{attempts}")
            return
        except (urllib.error.URLError, TimeoutError, RuntimeError, OSError) as exc:
            print(f"[preflight] provider probe failed {attempt}/{attempts}: {exc}")
            if attempt >= attempts:
                raise
            time.sleep(delay_seconds)


def run_android_execution(execution: str) -> int:
    root = repo_root()
    load_dotenv_file(root / ".env")
    sanitize_network_env()
    configure_provider_retries()
    wait_for_provider(root)

    os.chdir(root)
    command = [
        sys.executable,
        "-m",
        "platforms.android.cli",
        "--execution",
        execution,
    ]
    print("[run] " + " ".join(command))
    return subprocess.call(command)
