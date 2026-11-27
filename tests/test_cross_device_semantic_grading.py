"""Cross-device desktop checks grade what the briefs describe, not one spelling of it.

* linux_android_launch_review_minutes_hard: the brief names seven tables that summarize the
  note; any headers/wording pass as long as each table carries its note section's facts.
* windows_android_budget_review_hard: the brief describes the D:H formulas by their rules;
  any formula spelling passes when its saved result is right.

Both checks are Python embedded in the task YAML; they are run here against local files.
"""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "tasks/v1/cross_device/linux_android_launch_review_minutes_hard.yaml"
BUDGET = ROOT / "tasks/v1/cross_device/windows_android_budget_review_hard.yaml"


def _run(code: str, tmp_path: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "check.py"
    script.write_text(code, encoding="utf-8")
    return subprocess.run([sys.executable, "-W", "ignore", str(script)], capture_output=True, text=True,
                          timeout=120, env={**os.environ, **(env or {})})


# --------------------------------------------------------------------------- launch review tables

def _launch_task():
    return yaml.safe_load(LAUNCH.read_text(encoding="utf-8"))


def _docx_check() -> str:
    command = _launch_task()["evaluation"]["params"]["linux"][1]["params"]["command"]
    return command.split("<<'OSOMNI_PY'\n", 1)[1].rsplit("\nOSOMNI_PY", 1)[0]


def _note_lines() -> list[str]:
    source = _launch_task()["init"]["params"]["android"]["params"]["source_text"]
    return [line.strip() for line in source.splitlines() if line.strip()]


# The tables the old check demanded cell for cell.
REFERENCE_TABLES = [
    [["Route", "Owner", "Predecessor", "Status"], ["vendor-packet", "Jordan Lee", "Maya review", "blocked"],
     ["demo-audio", "Priya Nair", "archive receipt", "ready"],
     ["travel-exception", "Theo Martin", "director signoff", "locked"]],
    [["Evidence", "Gate", "Status"], ["vendor-staging", "Gate 1", "pending"], ["demo-audio", "Gate 2", "ready"],
     ["travel-roster", "Gate 3", "ready"]],
    [["Artifact", "Feeds"], ["Android source note", "Windows minutes"],
     ["Windows minutes", "Owner matrix and archive manifest"], ["Archive manifest", "Director question packet"]],
    [["Owner", "Final state"], ["Jordan", "blocked until vendor credentials are active"],
     ["Priya", "ready after dry-run audio validation"], ["Theo", "locked after travel exception review"]],
    [["Reviewer", "Area", "Required check"], ["Maya Chen", "agenda", "packet receipts"],
     ["Jordan Lee", "vendor access", "route locks"], ["Priya Nair", "demo audio", "field comments"],
     ["Theo Martin", "travel roster", "exception locks"]],
    [["Criterion", "Expected state"], ["gate ownership", "named owner on every gate"],
     ["packet lineage", "predecessor and status on every packet"],
     ["evidence mapping", "every evidence item maps to a gate"],
     ["blocked escalation", "blocked item has escalation owner"]],
    [["Consistency check", "Result"], ["Android source", "single source of truth"],
     ["Windows ordering", "preserves Android ordering"], ["Embedded tables", "summarize transferred note only"]],
]

# The same seven summaries with other headers, wording and layout (a title row, a transposed table).
OTHER_TABLES = [
    [["Routing Matrix", "Routing Matrix", "Routing Matrix"], ["Packet", "Routed to", "Before"],
     ["Vendor packet", "Jordan", "Maya review"], ["Demo audio packet", "Priya", "Archive receipt"],
     ["Travel exception packet", "Theo", "Director signoff"]],
    [["Evidence hash", "Matched to"], ["vendor-staging", "Gate 1 evidence"], ["demo-audio", "Gate 2 checksum"],
     ["travel-roster", "Gate 3 QA packet"]],
    [["Step", "Android source note", "Windows minutes", "Archive manifest"],
     ["Feeds", "Windows minutes", "Owner matrix; archive manifest", "Director question packet"]],
    [["Person", "Status", "Condition"], ["Jordan", "Blocked", "Until vendor credentials are active"],
     ["Priya", "Ready", "After dry-run audio validation"], ["Theo", "Locked", "After travel exception review"]],
    [["Reviewer", "Reviews"], ["Maya", "Agenda and packet receipts"], ["Jordan", "Vendor access and route locks"],
     ["Priya", "Demo audio and field comments"], ["Theo", "Travel roster and exception locks"]],
    [["#", "Criterion"], ["1", "Every gate has a named owner."], ["2", "Every packet has a predecessor and status."],
     ["3", "Every evidence item maps to a gate."], ["4", "Every blocked item has an escalation owner."]],
    [["Check", "Requirement"], ["Source of truth", "The Android note must be the single source of truth."],
     ["Ordering", "The Windows minutes must preserve the Android ordering."],
     ["Tables", "The embedded tables must summarize the transferred note only."]],
]


def _minutes(tmp_path: Path, tables, lines=None) -> dict[str, str]:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    for line in _note_lines() if lines is None else lines:
        document.add_paragraph(line)
    for rows in tables:
        table = document.add_table(rows=len(rows), cols=max(len(row) for row in rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                table.cell(r, c).text = text
        if rows[0] and len(set(rows[0])) == 1 and len(rows[0]) > 1:  # a merged title row
            merged = table.cell(0, 0).merge(table.cell(0, len(rows[0]) - 1))
            merged.text = rows[0][0]
        document.add_paragraph("")
    (tmp_path / "Documents").mkdir(exist_ok=True)
    document.save(tmp_path / "Documents" / "launch_review_minutes.docx")
    return {"USERPROFILE": str(tmp_path)}


def _launch_result(tmp_path, tables, lines=None):
    return _run(_docx_check(), tmp_path, _minutes(tmp_path, tables, lines))


@pytest.mark.parametrize("tables", [REFERENCE_TABLES, OTHER_TABLES, OTHER_TABLES[::-1]],
                         ids=["reference", "other_wording", "other_order"])
def test_any_faithful_seven_tables_pass(tmp_path, tables):
    done = _launch_result(tmp_path, tables)
    assert "EVAL_RESULT:PASS" in done.stdout, done.stdout + done.stderr


def test_reworded_tables_failed_the_old_cell_for_cell_check():
    # The old grader required every REFERENCE_TABLES grid verbatim; none of these is one.
    assert all(table not in REFERENCE_TABLES for table in OTHER_TABLES)


def test_a_missing_or_merged_table_fails(tmp_path):
    six = _launch_result(tmp_path, OTHER_TABLES[:-1])
    assert "MISSING_TABLE:Cross-VM Consistency Checks" in six.stdout and six.returncode == 1
    # One big table holding every fact is not seven tables.
    combined = [row for table in REFERENCE_TABLES for row in table]
    one = _launch_result(tmp_path, [combined])
    assert "EVAL_RESULT:PASS" not in one.stdout and one.returncode == 1


def test_tables_with_wrong_or_placeholder_content_fail(tmp_path):
    wrong = [table[:] for table in OTHER_TABLES]
    wrong[0] = [["Packet", "Routed to", "Before"], ["Vendor packet", "Priya", "Maya review"],
                ["Demo audio packet", "Jordan", "Archive receipt"], ["Travel exception packet", "Theo", "Director signoff"]]
    done = _launch_result(tmp_path, wrong)
    assert "MISSING_TABLE:Routing Matrix" in done.stdout and done.returncode == 1
    # What an earlier run left: one skeleton table.
    placeholder = _launch_result(tmp_path, [[["Route", ""], ["Status", "Handoff"], ["", ""], ["", ""]]])
    assert placeholder.stdout.count("MISSING_TABLE:") == 7
    # A one-cell table holding the section text is not a table summary.
    lines = _note_lines()
    start = lines.index("Director Packet Routing:")
    dump = [[["\n".join(lines[start + 1:start + 4])]]] + OTHER_TABLES[1:]
    assert "MISSING_TABLE:Routing Matrix" in _launch_result(tmp_path, dump).stdout


def test_note_paragraphs_are_still_required(tmp_path):
    lines = _note_lines()
    done = _launch_result(tmp_path, OTHER_TABLES, lines[:5] + lines[6:])
    assert "MISSING_OR_OUT_OF_ORDER:Theo Martin" in done.stdout


# --------------------------------------------------------------------------- budget review formulas

ROWS = [("Travel", 1200, 980), ("Lodging", 2100, 2240), ("Meals", 450, 390), ("Supplies", 300, 340),
        ("Contingency", 600, 720), ("Permits", 250, 410), ("Training", 500, 455), ("Equipment", 850, 1025)]


def _xlsx_check(path: Path) -> str:
    command = yaml.safe_load(BUDGET.read_text(encoding="utf-8"))["evaluation"]["params"]["windows"][1]["params"]["command"]
    code = command.split("@'\n", 1)[1].rsplit("'@", 1)[0]
    assert "C:/Users/User/Documents/budget_review.xlsx" in code
    return code.replace("C:/Users/User/Documents/budget_review.xlsx", path.as_posix())


def _write_xlsx(path: Path, cells: dict) -> None:
    """Write sheet1 the way LibreOffice does: shared strings, <f> plus the cached <v> result."""
    shared: list[str] = []
    by_row: dict[int, list[str]] = {}

    def key(ref):
        letters = "".join(ch for ch in ref if ch.isalpha())
        return int(ref[len(letters):]), letters

    for ref in sorted(cells, key=lambda ref: (key(ref)[0], len(key(ref)[1]), key(ref)[1])):
        value = cells[ref]
        if isinstance(value, tuple):
            formula, cached = value
            kind = ' t="str"' if isinstance(cached, str) else ""
            cached_xml = "" if cached is None else f"<v>{escape(str(cached))}</v>"
            xml = f'<c r="{ref}"{kind}><f>{escape(formula.lstrip("="))}</f>{cached_xml}</c>'
        elif isinstance(value, str):
            shared.append(value)
            xml = f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>'
        else:
            xml = f'<c r="{ref}" t="n"><v>{value}</v></c>'
        by_row.setdefault(key(ref)[0], []).append(xml)
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet = f'<worksheet xmlns="{ns}"><sheetData>' + "".join(
        f'<row r="{r}">{"".join(xml)}</row>' for r, xml in sorted(by_row.items())) + "</sheetData></worksheet>"
    strings = f'<sst xmlns="{ns}">' + "".join(f"<si><t>{escape(s)}</t></si>" for s in shared) + "</sst>"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
        zf.writestr("xl/sharedStrings.xml", strings)


REFERENCE = {
    "D": "=C{r}-B{r}",
    "E": '=IF(D{r}>0,"Over","Under")',
    "F": '=IF(ABS(D{r})>=100,"Finance Director","Team Lead")',
    "G": '=IF(F{r}="Finance Director","Schedule Friday review","Track in team sync")',
    "H": '=A{r}&": "&E{r}&" by "&ABS(D{r})',
}
EQUIVALENT = {
    "D": "=-(B{r}-C{r})",
    "E": '=IF(D{r}<=0,"Under","Over")',
    "F": '=IF(ABS(D{r})<100,"Team Lead","Finance Director")',
    "G": '=IF(F{r}<>"Finance Director","Track in team sync","Schedule Friday review")',
    "H": '=CONCATENATE(A{r},": ",E{r}," by ",ABS(D{r}))',
}


def _budget_cells(formulas=REFERENCE, cached=True, total="=SUM({c}2:{c}9)"):
    cells = {f"{col}1": name for col, name in zip("ABCDEFGH", ["Category", "Planned", "Actual", "Variance", "Status",
                                                                "Owner", "Action", "Review Note"])}
    for r, (category, planned, actual) in enumerate(ROWS, start=2):
        variance = actual - planned
        status = "Over" if variance > 0 else "Under"
        owner = "Finance Director" if abs(variance) >= 100 else "Team Lead"
        action = "Schedule Friday review" if owner == "Finance Director" else "Track in team sync"
        results = {"D": variance, "E": status, "F": owner, "G": action, "H": f"{category}: {status} by {abs(variance)}"}
        cells.update({f"A{r}": category, f"B{r}": planned, f"C{r}": actual})
        for col, formula in formulas.items():
            cells[f"{col}{r}"] = (formula.format(r=r), results[col] if cached else None)
    cells["A10"] = "Total"
    for col, value in zip("BCD", (6250, 6560, 310)):
        cells[f"{col}10"] = (total.format(c=col), value if cached else None)
    return cells


def _budget_result(tmp_path, cells):
    path = tmp_path / "budget_review.xlsx"
    _write_xlsx(path, cells)
    return _run(_xlsx_check(path), tmp_path)


def _legacy_formula_text_check(cells) -> bool:
    """The old grader: every D:H and total formula had to equal the reference text."""
    expected = _budget_cells()
    return all(cells.get(ref) == value if not isinstance(value, tuple) else
               isinstance(cells.get(ref), tuple) and cells[ref][0] == value[0]
               for ref, value in expected.items())


def test_reference_and_equivalent_formulas_pass(tmp_path):
    for formulas in (REFERENCE, EQUIVALENT):
        done = _budget_result(tmp_path, _budget_cells(formulas))
        assert done.stdout.strip() == "PASS", done.stdout + done.stderr
    assert _legacy_formula_text_check(_budget_cells(REFERENCE))
    assert not _legacy_formula_text_check(_budget_cells(EQUIVALENT))


def test_typed_values_or_constant_formulas_fail(tmp_path):
    typed = _budget_cells()
    typed["E2"] = "Under"
    done = _budget_result(tmp_path, typed)
    assert "FORMULA_MISSING:E2" in done.stderr
    constant = _budget_cells()
    constant["H2"] = ('="Travel: Under by 220"', "Travel: Under by 220")
    assert "FORMULA_HAS_NO_CELL_REFERENCE:H2" in _budget_result(tmp_path, constant).stderr
    no_if = _budget_cells()
    no_if["F2"] = ('=CHOOSE(1+(ABS(D2)>=100),"Team Lead","Finance Director")', "Finance Director")
    assert "FORMULA_NEEDS_IF:F2" in _budget_result(tmp_path, no_if).stderr


def test_wrong_rules_fail_on_the_saved_result(tmp_path):
    cells = _budget_cells({**REFERENCE, "F": '=IF(ABS(D{r})>150,"Finance Director","Team Lead")'})
    # Lodging's variance is 140: the threshold the brief gives (at least 100) makes it Finance Director.
    cells["F3"] = (cells["F3"][0], "Team Lead")
    done = _budget_result(tmp_path, cells)
    assert "RESULT_MISMATCH:F3" in done.stderr and "PASS" not in done.stdout
    note = _budget_cells({**REFERENCE, "H": '=A{r}&" - "&E{r}&" by "&ABS(D{r})'})
    note["H2"] = (note["H2"][0], "Travel - Under by 220")
    assert "RESULT_MISMATCH:H2" in _budget_result(tmp_path, note).stderr


def test_totals_need_sum_formulas(tmp_path):
    cells = _budget_cells(total="=B2+B3+B4+B5+B6+B7+B8+B9")
    assert "FORMULA_NEEDS_SUM:B10" in _budget_result(tmp_path, cells).stderr


def test_without_saved_results_only_the_reference_text_passes(tmp_path):
    assert _budget_result(tmp_path, _budget_cells(REFERENCE, cached=False)).stdout.strip() == "PASS"
    done = _budget_result(tmp_path, _budget_cells(EQUIVALENT, cached=False))
    assert "FORMULA_HAS_NO_SAVED_RESULT:D2" in done.stderr
