import json
import re

from evaluators.cua_review.initializers.macos.deltachat_snapshot import (
    DeltaChatSnapshotInitializer,
)


class FakeGuest:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.uploads = []
        self.copies = []

    def run_python_script(self, script, timeout=None):
        match = re.search(r"wanted = (\[.*\])", script)
        wanted = json.loads(match.group(1))
        rows = [
            {"path": path, "exists": path.rsplit("/", 1)[-1] in self.existing}
            for path in wanted
        ]
        return {"returncode": 0, "stdout": json.dumps(rows)}

    def upload_file(self, local_path, remote_path):
        self.uploads.append((local_path, remote_path))

    def run_bash_script(self, script, timeout=None):
        if "cp -n" in script:
            match = re.search(r"/tmp/os-omni-deltachat-inputs/([^ '\"]+)", script)
            assert match
            filename = match.group(1)
            self.existing.add(filename)
            self.copies.append(filename)
        return {"status": "success", "returncode": 0, "output": ""}


def test_rebuilds_only_missing_documents_and_verifies_them():
    controller = FakeGuest(existing={"Round1_Ops.txt"})
    count, rebuilt = DeltaChatSnapshotInitializer()._check_documents(
        controller,
        ["~/Documents/Round1_Ops.txt", "~/Documents/Round2_Design.txt"],
    )

    assert count == 2
    assert [item["filename"] for item in rebuilt] == ["Round2_Design.txt"]
    assert [path.split("/")[-1] for path, _ in controller.uploads] == ["Round2_Design.txt"]
    assert controller.copies == ["Round2_Design.txt"]


def test_unknown_missing_document_fails_instead_of_inventing_an_asset():
    controller = FakeGuest()

    try:
        DeltaChatSnapshotInitializer()._check_documents(
            controller, ["~/Documents/Unknown.txt"]
        )
    except Exception as exc:
        assert "no rebuilt asset is available" in str(exc)
    else:
        raise AssertionError("unknown task assets should fail closed")
