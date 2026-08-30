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

EXPECTED = {"collection_paths": ["Research > Transformer Mechanism Spine > Attention Head Ledger", "Data Queue > Curation Failure Spine > Deduplication Failure Ledger", "Retrieval Queue > Retrieval Failure Spine > RAG Failure Case Ledger", "Safety Queue > Red Team Spine > Red Team Escalation Lock", "Scaling Queue > Scaling Caveat Spine > Compute Frontier Caveats", "Compression Queue > Compression Delta Spine > Distillation Delta Ledger", "Agent Systems > Tool Trace Spine > Tool Trace Exception Board", "Long Context Queue > Context Window Spine > Window Regression Ledger", "Optimization Queue > Optimizer Evidence Spine > AdamW Baseline Delta", "Robustness Queue > Attack Surface Spine > Attack Surface Register", "Interpretability Queue > Circuit Dispute Spine > Circuit Dispute Ledger", "Benchmark Queue > Benchmark Release Spine > Release Gate Lock"], "collections": ["Research", "Reading Notes", "Methods Queue", "Reading Backlog", "Seminar Queue", "Replication Queue", "Survey Queue", "Optimization Queue", "Systems Queue", "Theory Queue", "Evaluation Queue", "Interpretability Queue", "Data Queue", "Benchmark Queue", "Safety Queue", "Optimization Backlog", "Robustness Queue", "Retrieval Queue", "Scaling Queue", "Compression Queue", "Agent Systems", "Long Context Queue", "Transformer Audit", "Data Curation Lab", "Retrieval Evidence", "Safety Red Team", "Scaling Appendix", "Compression Audit", "Agent Tool Logs", "Long Context Evidence", "Optimizer Backtest", "Robustness Lab", "Interpretability Review Board", "Benchmark Lockbox", "Transformer Mechanism Spine", "Attention Head Ledger", "Curation Failure Spine", "Deduplication Failure Ledger", "Retrieval Failure Spine", "RAG Failure Case Ledger", "Red Team Spine", "Red Team Escalation Lock", "Scaling Caveat Spine", "Compute Frontier Caveats", "Compression Delta Spine", "Distillation Delta Ledger", "Tool Trace Spine", "Tool Trace Exception Board", "Context Window Spine", "Window Regression Ledger", "Optimizer Evidence Spine", "AdamW Baseline Delta", "Attack Surface Spine", "Attack Surface Register", "Circuit Dispute Spine", "Circuit Dispute Ledger", "Benchmark Release Spine", "Release Gate Lock", "Window A Research Bridge", "Window B Queue Bridge", "Window C Final Reconciliation"], "notes": ["Foundational text on deep learning", "Use chapters 1 and 2 for onboarding", "Prioritize for architecture review", "Discuss during mentoring circle", "Use as CNN baseline discussion", "Use for RL baseline replication", "Use for method taxonomy cross-check", "Check optimizer defaults", "Use scheduler chapter for OS baseline", "Use margin theory context", "Use metric caveat discussion", "Use for circuit discussion", "Use data validation chapter", "Use scenario taxonomy", "Use robustness framing", "Compare with Adam defaults", "Use adversarial baseline", "Use RAG baseline", "Use compute scaling caveat", "Use compression baseline", "Use tool-call comparison", "Use sparse attention baseline", "Map attention heads to audit rows", "Check data curation assumptions", "Link retrieval evidence to RAG baseline", "Escalate red-team findings", "Separate compute scaling caveats", "Compare compression losses with baseline", "Review tool-use traces before final lock", "Attach sparse attention evidence", "Backtest optimizer defaults", "Tie robustness ledger to adversarial queue", "Review circuit minutes before export", "Lock benchmark package after audit", "Index transformer mechanism evidence before attention audit", "Map attention heads back to Attention Is All You Need", "Index curation failure modes before dedup review", "Check deduplication failures against data validation notes", "Index retrieval failures before RAG ledger review", "Link RAG failures back to retrieval baseline evidence", "Index safety red-team evidence before escalation", "Escalate red-team lock against safety queue evidence", "Index scaling caveats before compute frontier review", "Separate compute frontier caveats from Scaling Laws", "Index compression deltas before distillation review", "Compare distillation deltas with compression baseline", "Index tool traces before exception review", "Review tool trace exceptions before benchmark lock", "Index context-window evidence before regression review", "Bind regression ledger to Longformer sparse attention evidence", "Index optimizer evidence before AdamW comparison", "Backtest AdamW delta against optimizer defaults", "Index robustness evidence before attack register review", "Tie attack surface register to adversarial examples", "Index interpretability disputes before circuit review", "Review circuit dispute ledger before export lock", "Index benchmark release evidence before final gate", "Lock release gate after benchmark evidence review", "Window A verifies Research and hands transformer status to Window B", "Window B verifies queue expansion and hands nested audit status to Window C", "Window C verifies nested audit locks and reconciles final status back to Window A"], "tags": ["textbook", "ml-reference", "transformers", "software-practice", "vision", "reinforcement-learning", "survey", "optimization", "systems", "theory", "evaluation", "interpretability", "ml-systems", "benchmarking", "safety", "optimization", "robustness", "retrieval", "scaling", "distillation", "tool-use", "long-context", "transformer-audit", "data-curation", "rag-evidence", "safety-red-team", "scaling-caveat", "compression-audit", "tool-trace", "sparse-attention", "optimizer-backtest", "adversarial-ledger", "circuit-review", "benchmark-lockbox", "path-transformer-spine", "path-attention-ledger", "path-curation-spine", "path-dedup-ledger", "path-retrieval-spine", "path-rag-failure", "path-red-team-spine", "path-escalation-lock", "path-scaling-spine", "path-compute-frontier", "path-compression-spine", "path-distillation-delta", "path-tool-trace-spine", "path-tool-exception", "path-context-spine", "path-window-regression", "path-optimizer-spine", "path-adamw-delta", "path-attack-spine", "path-attack-register", "path-circuit-spine", "path-circuit-dispute", "path-release-spine", "path-release-lock", "window-a-bridge", "window-b-bridge", "window-c-bridge"], "titles": ["Deep Learning", "Pattern Recognition and Machine Learning", "Attention Is All You Need", "The Pragmatic Programmer", "ImageNet Classification with Deep Convolutional Neural Networks", "Playing Atari with Deep Reinforcement Learning", "A Survey of Reinforcement Learning", "Adam: A Method for Stochastic Optimization", "Operating System Concepts", "The Nature of Statistical Learning Theory", "BLEU: a Method for Automatic Evaluation of Machine Translation", "A Mathematical Framework for Transformer Circuits", "Designing Machine Learning Systems", "HELM", "Concrete Problems in AI Safety", "Decoupled Weight Decay Regularization", "Explaining and Harnessing Adversarial Examples", "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks", "Scaling Laws for Neural Language Models", "Distilling the Knowledge in a Neural Network", "Toolformer", "Longformer", "Transformer Mechanism Audit", "Dataset Curation Failure Modes", "RAG Evidence Ledger", "Red Teaming Language Models", "Scaling Law Caveats", "Distillation Compression Ledger", "Tool Use Trace Review", "Sparse Attention Evidence Pack", "Optimizer Backtest Memo", "Adversarial Robustness Ledger", "Circuit Review Minutes", "Benchmark Lockbox Manifest", "Transformer Mechanism Spine Index", "Attention Head Ledger", "Curation Failure Spine Index", "Deduplication Failure Ledger", "Retrieval Failure Spine Index", "RAG Failure Case Ledger", "Red Team Spine Index", "Red Team Escalation Lock", "Scaling Caveat Spine Index", "Compute Frontier Caveats", "Compression Delta Spine Index", "Distillation Delta Ledger", "Tool Trace Spine Index", "Tool Trace Exception Board", "Context Window Spine Index", "Window Regression Ledger", "Optimizer Evidence Spine Index", "AdamW Baseline Delta", "Attack Surface Spine Index", "Attack Surface Register", "Circuit Dispute Spine Index", "Circuit Dispute Ledger", "Benchmark Release Spine Index", "Release Gate Lock", "A-to-B Research Bridge Ledger", "B-to-C Queue Bridge Ledger", "C-to-A Final Reconciliation Ledger"]}
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
