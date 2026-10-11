from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from appium.webdriver.common.appiumby import AppiumBy

from core.init import InitStatus
from initializers.ios.safari_prepare_open_app import SafariPrepareOpenAppInitializer


class _Store:
    def purge_history(self, **kwargs):
        return 0

    def purge_bookmarks(self, **kwargs):
        return 0

    def purge_tabs(self, **kwargs):
        return 0


class _Element:
    def __init__(self, clicked: list[bool]):
        self.clicked = clicked

    def click(self):
        self.clicked.append(True)


class _Driver:
    def __init__(self):
        self.lookups: list[tuple[str, str]] = []
        self.clicked: list[bool] = []

    def find_element(self, by, value):
        self.lookups.append((by, value))
        return _Element(self.clicked)


class _Controller:
    def __init__(self, observations):
        self.observations = list(observations)
        self.driver = _Driver()
        self.calls: list[tuple] = []

    def terminate_app(self, bundle_id):
        self.calls.append(("terminate", bundle_id))

    def press_home(self):
        self.calls.append(("home",))

    def activate_app(self, bundle_id):
        self.calls.append(("activate", bundle_id))

    def alert_dismiss(self):
        return False

    def observe(self, include_ui_tree=True):
        self.calls.append(("observe", include_ui_tree))
        if len(self.observations) > 1:
            return self.observations.pop(0)
        return self.observations[0]


class SafariInitializerOnboardingTests(unittest.TestCase):
    @staticmethod
    def _observation(nodes):
        return SimpleNamespace(ui_nodes=nodes)

    def test_closes_start_page_sheet_only_when_matching_heading_is_visible(self):
        controller = _Controller([
            self._observation([
                {"type": "StaticText", "text": "Start Page"},
                {"type": "Button", "text": "close"},
            ]),
            self._observation([]),
        ])
        initializer = SafariPrepareOpenAppInitializer()

        with (
            patch.object(initializer, "_build_store", return_value=_Store()),
            patch("initializers.ios.safari_prepare_open_app.time.sleep"),
        ):
            result = initializer.initialize({
                "controller": controller,
                "params": {"bundle_id": "com.apple.mobilesafari", "terminate_after_setup": True},
            })

        self.assertEqual(result.status, InitStatus.PASS)
        self.assertTrue(result.metadata["dismissed_start_page_onboarding"])
        self.assertEqual(controller.driver.lookups, [(AppiumBy.ACCESSIBILITY_ID, "close")])
        self.assertEqual(controller.driver.clicked, [True])
        self.assertIn(("terminate", "com.apple.mobilesafari"), controller.calls)

    def test_leaves_safari_untouched_when_start_page_sheet_is_absent(self):
        controller = _Controller([self._observation([
            {"type": "Button", "text": "Bookmarks"},
        ])])
        initializer = SafariPrepareOpenAppInitializer()

        with (
            patch.object(initializer, "_build_store", return_value=_Store()),
            patch("initializers.ios.safari_prepare_open_app.time.sleep"),
        ):
            result = initializer.initialize({"controller": controller, "params": {}})

        self.assertEqual(result.status, InitStatus.PASS)
        self.assertFalse(result.metadata["dismissed_start_page_onboarding"])
        self.assertEqual(controller.driver.lookups, [])
        self.assertEqual(controller.driver.clicked, [])

    def test_fails_initialization_when_onboarding_cannot_be_dismissed(self):
        sheet = self._observation([
            {"type": "StaticText", "text": "Start Page"},
            {"type": "Button", "text": "close"},
        ])
        controller = _Controller([sheet, sheet, sheet])
        initializer = SafariPrepareOpenAppInitializer()

        with (
            patch.object(initializer, "_build_store", return_value=_Store()),
            patch("initializers.ios.safari_prepare_open_app.time.sleep"),
        ):
            result = initializer.initialize({"controller": controller, "params": {}})

        self.assertEqual(result.status, InitStatus.ERROR)
        self.assertIn("remained open", result.message)


if __name__ == "__main__":
    unittest.main()
