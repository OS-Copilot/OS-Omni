"""The Windows OpenDriver initializer serves CanvasKit and a text font from app.asar itself."""

import json
import os
import struct
from pathlib import Path

import pytest

from evaluators.cua_review.initializers.windows import opendriver

BOOTSTRAP = (
    "(()=>{class b{async load({serviceWorkerSettings:e,config:r}={}){}}})();\r\n"
    "_flutter.buildConfig = {\"builds\":[{\"renderer\":\"canvaskit\"}]};\r\n"
    "_flutter.loader.load({\r\n  serviceWorkerSettings: {\r\n    serviceWorkerVersion: \"1\"\r\n  }\r\n});\r\n"
)
FILES = {
    "package.json": b'{"name":"opendriver"}',
    "public/flutter_bootstrap.js": BOOTSTRAP.encode(),
    "public/canvaskit/canvaskit.wasm": b"\0asm" + bytes(range(256)) * 64,
    "shared/backend/src/server.js": b"console.log('server');",
}


def _write_asar(path: Path, files: dict) -> None:
    header: dict = {"files": {}}
    data = b""
    for name, content in files.items():
        node = header
        parts = name.split("/")
        for part in parts[:-1]:
            node = node["files"].setdefault(part, {"files": {}})
        node["files"][parts[-1]] = {"size": len(content), "offset": str(len(data))}
        data += content
    text = json.dumps(header).encode()
    padded = text + b"\0" * (-len(text) % 4)
    pickle = struct.pack("<II", 4 + len(padded), len(text)) + padded
    path.write_bytes(struct.pack("<II", 4, len(pickle)) + pickle + data)


def _read_asar(path: Path) -> dict:
    raw = path.read_bytes()
    header_size = struct.unpack_from("<I", raw, 4)[0]
    assert struct.unpack_from("<I", raw, 8)[0] == header_size - 4
    json_size = struct.unpack_from("<I", raw, 12)[0]
    header = json.loads(raw[16:16 + json_size])
    base = 8 + header_size
    files = {}

    def walk(node, prefix):
        for name, child in node["files"].items():
            if "files" in child:
                walk(child, prefix + name + "/")
            else:
                start = base + int(child["offset"])
                files[prefix + name] = raw[start:start + child["size"]]
    walk(header, "")
    return files


class _Guest:
    """Runs the guest-side patch script on this host, as the Windows runtime would."""

    def __init__(self, cwd: Path):
        self.cwd = cwd

    def run_python_script(self, code, timeout=30):
        import contextlib
        import io
        import subprocess

        out = io.StringIO()
        old_cwd = os.getcwd()
        os.chdir(self.cwd)
        old_run = subprocess.run
        subprocess.run = lambda *args, **kwargs: None  # taskkill
        try:
            with contextlib.redirect_stdout(out):
                exec(compile(code, "guest", "exec"), {"__name__": "__main__"})
            returncode = 0
        except SystemExit as exc:
            returncode = 0 if exc.code in (None, 0) else 1
            out.write(str(exc.code or ""))
        finally:
            subprocess.run = old_run
            os.chdir(old_cwd)
        return {"returncode": returncode, "stdout": out.getvalue(), "output": out.getvalue()}


@pytest.mark.skipif(os.name == "nt", reason="the guest font path is only relative on a POSIX host")
def test_patch_points_flutter_at_local_assets_and_is_idempotent(tmp_path):
    asar = tmp_path / "app.asar"
    _write_asar(asar, FILES)
    # %WINDIR% is not expanded on a POSIX host, so the guest font directory is a relative path here.
    fonts = tmp_path / "%WINDIR%\\Fonts"
    fonts.mkdir()
    (fonts / "segoeui.ttf").write_bytes(b"\0\1\0\0 segoe ui font bytes")
    guest = _Guest(tmp_path)
    params = {"app_asar_paths": [str(tmp_path / "missing.asar"), str(asar)]}

    first = json.loads(opendriver.serve_assets_locally(guest, params))
    assert first["status"] == "patched" and first["font"].endswith("segoeui.ttf")

    files = _read_asar(asar)
    bootstrap = files["public/flutter_bootstrap.js"].decode()
    assert 'canvasKitBaseUrl: "canvaskit/"' in bootstrap and 'fontFallbackBaseUrl: "osomni-fonts/"' in bootstrap
    assert bootstrap.count("_flutter.loader.load({") == 1
    assert files["public/osomni-fonts/roboto/v32/KFOmCnqEu92Fr1Me4GZLCzYlKw.woff2"] == b"\0\1\0\0 segoe ui font bytes"
    for name in ("package.json", "public/canvaskit/canvaskit.wasm", "shared/backend/src/server.js"):
        assert files[name] == FILES[name]

    second = json.loads(opendriver.serve_assets_locally(guest, params))
    assert second["status"] == "already patched"
    assert _read_asar(asar) == files


def test_patch_failure_is_a_preparation_error(tmp_path):
    guest = _Guest(tmp_path)
    with pytest.raises(opendriver.WindowsPreparationError, match="offline-assets patch failed"):
        opendriver.serve_assets_locally(guest, {"app_asar_paths": [str(tmp_path / "missing.asar")]})
