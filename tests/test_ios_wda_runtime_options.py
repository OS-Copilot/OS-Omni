from __future__ import annotations

from pathlib import Path

from platforms.ios.runners import episode


def test_author_eval_wda_cache_overrides_attempt_local_derived_data(tmp_path, monkeypatch):
    shared = tmp_path / "shared-wda-cache"
    monkeypatch.setenv("OS_OMNI_WDA_DERIVED_DATA", str(shared))
    ports = iter((8100, 9100))
    monkeypatch.setattr(episode, "_find_free_tcp_port", lambda: next(ports))

    options = episode._build_wda_runtime_options("device-123", tmp_path / "attempt")

    assert options["derived_data_path"] == str(shared.resolve())
    assert Path(options["derived_data_path"]).is_dir()
    assert options["wda_local_port"] == 8100
    assert options["mjpeg_server_port"] == 9100
