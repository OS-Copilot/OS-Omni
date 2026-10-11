# AndroidWorldAvd v2

Archive: $packageName

This archive replaces the previous ndroid/v2 AndroidWorldAvd package. It contains the current Android benchmark AVD with the updated OpenDriver, OpenNavigation, and OpenFood Android apps installed.

## Contents

- AndroidWorldAvd.avd/
- AndroidWorldAvd.ini
- $base_README.md
- $base_package_manifest.txt
- $shaPathName

## Update Notes

- OpenDriver is installed with Android HTTP access enabled and points to the host backend at http://10.0.2.2:4321.
- OpenDriver map tiles use the same Linux-style backend proxy path: /map/tiles/{z}/{x}/{y}{r}.png.
- The backend map configuration verified before export was OPENDRIVER_ONLINE_MAPS=true and OPENDRIVER_MAP_STYLE=osmde-retina; tile debug showed online-osmde-retina sources.
- App data for OpenDriver, OpenFood, and OpenNavigation was cleared before packaging so the image does not preserve manual login or UI test state.

## Install

Extract the archive into your Android AVD home. On Windows this is usually:

`	ext
%USERPROFILE%\.android\avd\
`

After extraction these paths should exist:

`	ext
%USERPROFILE%\.android\avd\AndroidWorldAvd.avd\
%USERPROFILE%\.android\avd\AndroidWorldAvd.ini
`

Edit AndroidWorldAvd.ini if necessary so path= points to the local absolute AVD directory.

Required system image:

`	ext
system-images;android-33;google_apis;x86_64
`

Runtime lock files, host-specific hardware files, and emulator snapshots are intentionally excluded. If the emulator reports the AVD is in use, remove stale *.lock files under the extracted .avd directory.
