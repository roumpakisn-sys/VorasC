from copy import deepcopy
from datetime import date
import base64
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from urllib.parse import quote

import gantt_staff_transfer as transfer
from assignment_store import AssignmentSaveError, save_changes
from test_assignment_store import Client
from test_assignment_policy import row
from test_placement_details import chart
from test_regression_smoke import get_source_functions

try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None

ROOT = Path(__file__).resolve().parents[1]


def records():
    return [
        {**row(), "id": "source-1", "employeeId": "e", "notes": "Αρχικό έργο"},
        {**row(), "id": "source-2", "employeeId": "e2", "notes": "Αρχικό έργο"},
        {**row(), "id": "target", "employeeId": "", "projectId": "p2", "startTime": "14:00",
         "endTime": "17:00", "arrivalTime": "13:45", "notes": "Οδηγίες προορισμού", "recurring_id": "series"},
    ]


SOURCE = {"AssignmentIds": ["source-1", "source-2"], "EmployeeIds": ["e", "e2"]}
TARGET = {"AssignmentIds": ["target"], "EmployeeIds": [""]}


class TransferTests(unittest.TestCase):
    def test_drop_back_to_list_only_unassigns_from_source_and_keeps_empty_bar(self):
        original = records()
        mapping = {"bar-source": "s"}
        payload = dict(token="token", source="bar-source", target=None, employee="e", nonce="one")
        event = transfer.DROP_PREFIX + quote(json.dumps(payload))
        for source_rows, source, expected in (
            (original[:2], SOURCE, [original[1]]),
            (original[:1], {"AssignmentIds": ["source-1"]}, [{**original[0], "employeeId": ""}]),
        ):
            with self.subTest(workers=len(source_rows)):
                all_rows = [*source_rows, original[-1]]
                client = Client(all_rows)
                state = {"gantt_staff_drag_token": "token"}
                result = transfer.apply_drop(event, state, mapping, {"s": source}, all_rows,
                                             lambda before, after: save_changes(client, before, after)["rows"])
                self.assertEqual(result, "unassigned")
                self.assertFalse(transfer.apply_drop(event, state, mapping, {"s": source}, all_rows, self.fail))
                request, = [params for name, params in client.calls if name == "save_assignment_changes"]
                self.assertEqual(request["p_expected"], source_rows)
                self.assertEqual(request["p_records"], expected)

    def test_list_drop_only_updates_destination_and_validates_availability(self):
        original = records()
        state = {"gantt_staff_drag_token": "token"}
        groups, mapping = {"t": TARGET}, {"bar-target": "t"}
        payload = dict(token="token", source=None, target="bar-target", employee="e", nonce="one")
        event = transfer.DROP_PREFIX + quote(json.dumps(payload))
        client = Client(original)
        client.ctx["assignments"] = original
        result = transfer.apply_drop(event, state, mapping, groups, original,
                                     lambda before, after: save_changes(client, before, after)["rows"])
        self.assertEqual(result, "assigned")
        request, = [params for name, params in client.calls if name == "save_assignment_changes"]
        self.assertEqual(request["p_expected"], [original[-1]])
        self.assertEqual(request["p_records"], [{**original[-1], "employeeId": "e"}])

        blocked = Client(original)
        blocked.ctx["rules"] = [
            dict(employee_id="e", scope="date", rule_date=original[-1]["date"], kind="unavailable"),
        ]
        with self.assertRaises(AssignmentSaveError):
            transfer.apply_drop(event, {"gantt_staff_drag_token": "token"}, mapping, groups, original,
                                lambda before, after: save_changes(blocked, before, after))
        self.assertFalse(any(name == "save_assignment_changes" for name, _ in blocked.calls))

    def test_drop_is_saved_once_and_invalid_destinations_are_rejected(self):
        state = {"gantt_staff_drag_token": "token"}
        groups, mapping = {"s": SOURCE, "t": TARGET}, {"bar-source": "s", "bar-target": "t"}
        payload = dict(token="token", source="bar-source", target="bar-target", employee="e", nonce="one")
        event = transfer.DROP_PREFIX + quote(json.dumps(payload))
        calls = []
        def save(before, after):
            calls.append((before, after))
            return after
        self.assertTrue(transfer.apply_drop(event, state, mapping, groups, records(), save))
        self.assertFalse(transfer.apply_drop(event, state, mapping, groups, records(), save))
        self.assertEqual(len(calls), 1)
        self.assertTrue(state["gantt_transfer_reset"])
        for changed in (dict(token="old"), dict(target="unknown"), dict(employee="missing")):
            event = transfer.DROP_PREFIX + quote(json.dumps({**payload, **changed}))
            with self.assertRaises(ValueError):
                transfer.apply_drop(event, state, mapping, groups, records(), save)
        self.assertEqual(len(calls), 1)

    def test_partial_transfer_adopts_destination_without_mutating_inputs(self):
        original = records()
        before, after = transfer.plan_transfer(original, SOURCE, TARGET, ["e"])
        self.assertEqual(original, records())
        self.assertEqual(before, original)
        self.assertEqual({r["id"] for r in after}, {"source-2", "target"})
        moved = next(r for r in after if r["employeeId"] == "e")
        self.assertEqual(moved, {**original[-1], "employeeId": "e"})

    def test_transfer_all_keeps_one_vacancy_and_fills_destination_once_per_worker(self):
        before, after = transfer.plan_transfer(records(), SOURCE, TARGET, ["e", "e2"])
        vacancy, = [r for r in after if r["projectId"] == before[0]["projectId"]]
        self.assertEqual(vacancy, {**before[0], "employeeId": ""})
        self.assertEqual({r["employeeId"] for r in after if r["projectId"] == "p2"}, {"e", "e2"})
        self.assertEqual(len({r["id"] for r in after}), len(after))

    def test_duplicate_destination_and_missing_rows_cannot_change_either_bar(self):
        original = records()
        with self.assertRaisesRegex(ValueError, "διαφορετική"):
            transfer.plan_transfer(original, SOURCE, SOURCE, ["e"])
        with self.assertRaisesRegex(ValueError, "ήδη"):
            transfer.plan_transfer([*original[:-1], {**original[-1], "employeeId": "e"}], SOURCE, TARGET, ["e"])
        with self.assertRaisesRegex(ValueError, "αλλάξει"):
            transfer.plan_transfer(original[1:], SOURCE, TARGET, ["e"])

    def test_same_atomic_save_validates_destination_and_stale_source(self):
        original = records()
        before, after = transfer.plan_transfer(original, SOURCE, TARGET, ["e"])
        client = Client(original)
        result = save_changes(client, before, after)
        self.assertEqual(len(result["rows"]), len(after))
        self.assertEqual(sum(name == "save_assignment_changes" for name, _ in client.calls), 1)

        blocked = Client(original)
        blocked.ctx["rules"] = [dict(employee_id="e", scope="date", rule_date=original[0]["date"], kind="unavailable")]
        with self.assertRaises(AssignmentSaveError):
            save_changes(blocked, before, after)
        self.assertFalse(any(name == "save_assignment_changes" for name, _ in blocked.calls))

        stale = Client([{**original[0], "notes": "Άλλος χρήστης"}, *original[1:]])
        with self.assertRaises(AssignmentSaveError):
            save_changes(stale, before, after)
        self.assertFalse(any(name == "save_assignment_changes" for name, _ in stale.calls))

    def test_chart_clicks_choose_source_and_target_without_opening_edit(self):
        state = {"clicked_key": None}
        groups = {"source": SOURCE, "target": TARGET}
        transfer.pick_bar(state, "source", groups)
        transfer.pick_bar(state, "target", groups)
        self.assertEqual(state[transfer.SOURCE], "source")
        self.assertEqual(state[transfer.TARGET], "target")
        self.assertIsNone(state["clicked_key"])


class DragMarkupTests(unittest.TestCase):
    def test_drag_handles_and_client_event_keep_worker_and_bar_identity(self):
        from datetime import datetime, timedelta
        day = date(2026, 11, 16)
        _, groups, _ = chart([row(), {**row(), "id": "other", "employeeId": "", "startTime": "14:00"}])
        staff = [
            {"id": eid, "name": name, "is_external_crew": True}
            for eid, name in (("free", "Άννα"), ("early", "Ελένη"), ("busy", "Μαρία"))
        ]
        assignments_by_date = {day: [
            {**row(), "employeeId": "early", "startTime": "07:00", "endTime": "08:00"},
            {**row(), "employeeId": "busy"},
        ]}
        env = get_source_functions(ROOT / "gantt_html.py", ("build_html_gantt", "get_local_today"), {
            "datetime": datetime, "timedelta": timedelta, "html_utils": html, "base64": base64,
            "st": SimpleNamespace(session_state=SimpleNamespace(
                employees=staff, leaves=[], assignments_by_date=assignments_by_date,
            )),
            "utils": SimpleNamespace(supabase=None, get_employee_name=lambda eid: "Άννα"),
            "config": SimpleNamespace(BLUE_STACK_HEX="#0000ff"), "fetch_rules": lambda _: ([], None),
        })
        mapping = {key: f"bar-{index}" for index, key in enumerate(groups)}
        build = env["build_html_gantt"]
        ordinary = build(groups, day, 1, mapping, 500)
        self.assertNotIn("draggable='true'", ordinary)
        output = build(groups, day, 1, mapping, 500, staff_drag_token="token")

        class Collector(HTMLParser):
            def __init__(self):
                super().__init__()
                self.tags = []
            def handle_starttag(self, tag, attrs):
                self.tags.append((tag, dict(attrs)))
        parsed = Collector()
        parsed.feed(output)
        handles = [attrs for _, attrs in parsed.tags
                   if attrs.get("class") == "gantt-transfer-worker" and "data-staff-origin" not in attrs]
        self.assertEqual([(handle["data-employee"], handle["draggable"]) for handle in handles],
                         [("e", "true")])
        self.assertEqual(sum("data-staff-drop-target" in attrs for _, attrs in parsed.tags), 2)
        self.assertEqual(sum("data-staff-unassign-target" in attrs for _, attrs in parsed.tags), 7)
        for heading, employee_id in (("ΔΙΑΘΕΣΙΜΟΙ", "free"), ("ΜΕΤΑ ΤΑ ΠΡΩΙΝΑ", "early"),
                                     ("ΜΗ ΔΙΑΘΕΣΙΜΟΙ", "early")):
            self.assertRegex(output, rf"<b>{heading}:</b><br><span[^>]+data-staff-origin='availability' "
                                     rf"data-employee='{employee_id}'")

        source = next(group for group in groups.values() if group["Employees"] != ["ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ"])
        extra_staff = [
            {"id": f"extra-{index}", "name": f"Εργαζόμενος Δοκιμαστικού Συνεργείου {index}"}
            for index in range(4)
        ]
        staff.extend(extra_staff)
        short_bar = {
            **source,
            "StartTime": "09:00",
            "EndTime": "09:15",
            "ProjectDisplay": "Μακρύ όνομα έργου για πολύ μικρή μπάρα",
            "Employees": ["[ΜΕΤΑ ΑΠΟ 'ΑΛΛΟ ΕΡΓΟ' ▶ ΑΝΝΑ]", *[e["name"] for e in extra_staff]],
            "EmployeeIds": ["", "free", *[e["id"] for e in extra_staff]],
        }
        next_bar = {**source, "Key": "next-bar", "StartTime": "09:15", "EndTime": "09:30"}
        short_groups = {source["Key"]: short_bar, next_bar["Key"]: next_bar}
        short_mapping = {source["Key"]: "short-bar", next_bar["Key"]: "next-bar"}
        narrow = build(short_groups, day, 0.5, short_mapping, 500, staff_drag_token="token")
        narrow_tags = Collector()
        narrow_tags.feed(narrow)
        bars = {attrs["id"]: attrs for _, attrs in narrow_tags.tags if attrs.get("class") == "mygantt-bar"}
        self.assertIn("data-staff-widened", bars["short-bar"])
        self.assertNotIn("data-gantt-stacked", bars["short-bar"])
        self.assertIn("09:00-09:15", bars["short-bar"]["title"])
        self.assertIn("ΜΕΤΑ ΑΠΟ 'ΑΛΛΟ ΕΡΓΟ' ▶ ΑΝΝΑ", bars["short-bar"]["title"])
        project = html.escape(short_bar["ProjectDisplay"].upper())
        self.assertIn(f"<strong class='gantt-transfer-project'>{project}</strong>", narrow)
        for employee in [{"id": "free", "name": "Άννα"}, *extra_staff]:
            self.assertIn(f"data-employee='{employee['id']}'", narrow)
            self.assertIn(f">{employee['name']}</span>", narrow)
        ordinary_short = build(short_groups, day, 0.5, short_mapping, 500)
        self.assertNotIn("data-staff-widened", ordinary_short)
        self.assertNotIn("class='gantt-transfer-roster'", ordinary_short)
        self.check_short_bar_in_browser(narrow)

        node = shutil.which("node")
        if not node:
            return
        script = base64.b64decode(re.search(r'atob\("([^"]+)"\)', output)[1]).decode()
        harness = r'''
const assert = require('assert');
const handlers = {};
const displayClasses = () => {
  const classes = new Set();
  return {add: name => classes.add(name), remove: name => classes.delete(name), contains: name => classes.has(name)};
};
const source = {id:'bar-0'};
const target = {id:'bar-1', classList:displayClasses()};
const chip = {dataset:{employee:'e'},classList:displayClasses(),closest(){return source;}};
let reported;
const link = {click(){reported = this.id;}};
const surface = {
  dataset:{staffDragToken:'token'},classList:displayClasses(),style:{},offsetLeft:0,scrollWidth:600,scrollLeft:0,scrollTop:0,
  querySelector(){return null;},contains(el){return el === source;},getBoundingClientRect(){return {left:0,right:600,top:0,bottom:500};},
  addEventListener(type,fn){handlers[type] = fn;},removeEventListener(){}
};
global.sessionStorage = {getItem(){return null;},setItem(){}};
global.window = {addEventListener(){},removeEventListener(){}};
global.document = {
  body:{style:{}},getElementById(){return surface;},querySelector(){return link;},
  addEventListener(){},removeEventListener(){}
};
global.setTimeout = fn => {fn();};
'''
        checks = r'''
let prevented = false;
const e = {
  target:{closest(selector){return selector === '.gantt-transfer-worker' ? chip : null;}},
  dataTransfer:{setData(){}},preventDefault(){prevented=true;},stopPropagation(){}
};
handlers.mousedown({...e,button:0,pageX:0});
handlers.dragstart(e);
assert.strictEqual(prevented,false);
assert.strictEqual(e.dataTransfer.effectAllowed,'move');
assert.ok(chip.classList.contains('gantt-drag-origin'));
const dest = {...e,target:{closest(){return target;}},clientX:300,clientY:250};
handlers.dragover(dest);
assert.ok(target.classList.contains('gantt-drop-hover'));
handlers.drop(dest);
assert.ok(!target.classList.contains('gantt-drop-hover'));
assert.ok(!chip.classList.contains('gantt-drag-origin'));
assert.ok(reported.startsWith('gantt_staff_drop:'));
const payload = JSON.parse(decodeURIComponent(reported.split(':').slice(1).join(':')));
assert.deepStrictEqual([payload.source,payload.target,payload.employee,payload.token],['bar-0','bar-1','e','token']);
assert.ok(payload.nonce);

const listName = {dataset:{staffOrigin:'availability',employee:'free'},classList:displayClasses(),closest(){return null;}};
handlers.dragstart({...e,target:{closest(){return listName;}}});
assert.strictEqual(e.dataTransfer.effectAllowed,'copy');
handlers.dragover(dest);
assert.strictEqual(e.dataTransfer.dropEffect,'copy');
handlers.drop(dest);
const assignment = JSON.parse(decodeURIComponent(reported.slice('gantt_staff_drop:'.length)));
assert.deepStrictEqual([assignment.source,assignment.target,assignment.employee],[null,'bar-1','free']);

const leftList = {id:'',classList:displayClasses()};
const listDest = {...dest,target:{closest(selector){
  return selector === '[data-staff-unassign-target]' ? leftList : null;
}}};
handlers.dragstart({...e,target:{closest(){return listName;}}});
handlers.dragover(listDest);
assert.ok(!leftList.classList.contains('gantt-drop-hover'));
handlers.dragend();
handlers.dragstart(e);
handlers.dragover(listDest);
assert.ok(leftList.classList.contains('gantt-drop-hover'));
handlers.drop(listDest);
assert.ok(!leftList.classList.contains('gantt-drop-hover'));
const unassignment = JSON.parse(decodeURIComponent(reported.slice('gantt_staff_drop:'.length)));
assert.deepStrictEqual([unassignment.source,unassignment.target,unassignment.employee],['bar-0',null,'e']);

'''
        run = subprocess.run([node, "-"], input=harness + script + checks, text=True, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)

    def check_short_bar_in_browser(self, chart_html):
        browser = shutil.which("google-chrome")
        if browser is None:
            return
        script = """
<script>
window.addEventListener('load', () => {
    const bar = document.getElementById('short-bar');
    const next = document.getElementById('next-bar');
    const bounds = bar.getBoundingClientRect();
    const project = bar.querySelector('.gantt-transfer-project');
    const workers = Array.from(bar.querySelectorAll('.gantt-transfer-worker'));
    const withinBar = (element) => {
        const box = element.getBoundingClientRect();
        return box.height > 0 && box.width > 0 && box.top >= bounds.top
            && box.bottom <= bounds.bottom && box.left >= bounds.left && box.right <= bounds.right
            && element.scrollWidth <= element.clientWidth;
    };
    document.body.dataset.transferLayout = JSON.stringify({
        barWidth: Math.round(bounds.width),
        project: withinBar(project),
        workers: workers.length === 5 && workers.every(withinBar),
        separateLanes: next.getBoundingClientRect().top >= bounds.bottom,
    });
});
</script>
"""
        with TemporaryDirectory() as folder:
            fixture = Path(folder) / "transfer.html"
            fixture.write_text(f"<!doctype html><meta charset='utf-8'><body>{chart_html}{script}</body>",
                               encoding="utf-8")
            result = subprocess.run(
                [browser, "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
                 "--disable-background-networking", "--window-size=960,740", "--virtual-time-budget=1000",
                 f"--user-data-dir={folder}/profile", "--dump-dom", fixture.as_uri()],
                text=True, capture_output=True, timeout=45,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        page = re.search(r'data-transfer-layout="([^"]+)"', result.stdout)
        self.assertIsNotNone(page, "The browser did not report the transfer layout.")
        self.assertEqual(json.loads(html.unescape(page[1])), {
            "barWidth": 220, "project": True, "workers": True, "separateLanes": True,
        })


@unittest.skipIf(AppTest is None, "Install Streamlit UI test dependencies")
class TransferFormTests(unittest.TestCase):
    def test_failed_save_keeps_selection_and_both_bars_then_success_updates_both(self):
        app = AppTest.from_file(str(ROOT / "tests/fixtures/gantt_forms_app.py"))
        original = records()
        original = [{**r, "employeeId": {"e": "e1", "e2": "e2", "": ""}[r["employeeId"]],
                     "date": date(2026, 11, 16), "projectId": "p1"} for r in original]
        app.session_state["assignments"] = deepcopy(original)
        app.session_state["fixture_transfer"] = True
        app.session_state["fixture_persist"] = True
        app.session_state["fixture_headless"] = True
        app.run()
        app.toggle(key="gantt_staff_transfer_mode").set_value(True).run()
        self.assertFalse(app.exception)
        source, target = app.session_state.fixture_group_keys
        app.selectbox(key=transfer.SOURCE).set_value(source).run()
        app.selectbox(key=transfer.TARGET).set_value(target).run()
        app.multiselect(key=transfer.STAFF).set_value(["e1", "e2"]).run()
        app.checkbox(key="fail_save").set_value(True).run()
        app.button(key="gantt_transfer_save").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state.assignments, original)
        self.assertEqual(app.multiselect(key=transfer.STAFF).value, ["e1", "e2"])
        app.checkbox(key="fail_save").set_value(False).run()
        app.button(key="gantt_transfer_save").click().run()
        self.assertFalse(app.exception)
        saved = app.session_state.assignments
        self.assertEqual({r["employeeId"] for r in saved if r["startTime"] == "14:00"}, {"e1", "e2"})
        self.assertEqual([r["employeeId"] for r in saved if r["startTime"] != "14:00"], [""])
        self.assertEqual(len(app.session_state.save_calls), 2)
        self.assertEqual(app.selectbox(key=transfer.SOURCE).value, "")
