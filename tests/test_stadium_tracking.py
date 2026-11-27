from datetime import date, time
import unittest

import stadium_tracking as tracking


class StadiumTrackingTests(unittest.TestCase):
    def test_only_yellow_bars_with_stadium_words_match_on_selected_day(self):
        day = date(2026, 11, 29)
        base = dict(Date=day, Project="ΑΡΗΣ ΓΗΠΕΔΟ", StartTime="08:00", EndTime="12:00",
                    is_cancelled=False, HasAssignedEmployee=True, AssignmentIds=["a", "b"],
                    ColorHex=" #F1C232 ", ColorName="Προεπιλογή")
        groups = {
            "named": base,
            "stadium": dict(base, Project="Γήπεδο_Κερκίδες", StartTime="07:00", AssignmentIds=["g"]),
            "aris": dict(base, Project="Άρης · Καθαρισμός", StartTime="14:00", AssignmentIds=["r"]),
            "match": dict(base, Project="Καθαρισμός κερκίδων", ProjectDisplay="Καθαρισμός κερκίδων (Αγώνας)",
                          StartTime="19:00", AssignmentIds=["m"]),
            "unrelated_yellow": dict(base, Project="Καθαρισμός γραφείων"),
            "partial_word": dict(base, Project="ΧΑΡΗΣ"),
            "empty_yellow": dict(base, HasAssignedEmployee=False),
            "cancelled_yellow": dict(base, is_cancelled=True),
            "stadium_blue": dict(base, ColorHex="#4a86e8"),
            "earlier_yellow": dict(base, Date=date(2026, 11, 28)),
        }
        bars = tracking.stadium_bars(groups, day)
        self.assertEqual([b["AssignmentIds"] for b in bars], [["a", "b"], ["g"], ["r"], ["m"]])

    def test_attendance_defaults_to_bar_unless_actual_times_were_saved(self):
        assignment = dict(startTime="23:30", endTime="02:00")
        self.assertEqual(tracking.attendance_time_defaults(assignment, {}), (time(23, 30), time(2)))
        self.assertEqual(tracking.attendance_time_defaults(
            assignment, dict(did_work=False, arrival=None, departure=None),
        ), (time(23, 30), time(2)))
        self.assertEqual(tracking.attendance_time_defaults(
            assignment, dict(arrival="23:45:00", departure="01:30:00"),
        ), (time(23, 45), time(1, 30)))

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
