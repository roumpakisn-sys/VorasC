from datetime import date, time
import unittest

import stadium_tracking as tracking


class StadiumTrackingTests(unittest.TestCase):
    def test_stadium_titles_and_yellow_bars_match_on_selected_day(self):
        day = date(2026, 11, 29)
        base = dict(Date=day, Project="ΑΡΗΣ ΓΗΠΕΔΟ", StartTime="08:00", EndTime="12:00",
                    is_cancelled=False, HasAssignedEmployee=True, AssignmentIds=["a", "b"])
        yellow = dict(base, Project="Καθαρισμός κερκίδων", ColorHex=" #F1C232 ",
                      ColorName="Προεπιλογή", StartTime="07:00", AssignmentIds=["y"])
        groups = {
            "early": base,
            "match": dict(base, Project="Άρης Γήπεδο Αγώνας", StartTime="19:00", AssignmentIds=["m"]),
            "different_yellow": yellow,
            "empty_yellow": dict(yellow, HasAssignedEmployee=False),
            "cancelled_yellow": dict(yellow, is_cancelled=True),
            "different_blue": dict(yellow, ColorHex="#4a86e8"),
            "earlier_yellow": dict(yellow, Date=date(2026, 11, 28)),
        }
        bars = tracking.stadium_bars(groups, day)
        self.assertEqual([b["AssignmentIds"] for b in bars], [["a", "b"], ["m"], ["y"]])

    def test_night_shift_and_actual_hours_keep_the_assignment_id(self):
        assignment = dict(id="a", date=date(2026, 11, 29), notes="Σημείωση [Πραγματικές ώρες: 2]")
        entry = tracking.attendance_payload(
            assignment, "Εργαζόμενος", time(23, 30), time(2, 0), 30, "Χώρος", "", {},
        )
        self.assertEqual(entry["expected"]["id"], "a")
        self.assertEqual(entry["assignment_notes"], "Σημείωση [Πραγματικές ώρες: 2]")
        with self.assertRaises(ValueError):
            tracking.worked_minutes(time(23, 30), time(2, 0), 151)

    def test_day_summary_counts_worker_once_and_marks_match_date(self):
        day = date(2026, 11, 29)
        attendance = [
            dict(work_date=str(day), employee_id="e", employee_name="Εργαζόμενος", worked_minutes=90),
            dict(work_date=str(day), employee_id="e", employee_name="Εργαζόμενος", worked_minutes=120),
        ]
        tasks = [dict(work_date=str(day), status=status) for status in tracking.STATUSES]
        summary = tracking.summary(attendance, tasks, [{"match_date": str(day)}], day)
        self.assertEqual(summary["selected"], [("Εργαζόμενος", 210)])
        self.assertEqual(summary["workers"], [("Εργαζόμενος", 1, 210)])
        self.assertIn((day, True, 1, 210, 1), summary["daily"])
        self.assertEqual(tracking.match_date("29/11/2026 7:00:00 μμ"), day)
