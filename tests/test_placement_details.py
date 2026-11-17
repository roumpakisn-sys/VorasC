import base64
from datetime import date, datetime, timedelta
import html
from html.parser import HTMLParser
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

import placement_details as details
import placement_roles
from test_assignment_policy import row
import test_placement_roles as role_tests
from test_regression_smoke import get_source_functions

ROOT = Path(__file__).resolve().parents[1]
AppTest = role_tests.AppTest
SITE = {"address": 'Εγνατία 10 [2ος] & "Β"', "contact_phone": "+30 02310 123456 εσωτ. 2"}


def chart(records):
    env = get_source_functions(ROOT / "gantt_engine.py",
        ("generate_gantt_chart", "get_project_info", "get_employee_name", "_to_time_dt", "_clean_leave_note_from_bar"),
        {"datetime": datetime, "date": date, "timedelta": timedelta, "re": re,
         "placement_roles": placement_roles, "placement_details": details})
    day = date(2026, 11, 16)
    staff = [{"id": "e", "name": "Άννα"}, {"id": "e2", "name": "Ελένη"}]
    projects = [{"id": "p", "name": "Έργο"}]
    records = [{**r, "date": day} for r in records]
    return env["generate_gantt_chart"](day, 1, False, 0, {day: records}, [], staff, projects,
                                       {e["id"]: e for e in staff}, {"p": projects[0]})


class DetailStorageTests(unittest.TestCase):
    def test_round_trip_and_clear_leave_notes_and_roles_intact(self):
        note = placement_roles.combine_notes("Κλειδιά [Άδεια: Μαρία]", {"supervisor": "Σοφία"})
        saved = details.combine_notes(note, SITE)
        self.assertEqual(details.split_notes(saved), (note, SITE))
        self.assertEqual(details.combine_notes(saved, SITE), saved)
        self.assertEqual(details.combine_notes(saved, {}), note)
        self.assertEqual(placement_roles.split_notes(saved)[1]["supervisor"], "Σοφία")

    def test_empty_and_partial_fields_preserve_legacy_notes_and_phone_text(self):
        note = "  Αρχικές παρατηρήσεις  "
        self.assertEqual(details.combine_notes(note, {}), note)
        self.assertEqual(details.project_label("Έργο", {}), "Έργο")
        self.assertEqual(details.group_suffix({}), "")
        for value in (SITE, {"address": SITE["address"]}, {"contact_phone": SITE["contact_phone"]}):
            with self.subTest(value=value):
                self.assertEqual(details.split_notes(details.combine_notes("", value))[1], details.normalize(value))

    def test_bulk_note_replacement_keeps_address_phone_and_supervisor(self):
        env = get_source_functions(ROOT / "pages/8_Bulk_Gantt.py", ("build_delta",),
                                   {"re": re, "placement_roles": placement_roles, "placement_details": details})
        note = details.combine_notes(placement_roles.combine_notes("Παλιά [Άδεια: Μαρία]", {"supervisor": "Σοφία"}), SITE)
        result = env["build_delta"]({"notes": note}, "Αντικατάσταση παρατήρησης", {"notes": "Νέα"})["notes"]
        self.assertEqual(details.split_notes(result)[1], SITE)
        free, contacts = placement_roles.split_notes(details.split_notes(result)[0])
        self.assertEqual(free, "Νέα [Άδεια: Μαρία]")
        self.assertEqual(contacts["supervisor"], "Σοφία")

    def test_group_title_has_details_once_and_different_sites_stay_separate(self):
        _, groups, exported = chart([
            {**row(), "notes": details.combine_notes("Κλειδιά", SITE)},
            {**row(), "id": "b", "employeeId": "e2", "notes": details.combine_notes("Κλειδιά", SITE)},
            {**row(), "id": "c", "notes": details.combine_notes("", {"address": "Άλλη διεύθυνση"})},
        ])
        self.assertEqual(len(groups), 2)
        group = next(g for g in groups.values() if len(g["AssignmentIds"]) == 2)
        self.assertEqual(group["Project"], "Έργο")
        self.assertEqual(group["ProjectDetails"], SITE)
        self.assertEqual(group["ProjectDisplay"], details.project_label("Έργο", SITE))
        self.assertEqual(group["Notes"], "Κλειδιά")
        self.assertIn(group["ProjectDisplay"], [r["Έργο"] for r in exported])
        bulk = get_source_functions(ROOT / "pages/8_Bulk_Gantt.py", ("bar_groups", "as_date", "fmt"),
            {"utils": SimpleNamespace(safe_date_parse=lambda value: value),
             "placement_roles": placement_roles, "placement_details": details})
        day = date(2026, 11, 16)
        records = [{**row(), "date": day, "notes": details.combine_notes("", SITE)},
                   {**row(), "id": "b", "date": day, "notes": details.combine_notes("", {"address": "Άλλη"})}]
        self.assertEqual(len(bulk["bar_groups"](records, [{"id": "p"}], day, day, [], False)), 2)

    def test_html_shows_details_in_title_and_full_copy_as_safe_text(self):
        site = {**SITE, "address": '<img src=x onerror="alert(1)"> & Εγνατία 10'}
        _, groups, _ = chart([{**row(), "notes": details.combine_notes("", site)}])
        env = get_source_functions(ROOT / "gantt_html.py", ("build_html_gantt", "get_local_today"), {
            "datetime": datetime, "timedelta": timedelta, "html_utils": html, "base64": base64,
            "st": SimpleNamespace(session_state=SimpleNamespace(employees=[], leaves=[], assignments_by_date={})),
            "utils": SimpleNamespace(supabase=None, get_employee_name=lambda eid: "Άννα"),
            "config": SimpleNamespace(BLUE_STACK_HEX="#0000ff"), "fetch_rules": lambda _: ([], None),
        })
        output = env["build_html_gantt"](groups, date(2026, 11, 16), 1, {k: "bar-a" for k in groups}, 500)
        class Collector(HTMLParser):
            def __init__(self):
                super().__init__()
                self.tags = []
            def handle_starttag(self, tag, attrs):
                self.tags.append((tag, dict(attrs)))
        parsed = Collector()
        parsed.feed(output)
        title = next(attrs["title"] for tag, attrs in parsed.tags if attrs.get("class") == "mygantt-bar")
        full_copy = next(attrs["data-full-content"] for tag, attrs in parsed.tags if "data-full-content" in attrs)
        self.assertIn(details.project_label("Έργο", site).upper(), title)
        self.assertEqual(title, full_copy)
        # The existing chart has its own hidden script-bootstrap image. User
        # text must not create an additional image with the supplied handler.
        self.assertFalse(any("alert(1)" in attrs.get("onerror", "").lower()
                             for tag, attrs in parsed.tags))
        self.assertIn(html.escape(site["address"].upper()), output)
        self.assertEqual(next(attrs["data-project"] for tag, attrs in parsed.tags if "data-project" in attrs), "Έργο")


@unittest.skipIf(AppTest is None, "Install Streamlit UI test dependencies")
class DetailFormTests(unittest.TestCase):
    app = role_tests.ContactFormTests.app
    select = role_tests.ContactFormTests.select
    button = role_tests.ContactFormTests.button

    def field(self, app, key):
        return next(t for t in app.text_input if t.label == details.LABELS[key])

    def fill(self, app, values=SITE):
        for key, value in values.items():
            self.field(app, key).set_value(value)

    def test_only_details_change_saves_for_all_workers_and_reload_clear_work(self):
        for view in ("desktop", "mobile"):
            with self.subTest(view=view):
                app = self.app(view)
                self.select(app, view)
                self.fill(app)
                self.button(app, "💾 Αποθήκευση").click().run()
                self.assertFalse(app.exception)
                records = app.session_state.save_calls[-1]["new"]
                self.assertEqual({r["employeeId"] for r in records}, {"e1", "e2"})
                self.assertTrue(all(details.split_notes(r["notes"])[1] == SITE for r in records))
                app = self.app(view, records=app.session_state.assignments)
                self.select(app, view, index=2)
                self.assertTrue(all(self.field(app, key).value == "" for key in SITE))
                self.select(app, view)
                for key, value in SITE.items():
                    self.assertEqual(self.field(app, key).value, value)
                self.fill(app, details.normalize())
                self.button(app, "💾 Αποθήκευση").click().run()
                self.assertFalse(app.exception)
                self.assertTrue(all(not any(details.split_notes(r["notes"])[1].values()) for r in app.session_state.assignments))
                self.assertEqual(len(app.session_state.assignments), 4)

    def test_new_multiday_and_optional_empty_fields(self):
        for view in ("desktop", "mobile"):
            for values in ({}, SITE):
                with self.subTest(view=view, filled=bool(values)):
                    app = self.app(view, add=True)
                    self.fill(app, values)
                    next(n for n in app.number_input if "Διάρκεια" in n.label).set_value(2)
                    app.multiselect[0].set_value(["e1", "e2"])
                    self.button(app, "✅ Καταχώρηση" if view == "desktop" else "Καταχώρηση").click().run()
                    self.assertFalse(app.exception)
                    records = app.session_state.save_calls[-1]["new"]
                    self.assertEqual(len(records), 4)
                    self.assertEqual(len({r["date"] for r in records}), 2)
                    self.assertTrue(all(details.split_notes(r["notes"])[1] == details.normalize(values) for r in records))
                    self.assertTrue(all(self.field(app, key).value == "" for key in SITE))

    def test_failed_save_retains_details_without_changing_records(self):
        for view in ("desktop", "mobile"):
            with self.subTest(view=view):
                app = self.app(view)
                self.select(app, view)
                app.checkbox(key="fail_save").set_value(True).run()
                self.fill(app)
                self.button(app, "💾 Αποθήκευση").click().run()
                self.assertFalse(app.exception)
                for key, value in SITE.items():
                    self.assertEqual(self.field(app, key).value, value)
                self.assertTrue(all(not any(details.split_notes(r["notes"])[1].values()) for r in app.session_state.assignments))

    def test_clipboard_moves_details_between_both_forms(self):
        app = self.app()
        self.select(app)
        self.fill(app)
        self.button(app, "📋 Αντιγραφή στοιχείων").click().run()
        self.assertEqual(app.session_state.gantt_placement_clipboard["project_details"], SITE)
        app = self.app(add=True, clipboard=app.session_state.gantt_placement_clipboard)
        self.button(app, "📥 Επικόλληση όλων των στοιχείων").click().run()
        for key, value in SITE.items():
            self.assertEqual(self.field(app, key).value, value)
        self.field(app, "contact_phone").set_value("0030 2310 999999")
        self.button(app, "📋 Αντιγραφή στοιχείων").click().run()
        app = self.app(clipboard=app.session_state.gantt_placement_clipboard)
        self.select(app)
        self.button(app, "📥 Επικόλληση όλων των στοιχείων").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.field(app, "contact_phone").value, "0030 2310 999999")
        self.button(app, "💾 Αποθήκευση").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(details.split_notes(app.session_state.save_calls[-1]["new"][0]["notes"])[1]["contact_phone"], "0030 2310 999999")
