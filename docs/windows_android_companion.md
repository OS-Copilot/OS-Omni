# Windows + Android cross-device tasks (single screen)

The six `tasks/v1/cross_device/windows_android_*.yaml` tasks run on the Windows VM. They
use the same design as the Linux + Android tasks ([linux_android_companion.md](linux_android_companion.md)):
a companion Android phone is shown in a scrcpy window on the Windows desktop, the agent
sees only the Windows screen, and each task is a round trip. The agent prepares a file
in Markor on the phone, puts it on the Windows Desktop itself, builds the deliverable in
LibreOffice, and sends results back to the phone (a Markor note, Tasks items, Calendar
events, or a desktop file dropped onto the phone window).

The tasks were generated from the six Windows → Linux cross-VM workflows they replace.
The Notepad source stage moves to Markor on the phone, and the Linux LibreOffice target
stage moves to the Windows desktop with its checks unchanged (paths moved to
`C:\Users\User`, run with `py -3`). For `budget_review` and `launch_review_minutes` the
phone data is the Linux stage's own transfer file, because the Linux checks were written
against it; it differs from the file the Windows stage asks for.

The evaluator (`evaluators.windows.android_companion`) applies the Linux rules: the
phone's records over host adb, each phone copy's SHA-256 against the desktop file
(`Get-FileHash`), the Desktop copy and the document checked in the guest, and no executed
action that invokes or types `adb` or `scrcpy`.

## Components

| Part | Setup |
| --- | --- |
| Phone | The same Android V3 emulators and `osomni_cross_ready` snapshot as the Linux tasks (see the Linux doc); one per Windows VM |
| Windows VM | HF `Cloudriver/OS-Omni-VM` `v3.1/windows` (VMware package, snapshot `Final__Version`) converted for QEMU, plus scrcpy 3.1, saved as a QEMU snapshot |
| Link | The host forwarder from the Linux tasks. Under QEMU user networking the guest reaches it at the Docker bridge address `172.17.0.1`, like the Linux guest. |

## Windows VM under QEMU

The image is a VMware Workstation package. Its encryption is `partial` (vTPM and
configuration only), so the disks are plain sparse VMDKs.

1. Convert the writable child of the chain: `qemu-img convert -O qcow2 "Windows 11 x64-000003.vmdk" win11-v3.1-base.qcow2`.
2. Boot with UEFI without Secure Boot (`OVMF_CODE_4M.fd` with a qcow2 copy of `OVMF_VARS_4M.fd`). With the Microsoft-key
   variables the firmware refuses the boot loader (`Access Denied`).
3. Attach the disk to AHCI, not NVMe. QEMU's NVMe device cannot be migrated, so `savevm` fails. Before the switch, set
   `HKLM\SYSTEM\CurrentControlSet\Services\storahci\Start` to 0 while still booted from NVMe.
4. Use `-device VGA,edid=on,xres=1920,yres=1080` for a 1920x1080 desktop, and `-rtc base=2026-06-15T09:00:00` with the
   Windows Time service disabled. The image is Windows 11 Enterprise Evaluation, and at the current date its licence has
   expired (an expired evaluation shuts down every hour). At the fixed date it has 43 days left, and every snapshot
   restore returns to that time.
5. In the guest, once:
   * disable the VMware Tools service and its `VMware User Process` Run entry, and turn on automatic logon for `User`;
   * install the repo's runtime (`platforms/windows/guest/runtime_server.py`) under `%LOCALAPPDATA%\Temp\HelloWorldRuntime`
     with a watchdog started by a logon scheduled task, and remove the image's Startup shortcut to the older runtime in
     `C:\helloworld_runtime`, which does not come up under QEMU. Do not run `arrange-sota-desktop.py`: on this desktop it
     drags shortcuts into folders;
   * turn off app restore after sign-in (`RestartApps`) and the OneDrive autostart;
   * put scrcpy 3.1 for Windows (it bundles `adb.exe`) in `C:\OS-Omni\scrcpy` and add inbound firewall allow rules for
     `adb.exe` and `scrcpy.exe`, so no firewall prompt appears on the desktop;
   * backdate the LibreOffice installation files to before the guest date. Files newer than the clock make LibreOffice
     "update your installation" on every start (and then open a release-notes link). Then start Calc once, turn off the
     tip of the day, and quit, so the profile has no first-run dialogs.
   * in Notepad's settings, turn off spell check and autocorrect (the per-extension overrides in `SpellCheckState`
     too) and choose "Start new session" when Notepad starts. Autocorrect lowercases typed names (`Haddad` became
     `haddad`), and a restored session opens a tab whose file is gone, with an error dialog. The values live in the
     package's `Settings\settings.dat` hive (`SpellCheckState`, `AutoCorrect`, `GhostFile`);
   * in the LibreOffice profile (`registrymodifications.xcu`), turn off the AutoCorrect options that rewrite typed
     text (`/org.openoffice.Office.Common/AutoCorrect`: `CapitalAtStartSentence`, `ChangeDash`, `ReplaceSingleQuote`,
     `ReplaceDoubleQuote`, `UseReplacementTable`, `ChangeOrdinalNumber`, `SetInetAttribute`, `SetDOIAttribute`,
     `ChangeUnderlineWeight`, `TwoCapitalsAtStart`, `AddNonBreakingSpace`, `ChangeAngleQuotes`,
     `CorrectAccidentalCapsLock`) and AutoRecovery (`/org.openoffice.Office.Recovery/AutoSave` `Enabled`). The checks
     compare exact text: Writer otherwise capitalizes the first word of every table cell and turns " - " into an
     en dash, and its AutoRecovery saves stalled Writer in long sessions;
   * turn off toast notifications (`HKCU\...\PushNotifications` `ToastEnabled` 0, and the Windows Defender Security
     Center `DisableNotifications` policy). At the fixed old date Defender reports "virus protection is out of date".
6. Save the snapshot with `savevm os_omni_win_android`. A restore takes about 6 s.

## Starting programs from the runtime

The runtime runs PowerShell with its output captured. A program that keeps running and
inherits those pipes holds the request open until it exits: `adb` started implicitly as a
server, or anything started with `Start-Process -Redirect*`. `-WindowStyle Hidden` would
also hide scrcpy's phone window. The phone script (`platforms/windows/android_companion.py`)
therefore starts the adb server with plain `Start-Process`, runs adb commands with their
output redirected to files, and starts scrcpy through `wscript` with a hidden console. In
PowerShell 5.1, `Start-Process -Wait` also waits for every child, so it is not used.

The phone window opens at x=1420, y=40, height 940, clear of the taskbar. As on Linux,
scrcpy uses `--keyboard=uhid` and `--shortcut-mod=rsuper`, so the agents' Alt+Left does
not rotate the phone view. The launcher is kept in `C:\OS-Omni\scrcpy\android_phone.vbs`.
The "Android phone" shortcut on the Desktop runs `open_phone.vbs`: it restores and raises
the phone window if it is minimized (for example after Win+D), and starts the launcher
again if the agent closed the window; the instruction says so. The restore script is
started hidden, and Windows applies the hidden start flag to its first `ShowWindow` call,
so it calls `ShowWindow` twice.

## Typing into the phone

pyautogui on Windows sends `keybd_event` with scan code 0. scrcpy (SDL) reads scan codes,
so typed letters, digits and shortcuts never reach the phone (with `--keyboard=uhid` and
with `--keyboard=sdk`; only punctuation sent as text arrives). Set `OS_OMNI_KEY_SCANCODES=1`:
the agent code prelude (`platforms/linux/runners/base_episode.py` `code_prelude`) then fills
in the real scan code with `MapVirtualKeyW`, plus the extended-key flag for navigation keys.
It is off by default, so other Windows runs send the same events as before.

## Clicking into the phone

pyautogui moves the cursor and presses the button back to back. On Windows the move message
can reach the scrcpy (SDL) window after the press, and SDL uses the last position it knows,
so the tap lands where the previous action left the cursor. In a test on the Settings list,
2 of 8 clicks landed on the intended row. Set `OS_OMNI_POINTER_SETTLE=0.05`: the prelude then
moves the cursor first and waits 50 ms before every `click`, `mouseDown` and `mouseUp`, also
when an earlier call moved the cursor (`moveTo` then `dragTo`, which presses without
coordinates). 8 of 8 clicks landed, and swipes after a click elsewhere went from 0 of 5 to
5 of 5. It is off by default.

Evaluating a phone copy hashes the desktop file with read/write sharing, because
LibreOffice keeps an open document locked.

## Run settings

Use the phone environment variables from the Linux doc, with this VM's phone, and run the
batch runner with `--platform windows`:

```bash
export OS_OMNI_WINDOWS_RUNTIME_TOKEN=windowsbench-runtime-token
export OS_OMNI_MIN_TYPE_INTERVAL=0.02
export OS_OMNI_KEY_SCANCODES=1
export OS_OMNI_POINTER_SETTLE=0.05
python scripts/run_linux_qemu_batch.py --platform windows \
  --execution executions/v1/cross_device_windows_android.yaml \
  --qmp-socket <qmp socket> --snapshot os_omni_win_android --runtime-port <port> ...
```

The runner sets no VM provider for the Windows worker and raises the initializer timeout
to 600 s. Each task is checked four ways: the initializer alone fails; the phone file,
the Desktop copy and the document from the Linux stage oracle without the return part
fail; with the return applied at state level, as for the Linux tasks, it passes; and the
transfer file typed into Markor through the phone window with the agent's prelude passes
the phone check.
