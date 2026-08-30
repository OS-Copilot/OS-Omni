import glob
import json
import os
import secrets
import sqlite3
import string
import subprocess
import time

subprocess.run(['taskkill', '/F', '/IM', 'zotero.exe'], capture_output=True)
time.sleep(2)

EXPECTED = {"collection_paths": ["Reference Shelf > Reference Audit Spine > Spanner Evidence Lock", "Queue Triage > Lock Queue Spine > Lease Timing Exceptions", "Architecture Shelf > Architecture Conflict Spine > ADR Conflict Matrix", "Data Governance > Governance Evidence Spine > Lineage Provenance Pack", "Evidence Queue > Benchmark Evidence Spine > Evidence Ledger Crosscheck", "Observability Shelf > Telemetry Control Spine > Control Loop Ownership", "Security Review > Threat Review Spine > STRIDE Gap Register", "Operations Reading > Reliability Tabletop Spine > Incident Tabletop Pack", "Networking Queue > Transport Evidence Spine > QUIC Transport Appendix", "Testing Queue > Harness Evidence Spine > Harness Regression Lock", "Human Factors > Review Board Spine > Cognitive Load Review", "Storage Queue > Storage Provenance Spine > Storage Provenance Exceptions"], "collections": ["Reference Shelf", "AI Papers", "Project Notes", "Implementation Queue", "Review Board", "Evidence Queue", "Operations Reading", "Security Review", "Reproducibility Queue", "Database Queue", "Observability Shelf", "Testing Queue", "Scheduler Queue", "Storage Queue", "Human Factors", "Incident Review", "Networking Queue", "Ethics Queue", "Architecture Shelf", "Data Governance", "Queue Triage", "Distributed Systems Audit", "Benchmark Appendix", "Telemetry Deep Dive", "Threat Model Shelf", "Governance Archive", "Reliability Drill", "Networking Evidence", "Architecture Dispute", "Data Lineage Queue", "Locking Protocols", "Testing Artifacts", "Human Review Board", "Reference Audit Spine", "Spanner Evidence Lock", "Lock Queue Spine", "Lease Timing Exceptions", "Architecture Conflict Spine", "ADR Conflict Matrix", "Governance Evidence Spine", "Lineage Provenance Pack", "Benchmark Evidence Spine", "Evidence Ledger Crosscheck", "Telemetry Control Spine", "Control Loop Ownership", "Threat Review Spine", "STRIDE Gap Register", "Reliability Tabletop Spine", "Incident Tabletop Pack", "Transport Evidence Spine", "QUIC Transport Appendix", "Harness Evidence Spine", "Harness Regression Lock", "Review Board Spine", "Cognitive Load Review", "Storage Provenance Spine", "Storage Provenance Exceptions", "Window A Reference Bridge", "Window B Operations Bridge", "Window C Library Reconciliation"], "notes": ["Review before Friday", "Compare with Spark notes", "Use for planning risk discussion", "Attach to benchmark appendix", "Review incident chapter", "Review threat modeling chapter", "Use for artifact review rubric", "Compare transaction processing chapter", "Review telemetry chapter", "Use for regression checklist", "Compare scheduling primitives", "Review storage engine diagrams", "Use for incident drill", "Use for outage writeup", "Review transport chapter", "Use for model-card appendix", "Review tradeoff chapter", "Check dataset statement appendix", "Compare lease design", "Cross-check against Chubby lock service notes", "Tie evidence ledger to benchmark appendix", "Confirm telemetry loop ownership", "Escalate STRIDE coverage gaps", "Attach lineage notes to governance archive", "Use drill notes for reliability tabletop", "Compare transport behavior with networking shelf", "Record disputed tradeoff before final review", "Audit provenance before export lock", "Review lease timing against Queue Triage", "Pin regression harness evidence", "Use for operator load review", "Index the reference audit branch before opening the Spanner lockfile", "Tie Spanner evidence back to Reference Shelf and Queue Triage before final export", "Index lock queue dependencies before checking Chubby leases", "Compare lease timing against Queue Triage and Locking Protocols", "Index architecture conflicts before final ADR review", "Resolve ADR conflicts against Software Architecture: The Hard Parts", "Index governance evidence before lineage review", "Attach provenance evidence to Dataset Documentation Plan", "Index benchmark evidence before ledger crosscheck", "Cross-check latency evidence against Benchmark Appendix", "Index telemetry control loops before assigning ownership", "Confirm owner for every telemetry loop before export lock", "Index threat review branches before STRIDE gap triage", "Escalate STRIDE gaps against Security Engineering", "Index reliability tabletop steps before incident drill", "Bind tabletop notes to Site Reliability Engineering", "Index transport evidence before QUIC appendix review", "Compare QUIC appendix with networking shelf evidence", "Index harness evidence before regression lock", "Pin regression lock to Evaluation Harness Notes", "Index review board evidence before load review", "Cross-check cognitive load review with Operator Playbook", "Index storage provenance before exception review", "Attach storage exceptions to Database Internals evidence", "Window A verifies Reference Shelf and AI Papers before handing status to Window B", "Window B verifies operations security governance and hands nested locks to Window C", "Window C verifies nested lock branches and reconciles final status back to Window A"], "tags": ["systems", "transformer", "planning", "distributed-systems", "software-history", "measurement", "reliability", "security", "reproducibility", "database-systems", "observability", "testing", "cluster-scheduling", "storage", "operations", "incident-review", "networking", "documentation", "architecture", "data-governance", "distributed-locks", "spanner", "benchmark-evidence", "telemetry-control", "threat-modeling", "dataset-lineage", "incident-command", "quic", "architecture-record", "data-provenance", "distributed-lock-review", "regression-harness", "human-factors-review", "path-reference-spine", "path-spanner-lock", "path-lock-spine", "path-lease-exception", "path-architecture-spine", "path-adr-conflict", "path-governance-spine", "path-lineage-pack", "path-benchmark-spine", "path-evidence-crosscheck", "path-telemetry-spine", "path-control-loop", "path-threat-spine", "path-stride-gap", "path-reliability-spine", "path-tabletop-pack", "path-transport-spine", "path-quic-appendix", "path-harness-spine", "path-regression-lock", "path-human-spine", "path-cognitive-review", "path-storage-spine", "path-storage-provenance", "window-a-reference-bridge", "window-b-operations-bridge", "window-c-library-bridge"], "titles": ["Designing Data-Intensive Applications", "BERT", "Benchmark Plan", "MapReduce", "The Mythical Man-Month", "Latency Audit", "Site Reliability Engineering", "Security Engineering", "Reproducibility Checklist", "Readings in Database Systems", "Observability Engineering", "Evaluation Harness Notes", "The Google Borg Paper", "Database Internals", "Operator Playbook", "Postmortem Template", "Computer Networking: A Top-Down Approach", "Model Card Guidance", "Software Architecture: The Hard Parts", "Dataset Documentation Plan", "The Chubby Lock Service", "Spanner Design Notes", "Benchmark Evidence Ledger", "Telemetry Control Loops", "Threat Modeling Playbook", "Dataset Lineage Review", "Incident Command Drill", "QUIC Transport Notes", "Architecture Decision Records", "Data Provenance Audit", "Distributed Lock Review", "Regression Harness Appendix", "Operator Cognitive Load Study", "Reference Audit Spine Index", "Spanner Evidence Lockfile", "Lock Queue Spine Index", "Lease Timing Exception Ledger", "Architecture Conflict Spine Index", "ADR Conflict Matrix", "Governance Evidence Spine Index", "Lineage Provenance Pack", "Benchmark Evidence Spine Index", "Evidence Ledger Crosscheck", "Telemetry Control Spine Index", "Control Loop Ownership Ledger", "Threat Review Spine Index", "STRIDE Gap Register", "Reliability Tabletop Spine Index", "Incident Tabletop Pack", "Transport Evidence Spine Index", "QUIC Transport Appendix", "Harness Evidence Spine Index", "Harness Regression Lock", "Review Board Spine Index", "Cognitive Load Review Dossier", "Storage Provenance Spine Index", "Storage Provenance Exceptions", "A-to-B Reference Bridge Ledger", "B-to-C Operations Bridge Ledger", "C-to-A Library Reconciliation Ledger"]}
ALPHA = string.ascii_uppercase + string.digits


def _key():
    return ''.join(secrets.choice(ALPHA) for _ in range(8))


def _table_columns(conn, table):
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def _insert_collection(conn, name, parent_id=None):
    cur = conn.cursor()
    row = cur.execute(
        "select collectionID from collections where collectionName = ? and coalesce(parentCollectionID, -1) = coalesce(?, -1)",
        (name, parent_id),
    ).fetchone()
    if row:
        return int(row[0])
    cols = _table_columns(conn, 'collections')
    values = {'collectionName': name, 'libraryID': 1, 'key': _key(), 'parentCollectionID': parent_id}
    insert_cols = [c for c in ['collectionName', 'libraryID', 'key', 'parentCollectionID'] if c in cols]
    cur.execute(
        f"insert into collections({','.join(insert_cols)}) values({','.join(['?'] * len(insert_cols))})",
        [values[c] for c in insert_cols],
    )
    return int(cur.lastrowid)


def _insert_value(conn, value):
    if value:
        conn.execute("insert or ignore into itemDataValues(value) values(?)", (value,))


def _insert_tag(conn, tag):
    if tag:
        conn.execute("insert or ignore into tags(name) values(?)", (tag,))


def _insert_note(conn, note):
    if not note:
        return
    cols = _table_columns(conn, 'itemNotes')
    if not cols:
        return
    insert_cols = [c for c in ['note', 'title'] if c in cols]
    values = {'note': note, 'title': note[:120]}
    try:
        conn.execute(
            f"insert into itemNotes({','.join(insert_cols)}) values({','.join(['?'] * len(insert_cols))})",
            [values[c] for c in insert_cols],
        )
    except Exception as exc:
        print('note insert failed:', note[:80], exc)


def _seed_database(db):
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    try:
        cur.execute('PRAGMA foreign_keys = OFF')
    except Exception:
        pass
    for path in EXPECTED.get('collection_paths', []):
        parent = None
        for part in [p.strip() for p in path.split('>')]:
            parent = _insert_collection(conn, part, parent)
    for name in EXPECTED.get('collections', []):
        _insert_collection(conn, name)
    for value in EXPECTED.get('titles', []):
        _insert_value(conn, value)
    for tag in EXPECTED.get('tags', []):
        _insert_tag(conn, tag)
    for note in EXPECTED.get('notes', []):
        _insert_note(conn, note)
    conn.commit()
    try:
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    except Exception as exc:
        print('checkpoint failed:', exc)
    conn.close()


dbs = glob.glob(os.path.join(os.path.expandvars('%USERPROFILE%'), 'Zotero', '**', 'zotero.sqlite'), recursive=True)
print('databases:', dbs)
for db in dbs:
    try:
        _seed_database(db)
    except Exception as exc:
        print('oracle seed failed:', db, exc)
print('oracle done')
