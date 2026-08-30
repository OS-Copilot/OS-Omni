from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def dump_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")


ZOTERO_REFERENCE = [
    ("Reference Shelf", "Book", "Designing Data-Intensive Applications", "Martin Kleppmann", "systems", "Review storage chapter"),
    ("AI Papers", "Journal Article", "BERT", "Jacob Devlin", "transformer", "Use for encoder baseline"),
    ("Project Notes", "Report", "Benchmark Plan", "Riley Chen", "planning", "Review before Friday"),
    ("Implementation Queue", "Conference Paper", "MapReduce", "Jeffrey Dean", "distributed-systems", "Compare with Spark notes"),
    ("Review Board", "Book", "The Mythical Man-Month", "Frederick Brooks", "software-history", "Use for planning risk discussion"),
    ("Evidence Queue", "Report", "Latency Audit", "Dana Lee", "measurement", "Attach to benchmark appendix"),
    ("Operations Reading", "Book", "Site Reliability Engineering", "Betsy Beyer", "reliability", "Review incident chapter"),
    ("Security Review", "Book", "Security Engineering", "Ross Anderson", "security", "Review threat modeling chapter"),
    ("Reproducibility Queue", "Report", "Reproducibility Checklist", "Victoria Stodden", "reproducibility", "Use for artifact review rubric"),
    ("Database Queue", "Book", "Readings in Database Systems", "Joseph Hellerstein", "database-systems", "Compare transaction processing chapter"),
    ("Observability Shelf", "Book", "Observability Engineering", "Charity Majors", "observability", "Review telemetry chapter"),
    ("Testing Queue", "Report", "Evaluation Harness Notes", "Riley Chen", "testing", "Use for regression checklist"),
]

ZOTERO_RESEARCH = [
    ("Research", "Book", "Deep Learning", "Ian Goodfellow", "textbook", "Foundational text on deep learning"),
    ("Reading Notes", "Book", "Pattern Recognition and Machine Learning", "Christopher Bishop", "ml-reference", "Use chapters 1 and 2 for onboarding"),
    ("Methods Queue", "Journal Article", "Attention Is All You Need", "Ashish Vaswani", "transformers", "Prioritize for architecture review"),
    ("Reading Backlog", "Book", "The Pragmatic Programmer", "Andrew Hunt", "software-practice", "Discuss during mentoring circle"),
    ("Seminar Queue", "Conference Paper", "ImageNet Classification with Deep Convolutional Neural Networks", "Alex Krizhevsky", "vision", "Use as CNN baseline discussion"),
    ("Replication Queue", "Journal Article", "Playing Atari with Deep Reinforcement Learning", "Volodymyr Mnih", "reinforcement-learning", "Use for RL baseline replication"),
    ("Survey Queue", "Journal Article", "A Survey of Reinforcement Learning", "Leslie Kaelbling", "survey", "Use for method taxonomy cross-check"),
    ("Optimization Queue", "Conference Paper", "Adam: A Method for Stochastic Optimization", "Diederik Kingma", "optimization", "Check optimizer defaults"),
    ("Systems Queue", "Book", "Operating System Concepts", "Abraham Silberschatz", "systems", "Use scheduler chapter for OS baseline"),
    ("Theory Queue", "Book", "The Nature of Statistical Learning Theory", "Vladimir Vapnik", "theory", "Use margin theory context"),
    ("Evaluation Queue", "Conference Paper", "BLEU: a Method for Automatic Evaluation of Machine Translation", "Kishore Papineni", "evaluation", "Use metric caveat discussion"),
    ("Interpretability Queue", "Journal Article", "A Mathematical Framework for Transformer Circuits", "Nelson Elhage", "interpretability", "Use for circuit discussion"),
    ("Data Queue", "Book", "Designing Machine Learning Systems", "Chip Huyen", "ml-systems", "Use data validation chapter"),
    ("Benchmark Queue", "Report", "HELM", "Percy Liang", "benchmarking", "Use scenario taxonomy"),
]


def zotero_instruction(items: list[tuple[str, str, str, str, str, str]], files: dict[str, str]) -> str:
    parts = ["In Zotero, work under My Library."]
    for collection, item_type, title, author, tag, note in items:
        parts.append(
            f'Create a collection named "{collection}". In that collection add a manual {item_type} item titled '
            f'"{title}" with author "{author}". Add the tag "{tag}" and a child note with the exact text "{note}".'
        )
    parts.append("Make sure every requested collection exists and each requested item is visible in its collection.")
    for path, content in files.items():
        parts.append(f"Create {path} with exactly this content: {content!r}.")
    parts.append("Finish after the Zotero library and all handoff files are saved.")
    return " ".join(parts)


def zotero_eval_script(items: list[tuple[str, str, str, str, str, str]], files: dict[str, str]) -> str:
    expected = {
        "collections": [item[0] for item in items],
        "titles": [item[2] for item in items],
        "tags": [item[4] for item in items],
        "notes": [item[5] for item in items],
        "files": files,
    }
    expected_json = json.dumps(expected)
    return f'''$ErrorActionPreference = "Stop"
$py = @'
import glob
import json
import os
import shutil
import sqlite3
import sys
import tempfile

expected = json.loads({expected_json!r})
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
    print("EVAL_RESULT:FAIL missing " + "; ".join(missing[:12]))
    sys.exit(1)
print("EVAL_RESULT:PASS Zotero Linux-aligned library buildout verified")
'@
$py | py -3 -W ignore -
exit $LASTEXITCODE
'''


def update_zotero(task_rel: str, check_rel: str, items: list[tuple[str, str, str, str, str, str]], prefix: str, description: str) -> None:
    task_path = ROOT / task_rel
    check_path = ROOT / check_rel
    data = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    files = {
        rf"C:\Users\User\Documents\{prefix}_handoff.tsv": f"file\tcount\towner\ncollections\t{len(items)}\tlibrary-ops\nitems\t{len(items)}\tlibrary-ops\nstatus\tready\tlibrary-ops",
        rf"C:\Users\User\Documents\{prefix}_counts.txt": f"collections={len(items)}\nitems={len(items)}\nrequired_tags={len(items)}\nhandoff_status=ready",
        rf"C:\Users\User\Documents\{prefix}_review_queue.txt": "\n".join(item[0] for item in items[-3:]),
        rf"C:\Users\User\Documents\{prefix}_final_index.txt": f"database=zotero.sqlite\ncollection_count={len(items)}\ncrosswalk={prefix}_handoff.tsv\nterminal={items[-1][0]}",
    }
    data["instruction"] = zotero_instruction(items, files)
    data["evaluation"]["params"].pop("supplemental_checks", None)
    data["metadata"]["human_steps"] = max(int(data["metadata"].get("human_steps", 0)), len(items) * 9 + 20)
    data["metadata"]["description"] = description
    data["metadata"]["evaluation_standard"] = (
        "all requested collections, item titles, tags, notes, and exact handoff files are checked via SQLite and filesystem inspection"
    )
    dump_yaml(task_path, data)
    check_path.write_text(zotero_eval_script(items, files), encoding="utf-8")


def main() -> None:
    update_zotero(
        "tasks/windows/zotero_organize_library.yaml",
        "evaluators/windows/checks/zotero_organize_library.ps1",
        ZOTERO_REFERENCE,
        "zotero_reference",
        "Linux-aligned Zotero hard task: build a twelve-collection reference library with manual items, tags, notes, and exact handoff files.",
    )
    update_zotero(
        "tasks/windows/zotero_create_collection_with_notes.yaml",
        "evaluators/windows/checks/zotero_create_collection_with_notes.ps1",
        ZOTERO_RESEARCH,
        "zotero_research",
        "Linux-aligned Zotero hard task: build a fourteen-collection research library with manual items, tags, notes, and exact handoff files.",
    )
    update_wireshark()


def wireshark_script(artifacts: list[dict[str, str]]) -> str:
    expected_json = json.dumps(artifacts)
    return f'''$ErrorActionPreference = "Stop"
function Fail($message) {{ Write-Output "EVAL_RESULT:FAIL $message"; exit 1 }}
function Resolve-TShark {{
  foreach ($candidate in @("C:\\Program Files\\Wireshark\\tshark.exe", "C:\\Program Files (x86)\\Wireshark\\tshark.exe")) {{
    if (Test-Path $candidate) {{ return $candidate }}
  }}
  $cmd = Get-Command tshark.exe -ErrorAction SilentlyContinue
  if ($cmd) {{ return $cmd.Source }}
  return $null
}}
$expected = @'
{expected_json}
'@ | ConvertFrom-Json
$tshark = Resolve-TShark
if (-not $tshark) {{ Fail "tshark.exe not found" }}
foreach ($item in $expected) {{
  $path = $item.path
  if (-not (Test-Path -LiteralPath $path)) {{ Fail "missing artifact: $path" }}
  if ($item.kind -eq "text") {{
    $got = (Get-Content -LiteralPath $path -Raw) -replace "`r`n", "`n"
    $want = $item.equals -replace "`r`n", "`n"
    if ($got.TrimEnd("`n") -ne $want.TrimEnd("`n")) {{ Fail "text artifact mismatch: $path" }}
    continue
  }}
  $size = (Get-Item -LiteralPath $path).Length
  if ($size -lt 24) {{ Fail "pcap artifact too small: $path" }}
  $read = & $tshark -r $path -T fields -e frame.number 2>&1 | Out-String
  if ($LASTEXITCODE -ne 0) {{ Fail "tshark cannot read $path : $read" }}
  if ($item.PSObject.Properties.Name -contains "all_match_filter") {{
    $total = @($read -split "`r?`n" | Where-Object {{ $_.Trim() -ne "" }}).Count
    if ($total -gt 0) {{
      $filteredText = & $tshark -r $path -Y $item.all_match_filter -T fields -e frame.number 2>&1 | Out-String
      if ($LASTEXITCODE -ne 0) {{ Fail "filter failed for $path : $($item.all_match_filter)" }}
      $filtered = @($filteredText -split "`r?`n" | Where-Object {{ $_.Trim() -ne "" }}).Count
      if ($filtered -ne $total) {{ Fail "artifact contains packets outside filter $($item.all_match_filter): $path" }}
    }}
  }}
}}
Write-Output "EVAL_RESULT:PASS Linux-aligned Wireshark bundle artifacts verified"
'''


def update_wireshark() -> None:
    dl = r"C:\Users\User\Downloads"
    bundle = [
        {"kind": "pcap", "path": rf"{dl}\dns_only.pcapng", "all_match_filter": "dns"},
        {"kind": "pcap", "path": rf"{dl}\icmp_only.pcapng", "all_match_filter": "icmp"},
        {"kind": "pcap", "path": rf"{dl}\http_request_only.pcapng", "all_match_filter": "http.request"},
        {"kind": "pcap", "path": rf"{dl}\http_response_only.pcapng", "all_match_filter": "http.response"},
        {"kind": "pcap", "path": rf"{dl}\arp_only.pcapng", "all_match_filter": "arp"},
        {"kind": "pcap", "path": rf"{dl}\syn_only.pcapng", "all_match_filter": "tcp.flags.syn == 1 && tcp.flags.ack == 0"},
        {"kind": "pcap", "path": rf"{dl}\tcp_only.pcapng", "all_match_filter": "tcp"},
        {"kind": "pcap", "path": rf"{dl}\ip_only.pcapng", "all_match_filter": "ip"},
        {"kind": "pcap", "path": rf"{dl}\udp_only.pcapng", "all_match_filter": "udp"},
        {"kind": "pcap", "path": rf"{dl}\tcp80_only.pcapng", "all_match_filter": "tcp.port == 80"},
        {"kind": "pcap", "path": rf"{dl}\http_only.pcapng", "all_match_filter": "http"},
        {"kind": "pcap", "path": rf"{dl}\checkout_http_only.pcapng", "all_match_filter": 'http.request.uri contains "checkout" || http.response.code == 200'},
        {"kind": "text", "path": rf"{dl}\protocol_bundle_manifest.txt", "equals": "DNS ICMP exported\nHTTP request-response exported\nARP SYN exported\nTCP IP UDP TCP80 exported\nHTTP combined exported\ncheckout HTTP pair exported"},
    ]
    link = [
        {"kind": "pcap", "path": rf"{dl}\arp_only.pcapng", "all_match_filter": "arp"},
        {"kind": "pcap", "path": rf"{dl}\icmp_only.pcapng", "all_match_filter": "icmp"},
        {"kind": "pcap", "path": rf"{dl}\syn_only.pcapng", "all_match_filter": "tcp.flags.syn == 1 && tcp.flags.ack == 0"},
        {"kind": "pcap", "path": rf"{dl}\dns_all_for_link.pcapng", "all_match_filter": "dns"},
        {"kind": "pcap", "path": rf"{dl}\http_request_only.pcapng", "all_match_filter": "http.request"},
        {"kind": "pcap", "path": rf"{dl}\http_response_only.pcapng", "all_match_filter": "http.response"},
        {"kind": "pcap", "path": rf"{dl}\udp_only.pcapng", "all_match_filter": "udp"},
        {"kind": "pcap", "path": rf"{dl}\tcp80_only.pcapng", "all_match_filter": "tcp.port == 80"},
        {"kind": "text", "path": rf"{dl}\link_syn_manifest.txt", "equals": "arp/syn split complete\nICMP echo pair exported\nall DNS copy exported\nHTTP request-response plus UDP exported\nTCP80 slice exported"},
    ]
    task1 = ROOT / "tasks/windows/wireshark_advanced_filter_export.yaml"
    data = yaml.safe_load(task1.read_text(encoding="utf-8"))
    data["instruction"] = (
        'In Wireshark, use the already-open sample.pcapng capture to create a Linux-aligned protocol bundle. '
        'Export displayed packets as pcapng files in Downloads with these exact names and filters: dns_only.pcapng using dns, '
        'icmp_only.pcapng using icmp, http_request_only.pcapng using http.request, http_response_only.pcapng using http.response, '
        'arp_only.pcapng using arp, syn_only.pcapng using tcp.flags.syn == 1 && tcp.flags.ack == 0, tcp_only.pcapng using tcp, '
        'ip_only.pcapng using ip, udp_only.pcapng using udp, tcp80_only.pcapng using tcp.port == 80, http_only.pcapng using http, '
        'and checkout_http_only.pcapng using the checkout HTTP request plus its 200 response when present. '
        'Also create C:\\Users\\User\\Downloads\\protocol_bundle_manifest.txt with exactly these lines: '
        'DNS ICMP exported; HTTP request-response exported; ARP SYN exported; TCP IP UDP TCP80 exported; HTTP combined exported; checkout HTTP pair exported.'
    )
    data["evaluation"]["params"].pop("supplemental_checks", None)
    data["metadata"]["human_steps"] = 118
    data["metadata"]["description"] = "Linux-aligned Wireshark hard task: create twelve protocol-filtered pcapng exports plus an exact manifest file."
    data["metadata"]["evaluation_standard"] = "all exported pcapng artifacts are readable and match their declared filters when non-empty; exact manifest content is checked"
    dump_yaml(task1, data)
    (ROOT / "evaluators/windows/checks/wireshark_advanced_filter_export.ps1").write_text(wireshark_script(bundle), encoding="utf-8")

    task2 = ROOT / "tasks/windows/wireshark_statistics_report.yaml"
    data = yaml.safe_load(task2.read_text(encoding="utf-8"))
    data["instruction"] = (
        'In Wireshark, use the already-open sample.pcapng capture to create a Linux-aligned link and SYN export bundle. '
        'Export displayed packets as pcapng files in Downloads with these exact names and filters: arp_only.pcapng using arp, '
        'icmp_only.pcapng using icmp, syn_only.pcapng using tcp.flags.syn == 1 && tcp.flags.ack == 0, dns_all_for_link.pcapng using dns, '
        'http_request_only.pcapng using http.request, http_response_only.pcapng using http.response, udp_only.pcapng using udp, '
        'and tcp80_only.pcapng using tcp.port == 80. Also create C:\\Users\\User\\Downloads\\link_syn_manifest.txt with exactly these lines: '
        'arp/syn split complete; ICMP echo pair exported; all DNS copy exported; HTTP request-response plus UDP exported; TCP80 slice exported.'
    )
    data["evaluation"]["params"].pop("supplemental_checks", None)
    data["metadata"]["human_steps"] = 96
    data["metadata"]["description"] = "Linux-aligned Wireshark hard task: create eight filtered network exports plus an exact link/SYN manifest file."
    data["metadata"]["evaluation_standard"] = "all exported pcapng artifacts are readable and match their declared filters when non-empty; exact manifest content is checked"
    dump_yaml(task2, data)
    (ROOT / "evaluators/windows/checks/wireshark_statistics_report.ps1").write_text(wireshark_script(link), encoding="utf-8")


if __name__ == "__main__":
    main()
