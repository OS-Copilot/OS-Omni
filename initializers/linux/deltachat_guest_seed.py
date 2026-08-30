"""Guest-side Delta Chat profile seeder.

This file is read by the host initializer and executed inside the Linux guest
with ``python3 -``. It must remain self-contained and avoid repo-local imports.
"""

from __future__ import annotations

import json
import os
import pathlib
import queue
import shutil
import subprocess
import threading
import time


SELF_CONTACT_ID = 1


class RpcClient:
    def __init__(self, rpc_path: str, accounts_path: pathlib.Path) -> None:
        env = dict(os.environ)
        env["DC_ACCOUNTS_PATH"] = str(accounts_path)
        self._process = subprocess.Popen(
            [rpc_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        self._pending: dict[int, queue.Queue[dict]] = {}
        self._next_id = 1
        self._stderr_lines: list[str] = []
        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_thread.start()

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        for raw in self._process.stdout:
            line = raw.strip()
            if not line:
                continue
            payload = json.loads(line)
            response_id = payload.get("id")
            if not isinstance(response_id, int):
                continue
            waiter = self._pending.get(response_id)
            if waiter is not None:
                waiter.put(payload)

    def _read_stderr(self) -> None:
        assert self._process.stderr is not None
        for raw in self._process.stderr:
            line = raw.rstrip()
            if line:
                self._stderr_lines.append(line)

    def call(self, method: str, params: list | None = None, *, timeout: int = 180):
        if params is None:
            params = []
        request_id = self._next_id
        self._next_id += 1
        waiter: queue.Queue[dict] = queue.Queue()
        self._pending[request_id] = waiter
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        self._process.stdin.flush()
        try:
            response = waiter.get(timeout=timeout)
        finally:
            self._pending.pop(request_id, None)
        if "error" in response:
            raise RuntimeError(f"{method} failed: {response['error']}")
        return response.get("result")

    def wait_event(self, account_id: int, event_kind: str, *, timeout: int = 120) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = max(1, int(deadline - time.time()))
            batch = self.call("get_next_event_batch", [], timeout=remaining)
            for item in batch:
                event = item.get("event") or {}
                if item.get("contextId") == account_id and event.get("kind") == event_kind:
                    return event
        raise TimeoutError(f"Timed out waiting for {event_kind} on account {account_id}")

    def close(self) -> None:
        self._process.kill()


def create_profile(client: RpcClient, *, chatmail_qr: str, display_name: str) -> dict:
    account_id = int(client.call("add_account"))
    client.call("set_config_from_qr", [account_id, chatmail_qr])
    client.call("set_config", [account_id, "displayname", display_name])
    client.call("configure", [account_id], timeout=180)
    client.wait_event(account_id, "ImapInboxIdle", timeout=180)
    account_info = dict(client.call("get_account_info", [account_id]))
    return {"id": account_id, "info": account_info}


def seed_incoming_messages(
    *,
    main_client: RpcClient,
    main_profile: dict,
    temp_client: RpcClient,
    sender_profile: dict,
    messages: list[str],
) -> dict:
    main_vcard = main_client.call("make_vcard", [main_profile["id"], [SELF_CONTACT_ID]])
    sender_vcard = temp_client.call("make_vcard", [sender_profile["id"], [SELF_CONTACT_ID]])

    imported_on_main = main_client.call("import_vcard_contents", [main_profile["id"], sender_vcard])
    sender_contact_id_on_main = int(imported_on_main[0])

    imported_on_sender = temp_client.call("import_vcard_contents", [sender_profile["id"], main_vcard])
    main_contact_id_on_sender = int(imported_on_sender[0])

    chat_id_on_sender = int(
        temp_client.call("create_chat_by_contact_id", [sender_profile["id"], main_contact_id_on_sender])
    )
    chat_id_on_main: int | None = None
    for message_text in messages:
        temp_client.call("misc_send_text_message", [sender_profile["id"], chat_id_on_sender, message_text])
        incoming_event = main_client.wait_event(main_profile["id"], "IncomingMsg", timeout=180)
        if chat_id_on_main is None:
            chat_id_on_main = int(incoming_event["chatId"])
            main_client.call("accept_chat", [main_profile["id"], chat_id_on_main])

    if chat_id_on_main is None:
        raise RuntimeError(f"No messages were seeded for sender {sender_profile['info']['displayName']}")

    return {
        "sender_contact_id_on_main": sender_contact_id_on_main,
        "chat_id_on_main": chat_id_on_main,
        "chat_id_on_sender": chat_id_on_sender,
    }


def build_manifest(
    *,
    profile_root: pathlib.Path,
    main_profile: dict,
    contact_profiles: dict[str, dict],
    contact_results: dict[str, dict],
    group_result: dict,
) -> dict:
    db_candidates = sorted((profile_root / "accounts").glob("*/dc.db"))
    if len(db_candidates) != 1:
        raise RuntimeError(f"Expected exactly one main account db, found {len(db_candidates)}")

    main_db = db_candidates[0]
    manifest = {
        "profile_root": str(profile_root),
        "main_account": {
            "display_name": main_profile["info"]["displayName"],
            "address": main_profile["info"]["addr"],
            "db_path": str(main_db.relative_to(profile_root)),
        },
        "contacts": {},
        "groups": {
            "ops_sprint": group_result,
        },
    }
    for key, profile in contact_profiles.items():
        result = contact_results[key]
        manifest["contacts"][key] = {
            "display_name": profile["info"]["displayName"],
            "address": profile["info"]["addr"],
            "chat_name": profile["info"]["displayName"],
            "chat_id_on_main": result["chat_id_on_main"],
            "seed_messages": list(result["seed_messages"]),
        }
    return manifest


def main() -> None:
    payload = json.loads(os.environ["HELLOWORLD_DELTA_SEED_JSON"])
    profile_root = pathlib.Path(payload["profile_root"]).expanduser()
    temp_root = pathlib.Path(payload["temp_root"]).expanduser()
    rpc_path = str(payload["rpc_path"])
    chatmail_qr = str(payload.get("chatmail_qr") or "dcaccount:ci-chatmail.testrun.org")
    contact_seeds = list(payload["contacts"])
    group_spec = dict(payload["group"])

    shutil.rmtree(profile_root, ignore_errors=True)
    shutil.rmtree(temp_root, ignore_errors=True)
    (profile_root / "accounts").mkdir(parents=True, exist_ok=True)
    (temp_root / "accounts").mkdir(parents=True, exist_ok=True)
    (profile_root / "config.json").write_text("{}\n", encoding="utf-8")

    main_client = RpcClient(rpc_path, profile_root / "accounts")
    temp_client = RpcClient(rpc_path, temp_root / "accounts")
    try:
        main_profile = create_profile(
            main_client,
            chatmail_qr=chatmail_qr,
            display_name=str(payload.get("owner_display_name") or "Benchmark Owner"),
        )

        contact_profiles: dict[str, dict] = {}
        contact_results: dict[str, dict] = {}
        for entry in contact_seeds:
            key = str(entry["key"])
            display_name = str(entry["display_name"])
            messages = [str(item) for item in entry.get("messages") or []]
            if not messages:
                raise RuntimeError(f"Contact seed {key} is missing messages")
            contact_profile = create_profile(
                temp_client,
                chatmail_qr=chatmail_qr,
                display_name=display_name,
            )
            seed_result = seed_incoming_messages(
                main_client=main_client,
                main_profile=main_profile,
                temp_client=temp_client,
                sender_profile=contact_profile,
                messages=messages,
            )
            seed_result["seed_messages"] = list(messages)
            contact_profiles[key] = contact_profile
            contact_results[key] = seed_result

        group_name = str(group_spec["name"])
        group_chat_id = int(main_client.call("create_group_chat", [main_profile["id"], group_name, False]))
        for member_key in group_spec.get("members", []):
            contact_address = contact_profiles[member_key]["info"]["addr"]
            contact_id = main_client.call("lookup_contact_id_by_addr", [main_profile["id"], contact_address])
            if contact_id is None:
                raise RuntimeError(f"Missing contact for group member {member_key}")
            main_client.call("add_contact_to_chat", [main_profile["id"], group_chat_id, int(contact_id)])
        group_messages = [str(item) for item in group_spec.get("messages") or []]
        for message_text in group_messages:
            main_client.call("misc_send_text_message", [main_profile["id"], group_chat_id, message_text])

        manifest = build_manifest(
            profile_root=profile_root,
            main_profile=main_profile,
            contact_profiles=contact_profiles,
            contact_results=contact_results,
            group_result={
                "chat_name": group_name,
                "chat_id_on_main": group_chat_id,
                "seed_messages": group_messages,
            },
        )
        manifest_path = profile_root / "benchmark_manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "ok", "manifest_path": str(manifest_path)}, ensure_ascii=False))
    finally:
        main_client.close()
        temp_client.close()
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
