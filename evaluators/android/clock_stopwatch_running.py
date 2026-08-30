"""Evaluator for ClockStopWatchRunning task.

Checks whether the stopwatch is currently running in the Clock app.

Primary method: take two screenshots ~1s apart and compare their MD5
hashes on-device.  When the stopwatch is running, the timer digits
update continuously, causing pixel changes between frames.  This
bypasses ``uiautomator dump`` which cannot work during timer
animations ("could not get idle state").

Fallback: inspect the accessibility tree for "Pause" and "Lap" buttons
(the original android_world approach, works only when uiautomator succeeds).

Reference: android_world/task_evals/single/clock.py
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus


class ClockStopWatchRunningEvaluator(BaseEvaluator):
    """Validate that the stopwatch is actively running."""

    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
        controller = context.get("controller")
        final_observation = context.get("final_observation")

        # ------------------------------------------------------------------
        # Strategy 1: Screenshot diff (always works, even during animations)
        # ------------------------------------------------------------------
        if controller is not None and hasattr(controller, "execute_adb"):
            try:
                result = self._check_via_screenshot_diff(controller)
                if result is not None:
                    return result
            except Exception:
                pass  # Fall through to Strategy 2

        # ------------------------------------------------------------------
        # Strategy 2: UI tree — look for Pause + Lap buttons
        # ------------------------------------------------------------------
        observation = final_observation
        if observation is None and controller is not None and hasattr(controller, "observe"):
            try:
                observation = controller.observe(include_ui_tree=True)
            except Exception:
                pass

        if observation is not None:
            result = self._check_via_ui_tree(observation)
            if result is not None:
                return result

        return EvalResult(
            status=EvalStatus.UNDETERMINED,
            message="Could not determine stopwatch state with any strategy",
        )

    # ----- Strategy 1 -----

    # Crop region for the stopwatch timer display (avoids status bar clock).
    # Older AVDs used ~1080×2400 where a fixed 300..1200 crop was enough, but
    # newer emulator skins are much taller (for example 1280×2856) and place
    # the stopwatch digits lower on the screen. Use proportional bounds so the
    # timer remains inside the sampled region across common AVD sizes.
    _CROP_Y_START_RATIO = 0.10
    _CROP_Y_END_RATIO = 0.78

    def _check_via_screenshot_diff(self, controller: Any) -> EvalResult | None:
        """Take two screenshots 1.2s apart, crop to the timer region, and
        compare their MD5 on-device.

        Only the stopwatch time display area is compared so that the
        status-bar clock (top-right) does not cause false positives.
        """
        # First, verify Clock app is in the foreground
        activity_output = controller.execute_adb([
            "shell", "dumpsys", "activity", "activities",
        ])
        if not activity_output or "DeskClock" not in str(activity_output):
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Clock app is not in the foreground",
                metadata={"detection_method": "screenshot_diff"},
            )

        # Take two raw screenshots to temp files on device
        raw1 = "/data/local/tmp/_sw_eval_1.png"
        raw2 = "/data/local/tmp/_sw_eval_2.png"
        crop1 = "/data/local/tmp/_sw_eval_crop1.raw"
        crop2 = "/data/local/tmp/_sw_eval_crop2.raw"

        controller.execute_adb(["shell", "screencap", "-p", raw1])
        time.sleep(1.2)
        controller.execute_adb(["shell", "screencap", "-p", raw2])

        # Crop to the timer region using on-device Python or dd.
        # screencap -p produces PNG; to crop without ImageMagick we
        # re-capture as raw RGBA with screencap (no -p), then extract
        # the byte range for our crop rows.  screencap raw format is
        # 4 bytes header (w, h) + w*h*4 RGBA pixels stored row-major.
        #
        # Alternatively, we can just hash a sub-region of the raw bytes.
        # Approach: capture raw, dd out the rows we care about, md5sum.

        # Get screen dimensions
        wh_output = controller.execute_adb(["shell", "wm", "size"])
        width, height = 1080, 2400  # defaults
        if wh_output:
            # "Physical size: 1080x2400"
            for part in str(wh_output).split():
                if "x" in part:
                    try:
                        w, h = part.split("x")
                        width, height = int(w), int(h)
                    except ValueError:
                        pass

        y_start, y_end = self._crop_bounds(height)
        bytes_per_row = width * 4  # RGBA
        skip_bytes = 12 + y_start * bytes_per_row  # 12-byte header
        crop_bytes = (y_end - y_start) * bytes_per_row

        # Re-capture as raw RGBA (no -p flag)
        raw1_bin = "/data/local/tmp/_sw_raw1.bin"
        raw2_bin = "/data/local/tmp/_sw_raw2.bin"
        controller.execute_adb(["shell", "screencap", raw1_bin])
        time.sleep(1.2)
        controller.execute_adb(["shell", "screencap", raw2_bin])

        # Extract crop region and compute MD5
        hash_cmd = (
            f"dd if={raw1_bin} bs=1 skip={skip_bytes} count={crop_bytes} 2>/dev/null | md5sum && "
            f"dd if={raw2_bin} bs=1 skip={skip_bytes} count={crop_bytes} 2>/dev/null | md5sum"
        )
        hash_output = controller.execute_adb(["shell", hash_cmd])

        # Clean up all temp files
        controller.execute_adb([
            "shell", "rm", "-f", raw1, raw2, raw1_bin, raw2_bin, crop1, crop2
        ])

        if not hash_output:
            return None

        # Parse md5sum output: "<hash>  -\n<hash>  -"
        lines = [l.strip() for l in hash_output.strip().split("\n") if l.strip()]
        if len(lines) < 2:
            return None

        hash1 = lines[0].split()[0] if lines[0] else ""
        hash2 = lines[1].split()[0] if lines[1] else ""

        if not hash1 or not hash2:
            return None

        if hash1 != hash2:
            return EvalResult(
                status=EvalStatus.PASS,
                message="Stopwatch is running (timer region differs between captures)",
                metadata={
                    "detection_method": "screenshot_diff_cropped",
                    "crop_region": f"y={y_start}..{y_end}",
                    "hash1": hash1,
                    "hash2": hash2,
                },
            )
        else:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Stopwatch does not appear to be running (timer region unchanged)",
                metadata={
                    "detection_method": "screenshot_diff_cropped",
                    "crop_region": f"y={y_start}..{y_end}",
                    "hash": hash1,
                },
            )

    # ----- Strategy 2 -----

    @classmethod
    def _crop_bounds(cls, height: int) -> tuple[int, int]:
        safe_height = max(int(height or 0), 1)
        y_start = max(1, int(safe_height * cls._CROP_Y_START_RATIO))
        y_end = min(safe_height, int(safe_height * cls._CROP_Y_END_RATIO))
        if y_end <= y_start:
            y_end = safe_height
        return y_start, y_end

    @staticmethod
    def _check_via_ui_tree(observation: Any) -> EvalResult | None:
        """Check stopwatch state by looking for Pause and Lap buttons in UI."""
        ui_nodes = getattr(observation, "ui_nodes", []) or []

        texts = set()
        content_descs = set()
        for node in ui_nodes:
            if isinstance(node, dict):
                text = str(node.get("text", "") or "").strip()
                desc = str(node.get("content_description", "") or "").strip()
            else:
                text = str(getattr(node, "text", "") or "").strip()
                desc = str(getattr(node, "content_description", "") or "").strip()
            if text:
                texts.add(text)
            if desc:
                content_descs.add(desc)

        if not texts and not content_descs:
            return None

        pause_present = "Pause" in content_descs or "Pause" in texts
        lap_present = "Lap" in content_descs or "Lap" in texts

        if pause_present and lap_present:
            return EvalResult(
                status=EvalStatus.PASS,
                message="Stopwatch is running (Pause and Lap buttons visible)",
                metadata={"detection_method": "ui_tree"},
            )

        start_present = "Start" in content_descs or "Start" in texts
        if start_present:
            return EvalResult(
                status=EvalStatus.FAIL,
                message="Stopwatch is paused (Start button visible instead of Pause)",
                metadata={"detection_method": "ui_tree"},
            )

        return None
