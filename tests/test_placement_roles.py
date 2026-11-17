import ast
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

import placement_roles as roles
import placement_details
from assignment_store import save_changes
from test_assignment_store import Client
from test_assignment_policy import row

try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None

ROOT = Path(__file__).resolve().parents[1]
CONTACTS = {"transfer_driver": "Νίκος", "return_driver": "Γιάννης", "supervisor": "Ελένη"}


class ContactStorageTests(unittest.TestCase):
    def test_legacy_notes_are_unchanged_when_fields_are_empty(self):
        for note in ("", "Απλή σημείωση", "  Χωρίς αλλαγές  ", "[Άδεια: Α] | [Εμπλοκή: Β]"):
            with self.subTest(note=note):
                self.assertEqual(roles.combine_notes(note, {}), note)
                self.assertEqual(roles.split_notes(note), (note, roles.normalize()))

    def test_all_fields_round_trip_with_quotes_brackets_and_backslashes(self):
        contacts = {**CONTACTS, "transfer_driver": r'Νίκος [εφεδρικός] \ "Α"'}
        note = "Κλειδιά στην είσοδο [Άδεια: Μαρία] [Εμπλοκή: Άννα]"
        saved = roles.combine_notes(note, contacts)
        self.assertEqual(roles.split_notes(saved), (note, contacts))
        self.assertEqual(roles.combine_notes(saved, contacts), saved)

    def test_replace_and_clear_do_not_accumulate_tags_or_remove_context(self):
        note = "Κλειδιά [Άδεια: Μαρία]"
        saved = roles.combine_notes(note, CONTACTS)
        updated = roles.combine_notes(saved, {"supervisor": "  Νέα επόπτρια  "})
        self.assertEqual(roles.split_notes(updated), (note, roles.normalize({"supervisor": "Νέα επόπτρια"})))
        self.assertNotIn("Οδηγός", updated)
        self.assertEqual(roles.combine_notes(updated, {}), note)

    def test_unrelated_or_incomplete_notes_remain_readable(self):
        note = "[Επόπτης χωρίς τιμή] [Οδηγός μεταφοράς: ανοιχτό"
        self.assertEqual(roles.split_notes(note), (note, roles.normalize()))

    def test_existing_atomic_api_confirms_contacts_for_every_worker(self):
        before = [row(), {**row(), "id": "b", "employeeId": "e2"}]
        proposed = [{**r, "notes": roles.combine_notes("Παρατήρηση", CONTACTS)} for r in before]
        client = Client(before)
        result = save_changes(client, before, proposed)
        self.assertEqual({r["employeeId"] for r in result["rows"]}, {"e", "e2"})
        for record in result["rows"]:
            self.assertEqual(roles.split_notes(record["notes"]), ("Παρατήρηση", CONTACTS))
        self.assertFalse(any(name == "assignment_validation_context" for name, _ in client.calls))

    def test_bulk_note_replacement_preserves_contacts_and_leave_annotation(self):
        tree = ast.parse((ROOT / "pages/8_Bulk_Gantt.py").read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build_delta")
        env = {"re": re, "placement_roles": roles, "placement_details": placement_details}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "bulk", "exec"), env)
        saved = roles.combine_notes("Παλιά [Άδεια: Μαρία]", CONTACTS)
        delta = env["build_delta"]({"notes": saved}, "Αντικατάσταση παρατήρησης", {"notes": "Νέα"})
        self.assertEqual(roles.split_notes(delta["notes"]), ("Νέα [Άδεια: Μαρία]", CONTACTS))


@unittest.skipIf(AppTest is None, "Install Streamlit UI test dependencies")
class ContactFormTests(unittest.TestCase):
    def app(self, view="desktop", add=False, records=None, clipboard=None):
        app = AppTest.from_file(str(ROOT / "tests/fixtures/gantt_forms_app.py"))
        app.session_state["fixture_headless"] = True
        app.session_state["fixture_persist"] = True
        app.session_state["fixture_show_add"] = add
        if records is not None:
            app.session_state["assignments"] = deepcopy(records)
        if clipboard is not None:
            app.session_state["gantt_placement_clipboard"] = deepcopy(clipboard)
        app.run()
        if view == "mobile":
            next(s for s in app.selectbox if s.label == "Έκδοση").set_value(view).run()
        self.assertFalse(app.exception)
        return app

    def button(self, app, label):
        return next(b for b in app.button if b.label == label)

    def text(self, app, field):
        return next(t for t in app.text_input if t.label == roles.LABELS[field])

    def select(self, app, view="desktop", index=1):
        key = "edit_bar_select_widget" if view == "desktop" else "mobile_edit_select_widget"
        element = app.selectbox(key=key)
        element.set_value(app.session_state.fixture_group_keys[index - 1]).run()
        self.assertFalse(app.exception)

    def fill(self, app, contacts=CONTACTS):
        for key, value in contacts.items():
            self.text(app, key).set_value(value)

    def test_save_reload_and_clear_contacts_for_two_workers(self):
        for view in ("desktop", "mobile"):
            with self.subTest(view=view):
                app = self.app(view)
                self.select(app, view)
                self.fill(app)
                self.button(app, "💾 Αποθήκευση").click().run()
                self.assertFalse(app.exception)
                saved = app.session_state.save_calls[-1]["new"]
                self.assertEqual({r["employeeId"] for r in saved}, {"e1", "e2"})
                for record in saved:
                    self.assertEqual(roles.split_notes(record["notes"])[1], CONTACTS)
                # Recreate the session from confirmed records, as on page refresh.
                app = self.app(view, records=app.session_state.assignments)
                self.select(app, view)
                for key, value in CONTACTS.items():
                    self.assertEqual(self.text(app, key).value, value)
                self.fill(app, roles.normalize())
                self.button(app, "💾 Αποθήκευση").click().run()
                self.assertFalse(app.exception)
                app = self.app(view, records=app.session_state.assignments)
                self.select(app, view)
                for key in CONTACTS:
                    self.assertEqual(self.text(app, key).value, "")
                self.assertEqual(len(app.session_state.assignments), 4)

    def test_failed_save_retains_contact_draft(self):
        for view in ("desktop", "mobile"):
            with self.subTest(view=view):
                app = self.app(view)
                self.select(app, view)
                app.checkbox(key="fail_save").set_value(True).run()
                self.fill(app)
                self.button(app, "💾 Αποθήκευση").click().run()
                self.assertFalse(app.exception)
                for key, value in CONTACTS.items():
                    self.assertEqual(self.text(app, key).value, value)
                self.assertTrue(all(not any(roles.split_notes(r.get("notes"))[1].values())
                                    for r in app.session_state.assignments))

    def test_switching_bar_does_not_carry_contacts_over(self):
        for view in ("desktop", "mobile"):
            with self.subTest(view=view):
                app = self.app(view)
                self.select(app, view)
                self.fill(app)
                self.button(app, "💾 Αποθήκευση").click().run()
                app = self.app(view, records=app.session_state.assignments)
                self.select(app, view, index=2)
                for key in CONTACTS:
                    self.assertEqual(self.text(app, key).value, "")

    def test_new_multiday_assignments_with_optional_contacts(self):
        for view in ("desktop", "mobile"):
            for contacts in ({}, CONTACTS):
                with self.subTest(view=view, contacts=bool(contacts)):
                    app = self.app(view, add=True)
                    self.fill(app, contacts)
                    duration = next(n for n in app.number_input if "Διάρκεια" in n.label)
                    duration.set_value(2)
                    app.multiselect[0].set_value(["e1", "e2"])
                    self.button(app, "✅ Καταχώρηση" if view == "desktop" else "Καταχώρηση").click().run()
                    self.assertFalse(app.exception)
                    records = app.session_state.save_calls[-1]["new"]
                    self.assertEqual(len(records), 4)
                    self.assertEqual(len({r["date"] for r in records}), 2)
                    for record in records:
                        self.assertEqual(roles.split_notes(record["notes"])[1], roles.normalize(contacts))
                    for key in CONTACTS:
                        self.assertEqual(self.text(app, key).value, "")

    def test_contacts_copy_between_edit_and_new_forms(self):
        app = self.app()
        self.select(app)
        self.fill(app)
        self.button(app, "📋 Αντιγραφή στοιχείων").click().run()
        self.assertEqual(app.session_state.gantt_placement_clipboard["support_roles"], CONTACTS)
        self.assertEqual(app.session_state.save_calls, [])
        app = self.app(add=True, clipboard=app.session_state.gantt_placement_clipboard)
        self.button(app, "📥 Επικόλληση όλων των στοιχείων").click().run()
        self.assertFalse(app.exception)
        for key, value in CONTACTS.items():
            self.assertEqual(self.text(app, key).value, value)
        self.text(app, "supervisor").set_value("Άλλος επόπτης")
        self.button(app, "📋 Αντιγραφή στοιχείων").click().run()
        app = self.app(clipboard=app.session_state.gantt_placement_clipboard)
        self.select(app)
        self.button(app, "📥 Επικόλληση όλων των στοιχείων").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.text(app, "supervisor").value, "Άλλος επόπτης")
        self.button(app, "💾 Αποθήκευση").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(roles.split_notes(app.session_state.save_calls[-1]["new"][0]["notes"])[1]["supervisor"], "Άλλος επόπτης")


class GroupingTests(unittest.TestCase):
    def test_different_contacts_separate_bars_and_same_contacts_group_workers(self):
        # Execute the real pure grouping function without importing UI dependencies.
        from test_regression_smoke import get_source_functions
        env = get_source_functions(ROOT / "gantt_engine.py",
            ("generate_gantt_chart", "get_project_info", "get_employee_name", "_to_time_dt", "_clean_leave_note_from_bar"),
            {"datetime": datetime, "date": date, "timedelta": timedelta, "re": re,
             "placement_roles": roles, "placement_details": placement_details})
        day = date(2026, 11, 16)
        staff = [{"id": "e", "name": "Α"}, {"id": "e2", "name": "Β"}]
        projects = [{"id": "p", "name": "Έργο"}]
        rows = [{**row(), "date": day, "notes": roles.combine_notes("Πρώτη", CONTACTS)},
                {**row(), "date": day, "id": "b", "employeeId": "e2", "notes": roles.combine_notes("Δεύτερη", CONTACTS)},
                {**row(), "date": day, "id": "c", "employeeId": "", "notes": roles.combine_notes("", {"supervisor": "Άλλος"})}]
        _, groups, _ = env["generate_gantt_chart"](day, 1, False, 0, {day: rows}, [], staff, projects,
                                                   {e["id"]: e for e in staff}, {"p": projects[0]})
        self.assertEqual(len(groups), 2)
        group = next(g for g in groups.values() if len(g["AssignmentIds"]) == 2)
        self.assertEqual(group["SupportRoles"], CONTACTS)
        self.assertEqual(group["Notes"].count("Οδηγός μεταφοράς:"), 1)
        self.assertEqual(roles.split_notes(group["Notes"])[0], "Πρώτη | Δεύτερη")
        self.assertEqual(set(group["EmployeeIds"]), {"e", "e2"})
        self.assertEqual(roles.group_suffix({}), "")
        bulk = get_source_functions(ROOT / "pages/8_Bulk_Gantt.py", ("bar_groups", "fmt", "as_date"),
                                    {"datetime": datetime, "date": date, "placement_roles": roles,
                                     "placement_details": placement_details,
                                     "utils": SimpleNamespace(safe_date_parse=lambda value: value)})
        grouped = bulk["bar_groups"](rows, projects, day, day, [], False)
        self.assertEqual({frozenset(r["id"] for r in group) for group in grouped},
                         {frozenset(["a", "b"]), frozenset(["c"])})
