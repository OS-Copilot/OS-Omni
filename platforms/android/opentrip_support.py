"""Android OpenTrip helpers shared by reviewed-task evaluators."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from platforms.android.openshop_support import OpenShopAndroidStore

DEFAULT_APP_PACKAGE = "com.killt.opentrip"
DEFAULT_APP_ACTIVITY = "com.killt.opentrip.MainActivity"
LOCAL_STATE_KEY = "opentrip.localState.v1"
DEFAULT_LEVELDB_PATH_TEMPLATE = (
    "/data/user/0/{app_package}/app_webview/Default/Local Storage/leveldb"
)


class OpenTripAndroidStore(OpenShopAndroidStore):
    """Read OpenTrip's single WebView localStorage state object.

    OpenTrip and OpenShop use the same Capacitor/WebView storage layout.  The
    parent implementation already provides DevTools-first reads with a
    LevelDB snapshot fallback, so this adapter only supplies OpenTrip's
    package and storage-key defaults.
    """

    def __init__(
        self,
        controller: Any,
        *,
        app_package: str = DEFAULT_APP_PACKAGE,
        local_state_key: str = LOCAL_STATE_KEY,
        leveldb_path: str | None = None,
    ) -> None:
        super().__init__(
            controller,
            app_package=app_package,
            local_state_key=local_state_key,
            # Seed data is not used by read_state(), but the shared store keeps
            # the path as part of its general OpenShop API.
            seed_data_path=Path(__file__),
            leveldb_path=(
                leveldb_path
                or DEFAULT_LEVELDB_PATH_TEMPLATE.format(app_package=app_package)
            ),
        )
