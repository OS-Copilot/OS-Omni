"""Read-only bounded admin evidence capture for locally isolated GreenMail.

Targets the official installed REST schema
``GET /greenmail-openapi.yml`` (GreenMail 2.1.14), restricted to
the single read endpoint::

    GET /api/user/{emailOrId}/messages/{folderName}

Each message carries ``uid``, ``contentType`` and ``mimeMessage`` (raw MIME).
This helper performs no mutations: it never calls ``GET /api/user`` (which
exposes passwords), never calls POST/DELETE reset/purge endpoints, and only
issues HTTP GET against an explicit loopback base URL (127.0.0.1/localhost).

Captured bytes are bounded (per-mailbox response cap and per-message MIME
cap), hashed per file (SHA256 + size manifest, UTC timestamps), and written
only to a dedicated admin evidence directory -- never into the model prompt.
Per-target failures are recorded in the manifest ``errors`` list and never
affect the task PASS/FAIL verdict. Stored artifacts never contain request
headers, passwords, API keys or tokens.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError

CAPTURE_ENV_VAR = "OS_OMNI_CAPTURE_LOCAL_MAIL"
EVIDENCE_DIRNAME = "local_mail_evidence"
MANIFEST_NAME = "manifest.json"
SCHEMA_REF = "GET /greenmail-openapi.yml"
SCHEMA_VERSION = "2.1.14"
MESSAGES_ENDPOINT_TEMPLATE = "/api/user/{email}/messages/{folder}"

DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_RESPONSE_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_MIME_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_TARGETS = 16
DEFAULT_FOLDER = "INBOX"

_FOLDER_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def is_loopback_base_url(base_url: str) -> bool:
    """Return True only for explicit local ``http(s)://127.0.0.1|localhost`` URLs."""
    try:
        parts = urllib.parse.urlparse(base_url)
    except (ValueError, AttributeError):
        return False
    if parts.scheme not in ("http", "https"):
        return False
    if parts.username or parts.password:
        return False
    host = (parts.hostname or "").lower()
    if host not in ("127.0.0.1", "localhost"):
        return False
    return bool(parts.netloc)


def _require_test_user(email: str) -> str:
    user = email.strip()
    if "@" not in user or not user.lower().endswith(".test"):
        raise ValueError(f"refusing non-fake user (must end with .test): {email!r}")
    return user


def _require_folder(folder: str) -> str:
    name = folder.strip() or DEFAULT_FOLDER
    if not _FOLDER_RE.match(name):
        raise ValueError(f"refusing unsafe folder name: {folder!r}")
    return name


def discover_maily_targets(
    checkpoint_specs: Sequence[Mapping[str, Any]],
    *,
    folder: str = DEFAULT_FOLDER,
) -> list[dict[str, str]]:
    """Derive explicit (user, folder) targets from evaluator checkpoint specs.

    Reads explicit ``spec["mailbox"]`` or ``spec["recipient"]`` entries (e.g. ``CHECKPOINT_SPECS`` in
    ``evaluators/ios/maily_instruction_3_*.py``) without guessing users.
    Every mailbox must be a fake ``.test`` address; anything else raises.
    """
    seen: dict[tuple[str, str], dict[str, str]] = {}
    clean_folder = _require_folder(folder)
    for spec in checkpoint_specs:
        mailbox = str(spec.get("mailbox") or spec.get("recipient") or "").strip()
        if not mailbox:
            raise ValueError("checkpoint spec is missing its mailbox user")
        user = _require_test_user(mailbox)
        seen.setdefault((user, clean_folder), {"email": user, "folder": clean_folder})
    return [seen[key] for key in sorted(seen)]


def discover_task_eval_params(task_file: str | Path) -> dict[str, Any]:
    """Return ``{task_id, evaluator_id, params}`` from a task YAML file.

    Uses ``yaml.safe_load`` when available, else a minimal fallback parser
    for the ``evaluation:`` block. Never invents users or folders.
    """
    text = Path(task_file).read_text(encoding="utf-8")
    data: Any = None
    try:
        import yaml  # type: ignore[import]

        data = yaml.safe_load(text)
    except ImportError:
        data = None
    if not isinstance(data, dict):
        data = {}
        in_eval = False
        for line in text.splitlines():
            if line.startswith("task_id:"):
                data.setdefault("task_id", line.split(":", 1)[1].strip())
            elif line.startswith("evaluation:"):
                in_eval = True
                data.setdefault("evaluation", {})
            elif in_eval and line.startswith("  evaluator_id:"):
                data["evaluation"]["evaluator_id"] = line.split(":", 1)[1].strip()
    evaluation = data.get("evaluation") or {}
    return {
        "task_id": data.get("task_id", ""),
        "evaluator_id": evaluation.get("evaluator_id", ""),
        "params": dict(evaluation.get("params") or {}),
    }


def _safe_stem(email: str, folder: str) -> str:
    return f"{_SAFE_RE.sub('_', email).strip('_.')[:96]}__{_SAFE_RE.sub('_', folder)}"


def _read_bounded(response: Any, limit: int) -> tuple[bytes, bool]:
    raw = response.read(limit + 1)
    if len(raw) > limit:
        return raw[:limit], True
    return raw, False


def capture_local_mail_evidence(
    *,
    base_url: str,
    targets: Sequence[Mapping[str, str]],
    output_dir: str | Path,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    max_mime_bytes: int = DEFAULT_MAX_MIME_BYTES,
    max_targets: int = DEFAULT_MAX_TARGETS,
    urlopen: Any | None = None,
) -> dict[str, Any]:
    """GET bounded GreenMail mailbox JSON + raw MIME into ``output_dir``.

    ``targets`` is an explicit list of ``{"email", "folder"}`` mappings
    supplied by the caller (see :func:`discover_maily_targets`); users are
    never enumerated via ``GET /api/user``. Raises ``ValueError`` for a
    non-loopback ``base_url``, non-``.test`` users, unsafe folders, or an
    over-budget target list. Per-target HTTP/parse failures are recorded in
    ``manifest["errors"]`` and do not raise.
    """
    if not is_loopback_base_url(base_url):
        raise ValueError(f"refusing non-local GreenMail base URL: {base_url!r}")
    clean_targets = [
        {
            "email": _require_test_user(str(item.get("email", ""))),
            "folder": _require_folder(str(item.get("folder", DEFAULT_FOLDER))),
        }
        for item in targets
    ]
    if not clean_targets or len(clean_targets) > max_targets:
        raise ValueError(f"target count out of bounds: {len(clean_targets)}")
    if max_response_bytes <= 0 or max_mime_bytes <= 0:
        raise ValueError("byte bounds must be positive")

    opener = urlopen or urllib.request.urlopen
    out_dir = Path(output_dir) / EVIDENCE_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)

    files: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    mailboxes: dict[str, int] = {}

    for target in clean_targets:
        email = target["email"]
        folder = target["folder"]
        stem = _safe_stem(email, folder)
        url = (
            base_url.rstrip("/")
            + MESSAGES_ENDPOINT_TEMPLATE.format(
                email=urllib.parse.quote(email, safe=""),
                folder=urllib.parse.quote(folder, safe=""),
            )
        )
        request = urllib.request.Request(url, method="GET")
        if request.get_method() != "GET":
            raise RuntimeError("local-mail evidence attempted a non-GET request")
        try:
            with opener(request, timeout=timeout_seconds) as response:
                raw, truncated = _read_bounded(response, max_response_bytes)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            errors.append({"target": f"{email}/{folder}", "reason": f"{type(exc).__name__}"})
            continue
        raw_name = f"{stem}.json"
        (out_dir / raw_name).write_bytes(raw)
        files.append(
            {"path": raw_name, "sha256": sha256_hex(raw), "size": len(raw),
             "truncated": truncated}
        )
        if truncated:
            errors.append({"target": f"{email}/{folder}", "reason": "response-size-exceeded"})
            mailboxes[f"{email}/{folder}"] = 0
            continue
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append({"target": f"{email}/{folder}", "reason": f"{type(exc).__name__}"})
            mailboxes[f"{email}/{folder}"] = 0
            continue
        if not isinstance(data, list):
            errors.append({"target": f"{email}/{folder}", "reason": "unexpected-payload"})
            mailboxes[f"{email}/{folder}"] = 0
            continue
        count = 0
        for message in data:
            if not isinstance(message, dict):
                continue
            uid = message.get("uid")
            try:
                uid_text = str(int(uid))
            except (TypeError, ValueError):
                errors.append({"target": f"{email}/{folder}", "reason": "bad-uid"})
                continue
            mime = message.get("mimeMessage", "")
            mime_bytes = mime.encode("utf-8") if isinstance(mime, str) else b""
            mime_truncated = False
            if len(mime_bytes) > max_mime_bytes:
                mime_bytes = mime_bytes[:max_mime_bytes]
                mime_truncated = True
            eml_name = f"{stem}__uid-{uid_text}.eml"
            (out_dir / eml_name).write_bytes(mime_bytes)
            entry: dict[str, Any] = {
                "path": eml_name,
                "sha256": sha256_hex(mime_bytes),
                "size": len(mime_bytes),
                "truncated": mime_truncated,
                "uid": uid_text,
            }
            for key in ("messageId", "subject", "contentType"):
                if isinstance(message.get(key), str):
                    entry[key] = message[key]
            files.append(entry)
            count += 1
            if mime_truncated:
                errors.append(
                    {"target": f"{email}/{folder}/uid-{uid_text}", "reason": "mime-size-exceeded"}
                )
        mailboxes[f"{email}/{folder}"] = count

    manifest: dict[str, Any] = {
        "evidence_kind": "administrative-local-mail",
        "for_decision_system": False,
        "greenmail_schema": SCHEMA_REF,
        "greenmail_version": SCHEMA_VERSION,
        "endpoint": "GET /api/user/{emailOrId}/messages/{folderName}",
        "captured_at_utc": utc_now_iso(),
        "base_url_host": urllib.parse.urlparse(base_url).hostname,
        "targets": [f"{item['email']}/{item['folder']}" for item in clean_targets],
        "mailbox_message_counts": mailboxes,
        "files": files,
        "errors": errors,
    }
    (out_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest


def maybe_capture_local_mail_evidence(
    *,
    base_url: str,
    targets: Sequence[Mapping[str, str]],
    output_dir: str | Path,
    enabled: bool | None = None,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Opt-in wrapper: captures only when ``OS_OMNI_CAPTURE_LOCAL_MAIL=1``."""
    flag = os.environ.get(CAPTURE_ENV_VAR, "") if enabled is None else ("1" if enabled else "")
    if flag != "1":
        return None
    if not base_url:
        return None
    return capture_local_mail_evidence(
        base_url=base_url, targets=targets, output_dir=output_dir, **kwargs
    )


def capture_task_local_mail_evidence(
    *, task_file: str | Path, output_dir: str | Path
) -> dict[str, Any] | None:
    """Capture the declared Maily mailboxes after the model has stopped.

    Only the three existing iOS Maily tasks are supported. Targets and the
    local service URL come from their actual evaluator contract; neither
    arbitrary module imports nor mailbox enumeration are performed.
    """
    if os.environ.get(CAPTURE_ENV_VAR) != "1":
        return None
    task = discover_task_eval_params(task_file)
    task_id = task.get("task_id", "")
    suffix = {f"ios.maily.instruction_3_{n}": n for n in (1, 2, 3)}.get(task_id)
    if suffix is None:
        return None
    module_name, class_name = task["evaluator_id"].split(":", 1)
    expected_module = f"evaluators.ios.maily_instruction_3_{suffix}"
    if module_name != expected_module:
        raise ValueError("Maily evidence evaluator binding mismatch")
    module = importlib.import_module(expected_module)
    specs = getattr(module, "MESSAGE_SPECS", None) or module.CHECKPOINT_SPECS
    targets = discover_maily_targets(specs)
    sender = getattr(module, "SENDER_EMAIL", None) or getattr(module, "SENDER", None)
    if sender:
        targets = discover_maily_targets([{"mailbox": t["email"]} for t in targets] + [{"mailbox": sender}])
    base_url = task["params"].get("api_base_url") or getattr(module, class_name).DEFAULT_API_BASE_URL
    return capture_local_mail_evidence(base_url=base_url, targets=targets, output_dir=output_dir)
