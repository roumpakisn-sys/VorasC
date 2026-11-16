"""Export regressions: absent worker's placeholder plus an actual replacement."""
from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import unittest

from test_regression_smoke import get_source_functions

try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None

ROOT = Path(__file__).resolve().parents[1]


def assignment(ident="empty", employee="", **changes):
    return dict({"id": ident, "employeeId": employee, "projectId": "p1",
                 "date": date(2026, 11, 16), "startTime": "09:00", "endTime": "12:00",
                 "arrivalTime": "", "notes": "", "is_cancelled": False}, **changes)


class ViberGroupingTests(unittest.TestCase):
    def setUp(self):
        self.env = get_source_functions(ROOT / "pages/3_Viber_Export.py",
            ("_project_name", "_employee_name", "_employee_viber_label", "_group_after_project_labels",
             "_format_viber_employees", "_group_viber_assignments"),
            {"utils": SimpleNamespace(
                get_project_info=lambda pid: {"name": "Προηγούμενο" if pid == "previous" else "Έργο"},
                get_employee_name=lambda eid: {"e1": "Άννα", "e2": "Ελένη"}.get(eid, "Χωρίς Προσωπικό"))})

    def groups(self, rows, context=None):
        before = deepcopy(rows)
        result = self.env["_group_viber_assignments"](rows, context if context is not None else rows)
        self.assertEqual(rows, before, "Export must not modify stored rows")
        return result

    def test_leave_placeholder_and_replacement_are_one_staffed_entry(self):
        empty = assignment(notes="[Άδεια: Μαρία]")
        replacement = assignment("replacement", "e1", notes="Κλειδιά στη ρεσεψιόν")
        for rows in ([empty, replacement], [replacement, empty]):
            group, = self.groups(rows)
            self.assertEqual(group["employees"], ["Άννα"])
            self.assertEqual(set(group["notes"]), {"[Άδεια: Μαρία]", "Κλειδιά στη ρεσεψιόν"})
            text = self.env["_format_viber_employees"](group["employees"])
            self.assertEqual(text, "*Άννα*")
            self.assertNotIn("Χωρίς Προσωπικό", text)

    def test_actual_unstaffed_shift_remains_unstaffed(self):
        group, = self.groups([assignment(notes="[Άδεια: Μαρία]")])
        self.assertEqual(self.env["_format_viber_employees"](group["employees"]), "*Χωρίς Προσωπικό*")

    def test_different_shift_or_project_or_day_does_not_hide_unstaffed_work(self):
        empty = assignment(notes="[Άδεια: Μαρία]")
        variants = [{"startTime": "14:00", "endTime": "17:00"},
                    {"endTime": "11:00"}, {"projectId": "p2"},
                    {"date": date(2026, 11, 17)}, {"arrivalTime": "08:00"},
                    {"is_general": True}]
        for change in variants:
            with self.subTest(change=change):
                groups = self.groups([empty, assignment("replacement", "e1", **change)])
                self.assertEqual(len(groups), 2)
                self.assertEqual(sum(not g["employees"] for g in groups), 1)

    def test_cancelled_replacement_does_not_cover_placeholder(self):
        groups = self.groups([assignment(notes="[Άδεια: Μαρία]"),
                              assignment("replacement", "e1", is_cancelled=True)])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["employees"], [])

    def test_null_arrival_matches_empty_and_seconds_are_normalized(self):
        groups = self.groups([assignment(arrivalTime=None, startTime="09:00:00", endTime="12:00:00"),
                              assignment("replacement", "e1", arrivalTime="")])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["employees"], ["Άννα"])

    def test_all_workers_notes_and_transport_contacts_are_retained(self):
        contacts = "[Οδηγός μεταφοράς: Νίκος] [Οδηγός επιστροφής: Γιώργος] [Επόπτης: Σοφία]"
        group, = self.groups([assignment(notes="[Άδεια: Μαρία]"),
            assignment("a", "e1", notes=contacts), assignment("b", "e2", notes=contacts),
            assignment("c", "e1", notes="Άλλη παρατήρηση")])
        self.assertEqual(group["employees"], ["Άννα", "Ελένη"])
        self.assertEqual(group["notes"].count(contacts), 1)
        self.assertIn("Άλλη παρατήρηση", group["notes"])

    def test_after_project_styling_uses_full_day_even_when_previous_is_filtered(self):
        replacement = assignment("replacement", "e1", startTime="10:00", endTime="13:00")
        previous = assignment("previous", "e1", projectId="previous", startTime="09:00", endTime="11:00")
        group, = self.groups([replacement], [previous, replacement])
        self.assertEqual(self.env["_format_viber_employees"](group["employees"]),
                         "_ΜΕΤΑ ΑΠΟ 'Προηγούμενο' >_ *Άννα*")


@unittest.skipIf(AppTest is None, "Install Streamlit UI test dependencies")
class ViberPageTests(unittest.TestCase):
    def app(self, covered=True):
        app = AppTest.from_file(str(ROOT / "tests/fixtures/viber_export_app.py"))
        app.session_state["fixture_covered"] = covered
        app.run()
        self.assertFalse(app.exception)
        return app

    def test_message_has_one_project_and_replacement_with_leave_footer(self):
        app = self.app()
        message = app.code[0].value
        self.assertEqual(message.count("🏗️ Έργο"), 1)
        self.assertEqual(message.count("👥 Προσωπικό:"), 1)
        self.assertIn("👥 Προσωπικό: *Άννα*", message)
        self.assertNotIn("Χωρίς Προσωπικό", message)
        self.assertIn("🌴 *Άδειες / Απουσίες*", message)
        self.assertIn("🔸 Μαρία (Αντικαταστάτης: Άννα)", message)
        self.assertIn("Κλειδιά στη ρεσεψιόν", message)
        self.assertEqual(len(app.session_state.assignments), 2)

    def test_project_and_leave_filters_still_control_message(self):
        app = self.app()
        app.checkbox(key="chk_proj_p1").set_value(False).run()
        self.assertFalse(app.exception)
        self.assertNotIn("🏗️", app.code[0].value)
        self.assertIn("🌴 *Άδειες / Απουσίες*", app.code[0].value)
        app.checkbox(key="chk_include_leaves").set_value(False).run()
        self.assertFalse(app.exception)
        self.assertNotIn("🌴", app.code[0].value)

    def test_uncovered_work_is_still_shown(self):
        app = self.app(covered=False)
        self.assertEqual(app.code[0].value.count("🏗️ Έργο"), 1)
        self.assertIn("👥 Προσωπικό: *Χωρίς Προσωπικό*", app.code[0].value)
