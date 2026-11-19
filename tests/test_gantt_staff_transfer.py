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
        _, groups, _ = chart([row(), {**row(), "id": "other", "employeeId": "", "startTime": "14:00"}])
        env = get_source_functions(ROOT / "gantt_html.py", ("build_html_gantt", "get_local_today"), {
            "datetime": datetime, "timedelta": timedelta, "html_utils": html, "base64": base64,
            "st": SimpleNamespace(session_state=SimpleNamespace(employees=[], leaves=[], assignments_by_date={})),
            "utils": SimpleNamespace(supabase=None, get_employee_name=lambda eid: "Άννα"),
            "config": SimpleNamespace(BLUE_STACK_HEX="#0000ff"), "fetch_rules": lambda _: ([], None),
        })
        mapping = {key: f"bar-{index}" for index, key in enumerate(groups)}
        build = env["build_html_gantt"]
        ordinary = build(groups, date(2026, 11, 16), 1, mapping, 500)
        self.assertNotIn("draggable='true'", ordinary)
        output = build(groups, date(2026, 11, 16), 1, mapping, 500, staff_drag_token="token")

        class Collector(HTMLParser):
            def __init__(self):
                super().__init__()
                self.tags = []
            def handle_starttag(self, tag, attrs):
                self.tags.append((tag, dict(attrs)))
        parsed = Collector()
        parsed.feed(output)
        handle, = [attrs for _, attrs in parsed.tags if attrs.get("class") == "gantt-transfer-worker"]
        self.assertEqual(handle["data-employee"], "e")
        self.assertEqual(handle["draggable"], "true")
        self.assertEqual(sum("data-staff-drop-target" in attrs for _, attrs in parsed.tags), 2)

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
  querySelector(){return null;},getBoundingClientRect(){return {left:0,right:600,top:0,bottom:500};},
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
'''
        run = subprocess.run([node, "-"], input=harness + script + checks, text=True, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)


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
