import json
import pathlib
import re

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_yaml(relpath):
    return yaml.safe_load((ROOT / relpath).read_text(encoding="utf-8"))


def dump_yaml(relpath, data):
    (ROOT / relpath).write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )


def normalize_instruction(instruction):
    instruction = instruction.replace("/home/user/Documents/", "C:\\Users\\User\\Documents\\")
    instruction = instruction.replace("/home/user/Documents", r"C:\Users\User\Documents")
    instruction = re.sub(r"\s+", " ", instruction).strip()
    instruction = instruction.replace("Open Zotero.", "In Zotero, work under My Library.")
    instruction = instruction.replace(
        "Open Zotero and work in this exact order.",
        "In Zotero, work under My Library in this exact order.",
    )
    return instruction


def extract_items(instruction):
    if "zotero_reference_handoff.tsv" in instruction:
        return [
            ("Reference Shelf", "Designing Data-Intensive Applications", "Martin Kleppmann", "systems", None),
            ("AI Papers", "BERT", "Jacob Devlin", "transformer", None),
            ("Project Notes", "Benchmark Plan", None, "planning", "Review before Friday"),
            ("Implementation Queue", "MapReduce", "Jeffrey Dean", "distributed-systems", "Compare with Spark notes"),
            ("Review Board", "The Mythical Man-Month", "Frederick Brooks", "software-history", "Use for planning risk discussion"),
            ("Evidence Queue", "Latency Audit", "Dana Lee", "measurement", "Attach to benchmark appendix"),
            ("Operations Reading", "Site Reliability Engineering", "Betsy Beyer", "reliability", "Review incident chapter"),
            ("Security Review", "Security Engineering", "Ross Anderson", "security", "Review threat modeling chapter"),
            ("Reproducibility Queue", "Reproducibility Checklist", "Victoria Stodden", "reproducibility", "Use for artifact review rubric"),
            ("Database Queue", "Readings in Database Systems", "Joseph Hellerstein", "database-systems", "Compare transaction processing chapter"),
            ("Observability Shelf", "Observability Engineering", "Charity Majors", "observability", "Review telemetry chapter"),
            ("Testing Queue", "Evaluation Harness Notes", "Riley Chen", "testing", "Use for regression checklist"),
            ("Scheduler Queue", "The Google Borg Paper", "Abhishek Verma", "cluster-scheduling", "Compare scheduling primitives"),
            ("Storage Queue", "Database Internals", "Alex Petrov", "storage", "Review storage engine diagrams"),
            ("Human Factors", "Operator Playbook", "Mina Rao", "operations", "Use for incident drill"),
            ("Incident Review", "Postmortem Template", "Nora Patel", "incident-review", "Use for outage writeup"),
            ("Networking Queue", "Computer Networking: A Top-Down Approach", "James Kurose", "networking", "Review transport chapter"),
            ("Ethics Queue", "Model Card Guidance", "Margaret Mitchell", "documentation", "Use for model-card appendix"),
            ("Architecture Shelf", "Software Architecture: The Hard Parts", "Neal Ford", "architecture", "Review tradeoff chapter"),
            ("Data Governance", "Dataset Documentation Plan", "Timnit Gebru", "data-governance", "Check dataset statement appendix"),
            ("Queue Triage", "The Chubby Lock Service", "Mike Burrows", "distributed-locks", "Compare lease design"),
        ]

    item_type = r"(?:Book|Journal Article|Conference Paper|Report)"
    patterns = [
        rf'collection named\s+"([^"]+)".*?In (?:that collection|"[^"]+"), add (?:a manual |a new )?{item_type} item titled "([^"]+)"(?: with author "([^"]+)")?.*?tag "([^"]+)".*?(?:text|says) "([^"]+)"',
        rf'create [^"]*"([^"]+)".*?In (?:that collection|"[^"]+"), add (?:a manual |a new )?{item_type} item titled "([^"]+)"(?: with author "([^"]+)")?.*?tag "([^"]+)".*?(?:text|says) "([^"]+)"',
        rf'create (?:a collection named\s+)?"([^"]+)".*?add (?:a manual |a new )?{item_type} titled "([^"]+)"(?: to that collection)?(?: with author "([^"]+)")?.*?tag "([^"]+)".*?(?:text|says) "([^"]+)"',
        rf'create "([^"]+)" and add (?:a manual |a new )?{item_type} titled "([^"]+)"(?: to that collection)?(?: with author "([^"]+)")?.*?tag "([^"]+)".*?(?:text|says) "([^"]+)"',
    ]
    found = []
    for pattern in patterns:
        for match in re.finditer(pattern, instruction, flags=re.I | re.S):
            item = match.groups()
            if item not in found:
                found.append(item)

    if "Reference Shelf" in instruction and not any(item[0] == "Reference Shelf" for item in found):
        found.insert(
            0,
            (
                "Reference Shelf",
                "Designing Data-Intensive Applications",
                "Martin Kleppmann",
                "systems",
                "Review storage chapter",
            ),
        )
    if "Project Notes" in instruction and not any(item[0] == "Project Notes" for item in found):
        found.insert(2, ("Project Notes", "Benchmark Plan", None, "planning", "Review before Friday"))

    deduped = []
    seen = set()
    for collection, title, author, tag, note in found:
        key = (collection, title, tag, note)
        if key not in seen:
            seen.add(key)
            deduped.append((collection, title, author, tag, note))
    return deduped


def files_payload(family, count, owner, terminal):
    prefix = rf"C:\Users\User\Documents\zotero_{family}_"
    if family == "research":
        review_queue = "Compression Queue\nAgent Systems\nLong Context Queue"
        tag_audit = (
            "tag,collection,status\n"
            "distillation,Compression Queue,ready\n"
            "tool-use,Agent Systems,ready\n"
            "long-context,Long Context Queue,ready"
        )
    else:
        review_queue = "Architecture Shelf\nData Governance\nQueue Triage"
        tag_audit = (
            "tag,collection,status\n"
            "architecture,Architecture Shelf,ready\n"
            "data-governance,Data Governance,ready\n"
            "distributed-locks,Queue Triage,ready"
        )

    return {
        prefix + "handoff.tsv": f"file\tcount\towner\ncollections\t{count}\t{owner}\nitems\t{count}\t{owner}\nstatus\tready\t{owner}",
        prefix + "counts.txt": f"{family}_collections={count}\n{family}_items={count}\nrequired_tags={count}\nhandoff_status=ready",
        prefix + "review_queue.txt": review_queue,
        prefix + "tag_audit.csv": tag_audit,
        prefix
        + "curator_notes.txt": f"curator={owner}\nreview_batch={family}-hard\nfinal_collection={terminal}\naction=manual-ui-confirmed",
        prefix
        + "export_manifest.txt": f"export_scope=collections-{count}\nexport_format=manual-review\nowner={owner}\nstatus=staged",
        prefix
        + "bundle_crosswalk.tsv": (
            f"file\tdepends_on\tstatus\n"
            f"zotero_{family}_counts.txt\tzotero_{family}_handoff.tsv\tlinked\n"
            f"zotero_{family}_review_queue.txt\tzotero_{family}_counts.txt\tlinked\n"
            f"zotero_{family}_tag_audit.csv\tzotero_{family}_review_queue.txt\tlinked\n"
            f"zotero_{family}_export_manifest.txt\tzotero_{family}_tag_audit.csv\tlinked"
        ),
        prefix
        + "final_index.txt": f"database=zotero.sqlite\ncollection_count={count}\ncrosswalk=zotero_{family}_bundle_crosswalk.tsv\nterminal={terminal}",
    }


def update_task(linux_path, windows_path, family, owner, terminal, count, human_steps):
    linux = load_yaml(linux_path)
    windows = load_yaml(windows_path)
    instruction = normalize_instruction(linux["instruction"])
    items = extract_items(instruction)
    if len(items) != count:
        raise RuntimeError(f"{family}: expected {count} Zotero items, parsed {len(items)}")

    windows["instruction"] = instruction
    metadata = windows.setdefault("metadata", {})
    metadata["human_steps"] = human_steps
    metadata["estimated_min_steps"] = human_steps - 18
    metadata["linux_peer"] = linux["task_id"]
    metadata[
        "difficulty_alignment"
    ] = "mirrors Linux Zotero hard task in collection/item count, handoff files, and evaluator-checked final state"
    metadata[
        "description"
    ] = f"Linux-aligned Zotero hard task with {count} collections/items, tags, notes, and eight exact handoff files."
    metadata[
        "evaluation_standard"
    ] = "all requested collections, item titles, tags, notes, and exact handoff files are checked via SQLite and filesystem inspection"
    dump_yaml(windows_path, windows)

    return {
        "collections": [item[0] for item in items],
        "titles": [item[1] for item in items],
        "tags": [item[3] for item in items],
        "notes": [item[4] for item in items if item[4]],
        "files": files_payload(family, count, owner, terminal),
    }


def write_check(filename, payload):
    payload_json = json.dumps(payload, ensure_ascii=True)
    script = f"""$ErrorActionPreference = "Stop"
$py = @'
import glob
import json
import os
import shutil
import sqlite3
import sys
import tempfile

expected = json.loads({payload_json!r})
found = {{"collections": set(), "titles": set(), "tags": set(), "notes": []}}
for base in [os.path.expandvars(r"%USERPROFILE%\\Zotero"), r"C:\\Users\\User\\Zotero"]:
    for db in glob.glob(os.path.join(base, "**", "zotero.sqlite"), recursive=True):
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp.close()
        shutil.copyfile(db, tmp.name)
        try:
            conn = sqlite3.connect(tmp.name)
            found["collections"].update(str(r[0]) for r in conn.execute("select collectionName from collections"))
            found["titles"].update(str(r[0]) for r in conn.execute("select value from itemDataValues"))
            found["tags"].update(str(r[0]) for r in conn.execute("select name from tags"))
            found["notes"].extend(str(r[0] or "") for r in conn.execute("select note from itemNotes"))
            conn.close()
        except Exception:
            pass
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

missing = []
for key in ["collections", "titles", "tags"]:
    for value in expected[key]:
        if value not in found[key]:
            missing.append(key + ":" + value)
for value in expected["notes"]:
    if not any(value in note for note in found["notes"]):
        missing.append("note:" + value)
for path, content in expected["files"].items():
    if not os.path.exists(path):
        missing.append("file:" + path)
    else:
        got = open(path, encoding="utf-8").read().replace("\\r\\n", "\\n").rstrip("\\n")
        want = content.replace("\\r\\n", "\\n").rstrip("\\n")
        if got != want:
            missing.append("file_content:" + path)

if missing:
    print("EVAL_RESULT:FAIL missing " + "; ".join(missing[:16]))
    sys.exit(1)
print("EVAL_RESULT:PASS Zotero Linux-aligned library buildout verified")
'@
$py | py -3 -W ignore -
exit $LASTEXITCODE
"""
    (ROOT / "evaluators" / "windows" / "checks" / filename).write_text(script, encoding="utf-8")


def patch_oracle_generator(payloads):
    path = ROOT / "mine" / "oracle_agent" / "generate_windows_oracle_agents.py"
    text = path.read_text(encoding="utf-8")
    start = text.index("def _zotero_python(task_key: str) -> str:")
    marker = "    if task_key not in payloads:"
    mid = text.index(marker, start)
    replacement = "def _zotero_python(task_key: str) -> str:\n    payloads = " + repr(payloads) + "\n"
    path.write_text(text[:start] + replacement + text[mid:], encoding="utf-8")


def main():
    payloads = {
        "create_collection_with_notes": update_task(
            "tasks/linux/zotero_research_collection_with_notes_hard.yaml",
            "tasks/windows/zotero_create_collection_with_notes.yaml",
            "research",
            "research-ops",
            "Long Context Queue",
            22,
            220,
        ),
        "organize_library": update_task(
            "tasks/linux/zotero_reference_library_buildout_hard.yaml",
            "tasks/windows/zotero_organize_library.yaml",
            "reference",
            "library-ops",
            "Queue Triage",
            21,
            210,
        ),
    }
    write_check("zotero_create_collection_with_notes.ps1", payloads["create_collection_with_notes"])
    write_check("zotero_organize_library.ps1", payloads["organize_library"])
    patch_oracle_generator(payloads)
    print("updated Windows Zotero hard tasks to Linux-aligned counts")


if __name__ == "__main__":
    main()
