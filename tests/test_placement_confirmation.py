from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import base64
import html
import unittest

from assignment_policy import assess_assignment
import placement_confirmation as confirmation
from test_assignment_policy import context, row
from test_placement_details import chart
from test_regression_smoke import get_source_functions

try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None

ROOT = Path(__file__).resolve().parents[1]


class ConfirmationTests(unittest.TestCase):
    def test_pending_groups_hold_staff_and_regular_bars_keep_their_key(self):
        normal = {**row(), "notes": "Οδηγίες"}
        pending = {**normal, "id": "b", "notes": confirmation.combine_notes("Οδηγίες", "2026-11-15")}
        crew = {**pending, "id": "c", "employeeId": "e2"}
        _, baseline, _ = chart([normal])
        _, groups, _ = chart([normal, pending, crew])
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[next(iter(baseline))], next(iter(baseline.values())))
        filtered = confirmation.chart_groups(groups, True)
        group, = filtered.values()
        self.assertEqual(group["AssignmentIds"], ["b", "c"])
        self.assertEqual(group["CustomerConfirmation"], "2026-11-15")
        self.assertEqual(group["Notes"], "Οδηγίες")
        self.assertFalse(assess_assignment(normal, [pending], [], context()["employees"], [])[0])

        env = get_source_functions(ROOT / "gantt_html.py", ("build_html_gantt", "get_local_today"), {
            "datetime": datetime, "timedelta": timedelta, "html_utils": html, "base64": base64,
            "st": SimpleNamespace(session_state=SimpleNamespace(employees=[], leaves=[], assignments_by_date={})),
            "utils": SimpleNamespace(supabase=None, get_employee_name=lambda eid: "Άννα"),
            "config": SimpleNamespace(BLUE_STACK_HEX="#0000ff"), "fetch_rules": lambda _: ([], None),
        })
        builder = env["build_html_gantt"]
        day = date(2026, 11, 16)
        baseline_html = builder(baseline, day, 1, {}, 500)
        self.assertNotIn(confirmation.PENDING_LABEL, baseline_html)
        result = builder(filtered, day, 1, {}, 500)
        self.assertIn("border: 2px dashed #92400e", result)
        self.assertIn(confirmation.PENDING_LABEL, result)
        self.assertIn("Επανεπικοινωνία 15/11/2026", result)

    def test_regular_note_round_trip_and_cancellation(self):
        normal = "  Οδηγίες [Άδεια: Μαρία]  "
        self.assertEqual(confirmation.split_notes(normal), (normal, None))
        pending = confirmation.combine_notes(normal, "")
        self.assertEqual(confirmation.split_notes(pending), (normal.strip(), ""))
        self.assertEqual(confirmation.combine_notes(pending, None), normal.strip())
        self.assertFalse(confirmation.is_pending({"notes": pending, "is_cancelled": True}))


@unittest.skipIf(AppTest is None, "Install Streamlit UI test dependencies")
class ConfirmationFormTests(unittest.TestCase):
    def test_add_reschedule_and_confirm_in_both_gantt_forms(self):
        for view in ("desktop", "mobile"):
            with self.subTest(view=view):
                app = AppTest.from_file(str(ROOT / "tests/fixtures/gantt_forms_app.py"))
                app.session_state["fixture_headless"] = True
                app.session_state["fixture_persist"] = True
                app.session_state["fixture_show_add"] = True
                app.run()
                if view == "mobile":
                    next(w for w in app.selectbox if w.label == "Έκδοση").set_value(view).run()

                prefix = "qa" if view == "desktop" else "mqa"
                app.checkbox(key=f"{prefix}_customer_0_pending").set_value(True)
                follow_up = date(2026, 11, 17)
                app.date_input(key=f"{prefix}_customer_0_follow_up").set_value(follow_up)
                app.multiselect(key=f"{prefix}_emps_0").set_value(["e1", "e2"])
                add_label = "✅ Καταχώρηση" if view == "desktop" else "Καταχώρηση"
                next(b for b in app.button if b.label == add_label).click().run()
                self.assertFalse(app.exception)
                rows = app.session_state.save_calls[-1]["new"]
                self.assertEqual(len(rows), 2)
                self.assertTrue(all(confirmation.split_notes(r["notes"])[1] == follow_up.isoformat() for r in rows))

                key = "edit_bar_select_widget" if view == "desktop" else "mobile_edit_select_widget"
                pending_key = next(k for k in app.session_state.fixture_group_keys if "_customer_pending_" in k)
                app.selectbox(key=key).set_value(pending_key).run()
                edit_date = next(w for w in reversed(app.date_input) if w.label == "Ημερομηνία")
                edit_date.set_value(date(2026, 11, 20))
                next(b for b in app.button if b.label == "💾 Αποθήκευση").click().run()
                self.assertFalse(app.exception)
                pending_rows = [r for r in app.session_state.assignments if confirmation.is_pending(r)]
                self.assertEqual({r["date"] for r in pending_rows}, {date(2026, 11, 20)})
                self.assertEqual({r["employeeId"] for r in pending_rows}, {"e1", "e2"})

                pending_key = next(k for k in app.session_state.fixture_group_keys if "_customer_pending_" in k)
                app.selectbox(key=key).set_value(pending_key).run()
                next(b for b in app.button if b.label == "✓ Επιβεβαιώθηκε από τον πελάτη").click().run()
                self.assertFalse(app.exception)
                call = app.session_state.save_calls[-1]
                self.assertEqual(call["old"], pending_rows)
                self.assertEqual(call["new"], [
                    {**r, "notes": confirmation.combine_notes(r["notes"], None)} for r in pending_rows
                ])
                self.assertFalse(any(confirmation.is_pending(r) for r in app.session_state.assignments))
