import time

import pyautogui
import uiautomation as auto


pyautogui.PAUSE = 0.05
pyautogui.FAILSAFE = False


TARGET_POSITIONS = {
    "Recycle Bin": (37, 40),
    "VLC media player": (112, 42),
    "draw.io": (187, 40),
    "GIMP 2.10.38": (37, 143),
    "Zotero": (112, 143),
    "DeltaChat": (187, 143),
    "Google Chrome": (37, 246),
    "Actual Budget": (112, 246),
    "Dependencies": (187, 246),
    "LibreOffice": (37, 349),
    "Blender 2.79b": (112, 349),
    "Microsoft Edge": (37, 452),
    "Visual Studio Code": (112, 452),
    "Spotube": (37, 555),
    "Wireshark": (112, 555),
    "Thunderbird": (37, 658),
    "OpenShop": (112, 658),
}


def desktop_list():
    root = auto.GetRootControl()
    program_manager = root.Control(searchDepth=1, Name="Program Manager")
    if not program_manager.Exists(0, 0):
        return None
    return program_manager.Control(searchDepth=3, ControlType=auto.ControlType.ListControl, Name="Desktop")


def icon_centers():
    view = desktop_list()
    if view is None or not view.Exists(0, 0):
        return {}
    centers = {}
    for item in view.GetChildren():
        name = item.Name
        if not name:
            continue
        rect = item.BoundingRectangle
        if rect.width() <= 0 or rect.height() <= 0:
            continue
        centers[name] = ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
    return centers


def wait_for_icons(timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        centers = icon_centers()
        if "Recycle Bin" in centers and len(centers) >= 8:
            return centers
        time.sleep(0.5)
    return icon_centers()


def drag(src, dst):
    if abs(src[0] - dst[0]) < 8 and abs(src[1] - dst[1]) < 8:
        return
    pyautogui.moveTo(src[0], src[1], duration=0.04)
    pyautogui.mouseDown()
    time.sleep(0.08)
    pyautogui.moveTo(dst[0], dst[1], duration=0.22)
    time.sleep(0.05)
    pyautogui.mouseUp()
    time.sleep(0.14)


def main():
    pyautogui.hotkey("win", "d")
    time.sleep(1.0)

    centers = wait_for_icons()
    names = [name for name in TARGET_POSITIONS if name in centers and name != "Recycle Bin"]

    # Stage icons away from the left grid first. That prevents collisions when
    # restoring the desired SOTA layout on a fresh or auto-arranged desktop.
    staging = {}
    for i, name in enumerate(names):
        staging[name] = (720 + (i % 4) * 86, 90 + (i // 4) * 104)

    for name in names:
        centers = icon_centers()
        if name in centers:
            drag(centers[name], staging[name])

    for name, target in TARGET_POSITIONS.items():
        if name == "Recycle Bin":
            continue
        centers = icon_centers()
        if name in centers:
            drag(centers[name], target)

    pyautogui.moveTo(700, 300, duration=0.05)
    print("SOTA_DESKTOP_LAYOUT_DONE")


if __name__ == "__main__":
    main()
