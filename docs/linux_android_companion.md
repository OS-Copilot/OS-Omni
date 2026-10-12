# Linux + Android cross-device tasks (single screen)

The six `tasks/v1/cross_device/linux_android_*.yaml` tasks run on the Linux VM. A
companion Android phone is shown in a scrcpy window on the Linux desktop. The agent sees
only the Linux screen. It works on the phone through that window, moves the file to the
desktop itself (the harness does not copy it), and finishes in LibreOffice. The evaluator
then checks three things:

* the phone's file, read from the host over adb;
* the file on the Linux desktop and the finished document, checked in the guest;
* that no executed action invokes or types `adb` or `scrcpy`.

## Components

| Part | Setup |
| --- | --- |
| Phone | Android V3 image (HF `Cloudriver/OS-Omni-VM` `android_V3/android_V3.zip`, sha256 `746eb8f4…`) on the host, one emulator per Linux VM |
| Linux VM | Linux v3 image plus scrcpy 3.1, adb, `xclip`, openpyxl/python-docx/python-pptx, saved as a new QEMU snapshot |
| Link | Host forwarder from an address the guest can reach (Docker bridge `172.17.0.1`) to the emulator's adbd port. The initializer starts it if it is not running. |

## Phone (host)

1. Extract `AndroidWorldAvd.avd` and `AndroidWorldAvd.ini` from the V3 archive. Make one copy per Linux VM.
2. Fix the config before the first boot. A boot with the shipped config makes the emulator replace the userdata overlay and lose every installed app.
   * Convert `config.ini` to Unix line endings.
   * Use forward slashes in `image.sysdir.1`.
   * Delete the line `disk.dataPartition.path = <temp>`.
   * Write an absolute `path=` in `AndroidWorldAvd.ini`.
3. Add the emulator state files that V3 does not ship: `version_num.cache`, `qemu-version.txt`, `initrd`, `emulator-user.ini`, `netsim.ini`, `modem_simulator/` and `data/`. Take them from the v2 archive `AndroidWorldAvd_v2_20260625.zip`, which uses the same system image build 12342917. Without them the emulator also rebuilds the overlays.
4. Start each emulator with:
   `-port <5570|5572|…> -no-window -no-audio -gpu swiftshader_indirect -no-boot-anim -no-snapshot-load -no-snapshot-save -feature -Vulkan`.
   Without `-feature -Vulkan`, snapshot saving fails with `UNSUPPORTED_VK_APP`.
5. After the phone boots, prepare the clean state and save it:
   * keep the screen on and dismiss the keyguard;
   * run `settings put secure show_ime_with_hard_keyboard 0`, so scrcpy's hardware keyboard does not bring up the on-screen keyboard;
   * save the snapshot with `adb emu avd snapshot save osomni_cross_ready`.

   A restore takes about 3 s.

## Linux VM

Ubuntu 22.04's scrcpy 1.21 cannot sync the Android 13 clipboard. Its server fails with `NoSuchMethodException … addPrimaryClipChangedListener`, so text copied on the phone never reaches Linux. The official static scrcpy 3.1 build needs glibc 2.38, but the guest has 2.35.

1. On the host, build the 3.1 client in an `ubuntu:22.04` container:
   `meson setup build --buildtype=release -Dcompile_server=false -Dprebuilt_server=<release scrcpy-server>`, then `ninja`.
2. In the guest, starting from the clean snapshot:
   * install `scrcpy adb xclip python3-pip` with apt (the apt scrcpy package is only there for its runtime libraries);
   * install `openpyxl python-docx python-pptx` with pip;
   * put the 3.1 client, `scrcpy-server` and `adb` in `/opt/scrcpy`;
   * add a `/usr/local/bin/scrcpy` wrapper that sets `SCRCPY_SERVER_PATH` and `ADB`;
   * link `/usr/local/bin/adb`.
3. Save a new QEMU snapshot, for example `savevm os_omni_v3_android`.

The phone window opens with `--keyboard=uhid`, which presents a hardware keyboard to the phone. Even so, text typed with no gap between keys loses characters: at 0 ms most of a 780-character CSV was lost, at 10 ms one chunk was lost, and 20 ms was reliable in every trial. The harness therefore paces `pyautogui.write` when `OS_OMNI_MIN_TYPE_INTERVAL` is set. Use `0.02` for these tasks.

## Run settings

The initializer and evaluator read the phone settings from the environment, so one task file serves every VM:

```bash
export OS_OMNI_ANDROID_SERIAL=emulator-5570          # host adb serial of this VM's phone
export OS_OMNI_ANDROID_ADB=/path/to/platform-tools/adb
export ANDROID_ADB_SERVER_PORT=5037                  # host adb server that sees the emulators
export OS_OMNI_ANDROID_FORWARD=172.17.0.1:15571      # guest-reachable address forwarded to adbd (5571)
export OS_OMNI_ANDROID_SNAPSHOT=osomni_cross_ready
export OS_OMNI_MIN_TYPE_INTERVAL=0.02
python scripts/run_linux_qemu_batch.py --execution executions/v1/cross_device.yaml \
  --snapshot os_omni_v3_android ...
```

To probe a task without a model, run `scripts/linux_task_probe.py` with the same environment. A negative check runs the initializer and then the evaluator directly. For the positive check, the phone edit and the transfer are done in the real GUI (copy on the phone, paste into a text editor on Linux), and the document is built by the Windows stage oracle's Python with `USERPROFILE=/home/user`.

The six tasks were generated from the Android→Windows cross-VM workflows they replace. Their stage files under `tasks/v1/cross_vm/stages/` are kept as provenance.
