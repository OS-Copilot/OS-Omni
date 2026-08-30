#!/usr/bin/env python3
"""Cache Linux oracle setup assets locally.

The Linux setup initializer can upload host files into the VM.  Keeping these
small OSWorld seed files in a local cache avoids making every oracle run depend
on live Hugging Face downloads from inside the guest.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from huggingface_hub import hf_hub_download

from initializers.linux.asset_cache import CACHE_ROOT, HF_PATH_TO_CACHE

REPO_ID = "xlangai/ubuntu_osworld_file_cache"
REPO_TYPE = "dataset"


def main() -> int:
    for repo_path, local_rel in HF_PATH_TO_CACHE.items():
        target = CACHE_ROOT / local_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        source = Path(
            hf_hub_download(
                repo_id=REPO_ID,
                repo_type=REPO_TYPE,
                filename=repo_path,
                local_files_only=False,
            )
        )
        shutil.copy2(source, target)
        print(f"{repo_path} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
