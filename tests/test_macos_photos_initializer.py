import json
import os
import struct
import subprocess
import sys
from textwrap import dedent

from initializers.macos.photos import DEFAULT_ASSETS, PhotosInitializer


def test_photos_first_run_creates_the_exact_library_path_expected_by_evaluator():
    script = PhotosInitializer._setup_script(
        asset_dir="~/Pictures/photos_bench_inbox",
        assets=[dict(item) for item in DEFAULT_ASSETS],
        mode="open",
        open_files=[],
        reset_library=True,
        force_english=True,
        dismiss_prompts=True,
    )

    create_index = script.index('buttonName in {"Create New...", "Create New…", "Create New"}')
    open_index = script.index('/usr/bin/open -b com.apple.Photos')
    database_check_index = script.index("for attempt in $(seq 1 60)")
    assert open_index < create_index < database_check_index
    assert 'keystroke "Photos Library"' in script
    assert "Photos did not create the default library" in script
    assert 'windows of process "Photos"' in script
    assert "repeat with p in application processes" not in script


def test_photos_asset_generation_creates_all_expected_pngs_quickly(tmp_path):
    script = PhotosInitializer._setup_script(
        asset_dir="~/Pictures/photos_bench_inbox",
        assets=[dict(item) for item in DEFAULT_ASSETS],
        mode="open",
        open_files=[],
        reset_library=False,
        force_english=False,
        dismiss_prompts=False,
    )
    start = script.index("/usr/bin/python3 <<'PY'") + len("/usr/bin/python3 <<'PY'")
    end = script.index("\nPY\n", start)
    source = dedent(script[start:end])
    env = os.environ.copy()
    env["ASSET_DIR"] = str(tmp_path)
    env["ASSETS_JSON"] = json.dumps(DEFAULT_ASSETS)
    subprocess.run([sys.executable, "-c", source], env=env, check=True, timeout=10)

    generated = sorted(tmp_path.glob("*.png"))
    assert [path.name for path in generated] == sorted(item["filename"] for item in DEFAULT_ASSETS)
    for path in generated:
        data = path.read_bytes()
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        assert struct.unpack(">II", data[16:24]) == (900, 620)
