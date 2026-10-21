"""Initializer utilities for native Apple Maps tasks on macOS."""

from __future__ import annotations

import json
import time
from textwrap import dedent
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class MapsInitializer(BaseInitializer):
    """Reset Maps state, force English UI, launch Maps, and dismiss first-run prompts."""

    DEFAULT_FINAL_WAIT_MS = 3000

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "run_bash_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_bash_script is required")

        initial_url = str(params.get("initial_url") or "").strip()
        final_wait_ms = int(params.get("final_wait_ms", self.DEFAULT_FINAL_WAIT_MS) or 0)
        reset_state = bool(params.get("reset_state", True))
        force_english = bool(params.get("force_english", True))
        dismiss_prompts = bool(params.get("dismiss_prompts", True))

        try:
            setup_result = controller.run_bash_script(
                self._setup_script(
                    initial_url=initial_url,
                    reset_state=reset_state,
                    force_english=force_english,
                    dismiss_prompts=dismiss_prompts,
                ),
                timeout=90,
            )
            self._ensure_success(setup_result, action="prepare Maps")
            if dismiss_prompts:
                self._dismiss_prompt_actions(controller)
            if initial_url:
                reopen_result = controller.run_bash_script(
                    f"/usr/bin/open {json.dumps(initial_url)}\nsleep 2",
                    timeout=20,
                )
                self._ensure_success(reopen_result, action="reopen Maps URL")
                if dismiss_prompts:
                    self._dismiss_prompt_actions(controller)
            if final_wait_ms > 0:
                time.sleep(final_wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Maps: {exc}",
                metadata={
                    "initial_url": initial_url,
                    "final_wait_ms": final_wait_ms,
                    "reset_state": reset_state,
                    "force_english": force_english,
                    "dismiss_prompts": dismiss_prompts,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Maps",
            metadata={
                "initial_url": initial_url,
                "final_wait_ms": final_wait_ms,
                "reset_state": reset_state,
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

    @staticmethod
    def _setup_script(
        *,
        initial_url: str,
        reset_state: bool,
        force_english: bool,
        dismiss_prompts: bool,
    ) -> str:
        return dedent(
            f"""
            set -euo pipefail

            INITIAL_URL={json.dumps(initial_url)}
            RESET_STATE={1 if reset_state else 0}
            FORCE_ENGLISH={1 if force_english else 0}
            DISMISS_PROMPTS={1 if dismiss_prompts else 0}

            if [ "$FORCE_ENGLISH" -eq 1 ]; then
              defaults write com.apple.Maps AppleLanguages -array en-US
              defaults write com.apple.Maps AppleLocale -string en_US
              PREF_BASE="$HOME/Library/Containers/com.apple.Maps/Data/Library/Preferences/com.apple.Maps"
              mkdir -p "$(dirname "$PREF_BASE.plist")"
              defaults write "$PREF_BASE" AppleLanguages -array en-US
              defaults write "$PREF_BASE" AppleLocale -string en_US
            fi

            killall Maps >/dev/null 2>&1 || true
            killall mapssyncd >/dev/null 2>&1 || true

            if [ "$RESET_STATE" -eq 1 ]; then
              rm -rf "$HOME/Library/Saved Application State/com.apple.Maps.savedState"
              rm -rf "$HOME/Library/Containers/com.apple.Maps/Data/Library/Saved Application State/com.apple.Maps.savedState"
              rm -rf "$HOME/Library/Containers/com.apple.Maps/Data/Library/Caches/com.apple.Maps"
              rm -rf "$HOME/Library/Containers/com.apple.Maps/Data/Library/Caches/GeoServices"
              rm -f "$HOME/Library/Containers/com.apple.Maps/Data/Maps/MapsSync_0.0.1"*
              rm -f "$HOME/Library/Containers/com.apple.Maps/Data/Library/Preferences/com.apple.Maps.plist.lockfile"
              defaults delete com.apple.Maps LastViewedMapItemIdentifier >/dev/null 2>&1 || true
              defaults delete com.apple.Maps DidShowNoLocationWarning >/dev/null 2>&1 || true
              defaults delete com.apple.Maps ShouldShowOnboardingTipKit >/dev/null 2>&1 || true
              defaults delete com.apple.Maps HasShownSiriSuggestionsIntro >/dev/null 2>&1 || true
            fi

            if [ -n "$INITIAL_URL" ]; then
              /usr/bin/open "$INITIAL_URL"
            else
              /usr/bin/open -b com.apple.Maps
            fi

            sleep 3

            osascript <<'APPLESCRIPT' >/dev/null 2>&1 || true
            tell application "Maps" to activate
            tell application "System Events"
              tell process "Maps"
                repeat 20 times
                  try
                    if exists window 1 then
                      set position of window 1 to {{80, 80}}
                      set size of window 1 to {{1320, 860}}
                      exit repeat
                    end if
                  end try
                  delay 0.25
                end repeat
              end tell
            end tell
            APPLESCRIPT

            # Prompt dismissal is handled below through the runtime's current
            # accessibility tree. Repeatedly scanning every button in Maps,
            # CoreLocationAgent, and UserNotificationCenter here can block
            # AppleScript for minutes even when no prompt exists.
            if [ "$DISMISS_PROMPTS" -eq 1 ]; then
              /usr/bin/osascript -e 'tell application "Maps" to activate' >/dev/null 2>&1 || true
            fi

            if [ -n "$INITIAL_URL" ]; then
              /usr/bin/open "$INITIAL_URL"
              sleep 2
            fi
            for _ in 1 2 3; do
              osascript -e 'tell application "System Events" to click at {765, 780}' >/dev/null 2>&1 || true
              sleep 1
            done
            if [ -n "$INITIAL_URL" ]; then
              /usr/bin/open "$INITIAL_URL"
              sleep 2
            fi
            """
        ).strip()

    @staticmethod
    def _dismiss_prompt_actions(controller: Any) -> None:
        if not hasattr(controller, "observe") or not hasattr(controller, "execute_action"):
            return

        prompt_texts = [
            "Don't Allow",
            "Don’t Allow",
            "Not Now",
            "Continue",
            "Allow",
            "不允许",
            "以后",
            "稍后",
            "继续",
            "允许",
        ]
        for _ in range(8):
            try:
                observation = controller.observe(include_ui_tree=True, include_screenshot_data=False)
                ui_nodes = list(getattr(observation, "ui_nodes", []) or [])
            except Exception:
                return

            clicked = False
            prompt_visible = any(
                str(node.get("text") or "").strip() in prompt_texts
                for node in ui_nodes
                if isinstance(node, Mapping)
            )
            if not prompt_visible:
                return
            for text in prompt_texts:
                if not any(str(node.get("text") or "").strip() == text for node in ui_nodes if isinstance(node, Mapping)):
                    continue
                try:
                    result = controller.execute_action({"type": "tap", "target": {"text": text}}, ui_nodes)
                    returncode = int(result.get("returncode", 0)) if isinstance(result, Mapping) else 0
                    success = bool(result.get("success", returncode == 0)) if isinstance(result, Mapping) else True
                    if returncode == 0 and success:
                        clicked = True
                        time.sleep(0.5)
                        break
                except Exception:
                    continue
            if prompt_visible:
                try:
                    controller.execute_action({"type": "tap", "target": {"x": 0.398, "y": 0.723}}, ui_nodes)
                    clicked = True
                    time.sleep(0.5)
                except Exception:
                    pass
            if not clicked:
                time.sleep(0.5)
