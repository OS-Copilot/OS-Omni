import logging
from pathlib import Path
import sys
from types import SimpleNamespace

from core.platform_shared.benchmark_runner import BaseBenchmarkRunner


def test_child_utf8_output_is_decoded_independently_of_host_code_page(tmp_path):
    log = tmp_path / "runner.log"
    runner = SimpleNamespace(logger=logging.getLogger(__name__))
    code = BaseBenchmarkRunner.run_command_streaming(
        runner, [sys.executable, "-X", "utf8", "-c", "print('\u2713')"], log, run_prefix="unicode",
    )
    assert code == 0
    assert "\u2713" in Path(log).read_text(encoding="utf-8")
