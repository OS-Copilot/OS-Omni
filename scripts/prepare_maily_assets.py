#!/usr/bin/env python3
"""Resolve Maily FSNotes / photo baseline assets with hash verification.

The evaluator byte contracts (see ``EXPECTED_FILE_HASHES`` /
``EXPECTED_PHOTO_HASHES`` in ``initializers/ios/maily_benchmark_seed.py``)
are the acceptance gate: only files whose SHA-256 matches the corresponding
original-evaluator constant are accepted.

This script never touches the simulator, GreenMail, app containers, or any
private directory. The caller selects the source explicitly -- an official
simulator archive, an extracted data-container directory, or any directory
tree -- via ``--source``; actual filesystem extraction from official app
containers is handled by root. This script only searches the caller-provided
tree, verifies hashes, copies accepted assets to ``--out``, and writes a
provenance record.

Typical flow (run from the repository root)::

    python scripts/prepare_maily_assets.py list-expected
    python scripts/prepare_maily_assets.py extract \\
        --source /path/to/caller-selected-archive-root \\
        --out ./recovered-assets --write-provenance
    python scripts/prepare_maily_assets.py verify --assets-dir ./recovered-assets

Subcommands:
- ``list-expected``: print the expected filename/hash table (live tasks only
  by default; ``--include-orphan`` adds the orphaned 3_4 seek references).
- ``extract``: walk ``--source``, match FSNotes files by exact filename and
  photos by SHA-256 over JPEG candidates, copy verified assets to ``--out``.
- ``verify``: check an ``--assets-dir`` tree against the expected hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from initializers.ios.maily_benchmark_seed import (  # noqa: E402
    EXPECTED_FILE_HASHES,
    EXPECTED_PHOTO_HASHES,
    TASK_3_1,
    TASK_3_2,
    TASK_3_3,
)

LIVE_TASKS = (TASK_3_1, TASK_3_2, TASK_3_3)
JPEG_MAGIC = b"\xff\xd8\xff"
ORPHAN_MARKER = "orphan evaluator"


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_files(*, include_orphan: bool = False) -> dict[str, str]:
    """Map FSNotes filename -> expected SHA-256."""
    table = {}
    for filename, entry in EXPECTED_FILE_HASHES.items():
        if not include_orphan and ORPHAN_MARKER in str(entry.get("task") or ""):
            continue
        table[filename] = str(entry["sha256"])
    return table


def expected_photos(*, include_orphan: bool = False) -> list[dict[str, str]]:
    """List expected photo hashes (matched by content, not filename)."""
    return [
        dict(entry)
        for entry in EXPECTED_PHOTO_HASHES
        if include_orphan or ORPHAN_MARKER not in str(entry.get("task") or "")
    ]


def find_verified_files(
    source: Path, *, include_orphan: bool = False
) -> dict[str, dict[str, object]]:
    """Search ``source`` for FSNotes originals; return verified hits only."""
    wanted = expected_files(include_orphan=include_orphan)
    found: dict[str, dict[str, object]] = {}
    if not source.exists():
        raise FileNotFoundError(f"source does not exist: {source}")
    for candidate in source.rglob("*"):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        if candidate.name not in wanted or candidate.name in found:
            continue
        digest = sha256_of_file(candidate)
        if digest == wanted[candidate.name]:
            found[candidate.name] = {
                "path": str(candidate),
                "sha256": digest,
                "size": candidate.stat().st_size,
                "verified": True,
            }
    return found


def find_verified_photos(
    source: Path, *, include_orphan: bool = False, scan_all_files: bool = False
) -> list[dict[str, object]]:
    """Search ``source`` for JPEGs whose bytes match expected photo hashes."""
    wanted = {entry["sha256"]: entry for entry in expected_photos(include_orphan=include_orphan)}
    found: dict[str, dict[str, object]] = {}
    if not source.exists():
        raise FileNotFoundError(f"source does not exist: {source}")
    for candidate in source.rglob("*"):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        suffix = candidate.suffix.lower()
        if not scan_all_files and suffix not in (".jpg", ".jpeg"):
            continue
        try:
            with candidate.open("rb") as handle:
                magic = handle.read(3)
            if magic != JPEG_MAGIC:
                continue
            digest = sha256_of_file(candidate)
        except OSError:
            continue
        if digest in wanted and digest not in found:
            found[digest] = {
                "path": str(candidate),
                "sha256": digest,
                "size": candidate.stat().st_size,
                "label": wanted[digest]["label"],
                "task": wanted[digest]["task"],
                "verified": True,
            }
    return list(found.values())


def copy_verified_assets(
    *,
    files: dict[str, dict[str, object]],
    photos: list[dict[str, object]],
    out_dir: Path,
) -> dict[str, str]:
    """Copy verified assets into ``out_dir``; return logical-name -> path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    copied: dict[str, str] = {}
    for filename, info in sorted(files.items()):
        target = out_dir / filename
        target.write_bytes(Path(str(info["path"])).read_bytes())
        copied[f"file:{filename}"] = str(target)
    for index, info in enumerate(sorted(photos, key=lambda item: str(item["sha256"]))):
        target = out_dir / f"photo_{index + 1}_{str(info['sha256'])[:12]}.jpg"
        target.write_bytes(Path(str(info["path"])).read_bytes())
        copied[f"photo:{info['sha256']}"] = str(target)
    return copied


def write_provenance(
    *,
    out_dir: Path,
    source: Path,
    files: dict[str, dict[str, object]],
    photos: list[dict[str, object]],
    copied: dict[str, str],
) -> Path:
    """Write a provenance record alongside the copied assets."""
    record = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "source_note": (
            "Caller-selected official simulator archive / data-container tree. "
            "This script only reads the caller-provided tree; actual filesystem "
            "extraction from official app containers is handled by root."
        ),
        "method": "exact-filename match for FSNotes files; SHA-256 match over JPEG candidates for photos",
        "files": files,
        "photos": photos,
        "copied": copied,
        "hash_basis": "original evaluator constants in evaluators/ios/maily_instruction_3_[123].py",
    }
    path = out_dir / "provenance.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def cmd_list_expected(args: argparse.Namespace) -> int:
    print(json.dumps(
        {
            "files": expected_files(include_orphan=args.include_orphan),
            "photos": expected_photos(include_orphan=args.include_orphan),
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ))
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    source = Path(args.source)
    out_dir = Path(args.out)
    files = find_verified_files(source, include_orphan=args.include_orphan)
    photos = find_verified_photos(
        source, include_orphan=args.include_orphan, scan_all_files=args.scan_all_files
    )
    wanted_files = expected_files(include_orphan=args.include_orphan)
    wanted_photo_hashes = {entry["sha256"] for entry in expected_photos(include_orphan=args.include_orphan)}
    missing_files = sorted(set(wanted_files) - set(files))
    missing_photos = sorted(wanted_photo_hashes - {str(item["sha256"]) for item in photos})
    # Provenance is always written: every extraction must record what source
    # tree was searched and which hashes verified.
    copied = copy_verified_assets(files=files, photos=photos, out_dir=out_dir)
    provenance_path = write_provenance(
        out_dir=out_dir, source=source, files=files, photos=photos, copied=copied
    )
    report = {
        "verified_files": sorted(files),
        "verified_photos": [str(item["sha256"]) for item in photos],
        "missing_files": missing_files,
        "missing_photos": missing_photos,
        "copied": copied,
        "provenance": str(provenance_path),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if missing_files or missing_photos:
        print(
            "NOTE: missing assets must be recovered from official sources or "
            "re-minted with evaluator+yaml hash updates; never weaken the hash checks.",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    assets_dir = Path(args.assets_dir)
    if not assets_dir.is_dir():
        print(f"assets dir does not exist: {assets_dir}", file=sys.stderr)
        return 2
    wanted_files = expected_files(include_orphan=args.include_orphan)
    wanted_photo_hashes = {entry["sha256"] for entry in expected_photos(include_orphan=args.include_orphan)}
    ok = True
    for filename, digest in sorted(wanted_files.items()):
        candidate = assets_dir / filename
        if not candidate.is_file() or sha256_of_file(candidate) != digest:
            print(f"MISMATCH file: {filename}", file=sys.stderr)
            ok = False
    seen_photo_hashes = set()
    for candidate in assets_dir.rglob("*.jpg"):
        if candidate.is_file():
            seen_photo_hashes.add(sha256_of_file(candidate))
    for digest in sorted(wanted_photo_hashes):
        if digest not in seen_photo_hashes:
            print(f"MISMATCH photo: {digest}", file=sys.stderr)
            ok = False
    print("verify: " + ("OK" if ok else "FAILED"))
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    list_parser = sub.add_parser("list-expected", help="print expected filename/hash table")
    list_parser.add_argument("--include-orphan", action="store_true",
                             help="include orphaned 3_4 seek references (no task wiring)")
    list_parser.set_defaults(func=cmd_list_expected)
    extract_parser = sub.add_parser("extract", help="extract + verify assets from a caller-selected source tree")
    extract_parser.add_argument("--source", required=True,
                                help="caller-selected official simulator archive / container tree (never a private default)")
    extract_parser.add_argument("--out", required=True, help="output directory for verified copies")
    extract_parser.add_argument("--include-orphan", action="store_true",
                                help="also seek orphaned 3_4 assets")
    extract_parser.add_argument("--scan-all-files", action="store_true",
                                help="hash non-.jpg files too when hunting photos")
    extract_parser.add_argument("--write-provenance", action="store_true",
                                help="write provenance.json (always written)")
    extract_parser.set_defaults(func=cmd_extract)
    verify_parser = sub.add_parser("verify", help="verify an assets directory against expected hashes")
    verify_parser.add_argument("--assets-dir", required=True, help="directory holding previously extracted assets")
    verify_parser.add_argument("--include-orphan", action="store_true",
                               help="also require orphaned 3_4 assets")
    verify_parser.set_defaults(func=cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
