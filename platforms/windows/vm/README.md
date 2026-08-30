# Windows VM Assets

This folder contains local assets used by HelloWorld Windows VM workflows.

Directory layout:

```text
platforms/windows/vm/
  image/
    setup.iso           # user-provided Windows 11 ISO (ignored by git)
  setup/                # tracked provisioning/runtime payload mounted to \\host.lan\Data
    on-logon.ps1
    install.bat
    setup.ps1
    setup-tools.psm1
    tools_config.json
    server/
  storage/              # generated VM disk state (ignored by git)
```

Key notes:

- Put your Windows 11 ISO at `platforms/windows/vm/image/setup.iso`.
- Run `bash platforms/windows/scripts/prepare_windows_golden_image.sh` to build a golden storage.
- The `storage/` directory is persistent and can be corrupted by interrupted runs. Keep a backup copy for fast restore.
