"""Bootstrap communication apps on the Android emulator via UI automation."""

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
from platforms.android.controller import AdbController


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Automate first-time onboarding for Android communication benchmark apps.",
    )
    parser.add_argument(
        "--device",
        default="emulator-5554",
        help="ADB device serial. Default: emulator-5554",
    )

    subparsers = parser.add_subparsers(dest="app", required=True)

    deltachat = subparsers.add_parser("deltachat", help="Bootstrap Delta Chat against GreenMail.")
    deltachat.add_argument("--clear-app-data", action="store_true", help="Clear Delta Chat app data before onboarding.")
    deltachat.add_argument("--profile-name", default="BenchSender")
    deltachat.add_argument("--email", default="benchsender@example.test")
    deltachat.add_argument("--password", default="benchpass")
    deltachat.add_argument("--imap-login", default="benchsender@example.test")
    deltachat.add_argument("--imap-server", default="10.0.2.2")
    deltachat.add_argument("--imap-port", default="3143")
    deltachat.add_argument("--imap-security", default="Off")
    deltachat.add_argument("--smtp-login", default="benchsender@example.test")
    deltachat.add_argument("--smtp-password", default="benchpass")
    deltachat.add_argument("--smtp-server", default="10.0.2.2")
    deltachat.add_argument("--smtp-port", default="3025")
    deltachat.add_argument("--smtp-security", default="Off")
    deltachat.add_argument("--api-base-url", default="http://127.0.0.1:8081")
    deltachat.add_argument("--wait-after-submit-seconds", type=float, default=8.0)

    k9 = subparsers.add_parser("k9", help="Bootstrap K-9 Mail against GreenMail.")
    k9.add_argument("--clear-app-data", action="store_true", help="Clear K-9 Mail app data before onboarding.")
    k9.add_argument("--email", default="benchsender@example.test")
    k9.add_argument("--username", default="benchsender@example.test")
    k9.add_argument("--password", default="benchpass")
    k9.add_argument("--incoming-server", default="10.0.2.2")
    k9.add_argument("--incoming-port", default="3143")
    k9.add_argument("--incoming-security", default="None")
    k9.add_argument("--outgoing-server", default="10.0.2.2")
    k9.add_argument("--outgoing-port", default="3025")
    k9.add_argument("--outgoing-security", default="None")
    k9.add_argument("--display-name", default="BenchSender")
    k9.add_argument("--api-base-url", default="http://127.0.0.1:8081")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    controller = AdbController(adb_device=args.device)

    if args.app == "deltachat":
        config = DeltaChatBootstrapConfig(
            profile_name=args.profile_name,
            email=args.email,
            password=args.password,
            imap_login=args.imap_login,
            imap_server=args.imap_server,
            imap_port=str(args.imap_port),
            imap_security=args.imap_security,
            smtp_login=args.smtp_login,
            smtp_password=args.smtp_password,
            smtp_server=args.smtp_server,
            smtp_port=str(args.smtp_port),
            smtp_security=args.smtp_security,
            api_base_url=args.api_base_url,
            clear_app_data=bool(args.clear_app_data),
            wait_after_submit_seconds=float(args.wait_after_submit_seconds),
        )
        DeltaChatBootstrapper(controller, config).run()
        print("Delta Chat onboarding completed.")
        return 0

    if args.app == "k9":
        config = K9BootstrapConfig(
            email=args.email,
            username=args.username,
            password=args.password,
            incoming_server=args.incoming_server,
            incoming_port=str(args.incoming_port),
            incoming_security=args.incoming_security,
            outgoing_server=args.outgoing_server,
            outgoing_port=str(args.outgoing_port),
            outgoing_security=args.outgoing_security,
            display_name=args.display_name,
            api_base_url=args.api_base_url,
            clear_app_data=bool(args.clear_app_data),
        )
        K9Bootstrapper(controller, config).run()
        print("K-9 Mail onboarding completed.")
        return 0

    parser.error(f"Unsupported app: {args.app}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
