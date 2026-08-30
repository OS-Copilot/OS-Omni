"""Android initializers for Fossify Gallery benchmark tasks."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from platforms.android.bench_storage_support import (
    clear_and_launch_app,
    delete_media_store_relative_dirs,
    ensure_app_installed,
    grant_permissions,
    grant_post_notifications,
    push_base64_file,
    remove_path,
    scan_media_paths,
    tap_gallery_album,
    wait_for_gallery_media_grid,
)
from platforms.android.bootstrap import AndroidBootstrapDriver


DEFAULT_APP_PACKAGE = "org.fossify.gallery"
DEFAULT_APP_ACTIVITY = ".activities.SplashActivity.Green"
DEFAULT_WAIT_MS = 1500
DEFAULT_WORKSPACE_ROOT = "/sdcard/Pictures/bench_gallery_lab"

_RED_JPEG_BASE64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCACAAIADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD50ooor8MP9UwooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACuk0j4d6/ruiW+r2VlHLp893JYxSNcxIWmjRJJBtZg2FSRGZsbQCSSADjm677wZ8WLjwZZ+HoLazcvpV9qV008VyYnkS9tYLZ1RgMxuqQsVkBOC4OPl52pKm5fvHZf8H/K55uOni4U08HFSlrvt8La6reVlfW172M+P4U+Jpbt4Fs7basKTi6OoWwtXR2ZE2T+Z5blmR1CqxJKMMZU4zvHfhj/hCfG/iHw79p+2f2RqNxYfaPL8vzfKlZN+3J2525xk4z1Ndnq3xktfEUN1YazpWqatpMiWhjF5rby3gltzOUZ53jIZT9qnBRUQYK4wQSeM8eeJ/wDhNvHHiLxF9m+xf2vqNxqH2bzN/lebK0mzdgbsbsZwM46CtasaKh+7d3/w/l6HBgqmZ1K/+1wUYWe1t/dt9pv+ZbJeburYVFFFch9CFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFAH//2Q=="
)
_BLUE_JPEG_BASE64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCACAAIADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD896KKK/1TPhwooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACvRvD/wO13xd8OtN8UaIYb+W71S/wBMOnPNDDLut4LWYeVvkDTu4uWAjjUsPK77sDzmvVvh98atO8EeF/DdnN4bm1DWvDWv3XiLSdRTUvJiS4litFRZYfKYyIj2aPgOpbOMgZz5OZSxsKcZYGN5X1Tta3LLu4/ats7+uz0hyt+8c943+FuoeEIZLyJ/7Q0qC00Wa4vMLH5U2pacL6KHZuLHCrMu4cHysnbuC1JqXwS8ZaOdZS80qK3uNIlu4bq1a+t/tGbZmW5aOLzN8yRlJN0kYZBsc5wpx0t18b9G1vT7vTtb8KXN7p9za6CrxW+qiFjc6XYvZRSbjA37qSKRy0eN2SCJBiuh8aftaX/jK18RobDV9O/tKXVhbWdn4glisIob+6nuHWe3RF+0SIbqZQ+5ARs3IwXB8b6znkfZwjQT25m3H+WN2rS35ua+iVrW89LUtXc8Aooor685wooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooA//2Q=="
)
_GREEN_JPEG_BASE64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCACAAIADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDu6KKK/h8/ziCiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAK17Dwlqmp2D3lvbo0CxSzfNPGjtHGpaRlRmDMAAeQDyMdayK7vRPEOj2vh6GW7l3ana6de6fDEpdTiZZQvy7CrYMzHcXXjI2nAJ9HA0aFao415cqS726ryfS7t1PVy3D4bEVXHFT5YpX3S6run0u7W1sYB8F6spiDwwRCWGO4VpbuFFCSKGjJJcBSwOQDgnnjg1CfCeqrBPI1r5fkeZvikkRZcISHIjJ3MFw2SAQNpz0Nbll8RpLWa4/c3cME8FlEwsr028u62hEQO8KflYbiVx3HPGaWf4lXV1pU1tKt2JHS4jURX8iwFZnd2Lx8l2BkfBLc8ZBxz2+xyxpv2suvTz0+z1Wv4Ho+wyZpv20k/e6dnZfZ6rX8Hbcxb3wfq2n6f9tnt0WDyYrg7Z42cRSBSjlAxYKdyjJGMkDrxWNXQ3Xi43X9pf6Lt+2aXa6b/rM7PJ+z/P053fZ+nGN/U4556vNxUcPGa+rttefq/Jbqz+Z5GMjhYzSwjbjrv6tLot1Z+V7BRRRXGcAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQB//Z"
)


class _BaseFossifyGalleryInitializer(BaseInitializer):
    REQUIRED_PERMISSIONS = (
        "android.permission.READ_MEDIA_IMAGES",
        "android.permission.READ_MEDIA_VIDEO",
        "android.permission.READ_MEDIA_VISUAL_USER_SELECTED",
        "android.permission.ACCESS_MEDIA_LOCATION",
    )
    ERROR_TASK_LABEL = "gallery"
    SUCCESS_MESSAGE = "Fossify Gallery opened inside the camera album"

    def _prepare_common(self, context: Mapping[str, Any]) -> tuple[Any, dict[str, Any]] | InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for Fossify Gallery initialization",
            )

        app_package = str(params.get("app_package") or DEFAULT_APP_PACKAGE).strip()
        app_activity = str(params.get("app_activity") or DEFAULT_APP_ACTIVITY).strip()
        wait_ms = int(params.get("wait_ms", DEFAULT_WAIT_MS) or 0)
        clear_app_data = bool(params.get("clear_app_data", True))
        workspace_root = str(params.get("workspace_root") or DEFAULT_WORKSPACE_ROOT).strip()
        camera_dir = str(params.get("camera_dir") or f"{workspace_root}/camera").strip()
        receipts_dir = str(params.get("receipts_dir") or f"{workspace_root}/receipts").strip()
        extra_media_files = [
            dict(item)
            for item in (params.get("extra_media_files") or [])
            if isinstance(item, Mapping) and str(item.get("path") or "").strip()
        ]

        if not app_package or not app_activity or not workspace_root:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires app_package, app_activity, and workspace_root",
            )

        params.update(
            {
                "app_package": app_package,
                "app_activity": app_activity,
                "wait_ms": wait_ms,
                "clear_app_data": clear_app_data,
                "workspace_root": workspace_root,
                "camera_dir": camera_dir,
                "receipts_dir": receipts_dir,
                "camera_red": f"{camera_dir}/red.jpg",
                "camera_blue": f"{camera_dir}/blue.jpg",
                "receipts_green": f"{receipts_dir}/green.jpg",
                "extra_media_files": extra_media_files,
            }
        )
        return controller, params

    @staticmethod
    def _seed_media(controller: Any, params: Mapping[str, Any]) -> None:
        workspace_root = str(params["workspace_root"])
        remove_path(controller, workspace_root)
        media_root = workspace_root
        for prefix in ("/sdcard/", "/storage/emulated/0/"):
            if media_root.startswith(prefix):
                media_root = media_root[len(prefix) :]
                break
        media_root = media_root.strip("/")
        delete_media_store_relative_dirs(
            controller,
            (
                f"{media_root}/camera/",
                f"{media_root}/receipts/",
                f"{media_root}/archive/",
            ),
        )
        push_base64_file(controller, str(params["camera_red"]), _RED_JPEG_BASE64)
        push_base64_file(controller, str(params["camera_blue"]), _BLUE_JPEG_BASE64)
        push_base64_file(controller, str(params["receipts_green"]), _GREEN_JPEG_BASE64)
        seeded_paths = [
            str(params["camera_red"]),
            str(params["camera_blue"]),
            str(params["receipts_green"]),
        ]
        color_payloads = {
            "red": _RED_JPEG_BASE64,
            "blue": _BLUE_JPEG_BASE64,
            "green": _GREEN_JPEG_BASE64,
        }
        for item in params.get("extra_media_files") or []:
            remote_path = str(item.get("path") or "").strip()
            if not remote_path:
                continue
            color = str(item.get("color") or "blue").strip().lower()
            payload = color_payloads.get(color, _BLUE_JPEG_BASE64)
            push_base64_file(controller, remote_path, payload)
            seeded_paths.append(remote_path)
        scan_media_paths(controller, seeded_paths)

    def _launch_into_camera_album(self, controller: Any, params: Mapping[str, Any]) -> None:
        app_package = str(params["app_package"])
        app_activity = str(params["app_activity"])
        clear_app_data = bool(params.get("clear_app_data", True))
        wait_ms = int(params.get("wait_ms", DEFAULT_WAIT_MS) or 0)

        ensure_app_installed(controller, app_package, label="Fossify Gallery")
        clear_and_launch_app(
            controller,
            app_package=app_package,
            app_activity=app_activity,
            clear_app_data=clear_app_data,
            wait_ms=wait_ms,
        )
        grant_permissions(controller, app_package, self.REQUIRED_PERMISSIONS)
        grant_post_notifications(controller, app_package)
        clear_and_launch_app(
            controller,
            app_package=app_package,
            app_activity=app_activity,
            clear_app_data=False,
            wait_ms=wait_ms,
        )

        driver = AndroidBootstrapDriver(controller, expected_package=app_package, settle_delay_seconds=0.4)
        wait_for_gallery_media_grid(driver, timeout_seconds=12.0)
        tap_gallery_album(driver, "camera", timeout_seconds=10.0)
        driver.wait_for_node({"resource_id": "org.fossify.gallery:id/media_grid"}, timeout_seconds=10.0)

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        prepared = self._prepare_common(context)
        if isinstance(prepared, InitResult):
            return prepared
        controller, params = prepared

        try:
            self._seed_media(controller, params)
            self._launch_into_camera_album(controller, params)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=(
                    f"Failed to prepare Fossify Gallery {self.ERROR_TASK_LABEL} task: "
                    f"{type(exc).__name__}: {exc}"
                ),
                metadata=params,
            )

        return InitResult(
            status=InitStatus.PASS,
            message=self.SUCCESS_MESSAGE,
            metadata=params,
        )


class FossifyGalleryDeletePhotoInitializer(_BaseFossifyGalleryInitializer):
    """Seed gallery media and open the camera album."""
    ERROR_TASK_LABEL = "delete"


class FossifyGalleryRenamePhotoInitializer(_BaseFossifyGalleryInitializer):
    """Seed gallery media and open the camera album."""
    ERROR_TASK_LABEL = "rename"


class FossifyGalleryMoveRenamePhotoInitializer(_BaseFossifyGalleryInitializer):
    """Seed gallery media and open the camera album."""
    ERROR_TASK_LABEL = "move+rename"
