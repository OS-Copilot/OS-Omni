"""Verify downloaded consolidated evidence against its published manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def verify(directory: Path, *, members: bool = False) -> int:
    manifest = json.loads((directory / "release-manifest.json").read_text(encoding="utf-8"))
    assets = [*manifest["archives"], manifest["source_bundle"], *manifest.get("supplements", [])]
    for asset in assets:
        path = directory / asset["name"]
        if path.stat().st_size != asset["size"] or digest(path) != asset["sha256"]:
            raise ValueError(f"Asset checksum mismatch: {path.name}")
        if members and path.suffix == ".zip":
            with zipfile.ZipFile(path) as archive:
                inventory = json.loads(archive.read("FILE-MANIFEST.json"))
                assert set(archive.namelist()) == {entry["path"] for entry in inventory} | {"FILE-MANIFEST.json"}
                for entry in inventory:
                    value = hashlib.sha256()
                    size = 0
                    with archive.open(entry["path"]) as stream:
                        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                            value.update(block)
                            size += len(block)
                    if size != entry["bytes"] or value.hexdigest() != entry["sha256"]:
                        raise ValueError(f"Member checksum mismatch: {path.name}: {entry['path']}")
        print(f"Verified {path.name}")
    return len(assets)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--members", action="store_true", help="Also hash every file inside each ZIP")
    options = parser.parse_args()
    print(f"Verified {verify(options.directory, members=options.members)} assets")
