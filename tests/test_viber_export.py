"""Export regressions: absent worker's placeholder plus an actual replacement."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

import placement_roles
import placement_details
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
             "_format_viber_employees", "_clean_viber_notes", "_format_viber_contacts",
             "_group_viber_assignments"),
            {"re": re, "placement_roles": placement_roles, "placement_details": placement_details,
             "utils": SimpleNamespace(
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
            self.assertEqual(group["notes"], ["Κλειδιά στη ρεσεψιόν"])
            text = self.env["_format_viber_employees"](group["employees"])
            self.assertEqual(text, "*Άννα*")
            self.assertNotIn("Χωρίς Προσωπικό", text)

    def test_actual_unstaffed_shift_remains_unstaffed(self):
        group, = self.groups([assignment(notes="[Άδεια: Μαρία]")])
        self.assertEqual(self.env["_format_viber_employees"](group["employees"]), "*Χωρίς Προσωπικό*")
        self.assertEqual(group["notes"], [])

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
        self.assertEqual(group["notes"], ["Άλλη παρατήρηση"])
        self.assertEqual(group["support_roles"], {
            "transfer_driver": ["Νίκος"], "return_driver": ["Γιώργος"], "supervisor": ["Σοφία"]})
        self.assertEqual(self.env["_format_viber_contacts"](group["support_roles"]), [
            "🚐 *Οδηγός μεταφοράς: Νίκος*", "🚐 *Οδηγός επιστροφής: Γιώργος*", "👤 *Επόπτης: Σοφία*"])

    def test_leave_cleanup_preserves_real_notes_and_other_annotations(self):
        raw = "[Άδεια: Μαρία] | Κλειδιά [Άδεια: Νίκος] στην είσοδο | [Εμπλοκή: Άννα] |"
        self.assertEqual(self.env["_clean_viber_notes"](raw),
                         "Κλειδιά στην είσοδο | [Εμπλοκή: Άννα]")
        self.assertEqual(self.env["_clean_viber_notes"]("[Άδεια: Μαρία] | [Άδεια: Νίκος] |"), "")

    def test_distinct_contact_names_survive_grouping_without_duplicates(self):
        contacts = {"transfer_driver": "Νίκος [εφεδρικός]", "supervisor": "Σοφία"}
        group, = self.groups([
            assignment("a", "e1", notes=placement_roles.combine_notes("", contacts)),
            assignment("b", "e2", notes=placement_roles.combine_notes("", {**contacts, "transfer_driver": "Πέτρος"})),
        ])
        self.assertEqual(self.env["_format_viber_contacts"](group["support_roles"]), [
            "🚐 *Οδηγός μεταφοράς: Νίκος [εφεδρικός], Πέτρος*", "👤 *Επόπτης: Σοφία*"])
        self.assertEqual(group["notes"], [])

    def test_after_project_styling_uses_full_day_even_when_previous_is_filtered(self):
        replacement = assignment("replacement", "e1", startTime="10:00", endTime="13:00")
        previous = assignment("previous", "e1", projectId="previous", startTime="09:00", endTime="11:00")
        group, = self.groups([replacement], [previous, replacement])
        self.assertEqual(self.env["_format_viber_employees"](group["employees"]),
                         "_ΜΕΤΑ ΑΠΟ 'Προηγούμενο' >_ *Άννα*")

    def test_blank_leave_placeholder_joins_replacement_with_site_details(self):
        site = {"address": "Εγνατία 10", "contact_phone": "+30 2310 123456"}
        replacement = assignment("replacement", "e1", notes=placement_details.combine_notes("Κλειδιά", site))
        empty = assignment(notes="[Άδεια: Μαρία]")
        for records in ([empty, replacement], [replacement, empty]):
            group, = self.groups(records)
            self.assertEqual(group["project_details"], site)
            self.assertEqual(group["employees"], ["Άννα"])
            self.assertEqual(group["notes"], ["Κλειδιά"])

    def test_distinct_sites_are_not_combined_and_ambiguous_vacancy_is_retained(self):
        rows = [assignment("a", "e1", notes=placement_details.combine_notes("", {"address": "Εγνατία 10"})),
                assignment("b", "e2", notes=placement_details.combine_notes("", {"address": "Εγνατία 20"}))]
        groups = self.groups(rows)
        self.assertEqual(len(groups), 2)
        self.assertEqual({g["project_details"]["address"] for g in groups}, {"Εγνατία 10", "Εγνατία 20"})
        groups = self.groups([assignment(notes="[Άδεια: Μαρία]"), *rows])
        self.assertEqual(len(groups), 3)
        self.assertEqual(sum(not g["employees"] for g in groups), 1)


@unittest.skipIf(AppTest is None, "Install Streamlit UI test dependencies")
class ViberPageTests(unittest.TestCase):
    def app(self, covered=True, contacts=None, notes=None, duplicate=False, site=None):
        app = AppTest.from_file(str(ROOT / "tests/fixtures/viber_export_app.py"))
        app.session_state["fixture_covered"] = covered
        app.session_state["fixture_contacts"] = contacts or {}
        app.session_state["fixture_project_details"] = site or {}
        app.session_state["fixture_duplicate_worker"] = duplicate
        if notes is not None:
            app.session_state["fixture_notes"] = notes
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
        self.assertNotIn("Μαρία", message.split("🌴 *Άδειες / Απουσίες*")[0])
        self.assertIn("[Άδεια: Μαρία]", app.session_state.assignments[0]["notes"])
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
        self.assertNotIn("📝 Σημείωση:", app.code[0].value)

    def test_contacts_are_bold_separate_lines_and_not_notes(self):
        contacts = {"transfer_driver": "Νίκος", "return_driver": "Γιώργος", "supervisor": "Σοφία"}
        app = self.app(contacts=contacts, notes="", duplicate=True)
        message = app.code[0].value
        self.assertEqual(message.count("🏗️ Έργο"), 1)
        for line in ["🚐 *Οδηγός μεταφοράς: Νίκος*", "🚐 *Οδηγός επιστροφής: Γιώργος*", "👤 *Επόπτης: Σοφία*"]:
            self.assertEqual(message.count(line), 1)
            self.assertIn(line, message.splitlines())
        self.assertNotIn("📝 Σημείωση:", message)
        self.assertNotIn("[Οδηγός", message)
        self.assertNotIn("[Επόπτης:", message)
        self.assertNotIn("Μαρία", message.split("🌴 *Άδειες / Απουσίες*")[0])
        self.assertIn("Άννα", message)
        self.assertIn("Ελένη", message)

    def test_only_filled_roles_are_shown_and_real_notes_stay_notes(self):
        app = self.app(contacts={"supervisor": "Σοφία"})
        message = app.code[0].value
        self.assertIn("👤 *Επόπτης: Σοφία*\n", message)
        self.assertNotIn("Οδηγός", message)
        self.assertIn("📝 Σημείωση: Κλειδιά στη ρεσεψιόν\n", message)
        app.checkbox(key="chk_include_leaves").set_value(False).run()
        self.assertNotIn("Μαρία", app.code[0].value)

    def test_address_and_phone_appear_beside_project_only_once(self):
        site = {"address": "Εγνατία 10", "contact_phone": "0030 2310 123456"}
        app = self.app(site=site, contacts={"supervisor": "Σοφία"}, notes="Κλειδιά", duplicate=True)
        message = app.code[0].value
        header = next(line for line in message.splitlines() if "🏗️" in line)
        self.assertIn("🏗️ Έργο | 📍 Εγνατία 10 | ☎️ Τηλ. υπευθύνου: 0030 2310 123456", header)
        self.assertEqual(message.count("🏗️"), 1)
        self.assertEqual(message.count("Εγνατία 10"), 1)
        self.assertEqual(message.count("0030 2310 123456"), 1)
        self.assertIn("👤 *Επόπτης: Σοφία*", message)
        self.assertIn("📝 Σημείωση: Κλειδιά\n", message)
        self.assertNotIn("Χωρίς Προσωπικό", message)
        self.assertNotIn("Μαρία", message.split("🌴 *Άδειες / Απουσίες*")[0])

    def test_partial_site_details_do_not_emit_empty_labels(self):
        for site in ({"address": "Εγνατία 10"}, {"contact_phone": "02310123456"}, {}):
            with self.subTest(site=site):
                app = self.app(site=site, notes="")
                header = next(line for line in app.code[0].value.splitlines() if "🏗️" in line)
                self.assertEqual("📍" in header, bool(site.get("address")))
                self.assertEqual("Τηλ. υπευθύνου:" in header, bool(site.get("contact_phone")))
                self.assertNotIn("📝 Σημείωση:", app.code[0].value)
