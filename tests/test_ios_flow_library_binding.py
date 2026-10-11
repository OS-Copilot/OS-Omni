from pathlib import Path

from platforms.ios.flow_store import IOSFlowStore

def test_recovers_flattened_framework_link_and_existing_bad_helper_link(tmp_path):
    framework = tmp_path / "ios/ObjectBoxLocal/ObjectBox.xcframework/macos-arm64_x86_64/ObjectBox.framework"
    binary = framework / "Versions/A/ObjectBox"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"\xcf\xfa\xed\xfeactual Mach-O fixture")
    flattened = framework / "ObjectBox"
    flattened.write_text("Versions/Current/ObjectBox")
    helper = tmp_path / "lib/libobjectbox.dylib"
    helper.parent.mkdir()
    helper.symlink_to(flattened)
    store = IOSFlowStore.__new__(IOSFlowStore)
    store.flow_repo_path = tmp_path
    store._ensure_objectbox_library()
    assert helper.resolve() == binary
    assert helper.read_bytes() == binary.read_bytes()
    store._ensure_objectbox_library()
    assert helper.resolve() == binary
