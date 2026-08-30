"""Prepare reusable K-9 / Delta Chat app-data templates for Android tasks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from platforms.android.bootstrap import (
    DeltaChatBootstrapConfig,
    DeltaChatBootstrapper,
    K9BootstrapConfig,
    K9Bootstrapper,
)
from platforms.android.comm_state import (
    APP_STATE_SPECS,
    DEFAULT_TEMPLATE_DIR,
    ensure_adb_reverse_for_greenmail,
    export_app_data_template,
    restore_app_data_template,
    template_path_for,
)
from platforms.android.controller import AdbController


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create or restore reusable Android communication app states. "
            "Run this once before a large Android execution so task initializers "
            "can restore K-9 / Delta Chat state without repeating UI onboarding."
        )
    )
    parser.add_argument("--device", default="emulator-5554")
    parser.add_argument(
        "--apps",
        nargs="+",
        default=["k9", "deltachat"],
        choices=["k9", "deltachat"],
        help="Communication app states to prepare.",
    )
    parser.add_argument("--template-dir", default=str(DEFAULT_TEMPLATE_DIR))
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force UI onboarding and re-export templates even if they already exist.",
    )
    parser.add_argument(
        "--export-current",
        action="store_true",
        help="Do not run onboarding; export the currently configured app data as templates.",
    )
    parser.add_argument(
        "--restore-only",
        action="store_true",
        help="Only restore existing templates; fail if a template is missing.",
    )
    parser.add_argument(
        "--no-adb-reverse",
        action="store_true",
        help="Skip adb reverse setup for GreenMail SMTP/IMAP ports.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    controller = AdbController(adb_device=args.device)
    if not args.no_adb_reverse:
        ensure_adb_reverse_for_greenmail(controller)

    template_dir = Path(args.template_dir)
    for app_name in args.apps:
        path = template_path_for(app_name, template_dir)
        spec = APP_STATE_SPECS[app_name]
        print(f"[{spec.label}] template: {path}", flush=True)

        if args.restore_only:
            restore_app_data_template(controller, app_name, template_path=path)
            print(f"[{spec.label}] restored existing template", flush=True)
            continue

        if args.export_current:
            exported = export_app_data_template(controller, app_name, template_path=path)
            print(f"[{spec.label}] exported current app data to {exported}", flush=True)
            continue

        if path.is_file() and not args.refresh:
            restore_app_data_template(controller, app_name, template_path=path)
            print(f"[{spec.label}] restored existing template", flush=True)
            continue

        if app_name == "deltachat":
            DeltaChatBootstrapper(
                controller,
                DeltaChatBootstrapConfig(clear_app_data=True),
            ).run()
        elif app_name == "k9":
            K9Bootstrapper(
                controller,
                K9BootstrapConfig(clear_app_data=True),
            ).run()
        else:
            raise AssertionError(app_name)

        exported = export_app_data_template(controller, app_name, template_path=path)
        print(f"[{spec.label}] bootstrapped and exported to {exported}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
