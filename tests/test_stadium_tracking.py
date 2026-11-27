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
        self.assertIn(groups["empty_yellow"], tracking.stadium_bars(groups, day, include_unstaffed=True))
        self.assertNotIn(groups["cancelled_yellow"], tracking.stadium_bars(groups, day, include_unstaffed=True))

    def test_readiness_checks_all_bars_against_the_current_roster(self):
        day = date(2026, 11, 29)
        morning = dict(HasAssignedEmployee=True, AssignmentIds=["a"])
        evening = dict(HasAssignedEmployee=True, AssignmentIds=["b"])
        unstaffed = dict(HasAssignedEmployee=False, AssignmentIds=["c"])
        roster = [
            dict(id="a", projectId="p", employeeId="e1", date=day),
            dict(id="b", projectId="p", employeeId="e2", date=day),
        ]
        recorded = {
            tracking.attendance_key(dict(assignment_id="a", project_id="p", employee_id="e1",
                                         work_date=str(day), did_work=False)),
            ("b", "p", "old_employee", str(day)),
        }
        self.assertEqual(tracking.match_readiness([], roster, recorded), (tracking.MATCH_NO_SHIFT, None))
        self.assertEqual(tracking.match_readiness([morning, unstaffed], roster, recorded),
                         (tracking.MATCH_NO_STAFF, unstaffed))
        self.assertEqual(tracking.match_readiness([morning, evening], roster, recorded),
                         (tracking.MATCH_PENDING, evening))
        recorded.add(("b", "p", "e2", str(day)))
        self.assertEqual(tracking.match_readiness([morning, evening], roster, recorded),
                         (tracking.MATCH_COMPLETE, morning))

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
