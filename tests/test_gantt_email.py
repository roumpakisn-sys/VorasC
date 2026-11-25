import base64
from datetime import date, datetime, timedelta
import html
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
import unittest

import gantt_email
from test_assignment_policy import row
from test_placement_details import chart
from test_regression_smoke import get_source_functions
import placement_roles


ROOT = Path(__file__).resolve().parents[1]
STAFF = {
    "e": {"id": "e", "name": "Δοκιμαστικό Όνομα", "id_number": "TEST-01"},
    "e2": {"id": "e2", "name": "Δεύτερο Όνομα"},
    "s": {"id": "s", "name": "Επόπτης Δοκιμής", "id_number": "TEST-02"},
}
GROUP = {
    "Project": "Δοκιμαστικό έργο", "Date": date(2026, 12, 10), "StartTime": "07:00", "EndTime": "12:00",
    "EmployeeIds": ["e", "e", "", "e2"], "SupportRoles": {"supervisor": "Επόπτης Δοκιμής"},
}


class ChartTags(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class GanttEmailTests(unittest.TestCase):
    def test_templates_use_the_saved_team_and_supervisor_once(self):
        drafts = gantt_email.drafts(GROUP, STAFF)
        schedule = drafts["Προγραμματισμός / έναρξη έργου"].text
        self.assertIn("την Πέμπτη 10/12, με ώρα έναρξης 07:00", schedule)
        self.assertIn("Ομάδα καθαριότητας:\n- Δοκιμαστικό Όνομα με ΑΔΤ: TEST-01\n- Δεύτερο Όνομα", schedule)
        self.assertEqual(schedule.count("TEST-01"), 1)
        self.assertIn("Επόπτης εργασιών: Επόπτης Δοκιμής με ΑΔΤ: TEST-02", schedule)
        self.assertIn("Την αντικατάσταση θα αναλάβουν:", drafts["Αντικατάσταση προσωπικού"].text)
        self.assertIn("07:00–12:00", drafts["Ενημέρωση πελάτη"].text)

    def test_rich_templates_bullet_and_bold_names_only(self):
        drafts = gantt_email.drafts(GROUP, STAFF)
        crew = "<ul><li><strong>Δοκιμαστικό Όνομα</strong> με ΑΔΤ: TEST-01</li><li><strong>Δεύτερο Όνομα</strong></li></ul>"
        supervisor = "<ul><li>Επόπτης εργασιών: <strong>Επόπτης Δοκιμής</strong> με ΑΔΤ: TEST-02</li></ul>"
        for label in ("Προγραμματισμός / έναρξη έργου", "Αντικατάσταση προσωπικού"):
            self.assertIn(crew, drafts[label].html)
            self.assertIn(supervisor, drafts[label].html)
            self.assertIn("\n- Επόπτης εργασιών:", drafts[label].text)
        self.assertIn(supervisor, drafts["Ενημέρωση πελάτη"].html)

    def test_missing_and_ambiguous_personnel_do_not_create_identity_numbers(self):
        group = dict(GROUP, EmployeeIds=["missing"], SupportRoles={"supervisor": "Επόπτης Δοκιμής"})
        duplicates = dict(STAFF, other={"name": "Επόπτης Δοκιμής", "id_number": "OTHER"})
        drafts = gantt_email.drafts(group, duplicates)
        schedule = drafts["Προγραμματισμός / έναρξη έργου"].text
        self.assertNotIn("Ομάδα καθαριότητας", schedule)
        self.assertIn("Επόπτης εργασιών: Επόπτης Δοκιμής", schedule)
        self.assertNotIn("ΑΔΤ", schedule)
        self.assertIn("Θα σας ενημερώσουμε για το προσωπικό", drafts["Αντικατάσταση προσωπικού"].text)

    def test_pending_and_cancelled_placements_copy_the_correct_status(self):
        pending = gantt_email.drafts(dict(GROUP, CustomerConfirmation=""), STAFF)
        self.assertTrue(all("Παρακαλούμε για την επιβεβαίωσή σας." in body.text for body in pending.values()))
        self.assertTrue(all("έχουν προγραμματιστεί" not in body.text for body in pending.values()))
        cancelled = gantt_email.drafts(dict(GROUP, is_cancelled=True), STAFF)
        self.assertEqual(list(cancelled), ["Ενημέρωση ακύρωσης"])
        self.assertIn("ακυρώθηκαν", cancelled["Ενημέρωση ακύρωσης"].text)
        self.assertNotIn("ΑΔΤ", cancelled["Ενημέρωση ακύρωσης"].text)

    def test_live_dropdown_has_both_formats_and_is_removed_from_export(self):
        notes = placement_roles.combine_notes("", {"supervisor": "Επόπτης Δοκιμής"})
        _, groups, _ = chart([{**row(), "notes": notes}])
        group = next(iter(groups.values()))
        group["Project"] = "Έργο <δοκιμή> 'α'"
        env = get_source_functions(ROOT / "gantt_html.py", ("build_html_gantt", "get_local_today"), {
            "datetime": datetime, "timedelta": timedelta, "html_utils": html, "base64": base64,
            "st": SimpleNamespace(session_state=SimpleNamespace(
                employees=list(STAFF.values()), leaves=[], assignments_by_date={},
            )),
            "utils": SimpleNamespace(supabase=None, get_employee_name=lambda eid: STAFF[eid]["name"]),
            "config": SimpleNamespace(BLUE_STACK_HEX="#0000ff"), "fetch_rules": lambda _: ([], None),
        })
        draw = env["build_html_gantt"]
        args = (groups, date(2026, 11, 16), 1, {group["Key"]: "bar-test"}, 500)
        live_html = draw(*args, email_menu=True)
        tags = ChartTags(live_html).tags
        select, = [attrs for tag, attrs in tags if tag == "select"]
        self.assertEqual(select["aria-label"], "Αντιγραφή κειμένου email")
        options = [attrs for tag, attrs in tags if "data-email-copy" in attrs]
        available = [(attrs["data-email-copy"], attrs["data-email-html"]) for attrs in options]
        self.assertEqual(available, list(gantt_email.drafts(group, STAFF).values()))
        self.assertIn("Έργο &lt;δοκιμή&gt; &#x27;α&#x27;", options[0]["data-email-html"])
        self.assertEqual([attrs["id"] for tag, attrs in tags if attrs.get("class") == "mygantt-bar"], ["bar-test"])

        for exported in (draw(*args), gantt_email.without_email_menu(live_html)):
            self.assertNotIn("data-email-copy=", exported)
            self.assertNotIn("data-email-html=", exported)
            self.assertNotIn("TEST-02", exported)
            self.assertIn("data-crew-text=", exported)
