"""Build the upstream OpenTrip version matching the Windows multi-booking tasks.

No inventory is generated or rewritten. The only packaging adaptation changes
the default server port to the port declared by the task definitions.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import zipfile

REVISION = "044ab5a8e95597ffa7a4354c8736de43fa153c7e"
ROOT = "apps/opentrip/"


def build(source_repo: Path, output: Path) -> dict:
    paths = [ROOT + name for name in
             ("server.js", "package.json", "electron", "public", "shared")]
    archive = subprocess.run(
        ["git", "-C", str(source_repo), "archive", REVISION, *paths],
        check=True, capture_output=True,
    ).stdout
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        for entry in source:
            if entry.isfile():
                files[entry.name.removeprefix(ROOT)] = source.extractfile(entry).read()
    seed = json.loads(files["shared/seed-data.json"])
    flights = {row["id"]: row for row in seed["flights"]}
    hotels = {row["id"]: row for row in seed["hotels"]}
    for key, fields in {
        "f2008": {"flightNo": "ES8139", "from": "PVG", "to": "CKG", "date": "2026-06-01"},
        "f1001": {"flightNo": "ES6821", "from": "SHA", "to": "SYX", "date": "2026-06-12"},
    }.items():
        if any(flights[key].get(k) != v for k, v in fields.items()):
            raise ValueError(f"Upstream flight contract mismatch: {key}")
    for key, name in {"h4887": "Chengdu Jade Pavilion Boutique Stay",
                      "h4879": "Beijing Jade Pavilion Boutique Stay"}.items():
        if hotels[key]["name"] != name:
            raise ValueError(f"Upstream hotel contract mismatch: {key}")
    original = files["server.js"]
    if original.count(b"process.env.PORT || 4312") != 1:
        raise ValueError("Unexpected upstream server port declaration")
    manifest = {
        "repository": "https://github.com/killthefullmoon/OS-Omni-V2",
        "revision": REVISION,
        "adaptation": "server.js default port 4312 -> 4330",
        "upstream_server_sha256": hashlib.sha256(original).hexdigest(),
    }
    files["server.js"] = original.replace(b"process.env.PORT || 4312", b"process.env.PORT || 4330")
    manifest["installed_sha256"] = {
        name: hashlib.sha256(data).hexdigest() for name, data in files.items()
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as target:
        for name, data in files.items():
            target.writestr(name, data)
        target.writestr("osomni-build-manifest.json", json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.source_repo, args.output)
    print(f"Built pinned OpenTrip task baseline: {args.output}")
