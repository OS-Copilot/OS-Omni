"""Run the Python embedded in Windows desktop-app check scripts against local fixtures."""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHECKS = ROOT / "evaluators/windows/checks"


def _here_string(script_name: str, variable: str) -> str:
    text = (CHECKS / script_name).read_text(encoding="utf-8").replace("\r\n", "\n")
    return text.split(f"${variable} = @'\n", 1)[1].split("\n'@", 1)[0]


def _run(code: str, tmp_path: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "check.py"
    script.write_text(code, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-W", "ignore", str(script)],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, **env},
    )


# --------------------------------------------------------------------------- blender


def test_blender_robot_tower_expects_exactly_the_eleven_briefed_blend_files():
    text = (CHECKS / "blender_robot_tower_layout_scene.ps1").read_text(encoding="utf-8")
    payload = re.search(r'\$expectedJson = .*?FromBase64String\("([^"]+)"\)', text).group(1)
    expected = json.loads(base64.b64decode(payload))
    instruction = yaml.safe_load(
        (ROOT / "tasks/v1/windows/blender_robot_tower_layout_scene.yaml").read_text(encoding="utf-8")
    )["instruction"]
    briefed = set(re.findall(r"blender_social_render\\(\w+\.blend)", instruction))
    paths = [item["path"] for item in expected["additional"]]
    assert len(paths) == 10
    assert {path.rsplit("\\", 1)[1] for path in paths} | {"product_stage.blend"} == briefed
    assert len(briefed) == 11


# --------------------------------------------------------------------------- calc

QUARTERS = {
    "Q1": [("Alpha", 120, 36000), ("Beta", 85, 25500), ("Gamma", 200, 40000), ("Delta", 95, 28500), ("Epsilon", 160, 38400)],
    "Q2": [("Gamma", 180, 36000), ("Alpha", 150, 45000), ("Epsilon", 170, 40800), ("Beta", 90, 27000), ("Delta", 110, 33000)],
    "Q3": [("Delta", 125, 37500), ("Beta", 110, 33000), ("Alpha", 130, 39000), ("Gamma", 160, 32000), ("Epsilon", 155, 37200)],
    "Q4": [("Epsilon", 190, 45600), ("Gamma", 210, 42000), ("Delta", 140, 42000), ("Alpha", 170, 51000), ("Beta", 118, 35400)],
}
PRODUCTS = {"Alpha": ("Hardware", 165000), "Beta": ("Software", 125000), "Gamma": ("Hardware", 155000),
            "Delta": ("Services", 145000), "Epsilon": ("Software", 168000)}
SORTED = ["Alpha", "Gamma", "Delta", "Epsilon", "Beta"]


def _expected_row(product):
    revenue = [next(row[2] for row in QUARTERS[q] if row[0] == product) for q in QUARTERS]
    total = sum(revenue)
    variance = total - PRODUCTS[product][1]
    status = "Above Target" if variance >= 0 else "Below Target"
    return [PRODUCTS[product][0], *revenue, total, total / 4, revenue[3] / total, variance, status]


def _oracle_formulas(r):
    return [f"=VLOOKUP(A{r},Products!$A$2:$C$6,2,0)",
            *[f"=VLOOKUP(A{r},{q}!$A$2:$C$6,3,0)" for q in QUARTERS],
            f"=SUM(C{r}:F{r})", f"=AVERAGE(C{r}:F{r})", f"=F{r}/G{r}",
            f"=G{r}-VLOOKUP(A{r},Products!$A$2:$C$6,3,0)", f'=IF(J{r}>=0,"Above Target","Below Target")']


def _sumif_lookups(r):
    return [f"=SUMIF('{q}'!$A$2:$A$6,$A{r},'{q}'!$C$2:$C$6)" for q in QUARTERS]


def _build_workbook(path: Path, cells, *, cached=True, cf_range="J2:J6"):
    """Write quarterly.xlsx; ``cells(r, product)`` gives the B:K contents of a Summary row.

    With ``cached`` every formula cell also gets the cached value LibreOffice would save.
    """
    openpyxl = pytest.importorskip("openpyxl")
    from openpyxl.chart import BarChart, Reference
    from openpyxl.comments import Comment
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.styles import PatternFill

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in QUARTERS.items():
        ws = wb.create_sheet(name)
        ws.append(["Product", "Units", "Revenue"])
        for row in rows:
            ws.append(row)
    products = wb.create_sheet("Products")
    products.append(["Product", "Category", "Annual Target"])
    for name, (category, target) in PRODUCTS.items():
        products.append([name, category, target])
    summary = wb.create_sheet("Summary")
    summary.append(["Product", "Category", "Q1 Revenue", "Q2 Revenue", "Q3 Revenue", "Q4 Revenue", "Total Revenue",
                    "Average Revenue", "Q4 Share", "Target Variance", "Target Status"])
    values = {}
    for r, product in enumerate(SORTED, start=2):
        summary.append([product, *cells(r, product)])
        summary.cell(r, 9).number_format = "0.0%"
        for col, value in enumerate(_expected_row(product), start=2):
            values[f"{openpyxl.utils.get_column_letter(col)}{r}"] = value
    summary.freeze_panes = "A2"
    summary.auto_filter.ref = "A1:K6"
    summary["K1"].comment = Comment("Target status is based on Products targets", "QA")
    chart = BarChart()
    chart.title = "Annual Revenue by Product"
    chart.add_data(Reference(summary, min_col=7, min_row=1, max_row=6), titles_from_data=True)
    chart.set_categories(Reference(summary, min_col=1, min_row=2, max_row=6))
    summary.add_chart(chart, "M2")
    red = PatternFill(start_color="FFFF0000", end_color="FFFF0000", fill_type="solid")
    green = PatternFill(start_color="FF00FF00", end_color="FF00FF00", fill_type="solid")
    summary.conditional_formatting.add(cf_range, CellIsRule(operator="lessThan", formula=["0"], fill=red))
    summary.conditional_formatting.add(cf_range, CellIsRule(operator="greaterThanOrEqual", formula=["0"], fill=green))
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    if cached:
        _cache_formula_values(path, "xl/worksheets/sheet6.xml", values)


def _cache_formula_values(path: Path, member: str, values):
    with zipfile.ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    xml = contents[member].decode("utf-8")

    def fill(match):
        ref, attrs, formula = match.group(1), match.group(2), match.group(3)
        value = values[ref]
        if isinstance(value, str):
            return f'<c r="{ref}"{attrs} t="str"><f>{formula}</f><v>{value}</v></c>'
        return f'<c r="{ref}"{attrs}><f>{formula}</f><v>{value}</v></c>'

    xml = re.sub(r'<c r="([A-Z]+\d+)"([^>]*)><f>(.*?)</f><v\s*/?>(?:</v>)?</c>', fill, xml)
    contents[member] = xml.encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in contents.items():
            archive.writestr(name, data)


def _run_calc(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return _run(_here_string("calc_crosssheet_chart.ps1", "pyCode"), tmp_path, {"USERPROFILE": str(tmp_path)})


def _workbook(tmp_path: Path) -> Path:
    return tmp_path / "Downloads" / "quarterly.xlsx"


def test_calc_oracle_formulas_without_cached_values_still_pass(tmp_path):
    _build_workbook(_workbook(tmp_path), lambda r, _p: _oracle_formulas(r), cached=False)
    result = _run_calc(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "EVAL_RESULT:PASS" in result.stdout


def test_calc_accepts_any_lookup_formula_and_typed_derived_values(tmp_path):
    def cells(r, product):
        expected = _expected_row(product)
        return [expected[0], *_sumif_lookups(r), *expected[5:]]

    _build_workbook(_workbook(tmp_path), cells)
    result = _run_calc(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "EVAL_RESULT:PASS" in result.stdout


def test_calc_quarter_revenue_must_be_looked_up_not_typed(tmp_path):
    def cells(r, product):
        return _expected_row(product)

    _build_workbook(_workbook(tmp_path), cells)
    result = _run_calc(tmp_path)
    assert result.returncode == 1
    assert "Q1_not_lookup_formula row=2" in result.stdout


def test_calc_typed_derived_value_must_be_correct(tmp_path):
    def cells(r, product):
        expected = _expected_row(product)
        total = expected[5] + (1000 if product == "Delta" else 0)
        return [expected[0], *_sumif_lookups(r), total, *expected[6:]]

    _build_workbook(_workbook(tmp_path), cells)
    result = _run_calc(tmp_path)
    assert result.returncode == 1
    assert "derived_value_wrong cell=G4" in result.stdout


def test_calc_unrecognised_formula_needs_a_cached_value(tmp_path):
    def cells(r, product):
        return [_oracle_formulas(r)[0], *_sumif_lookups(r), *_oracle_formulas(r)[5:]]

    _build_workbook(_workbook(tmp_path), cells, cached=False)
    result = _run_calc(tmp_path)
    assert result.returncode == 1
    assert "Q1_value_missing row=2" in result.stdout


@pytest.mark.parametrize("cf_range, passes", [("J2:J6", True), ("J1:J1048576", True), ("J1:J6", True),
                                              ("J2:J5", False), ("I2:J6", False)])
def test_calc_conditional_formatting_range_is_the_target_variance_column(tmp_path, cf_range, passes):
    _build_workbook(_workbook(tmp_path), lambda r, _p: _oracle_formulas(r), cf_range=cf_range)
    result = _run_calc(tmp_path)
    assert (result.returncode == 0) is passes, result.stdout + result.stderr
    if not passes:
        assert "conditional_formatting_wrong" in result.stdout


# --------------------------------------------------------------------------- calendar

US = 1_000_000


def _calendar_profile(tmp_path: Path, events, *, init_log_start=None):
    profiles = tmp_path / "Profiles"
    data = profiles / "oracle.calendar.default" / "calendar-data"
    data.mkdir(parents=True)
    conn = sqlite3.connect(data / "local.sqlite")
    conn.executescript(
        """
        CREATE TABLE cal_events (cal_id TEXT, id TEXT, time_created INTEGER, last_modified INTEGER, title TEXT,
            event_start INTEGER, event_end INTEGER, event_start_tz TEXT, event_end_tz TEXT, recurrence_id INTEGER);
        CREATE TABLE cal_recurrence (item_id TEXT, cal_id TEXT, icalString TEXT);
        CREATE TABLE cal_alarms (cal_id TEXT, item_id TEXT, recurrence_id INTEGER, recurrence_id_tz TEXT,
            icalString TEXT);
        """
    )
    for index, (title, start, minutes, rrule, trigger) in enumerate(events):
        item = f"item-{index}"
        begin = int(start.replace(tzinfo=dt.timezone.utc).timestamp()) * US
        conn.execute(
            "INSERT INTO cal_events VALUES ('cal', ?, 0, 0, ?, ?, ?, 'UTC', 'UTC', NULL)",
            (item, title, begin, begin + minutes * 60 * US),
        )
        if rrule:
            conn.execute("INSERT INTO cal_recurrence VALUES (?, 'cal', ?)", (item, f"RRULE:{rrule}"))
        if trigger:
            conn.execute(
                "INSERT INTO cal_alarms VALUES ('cal', ?, NULL, NULL, ?)",
                (item, f"BEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:{trigger}\r\nEND:VALARM"),
            )
    conn.commit()
    conn.close()
    temp = tmp_path / "Temp"
    temp.mkdir()
    if init_log_start is not None:
        stamp = init_log_start.strftime("%Y-%m-%dT%H:%M:%S") + ".1234567-07:00"
        (temp / "helloworld_thunderbird_calendar_init.log").write_text(
            f"﻿{stamp} begin thunderbird calendar reset\n{stamp} done thunderbird calendar reset\n",
            encoding="utf-8",
        )
    return profiles, temp


def _run_calendar(tmp_path: Path, profiles: Path, temp: Path, now: dt.datetime):
    code = _here_string("calendar_create_recurring_event.ps1", "script")
    code = code.replace('os.path.expandvars(r"%APPDATA%\\Thunderbird\\Profiles")', repr(str(profiles)))
    code = code.replace("dt.datetime.now()", f"dt.datetime({now.year}, {now.month}, {now.day}, {now.hour}, {now.minute})")
    assert repr(str(profiles)) in code and "dt.datetime.now()" not in code
    return _run(code, tmp_path, {"TEMP": str(temp)})


def _release_plan(tuesday, thursday, friday, rrule="FREQ=WEEKLY", trigger="-PT15M"):
    return [
        ("Weekly Release Triage", dt.datetime.combine(tuesday, dt.time(9, 15)), 45, rrule, trigger),
        ("QA Sign-off", dt.datetime.combine(thursday, dt.time(11, 0)), 30, None, None),
        ("Launch Readiness Review", dt.datetime.combine(friday, dt.time(16, 0)), 60, None, None),
    ]


MONDAY = dt.date(2026, 6, 15)


def _day(offset):
    return MONDAY + dt.timedelta(days=offset)


def test_calendar_monday_start_accepts_the_coming_days_with_thunderbird_weekly_preset(tmp_path):
    # The saved Opus run: guest clock Monday 2026-06-15, events on 6/16, 6/18 and 6/19,
    # Repeat = Weekly (RRULE:FREQ=WEEKLY, no BYDAY).
    profiles, temp = _calendar_profile(tmp_path, _release_plan(_day(1), _day(3), _day(4)),
                                       init_log_start=dt.datetime(2026, 6, 15, 9, 0))
    result = _run_calendar(tmp_path, profiles, temp, dt.datetime(2026, 6, 15, 9, 30))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "EVAL_RESULT:PASS" in result.stdout


def test_calendar_monday_start_accepts_the_following_week_with_byday(tmp_path):
    profiles, temp = _calendar_profile(tmp_path, _release_plan(_day(8), _day(10), _day(11), rrule="FREQ=WEEKLY;BYDAY=TU"),
                                       init_log_start=dt.datetime(2026, 6, 15, 9, 0))
    result = _run_calendar(tmp_path, profiles, temp, dt.datetime(2026, 6, 15, 9, 30))
    assert result.returncode == 0, result.stdout + result.stderr


def test_calendar_rejects_mixing_readings_of_next(tmp_path):
    profiles, temp = _calendar_profile(tmp_path, _release_plan(_day(1), _day(10), _day(11)),
                                       init_log_start=dt.datetime(2026, 6, 15, 9, 0))
    result = _run_calendar(tmp_path, profiles, temp, dt.datetime(2026, 6, 15, 9, 30))
    assert result.returncode == 1
    assert ":date" in result.stdout


def test_calendar_evaluation_after_midnight_keeps_the_task_start_day(tmp_path):
    profiles, temp = _calendar_profile(tmp_path, _release_plan(_day(1), _day(3), _day(4)),
                                       init_log_start=dt.datetime(2026, 6, 15, 23, 40))
    result = _run_calendar(tmp_path, profiles, temp, dt.datetime(2026, 6, 16, 0, 20))
    assert result.returncode == 0, result.stdout + result.stderr


def test_calendar_without_init_log_uses_the_evaluation_day(tmp_path):
    profiles, temp = _calendar_profile(tmp_path, _release_plan(_day(1), _day(3), _day(4)))
    result = _run_calendar(tmp_path, profiles, temp, dt.datetime(2026, 6, 15, 9, 30))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("rrule", ["FREQ=WEEKLY;INTERVAL=2", "FREQ=WEEKLY;BYDAY=TU,TH", "FREQ=WEEKLY;BYDAY=MO"])
def test_calendar_weekly_rule_must_repeat_every_tuesday(tmp_path, rrule):
    profiles, temp = _calendar_profile(tmp_path, _release_plan(_day(1), _day(3), _day(4), rrule=rrule),
                                       init_log_start=dt.datetime(2026, 6, 15, 9, 0))
    result = _run_calendar(tmp_path, profiles, temp, dt.datetime(2026, 6, 15, 9, 30))
    assert result.returncode == 1
    assert "Weekly Release Triage:byday" in result.stdout


def test_calendar_missing_recurrence_and_alarm_still_fail(tmp_path):
    profiles, temp = _calendar_profile(tmp_path, _release_plan(_day(1), _day(3), _day(4), rrule=None, trigger="-PT30M"),
                                       init_log_start=dt.datetime(2026, 6, 15, 9, 0))
    result = _run_calendar(tmp_path, profiles, temp, dt.datetime(2026, 6, 15, 9, 30))
    assert result.returncode == 1
    assert "Weekly Release Triage:recurrence" in result.stdout
    assert "Weekly Release Triage:alarm" in result.stdout


# --------------------------------------------------------------------------- cross-app OpenShop + calendar

COFFEE_EVENTS = [
    ("Bench Coffee Delivery Follow-up", 2, 9, 0), ("Bench Coffee Receipt Audit", 1, 15, 15),
    ("Bench Coffee Stock Review", 3, 11, 45), ("Bench Coffee Packaging Check", 4, 10, 15),
    ("Bench Coffee Desk Drop Confirmation", 5, 14, 0), ("Bench Coffee Invoice Match Review", 6, 16, 30),
    ("Bench Coffee Pantry Count Update", 7, 9, 45), ("Bench Coffee Vendor Thank-You Draft", 8, 13, 15),
    ("Bench Coffee Delivery Exception Scan", 9, 15, 30), ("Bench Coffee Budget Sync", 10, 10, 0),
    ("Bench Coffee Facility Receipt Review", 11, 11, 0), ("Bench Coffee Supply Follow-up Closeout", 12, 16, 0),
    ("Bench Coffee Front Desk Pickup Audit", 13, 9, 30), ("Bench Coffee Stockroom Label Check", 14, 14, 30),
    ("Bench Coffee Order Retention", 15, 10, 45), ("Bench Coffee Team Brew Inventory", 16, 13, 45),
    ("Bench Coffee Vendor Receipt Archive", 17, 15, 0), ("Bench Coffee Final Closeout", 18, 16, 45),
]
PLACED_ORDER = {
    "id": "ORD-1", "status": "Awaiting Shipment", "address": {"label": "Office"},
    "payment": {"id": "wechat", "label": "WeChat Pay"}, "note": "Leave it at the front desk", "total": 90,
    "items": [{"product": {"id": "p1005"}, "quantity": 1, "selectedSpec": "20 sachets"}],
}


@pytest.fixture
def openshop_api():
    import http.server
    import threading

    payloads = {
        "/api/session": {"session": {"loggedIn": True, "user": {"phone": "13800138000"}}},
        "/api/cart": {"items": [], "total": 0},
        "/api/orders": {"orders": [{"id": "TBH-LUCAS-1"}, PLACED_ORDER]},
    }

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(payloads[self.path]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _coffee_events(start_day, *, minutes=30, skip=()):
    return [
        (title, dt.datetime.combine(start_day + dt.timedelta(days=offset), dt.time(hour, minute)), minutes, None, None)
        for title, offset, hour, minute in COFFEE_EVENTS
        if title not in skip
    ]


def _run_cross_app(tmp_path, base_url, profiles, temp, now):
    code = _here_string("cross_app_openshop_calendar_checkout_coffee_followup_hard.ps1", "script")
    replacements = {
        'BASE_URL = "http://127.0.0.1:4310"': f"BASE_URL = {base_url!r}",
        'os.path.expandvars(r"%APPDATA%\\Thunderbird\\Profiles")': repr(str(profiles)),
        "deadline = time.time() + 30": "deadline = time.time() + 1",
        "dt.datetime.now()": f"dt.datetime({now.year}, {now.month}, {now.day}, {now.hour}, {now.minute})",
    }
    for old, new in replacements.items():
        assert old in code
        code = code.replace(old, new)
    return _run(code, tmp_path, {"TEMP": str(temp)})


def test_cross_app_reads_thunderbird_integer_event_times(tmp_path, openshop_api):
    # The saved Opus run: guest day Monday 2026-06-15, events 6/16 .. 7/3 created in the GUI.
    profiles, temp = _calendar_profile(tmp_path, _coffee_events(MONDAY), init_log_start=dt.datetime(2026, 6, 15, 8, 7))
    result = _run_cross_app(tmp_path, openshop_api, profiles, temp, dt.datetime(2026, 6, 15, 8, 45))
    assert "EVAL_RESULT:PASS" in result.stdout, result.stdout + result.stderr


def test_cross_app_offsets_stay_relative_to_the_task_start_after_midnight(tmp_path, openshop_api):
    profiles, temp = _calendar_profile(tmp_path, _coffee_events(MONDAY), init_log_start=dt.datetime(2026, 6, 15, 23, 50))
    result = _run_cross_app(tmp_path, openshop_api, profiles, temp, dt.datetime(2026, 6, 16, 0, 30))
    assert "EVAL_RESULT:PASS" in result.stdout, result.stdout + result.stderr


@pytest.mark.parametrize("events, missing", [
    (_coffee_events(MONDAY, minutes=60), "Bench Coffee Delivery Follow-up"),
    (_coffee_events(MONDAY, skip={"Bench Coffee Budget Sync"}), "Bench Coffee Budget Sync"),
    (_coffee_events(MONDAY + dt.timedelta(days=1)), "Bench Coffee Delivery Follow-up"),
])
def test_cross_app_wrong_or_missing_events_fail(tmp_path, openshop_api, events, missing):
    profiles, temp = _calendar_profile(tmp_path, events, init_log_start=dt.datetime(2026, 6, 15, 8, 7))
    result = _run_cross_app(tmp_path, openshop_api, profiles, temp, dt.datetime(2026, 6, 15, 8, 45))
    assert "EVAL_RESULT:FAIL calendar event missing or wrong" in result.stdout
    assert missing in result.stdout


# --------------------------------------------------------------------------- brief / evaluator contract


@pytest.mark.parametrize("path", sorted((ROOT / "tasks/v1/windows").glob("*.yaml")), ids=lambda p: p.stem)
def test_windows_supplemental_files_are_named_in_the_brief(path):
    task = yaml.safe_load(path.read_text(encoding="utf-8"))
    checks = ((task.get("evaluation") or {}).get("params") or {}).get("supplemental_checks") or {}
    for item in checks.get("files") or []:
        assert item["path"] in task["instruction"]


@pytest.mark.parametrize("path", sorted((ROOT / "tasks/v1/windows").glob("*.yaml")), ids=lambda p: p.stem)
def test_supplemental_files_can_be_written_through_the_gui(path):
    """The agent may only drive the GUI, so a brief that asks for extra text files must not forbid the
    text editor (or demand a scripted 'file-writing method'), and the evaluator must not fail on Notepad."""
    task = yaml.safe_load(path.read_text(encoding="utf-8"))
    checks = ((task.get("evaluation") or {}).get("params") or {}).get("supplemental_checks") or {}
    if not checks.get("files"):
        return
    instruction = task["instruction"].lower()
    assert "file-writing method" not in instruction
    assert "notepad or another text editor" not in instruction
    assert "notepad" not in " ".join(str(x.get("label", "")) for x in checks.get("powershell") or [])


def test_supplemental_exact_text_accepts_utf8_bom():
    from platforms.windows.runners.evaluation import _run_supplemental_checks

    class _Controller:
        def get_file(self, path):
            return "\ufeffa\tb\r\nc\r\n".encode("utf-8")

    params = {"supplemental_checks": {"files": [{"path": r"C:\x.tsv", "exact_text": "a\tb\nc"}]}}
    assert _run_supplemental_checks(controller=_Controller(), params=params).status.value == "PASS"
