$ErrorActionPreference = "Stop"
$py = @'
import glob
import json
import os
import shutil
import sqlite3
import sys
import tempfile

expected = json.loads('{"collections":["Reference Shelf","AI Papers","Project Notes","Implementation Queue","Review Board","Evidence Queue","Operations Reading","Security Review","Reproducibility Queue","Database Queue","Observability Shelf","Testing Queue","Scheduler Queue","Storage Queue","Human Factors","Incident Review","Networking Queue","Ethics Queue","Architecture Shelf","Data Governance","Queue Triage","Distributed Systems Audit","Benchmark Appendix","Telemetry Deep Dive","Threat Model Shelf","Governance Archive","Reliability Drill","Networking Evidence","Architecture Dispute","Data Lineage Queue","Locking Protocols","Testing Artifacts","Human Review Board","Reference Audit Spine","Spanner Evidence Lock","Lock Queue Spine","Lease Timing Exceptions","Architecture Conflict Spine","ADR Conflict Matrix","Governance Evidence Spine","Lineage Provenance Pack","Benchmark Evidence Spine","Evidence Ledger Crosscheck","Telemetry Control Spine","Control Loop Ownership","Threat Review Spine","STRIDE Gap Register","Reliability Tabletop Spine","Incident Tabletop Pack","Transport Evidence Spine","QUIC Transport Appendix","Harness Evidence Spine","Harness Regression Lock","Review Board Spine","Cognitive Load Review","Storage Provenance Spine","Storage Provenance Exceptions"],"titles":["Designing Data-Intensive Applications","BERT","Benchmark Plan","MapReduce","The Mythical Man-Month","Latency Audit","Site Reliability Engineering","Security Engineering","Reproducibility Checklist","Readings in Database Systems","Observability Engineering","Evaluation Harness Notes","The Google Borg Paper","Database Internals","Operator Playbook","Postmortem Template","Computer Networking: A Top-Down Approach","Model Card Guidance","Software Architecture: The Hard Parts","Dataset Documentation Plan","The Chubby Lock Service","Spanner Design Notes","Benchmark Evidence Ledger","Telemetry Control Loops","Threat Modeling Playbook","Dataset Lineage Review","Incident Command Drill","QUIC Transport Notes","Architecture Decision Records","Data Provenance Audit","Distributed Lock Review","Regression Harness Appendix","Operator Cognitive Load Study","Reference Audit Spine Index","Spanner Evidence Lockfile","Lock Queue Spine Index","Lease Timing Exception Ledger","Architecture Conflict Spine Index","ADR Conflict Matrix","Governance Evidence Spine Index","Lineage Provenance Pack","Benchmark Evidence Spine Index","Evidence Ledger Crosscheck","Telemetry Control Spine Index","Control Loop Ownership Ledger","Threat Review Spine Index","STRIDE Gap Register","Reliability Tabletop Spine Index","Incident Tabletop Pack","Transport Evidence Spine Index","QUIC Transport Appendix","Harness Evidence Spine Index","Harness Regression Lock","Review Board Spine Index","Cognitive Load Review Dossier","Storage Provenance Spine Index","Storage Provenance Exceptions"],"tags":["systems","transformer","planning","distributed-systems","software-history","measurement","reliability","security","reproducibility","database-systems","observability","testing","cluster-scheduling","storage","operations","incident-review","networking","documentation","architecture","data-governance","distributed-locks","spanner","benchmark-evidence","telemetry-control","threat-modeling","dataset-lineage","incident-command","quic","architecture-record","data-provenance","distributed-lock-review","regression-harness","human-factors-review","path-reference-spine","path-spanner-lock","path-lock-spine","path-lease-exception","path-architecture-spine","path-adr-conflict","path-governance-spine","path-lineage-pack","path-benchmark-spine","path-evidence-crosscheck","path-telemetry-spine","path-control-loop","path-threat-spine","path-stride-gap","path-reliability-spine","path-tabletop-pack","path-transport-spine","path-quic-appendix","path-harness-spine","path-regression-lock","path-human-spine","path-cognitive-review","path-storage-spine","path-storage-provenance"],"notes":["Review before Friday","Compare with Spark notes","Use for planning risk discussion","Attach to benchmark appendix","Review incident chapter","Review threat modeling chapter","Use for artifact review rubric","Compare transaction processing chapter","Review telemetry chapter","Use for regression checklist","Compare scheduling primitives","Review storage engine diagrams","Use for incident drill","Use for outage writeup","Review transport chapter","Use for model-card appendix","Review tradeoff chapter","Check dataset statement appendix","Compare lease design","Cross-check against Chubby lock service notes","Tie evidence ledger to benchmark appendix","Confirm telemetry loop ownership","Escalate STRIDE coverage gaps","Attach lineage notes to governance archive","Use drill notes for reliability tabletop","Compare transport behavior with networking shelf","Record disputed tradeoff before final review","Audit provenance before export lock","Review lease timing against Queue Triage","Pin regression harness evidence","Use for operator load review","Index the reference audit branch before opening the Spanner lockfile","Tie Spanner evidence back to Reference Shelf and Queue Triage before final export","Index lock queue dependencies before checking Chubby leases","Compare lease timing against Queue Triage and Locking Protocols","Index architecture conflicts before final ADR review","Resolve ADR conflicts against Software Architecture: The Hard Parts","Index governance evidence before lineage review","Attach provenance evidence to Dataset Documentation Plan","Index benchmark evidence before ledger crosscheck","Cross-check latency evidence against Benchmark Appendix","Index telemetry control loops before assigning ownership","Confirm owner for every telemetry loop before export lock","Index threat review branches before STRIDE gap triage","Escalate STRIDE gaps against Security Engineering","Index reliability tabletop steps before incident drill","Bind tabletop notes to Site Reliability Engineering","Index transport evidence before QUIC appendix review","Compare QUIC appendix with networking shelf evidence","Index harness evidence before regression lock","Pin regression lock to Evaluation Harness Notes","Index review board evidence before load review","Cross-check cognitive load review with Operator Playbook","Index storage provenance before exception review","Attach storage exceptions to Database Internals evidence"],"collection_paths":["Reference Shelf > Reference Audit Spine > Spanner Evidence Lock","Queue Triage > Lock Queue Spine > Lease Timing Exceptions","Architecture Shelf > Architecture Conflict Spine > ADR Conflict Matrix","Data Governance > Governance Evidence Spine > Lineage Provenance Pack","Evidence Queue > Benchmark Evidence Spine > Evidence Ledger Crosscheck","Observability Shelf > Telemetry Control Spine > Control Loop Ownership","Security Review > Threat Review Spine > STRIDE Gap Register","Operations Reading > Reliability Tabletop Spine > Incident Tabletop Pack","Networking Queue > Transport Evidence Spine > QUIC Transport Appendix","Testing Queue > Harness Evidence Spine > Harness Regression Lock","Human Factors > Review Board Spine > Cognitive Load Review","Storage Queue > Storage Provenance Spine > Storage Provenance Exceptions"]}')
expected["collections"].extend(["Window A Reference Bridge", "Window B Operations Bridge", "Window C Library Reconciliation"])
expected["titles"].extend(["A-to-B Reference Bridge Ledger", "B-to-C Operations Bridge Ledger", "C-to-A Library Reconciliation Ledger"])
expected["tags"].extend(["window-a-reference-bridge", "window-b-operations-bridge", "window-c-library-bridge"])
expected["notes"].extend([
    "Window A verifies Reference Shelf and AI Papers before handing status to Window B",
    "Window B verifies operations security governance and hands nested locks to Window C",
    "Window C verifies nested lock branches and reconciles final status back to Window A",
])
found = {"collections": set(), "collection_paths": set(), "titles": set(), "tags": set(), "notes": []}
for base in [os.path.expandvars(r"%USERPROFILE%\Zotero"), r"C:\Users\User\Zotero"]:
    for db in glob.glob(os.path.join(base, "**", "zotero.sqlite"), recursive=True):
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp.close()
        shutil.copyfile(db, tmp.name)
        try:
            conn = sqlite3.connect(tmp.name)
            found["collections"].update(str(r[0]) for r in conn.execute("select collectionName from collections"))
            collection_cols = {row[1] for row in conn.execute("PRAGMA table_info(collections)").fetchall()}
            if {"collectionID", "collectionName", "parentCollectionID"}.issubset(collection_cols):
                rows = conn.execute("select collectionID, collectionName, parentCollectionID from collections").fetchall()
                names = {int(row[0]): str(row[1]) for row in rows}
                parents = {int(row[0]): row[2] for row in rows}
                for collection_id in names:
                    parts = []
                    seen = set()
                    current = collection_id
                    while current is not None and current not in seen and current in names:
                        seen.add(current)
                        parts.append(names[current])
                        parent = parents.get(current)
                        current = int(parent) if parent is not None else None
                    if parts:
                        found["collection_paths"].add(" > ".join(reversed(parts)))
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
for value in expected.get("collection_paths", []):
    if value not in found["collection_paths"]:
        missing.append("collection_path:" + value)
for value in expected["notes"]:
    if not any(value in note for note in found["notes"]):
        missing.append("note:" + value)
for path, content in expected.get("files", {}).items():
    if not os.path.exists(path):
        missing.append("file:" + path)
    else:
        got = open(path, encoding="utf-8").read().replace("\r\n", "\n").rstrip("\n")
        want = content.replace("\r\n", "\n").rstrip("\n")
        if got != want:
            missing.append("file_content:" + path)

if missing:
    print("EVAL_RESULT:FAIL missing " + "; ".join(missing[:16]))
    sys.exit(1)
print("EVAL_RESULT:PASS Zotero Linux-aligned library buildout verified")
'@
$py | py -3 -W ignore -
exit $LASTEXITCODE
