"""XDV-002..006: cross_device.linux_android.budget_review_hard grades the workbook the brief
describes, not one hidden build of it.

The brief names the six sheets, the RawBudget columns, the twelve VarianceReview columns
(formulas referencing RawBudget), the EscalationQueue filter (Variance Abs at least 100,
formulas referencing VarianceReview), SUMIF/COUNTIFS summaries by owner and by region, and the
eight ControlPanel items. It never gives the Status/Severity/... policy, the summary or queue
columns, the row orders, the labels or the "Android Transfer Status" text, which the old check
required cell for cell. The check is Python embedded in the task YAML; it is run here against
LibreOffice-style workbooks (formula text plus the saved result of each formula).
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "tasks/v1/cross_device/linux_android_budget_review_hard.yaml"

BUDGET = [
    ("Travel", 1200, 980, "Jordan Lee", "West", "2026-07-01"),
    ("Lodging", 2100, 2240, "Maya Chen", "West", "2026-07-03"),
    ("Meals", 450, 390, "Priya Nair", "Central", "2026-07-04"),
    ("Supplies", 300, 340, "Theo Martin", "East", "2026-07-05"),
    ("Contingency", 600, 720, "Maya Chen", "Central", "2026-07-08"),
    ("Permits", 250, 410, "Jordan Lee", "East", "2026-07-09"),
    ("Training", 500, 455, "Priya Nair", "West", "2026-07-10"),
    ("Equipment", 850, 1025, "Theo Martin", "Central", "2026-07-11"),
    ("Insurance", 430, 610, "Maya Chen", "East", "2026-07-12"),
    ("Catering", 780, 695, "Priya Nair", "Central", "2026-07-13"),
    ("Venue", 3200, 3560, "Jordan Lee", "West", "2026-07-14"),
    ("Security", 950, 910, "Theo Martin", "East", "2026-07-15"),
    ("Interpretation", 640, 820, "Maya Chen", "Central", "2026-07-16"),
    ("Signage", 380, 260, "Jordan Lee", "East", "2026-07-17"),
    ("Transport", 1450, 1695, "Theo Martin", "West", "2026-07-18"),
    ("Accessibility", 520, 750, "Priya Nair", "Central", "2026-07-19"),
]
SHEETS = ["RawBudget", "VarianceReview", "EscalationQueue", "OwnerSummary", "RegionalSummary", "ControlPanel"]
COMPUTED = ["Variance", "Variance Abs", "Status", "Severity", "Review Flag", "Disposition", "Recheck Owner",
            "Review Slot", "Audit ID", "Cross-VM Trace", "Evidence Link", "Packet Type"]
OWNERS = ["Jordan Lee", "Maya Chen", "Priya Nair", "Theo Martin"]
REGIONS = ["West", "Central", "East"]


def col(n: int) -> str:
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


# --------------------------------------------------------------------------- workbook writer

def _cell_xml(ref: str, value) -> str:
    """A cell as LibreOffice saves it: a value, or <f> with its cached <v> result."""
    if isinstance(value, dict):  # an array formula anchor: {"array": ref, "f": text, "v": cached}
        cached = value["v"]
        kind = ' t="str"' if isinstance(cached, str) else ""
        return (f'<c r="{ref}"{kind}><f t="array" ref="{value["array"]}">{escape(value["f"].lstrip("="))}</f>'
                f'<v>{escape(str(cached))}</v></c>')
    if isinstance(value, tuple):
        formula, cached = value
        kind = ' t="str"' if isinstance(cached, str) else ""
        cached_xml = "" if cached is None else f"<v>{escape(str(cached))}</v>"
        return f'<c r="{ref}"{kind}><f>{escape(formula.lstrip("="))}</f>{cached_xml}</c>'
    if isinstance(value, str):
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
    if isinstance(value, datetime.date):  # a date-styled serial number, as Calc saves a date cell
        return f'<c r="{ref}" s="1" t="n"><v>{(value - datetime.date(1899, 12, 30)).days}</v></c>'
    return f'<c r="{ref}" t="n"><v>{value}</v></c>'


def write_xlsx(path: Path, sheets: dict[str, dict[tuple[int, int], object]]) -> None:
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                      'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                      for i in range(1, len(sheets) + 1))
            + "</Types>"))
        zf.writestr("_rels/.rels", (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>'))
        zf.writestr("xl/workbook.xml", (
            f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets>'
            + "".join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
                      for i, name in enumerate(sheets, start=1))
            + "</sheets></workbook>"))
        zf.writestr("xl/_rels/workbook.xml.rels", (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(f'<Relationship Id="rId{i}" Type="{rel}/worksheet" Target="worksheets/sheet{i}.xml"/>'
                      for i in range(1, len(sheets) + 1))
            + f'<Relationship Id="rIdStyles" Type="{rel}/styles" Target="styles.xml"/>'
            + "</Relationships>"))
        zf.writestr("xl/styles.xml", (
            f'<styleSheet xmlns="{ns}"><fonts count="1"><font/></fonts><fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
            '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>'
            '<cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14" applyNumberFormat="1"/></cellXfs>'
            '</styleSheet>'))
        for i, cells in enumerate(sheets.values(), start=1):
            rows: dict[int, list[str]] = {}
            for (r, c) in sorted(cells):
                rows.setdefault(r, []).append(_cell_xml(f"{col(c)}{r}", cells[(r, c)]))
            zf.writestr(f"xl/worksheets/sheet{i}.xml", (
                f'<worksheet xmlns="{ns}"><sheetData>'
                + "".join(f'<row r="{r}">{"".join(xml)}</row>' for r, xml in sorted(rows.items()))
                + "</sheetData></worksheet>"))


def grid(rows) -> dict[tuple[int, int], object]:
    return {(r, c): v for r, row in enumerate(rows, start=1) for c, v in enumerate(row, start=1) if v is not None}


# --------------------------------------------------------------------------- the old build

def old_expected() -> dict[str, list[list[object]]]:
    """The cell-for-cell matrices the old check required (formula text or typed value)."""
    review = [["Category", "Planned", "Actual", "Owner", "Region", "DueDate"] + COMPUTED]
    for r in range(2, 18):
        review.append([f"=RawBudget!{c}{r}" for c in "ABCDEF"] + [
            f"=C{r}-B{r}", f"=ABS(G{r})", f'=IF(G{r}>0,"Over","Under")',
            f'=IF(H{r}>=300,"Critical",IF(H{r}>=150,"High",IF(H{r}>=75,"Medium","Low")))',
            f'=IF(H{r}>=100,"Escalate","Monitor")',
            f'=IF(K{r}="Escalate",IF(G{r}>0,"Overrun packet","Savings packet"),"Routine packet")',
            f'=IF(J{r}="Critical","Controller",IF(J{r}="High","Finance Director",D{r}))',
            f'=IF(L{r}="Overrun packet","Friday 10:00",IF(L{r}="Savings packet","Friday 14:00","Monday 09:00"))',
            '="AUD-"&TEXT(ROW()-1,"000")', f'="android->windows:"&A{r}&":"&O{r}',
            f'="Evidence/"&E{r}&"/"&A{r}&"/"&O{r}',
            f'=IF(AND(K{r}="Escalate",J{r}="Critical"),"Director packet",IF(K{r}="Escalate","Owner packet","Team note"))'])
    queue = [["Category", "Variance", "Severity", "Disposition", "Recheck Owner", "Review Slot"]] + [
        [f"=VarianceReview!{c}{s}" for c in "AGJLMN"] for s in (2, 3, 6, 7, 9, 10, 12, 14, 15, 16, 17)]
    owner = [["Owner", "Planned Total", "Actual Total", "Variance Total", "Escalation Count", "Critical Count"]] + [
        [name, f"=SUMIF(RawBudget!D:D,A{r},RawBudget!B:B)", f"=SUMIF(RawBudget!D:D,A{r},RawBudget!C:C)",
         f"=C{r}-B{r}", f'=COUNTIFS(VarianceReview!D:D,A{r},VarianceReview!K:K,"Escalate")',
         f'=COUNTIFS(VarianceReview!D:D,A{r},VarianceReview!J:J,"Critical")'] for r, name in enumerate(OWNERS, 2)]
    regional = [["Region", "Planned Total", "Actual Total", "Variance Total", "Escalation Count"]] + [
        [name, f"=SUMIF(RawBudget!E:E,A{r},RawBudget!B:B)", f"=SUMIF(RawBudget!E:E,A{r},RawBudget!C:C)",
         f"=C{r}-B{r}", f'=COUNTIFS(VarianceReview!E:E,A{r},VarianceReview!K:K,"Escalate")']
        for r, name in enumerate(REGIONS, 2)]
    panel = [["Metric", "Value"], ["Rows Imported", 16], ["Total Planned", "=SUM(RawBudget!B2:B17)"],
             ["Total Actual", "=SUM(RawBudget!C2:C17)"], ["Net Variance", "=SUM(VarianceReview!G2:G17)"],
             ["Absolute Variance", "=SUM(VarianceReview!H2:H17)"],
             ["Escalation Count", '=COUNTIF(VarianceReview!K2:K17,"Escalate")'],
             ["Critical Count", '=COUNTIF(VarianceReview!J2:J17,"Critical")'],
             ["Android Transfer Status", "consumed in LibreOffice Calc"]]
    raw = [["Category", "Planned", "Actual", "Owner", "Region", "DueDate"]] + [list(row) for row in BUDGET]
    return {"RawBudget": raw, "VarianceReview": review, "EscalationQueue": queue, "OwnerSummary": owner,
            "RegionalSummary": regional, "ControlPanel": panel}


def old_check_passes(sheets) -> bool:
    """The old grader: every sheet's top-left block equal, cell for cell, to old_expected()."""
    for name, expected in old_expected().items():
        cells = sheets[name]
        width = max(len(row) for row in expected)
        for r, row in enumerate(expected, start=1):
            for c in range(1, width + 1):
                value = cells.get((r, c))
                shown = value[0] if isinstance(value, tuple) else value.get("f") if isinstance(value, dict) else value
                if shown != (row[c - 1] if c <= len(row) else None):
                    return False
    return True


def policy(category, planned, actual, owner, region, index):
    """The VarianceReview policy the old check hard-coded (its saved results)."""
    variance = actual - planned
    vabs = abs(variance)
    status = "Over" if variance > 0 else "Under"
    severity = "Critical" if vabs >= 300 else "High" if vabs >= 150 else "Medium" if vabs >= 75 else "Low"
    flag = "Escalate" if vabs >= 100 else "Monitor"
    disposition = ("Overrun packet" if variance > 0 else "Savings packet") if flag == "Escalate" else "Routine packet"
    recheck = "Controller" if severity == "Critical" else "Finance Director" if severity == "High" else owner
    slot = {"Overrun packet": "Friday 10:00", "Savings packet": "Friday 14:00"}.get(disposition, "Monday 09:00")
    audit = f"AUD-{index:03d}"
    packet = ("Director packet" if severity == "Critical" else "Owner packet") if flag == "Escalate" else "Team note"
    return [variance, vabs, status, severity, flag, disposition, recheck, slot, audit,
            f"android->windows:{category}:{audit}", f"Evidence/{region}/{category}/{audit}", packet]


def reference_workbook() -> dict[str, dict]:
    """The old check's exact workbook, each formula with the result LibreOffice saves."""
    expected = old_expected()
    raw = [list(row) for row in expected["RawBudget"]]
    review_results = [list(BUDGET[i][:6]) + policy(*BUDGET[i][:5], i + 1) for i in range(16)]
    review = [expected["VarianceReview"][0]] + [
        [(f, v) for f, v in zip(expected["VarianceReview"][r], review_results[r - 1])] for r in range(1, 17)]
    by_row = {i + 2: review_results[i] for i in range(16)}
    queue = [expected["EscalationQueue"][0]]
    for formulas in expected["EscalationQueue"][1:]:
        source = int(formulas[0].rsplit("A", 1)[1])
        values = by_row[source]
        queue.append([(f, values[i]) for f, i in zip(formulas, (0, 6, 9, 11, 12, 13))])

    def summary(name, field, groups, metrics):
        rows = [expected[name][0]]
        for group, formulas in zip(groups, expected[name][1:]):
            members = [i for i, row in enumerate(BUDGET) if row[field] == group]
            values = {
                "planned": sum(BUDGET[i][1] for i in members), "actual": sum(BUDGET[i][2] for i in members),
                "variance": sum(BUDGET[i][2] - BUDGET[i][1] for i in members),
                "esc": sum(abs(BUDGET[i][2] - BUDGET[i][1]) >= 100 for i in members),
                "crit": sum(review_results[i][9] == "Critical" for i in members),
            }
            rows.append([group] + [(f, values[m]) for f, m in zip(formulas[1:], metrics)])
        return rows

    owner = summary("OwnerSummary", 3, OWNERS, ["planned", "actual", "variance", "esc", "crit"])
    regional = summary("RegionalSummary", 4, REGIONS, ["planned", "actual", "variance", "esc"])
    critical = sum(row[9] == "Critical" for row in review_results)
    panel_values = [16, 14600, 15860, 1260, 2400, 11, critical, "consumed in LibreOffice Calc"]
    panel = [expected["ControlPanel"][0]]
    for (label, item), value in zip(expected["ControlPanel"][1:], panel_values):
        panel.append([label, (item, value) if isinstance(item, str) and item.startswith("=") else item])
    return {"RawBudget": grid(raw), "VarianceReview": grid(review), "EscalationQueue": grid(queue),
            "OwnerSummary": grid(owner), "RegionalSummary": grid(regional), "ControlPanel": grid(panel)}


def other_workbook() -> dict[str, dict]:
    """A faithful build the brief allows: other column order, policy, layout, labels and orders."""
    raw = [["Category", "Planned", "Actual", "Owner", "Region", "DueDate"]] + [list(row) for row in BUDGET]
    # VarianceReview: computed columns first, a different (unstated) policy, rows sorted by variance.
    header = ["Category", "Owner", "Region"] + COMPUTED[::-1]
    order = sorted(range(16), key=lambda i: BUDGET[i][2] - BUDGET[i][1])
    review = [header]
    severity = {}
    for r, i in enumerate(order, start=2):
        category, planned, actual, owner, region, _ = BUDGET[i]
        variance = actual - planned
        level = "Critical" if abs(variance) >= 200 else "Normal"
        severity[category] = level
        values = {"Variance": variance, "Variance Abs": abs(variance), "Status": "over" if variance > 0 else "ok",
                  "Severity": level, "Review Flag": "Y" if abs(variance) >= 100 else "N",
                  "Disposition": "check", "Recheck Owner": owner, "Review Slot": "TBD", "Audit ID": f"A{r}",
                  "Cross-VM Trace": f"phone->linux:{category}", "Evidence Link": f"ev/{category}",
                  "Packet Type": "packet"}
        src = i + 2
        row = [(f"=RawBudget!A{src}", category), (f"=RawBudget!D{src}", owner), (f"=RawBudget!E{src}", region)]
        for name in header[3:]:
            formula = {"Variance": f"=RawBudget!C{src}-RawBudget!B{src}", "Variance Abs": f"=ABS(N{r})"}.get(
                name, f'=IF(O{r}>=100,"x","y")')
            row.append((formula, values[name]))
        review.append(row)
    # EscalationQueue: one FILTER array formula, two columns, largest first.
    escalated = sorted((i for i in range(16) if abs(BUDGET[i][2] - BUDGET[i][1]) >= 100),
                       key=lambda i: -abs(BUDGET[i][2] - BUDGET[i][1]))
    queue = [["Escalation Queue"], ["Category", "Variance Abs"]]
    for n, i in enumerate(escalated):
        category = BUDGET[i][0]
        vabs = abs(BUDGET[i][2] - BUDGET[i][1])
        if n == 0:
            queue.append([{"array": f"A3:B{2 + len(escalated)}", "v": category,
                           "f": "=SORT(FILTER(VarianceReview!A2:O17,VarianceReview!O2:O17>=100),2,-1)"}, vabs])
        else:
            queue.append([category, vabs])
    # OwnerSummary: a title row, other columns, owners in another order.
    owners = ["Theo Martin", "Priya Nair", "Maya Chen", "Jordan Lee"]
    owner = [["Owner summary"], ["Name", "Rows", "Total Planned", "Total Actual", "Escalations", "Critical"]]
    for r, name in enumerate(owners, start=3):
        members = [row for row in BUDGET if row[3] == name]
        owner.append([name, (f"=COUNTIF(RawBudget!D2:D17,A{r})", len(members)),
                      (f"=SUMIF(RawBudget!D2:D17,A{r},RawBudget!B2:B17)", sum(m[1] for m in members)),
                      (f"=SUMIF(RawBudget!D2:D17,A{r},RawBudget!C2:C17)", sum(m[2] for m in members)),
                      (f"=COUNTIFS(VarianceReview!B2:B17,A{r},VarianceReview!O2:O17,\">=100\")",
                       sum(abs(m[2] - m[1]) >= 100 for m in members)),
                      (f"=COUNTIFS(VarianceReview!B2:B17,A{r},VarianceReview!L2:L17,\"Critical\")",
                       sum(severity[m[0]] == "Critical" for m in members))])
    owner.append(["Total", ("=SUM(B3:B6)", 16)])
    # RegionalSummary: alphabetical regions, net variance only.
    regional = [["Region", "Net Variance", "Absolute Variance"]]
    for r, name in enumerate(sorted(REGIONS), start=2):
        members = [row for row in BUDGET if row[4] == name]
        regional.append([name, (f"=SUMIF(RawBudget!E2:E17,A{r},RawBudget!C2:C17)-SUMIF(RawBudget!E2:E17,A{r},"
                                f"RawBudget!B2:B17)", sum(m[2] - m[1] for m in members)),
                         (f"=SUMIF(VarianceReview!C2:C17,A{r},VarianceReview!O2:O17)",
                          sum(abs(m[2] - m[1]) for m in members))])
    # ControlPanel: a row of labels with the values below them.
    critical = sum(level == "Critical" for level in severity.values())
    panel = [["Imported Rows", "Total Planned", "Total Actual", "Net Variance", "Absolute Variance",
              "Escalation Count", "Critical Count", "Android Transfer Status"],
             [("=COUNTA(RawBudget!A2:A17)", 16), ("=SUM(RawBudget!B2:B17)", 14600),
              ("=SUM(RawBudget!C2:C17)", 15860), ("=C2-B2", 1260), ("=ABS(D2)", 1260),
              ("=COUNTA(EscalationQueue!A3:A13)", 11), (f'=COUNTIF(VarianceReview!L2:L17,"Critical")', critical),
              "Received from the phone"]]
    return {"RawBudget": grid(raw), "VarianceReview": grid(review), "EscalationQueue": grid(queue),
            "OwnerSummary": grid(owner), "RegionalSummary": grid(regional), "ControlPanel": grid(panel)}


# --------------------------------------------------------------------------- running the check

def _check(task_text: str) -> str:
    command = yaml.safe_load(task_text)["evaluation"]["params"]["linux"][1]["params"]["command"]
    return command.split("<<'OSOMNI_PY'\n", 1)[1].rsplit("\nOSOMNI_PY", 1)[0]


def run(tmp_path: Path, sheets) -> subprocess.CompletedProcess[str]:
    pytest.importorskip("openpyxl")
    (tmp_path / "Documents").mkdir(exist_ok=True)
    write_xlsx(tmp_path / "Documents" / "budget_review.xlsx", sheets)
    script = tmp_path / "check.py"
    script.write_text(_check(TASK.read_text(encoding="utf-8")), encoding="utf-8")
    return subprocess.run([sys.executable, "-W", "ignore", str(script)], capture_output=True, text=True,
                          timeout=120, env={**os.environ, "USERPROFILE": str(tmp_path)})


def passed(done) -> bool:
    return done.returncode == 0 and "EVAL_RESULT:PASS" in done.stdout


@pytest.mark.parametrize("build", [reference_workbook, other_workbook], ids=["old_reference", "other_faithful"])
def test_faithful_workbooks_pass(tmp_path, build):
    done = run(tmp_path, build())
    assert passed(done), done.stdout + done.stderr


def test_old_check_accepted_only_its_own_build():
    assert old_check_passes(reference_workbook())
    assert not old_check_passes(other_workbook())


def _mutate(build, sheet, change):
    sheets = build()
    change(sheets[sheet])
    return sheets


def _set(ref, value):
    return lambda cells: cells.__setitem__(ref, value)


@pytest.mark.parametrize("sheet, change, code", [
    ("RawBudget", _set((3, 2), 2000), "RawBudget_MISMATCH"),
    # VarianceReview: Planned minus Actual is not the brief's variance (net = actual minus planned).
    ("VarianceReview", _set((2, 7), ("=B2-C2", 220)), "VarianceReview_WRONG_VARIANCE"),
    ("VarianceReview", _set((2, 9), "Under"), "VarianceReview_TYPED_VALUE"),
    ("VarianceReview", lambda cells: cells.pop((1, 18)), "VarianceReview_MISSING_COLUMNS"),
    ("VarianceReview", lambda cells: [cells.pop(k) for k in [k for k in cells if k[0] == 17]],
     "VarianceReview_MISSING_ROWS"),
    ("EscalationQueue", _set((13, 1), ("=VarianceReview!A4", "Meals")), "EscalationQueue_ROWS"),
    ("EscalationQueue", lambda cells: [cells.pop(k) for k in [k for k in cells if k[0] == 12]],
     "EscalationQueue_ROWS"),
    ("EscalationQueue", _set((2, 1), "Travel"), "EscalationQueue_TYPED_VALUE"),
    ("OwnerSummary", _set((2, 2), ("=SUMIF(RawBudget!D:D,A2,RawBudget!C:C)", 6795)), "OwnerSummary_WRONG_VALUE"),
    ("OwnerSummary", _set((3, 2), 3600), "OwnerSummary_TYPED_VALUE"),
    ("RegionalSummary", lambda cells: [cells.pop(k) for k in [k for k in cells if k[0] == 4]],
     "RegionalSummary_MISSING_ROWS"),
    ("ControlPanel", _set((2, 2), 15), "ControlPanel_WRONG_VALUE"),
    ("ControlPanel", _set((8, 2), ('=COUNTIF(VarianceReview!J2:J17,"High")', 6)), "ControlPanel_WRONG_VALUE"),
    ("ControlPanel", lambda cells: [cells.pop((9, 1)), cells.pop((9, 2))], "ControlPanel_MISSING:status"),
])
def test_what_the_brief_states_is_still_required(tmp_path, sheet, change, code):
    done = run(tmp_path, _mutate(reference_workbook, sheet, change))
    assert not passed(done) and code in done.stdout, done.stdout + done.stderr


def test_summary_without_conditional_aggregates_fails(tmp_path):
    def plain(cells):
        for (r, c), value in list(cells.items()):
            if r > 1 and c > 1:
                cells[(r, c)] = ("=0+" + str(value[1]), value[1])
    done = run(tmp_path, _mutate(reference_workbook, "RegionalSummary", plain))
    assert "RegionalSummary_NO_SUMIF_COUNTIFS" in done.stdout


@pytest.mark.parametrize("as_date, ok", [(True, True), (False, False)], ids=["date_cells", "bare_serials"])
def test_due_dates_saved_as_dates_are_the_csv_dates(tmp_path, as_date, ok):
    # Calc may turn the ISO DueDate text into date cells; a date cell is the same CSV value, a
    # bare serial number is not.
    def convert(cells):
        for (r, c), value in list(cells.items()):
            if r > 1 and c == 6:
                day = datetime.date.fromisoformat(value)
                cells[(r, c)] = day if as_date else (day - datetime.date(1899, 12, 30)).days
    done = run(tmp_path, _mutate(reference_workbook, "RawBudget", convert))
    assert passed(done) is ok, done.stdout + done.stderr
