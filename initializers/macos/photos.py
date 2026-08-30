"""Initializer utilities for native Apple Photos tasks on macOS."""

from __future__ import annotations

import json
import time
import shlex
from textwrap import dedent
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


DEFAULT_ASSETS: list[dict[str, str]] = [
    {"filename": "client_receipt_blue_final_774.png", "label": "RECEIPT BLUE FINAL 774", "color": "#4f8fd8"},
    {"filename": "client_receipt_green_final_610.png", "label": "RECEIPT GREEN FINAL 610", "color": "#4fa56b"},
    {"filename": "client_receipt_red_final_203.png", "label": "RECEIPT RED FINAL 203", "color": "#d75b55"},
    {"filename": "blue_route_card_final_1740.png", "label": "BLUE ROUTE FINAL 1740", "color": "#3868c8"},
    {"filename": "blue_route_map_final_303.png", "label": "BLUE ROUTE MAP FINAL 303", "color": "#2f76c2"},
    {"filename": "blue_route_cover_final_501.png", "label": "BLUE ROUTE COVER FINAL 501", "color": "#3a8bbf"},
    {"filename": "receipt_blue_draft_774.png", "label": "RECEIPT BLUE DRAFT 774", "color": "#9bbce5"},
    {"filename": "client_receipt_green_backup_610.png", "label": "RECEIPT GREEN BACKUP 610", "color": "#9bcfa8"},
    {"filename": "blue_route_card_hold_1740.png", "label": "BLUE ROUTE HOLD 1740", "color": "#8aa4d6"},
    {"filename": "red_route_cover_final_501.png", "label": "RED ROUTE FINAL 501", "color": "#d06a74"},
]


def photos_asset_filenames() -> list[str]:
    """Return the default asset filenames in creation order."""

    return [item["filename"] for item in DEFAULT_ASSETS]


class PhotosInitializer(BaseInitializer):
    """Reset Photos, generate labeled PNG assets, and optionally open/import them."""

    DEFAULT_ASSET_DIR = "~/Pictures/photos_bench_inbox"
    DEFAULT_FINAL_WAIT_MS = 3000

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "run_bash_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_bash_script is required")

        asset_dir = str(params.get("asset_dir") or self.DEFAULT_ASSET_DIR).strip()
        assets = params.get("assets")
        if not isinstance(assets, list) or not assets:
            assets = DEFAULT_ASSETS
        mode = str(params.get("mode") or "open").strip().lower()
        open_files = self._string_list(params.get("open_files"))
        reset_library = bool(params.get("reset_library", True))
        force_english = bool(params.get("force_english", True))
        dismiss_prompts = bool(params.get("dismiss_prompts", True))
        final_wait_ms = int(params.get("final_wait_ms", self.DEFAULT_FINAL_WAIT_MS) or 0)

        try:
            result = controller.run_bash_script(
                self._setup_script(
                    asset_dir=asset_dir,
                    assets=[dict(item) for item in assets if isinstance(item, Mapping)],
                    mode=mode,
                    open_files=open_files,
                    reset_library=reset_library,
                    force_english=force_english,
                    dismiss_prompts=dismiss_prompts,
                ),
                timeout=150,
            )
            self._ensure_success(result, action="prepare Photos")
            if final_wait_ms > 0:
                time.sleep(final_wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Photos: {exc}",
                metadata={
                    "asset_dir": asset_dir,
                    "mode": mode,
                    "open_files": open_files,
                    "reset_library": reset_library,
                    "force_english": force_english,
                    "dismiss_prompts": dismiss_prompts,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Photos",
            metadata={
                "asset_dir": asset_dir,
                "asset_count": len(assets),
                "mode": mode,
                "open_files": open_files,
                "reset_library": reset_library,
                "force_english": force_english,
                "dismiss_prompts": dismiss_prompts,
            },
        )

    @staticmethod
    def _ensure_success(result: Mapping[str, Any], *, action: str) -> None:
        returncode = int(result.get("returncode", 0))
        success = bool(result.get("success", returncode == 0))
        if returncode != 0 or not success:
            output = str(result.get("output") or result.get("stdout") or result.get("message") or "").strip()
            raise RuntimeError(output or f"{action} failed with exit code {returncode}")

    @classmethod
    def _setup_script(
        cls,
        *,
        asset_dir: str,
        assets: list[dict[str, Any]],
        mode: str,
        open_files: list[str],
        reset_library: bool,
        force_english: bool,
        dismiss_prompts: bool,
    ) -> str:
        python_block = dedent(
            """
            import json
            import os
            import struct
            import zlib
            from pathlib import Path

            asset_dir = Path(os.path.expanduser(os.environ["ASSET_DIR"]))
            asset_dir.mkdir(parents=True, exist_ok=True)
            for old in asset_dir.glob("*.png"):
                old.unlink()

            assets = json.loads(os.environ["ASSETS_JSON"])

            FONT = {
                "A":["01110","10001","10001","11111","10001","10001","10001"], "B":["11110","10001","10001","11110","10001","10001","11110"],
                "C":["01111","10000","10000","10000","10000","10000","01111"], "D":["11110","10001","10001","10001","10001","10001","11110"],
                "E":["11111","10000","10000","11110","10000","10000","11111"], "F":["11111","10000","10000","11110","10000","10000","10000"],
                "G":["01111","10000","10000","10111","10001","10001","01110"], "H":["10001","10001","10001","11111","10001","10001","10001"],
                "I":["11111","00100","00100","00100","00100","00100","11111"], "J":["00111","00010","00010","00010","00010","10010","01100"],
                "K":["10001","10010","10100","11000","10100","10010","10001"], "L":["10000","10000","10000","10000","10000","10000","11111"],
                "M":["10001","11011","10101","10101","10001","10001","10001"], "N":["10001","11001","10101","10011","10001","10001","10001"],
                "O":["01110","10001","10001","10001","10001","10001","01110"], "P":["11110","10001","10001","11110","10000","10000","10000"],
                "Q":["01110","10001","10001","10001","10101","10010","01101"], "R":["11110","10001","10001","11110","10100","10010","10001"],
                "S":["01111","10000","10000","01110","00001","00001","11110"], "T":["11111","00100","00100","00100","00100","00100","00100"],
                "U":["10001","10001","10001","10001","10001","10001","01110"], "V":["10001","10001","10001","10001","01010","01010","00100"],
                "W":["10001","10001","10001","10101","10101","11011","10001"], "X":["10001","01010","00100","00100","00100","01010","10001"],
                "Y":["10001","01010","00100","00100","00100","00100","00100"], "Z":["11111","00001","00010","00100","01000","10000","11111"],
                "0":["01110","10001","10011","10101","11001","10001","01110"], "1":["00100","01100","00100","00100","00100","00100","01110"],
                "2":["01110","10001","00001","00010","00100","01000","11111"], "3":["11110","00001","00001","01110","00001","00001","11110"],
                "4":["00010","00110","01010","10010","11111","00010","00010"], "5":["11111","10000","10000","11110","00001","00001","11110"],
                "6":["01110","10000","10000","11110","10001","10001","01110"], "7":["11111","00001","00010","00100","01000","01000","01000"],
                "8":["01110","10001","10001","01110","10001","10001","01110"], "9":["01110","10001","10001","01111","00001","00001","01110"],
                "-":["00000","00000","00000","11111","00000","00000","00000"], "_":["00000","00000","00000","00000","00000","00000","11111"],
                " ":["00000","00000","00000","00000","00000","00000","00000"],
            }

            def hex_rgb(value):
                value = str(value or "#777777").strip().lstrip("#")
                return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))

            def png_bytes(width, height, pixels):
                raw = b"".join(b"\\x00" + bytes(row) for row in pixels)
                def chunk(kind, data):
                    body = kind + data
                    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xffffffff)
                return (
                    b"\\x89PNG\\r\\n\\x1a\\n"
                    + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress(raw, 9))
                    + chunk(b"IEND", b"")
                )

            def draw_rect(pixels, x0, y0, x1, y1, rgb):
                height = len(pixels)
                width = len(pixels[0]) // 3
                x0, y0 = max(0, x0), max(0, y0)
                x1, y1 = min(width, x1), min(height, y1)
                for y in range(y0, y1):
                    row = pixels[y]
                    for x in range(x0, x1):
                        row[x*3:x*3+3] = rgb

            def draw_text(pixels, text, x, y, scale, rgb):
                cursor = x
                for ch in text.upper():
                    glyph = FONT.get(ch, FONT[" "])
                    for gy, line in enumerate(glyph):
                        for gx, bit in enumerate(line):
                            if bit == "1":
                                draw_rect(pixels, cursor + gx*scale, y + gy*scale, cursor + (gx+1)*scale, y + (gy+1)*scale, rgb)
                    cursor += 6 * scale

            def wrap_words(label, max_chars=14):
                words = str(label).upper().replace("_", " ").split()
                lines = []
                current = ""
                for word in words:
                    candidate = word if not current else current + " " + word
                    if len(candidate) <= max_chars:
                        current = candidate
                    else:
                        if current:
                            lines.append(current)
                        current = word
                if current:
                    lines.append(current)
                return lines[:4]

            for item in assets:
                filename = str(item.get("filename") or "").strip()
                if not filename:
                    continue
                label = str(item.get("label") or filename.rsplit(".", 1)[0]).strip()
                bg = hex_rgb(item.get("color"))
                width, height = 900, 620
                pixels = [bytearray(bg * width) for _ in range(height)]
                draw_rect(pixels, 35, 35, width - 35, height - 35, (245, 245, 238))
                draw_rect(pixels, 55, 55, width - 55, height - 55, bg)
                lines = wrap_words(label)
                scale = 12
                line_height = 8 * scale
                start_y = max(90, (height - line_height * len(lines)) // 2)
                for idx, line in enumerate(lines):
                    text_width = len(line) * 6 * scale
                    draw_text(pixels, line, max(70, (width - text_width) // 2), start_y + idx * line_height, scale, (18, 22, 25))
                (asset_dir / filename).write_bytes(png_bytes(width, height, pixels))
            """
        ).strip()

        prefix = dedent(
            f"""
            set -euo pipefail

            ASSET_DIR={cls._asset_dir_shell_value(asset_dir)}
            MODE={shlex.quote(mode)}
            OPEN_FILES_JSON={shlex.quote(json.dumps(open_files, ensure_ascii=False))}
            RESET_LIBRARY={1 if reset_library else 0}
            FORCE_ENGLISH={1 if force_english else 0}
            DISMISS_PROMPTS={1 if dismiss_prompts else 0}
            ASSETS_JSON={shlex.quote(json.dumps(assets, ensure_ascii=False))}
            export ASSET_DIR MODE OPEN_FILES_JSON ASSETS_JSON

            killall Photos >/dev/null 2>&1 || true
            killall photolibraryd >/dev/null 2>&1 || true
            killall photoanalysisd >/dev/null 2>&1 || true

            if [ "$FORCE_ENGLISH" -eq 1 ]; then
              defaults write com.apple.Photos AppleLanguages -array en-US
              defaults write com.apple.Photos AppleLocale -string en_US
              killall cfprefsd >/dev/null 2>&1 || true
            fi

            if [ "$RESET_LIBRARY" -eq 1 ]; then
              rm -rf "$HOME/Pictures/Photos Library.photoslibrary"
              rm -rf "$HOME/Library/Saved Application State/com.apple.Photos.savedState"
              rm -rf "$HOME/Library/Containers/com.apple.Photos/Data/Library/Saved Application State/com.apple.Photos.savedState"
              rm -rf "$HOME/Library/Containers/com.apple.Photos/Data/Library/Caches"
              rm -f "$HOME/Library/Preferences/com.apple.Photos.plist.lockfile"
            fi

            /usr/bin/python3 <<'PY'
            """
        ).strip()

        suffix = dedent(
            f"""
            PY

            /usr/bin/open -b com.apple.Photos || true
            sleep 8
            {cls._applescript_click_buttons(["Get Started", "开始使用", "Continue", "继续"])}
            sleep 2

            if [ "$DISMISS_PROMPTS" -eq 1 ]; then
              {cls._prompt_dismiss_script()}
            fi

            if [ "$MODE" = "import_prompt" ] || [ "$MODE" = "imported" ]; then
              : > /tmp/photos_open_files.txt
              /usr/bin/python3 -c 'import json, os; print("\\n".join(json.loads(os.environ["OPEN_FILES_JSON"])))' | while IFS= read -r name; do
                if [ -f "$ASSET_DIR/$name" ]; then
                  printf '%s\\n' "$ASSET_DIR/$name" >> /tmp/photos_open_files.txt
                fi
              done
              if [ ! -s /tmp/photos_open_files.txt ]; then
                find "$ASSET_DIR" -maxdepth 1 -type f -name '*.png' | sort > /tmp/photos_open_files.txt
              fi
              if [ -s /tmp/photos_open_files.txt ]; then
                xargs /usr/bin/open -b com.apple.Photos < /tmp/photos_open_files.txt
                sleep 8
              fi
            fi

            if [ "$MODE" = "imported" ]; then
              osascript -e 'tell application "System Events" to click at {1470, 116}' >/dev/null 2>&1 || true
              sleep 14
            fi

            osascript -e 'tell application "Photos" to activate' >/dev/null 2>&1 || true
            osascript -e 'tell application "System Events" to click at {80, 80}' >/dev/null 2>&1 || true
            """
        ).strip()

        return "\n".join([prefix, python_block, suffix])

    @staticmethod
    def _asset_dir_shell_value(asset_dir: str) -> str:
        normalized = str(asset_dir or PhotosInitializer.DEFAULT_ASSET_DIR).strip()
        if normalized == "~":
            return '"$HOME"'
        if normalized.startswith("~/"):
            return '"$HOME/' + normalized[2:].replace('"', '\\"') + '"'
        return shlex.quote(normalized)

    @staticmethod
    def _applescript_click_buttons(labels: list[str]) -> str:
        labels_literal = "{" + ", ".join(json.dumps(label, ensure_ascii=False) for label in labels) + "}"
        return dedent(
            f"""
            osascript <<'APPLESCRIPT' >/dev/null 2>&1 || true
            on clickWalk(e, targetName, depth)
              if depth > 12 then return false
              tell application "System Events"
                set roleName to ""
                set titleName to ""
                set descName to ""
                set valueName to ""
                try
                  set roleName to role of e
                end try
                try
                  set titleName to title of e
                end try
                try
                  set descName to description of e
                end try
                try
                  set valueName to value of e as text
                end try
                if (roleName is "AXButton" or roleName is "AXCheckBox" or roleName is "AXMenuItem") and (titleName is targetName or descName is targetName or valueName is targetName) then
                  click e
                  return true
                end if
                try
                  repeat with k in UI elements of e
                    if my clickWalk(k, targetName, depth + 1) then return true
                  end repeat
                end try
              end tell
              return false
            end clickWalk

            tell application "System Events"
              repeat with targetName in {labels_literal}
                repeat with p in application processes
                  try
                    repeat with w in windows of p
                      if my clickWalk(w, targetName as text, 0) then delay 0.5
                    end repeat
                  end try
                end repeat
              end repeat
            end tell
            APPLESCRIPT
            """
        ).strip()

    @staticmethod
    def _prompt_dismiss_script() -> str:
        return dedent(
            """
            osascript <<'APPLESCRIPT' >/dev/null 2>&1 || true
            tell application "System Events"
              set promptButtons to {"Allow", "允许", "OK", "好", "Not Now", "以后", "稍后", "Continue", "继续"}
              repeat 8 times
                repeat with p in application processes
                  repeat with w in windows of p
                    repeat with buttonName in promptButtons
                      try
                        if exists button (buttonName as text) of w then
                          click button (buttonName as text) of w
                          delay 0.4
                        end if
                      end try
                    end repeat
                  end repeat
                end repeat
                delay 0.25
              end repeat
            end tell
            APPLESCRIPT
            """
        ).strip()

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []
