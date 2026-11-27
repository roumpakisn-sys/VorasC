from datetime import date
import unittest

import truework_report as report
from gantt_helpers import record_assignment_absence


class TrueworkReportTests(unittest.TestCase):
    def setUp(self):
        self.day = date(2026, 11, 28)
        self.slot = dict(date=self.day, projectId="p", startTime="09:00", endTime="12:00")

    def test_month_and_effective_color(self):
        yellow = dict(self.slot, id="yellow", colorHex="#F1C232")
        inherited = dict(self.slot, id="inherited")
        blue_override = dict(self.slot, id="blue", colorHex="#4a86e8")
        outside_month = dict(yellow, id="outside", date=date(2026, 12, 1))
        assignments = {self.day: [yellow, inherited, blue_override], outside_month["date"]: [outside_month]}
        projects = {"p": {"color": "#f1c232"}}
        self.assertEqual(report.month_assignments(assignments, projects, date(2026, 11, 1), date(2026, 12, 1)),
                         [yellow, inherited])

    def test_a_staffed_shift_keeps_an_open_position_until_it_is_filled(self):
        note = record_assignment_absence("Σημείωση", "Μαρία")
        self.assertEqual(note, record_assignment_absence(note, "Μαρία"))
        staffed = dict(self.slot, id="a", employeeId="e1")
        vacancy = dict(self.slot, id="b", employeeId="", notes=note)
        people = {"e1": "Ελένη", "e2": "Νίκος"}
        [shift] = report.month_shifts([staffed, vacancy], people, [])
        self.assertEqual((shift.status, shift.vacancies, shift.absences), (report.PARTIAL, 1, {"Μαρία"}))
        [filled] = report.month_shifts([staffed, dict(vacancy, employeeId="e2")], people, [])
        self.assertEqual((filled.status, filled.absences, filled.replacements), (report.COVERED, {"Μαρία"}, {"Νίκος"}))

    def test_attendance_and_leave_are_linked_to_the_original_slot(self):
        assignment = dict(self.slot, id="a", employeeId="e")
        record = dict(assignment_id="a", project_id="p", employee_id="e", employee_name="Μαρία",
                      work_date=str(self.day), did_work=False)
        people = {"e": "Μαρία", "cover": "Ελένη"}
        leave = dict(employeeId="e", startDate=self.day, endDate=self.day)
        [absent] = report.month_shifts([assignment], people, [], [record])
        self.assertEqual((absent.status, absent.absences), (report.UNSTAFFED, {"Μαρία"}))
        [scheduled_on_leave] = report.month_shifts([assignment], people, [leave])
        self.assertEqual(scheduled_on_leave.status, report.UNSTAFFED)
        [present] = report.month_shifts([assignment], people, [leave], [dict(record, did_work=True)])
        self.assertEqual((present.status, present.absences), (report.COVERED, set()))
        [covered] = report.month_shifts([dict(assignment, employeeId="cover")], people, [], [record])
        self.assertEqual((covered.status, covered.absences, covered.replacements),
                         (report.COVERED, {"Μαρία"}, {"Ελένη"}))
        [unrelated] = report.month_shifts([dict(assignment, projectId="other")], people, [], [record])
        self.assertEqual((unrelated.status, unrelated.absences), (report.COVERED, set()))

    def test_cancelled_and_pending_shifts_are_separate_from_vacancies(self):
        rows = [
            dict(self.slot, id="a", employeeId="", is_cancelled=True, cancel_reason="Κλειστό"),
            dict(self.slot, id="b", employeeId="", notes="[Επιβεβαίωση πελάτη: αναμονή]"),
        ]
        self.assertCountEqual([shift.status for shift in report.month_shifts(rows, {}, [])],
                              [report.CANCELLED, report.PENDING])
