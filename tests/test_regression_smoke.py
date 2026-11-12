"""Read-only regression smoke tests for STAFF.PRO, no Supabase credentials or writes."""
import ast
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import sys

import availability_rules as availability
import replacement_engine
import scheduling


def shift(day=date(2026, 11, 16), start="09:00", end="13:00", emp="emp1", project="p1", ident="s1"):
    return {
        "id": ident, "employeeId": emp, "projectId": project, "date": day,
        "startTime": start, "endTime": end,
    }


def rule(day_index=0, kind="unavailable", start=None, end=None):
    return {
        "employee_id": "emp1", "scope": "weekday", "weekday": day_index,
        "kind": kind, "start_time": start, "end_time": end, "is_active": True,
    }


class AvailabilityTests(unittest.TestCase):
    def test_weekly_whole_day_exclusion(self):
        self.assertFalse(availability.assess_rules("emp1", shift(), [rule()])[0])
        self.assertTrue(availability.assess_rules("emp2", shift(emp="emp2"), [rule()])[0])
        self.assertTrue(availability.assess_rules("emp1", shift(day=date(2026, 11, 17)), [rule()])[0])

    def test_partial_time_exclusion(self):
        r = rule(start="10:00", end="12:00")
        self.assertFalse(availability.assess_rules("emp1", shift(), [r])[0])
        self.assertTrue(availability.assess_rules("emp1", shift(start="12:00", end="16:00"), [r])[0])

    def test_only_available_interval(self):
        r = rule(kind="only_available", start="08:00", end="14:00")
        self.assertTrue(availability.assess_rules("emp1", shift(), [r])[0])
        self.assertFalse(availability.assess_rules("emp1", shift(start="13:00", end="15:00"), [r])[0])

    def test_preference_is_advisory(self):
        r = rule(kind="preferred", start="08:00", end="14:00")
        allowed, reason, bonus = availability.assess_rules("emp1", shift(), [r])
        self.assertTrue(allowed)
        self.assertEqual(bonus, 8)

    def test_date_specific_rule(self):
        r = {
            "employee_id": "emp1", "scope": "date", "rule_date": "2026-11-18",
            "kind": "unavailable", "start_time": None, "end_time": None,
        }
        self.assertFalse(availability.assess_rules("emp1", shift(day=date(2026, 11, 18)), [r])[0])
        self.assertTrue(availability.assess_rules("emp1", shift(day=date(2026, 11, 19)), [r])[0])

    def test_overnight_respects_next_day(self):
        r = rule(day_index=1, start="00:00", end="03:00")
        self.assertFalse(availability.assess_rules("emp1", shift(start="22:00", end="02:00"), [r])[0])

    def test_disabled_rules_do_not_block(self):
        r = rule()
        r["is_active"] = False
        self.assertTrue(availability.assess_rules("emp1", shift(), [r])[0])

    def test_missing_rules_does_not_imply_restriction(self):
        self.assertTrue(availability.assess_rules("emp1", shift(), [])[0])


class ReplacementTests(unittest.TestCase):
    employee = {"id": "emp1", "name": "Δοκιμαστικός", "status": "Ενεργός"}

    def test_candidate_without_conflicts(self):
        report = replacement_engine.candidate_assessment(
            self.employee, shift(emp=""), [], [], availability=[],
            today=date(2026, 11, 12),
        )
        self.assertTrue(report["eligible"])

    def test_candidate_excluded_by_availability(self):
        report = replacement_engine.candidate_assessment(
            self.employee, shift(emp=""), [], [], availability=[rule()],
            today=date(2026, 11, 12),
        )
        self.assertFalse(report["eligible"])

    def test_candidate_excluded_by_leave(self):
        leaves = [{"employeeId": "emp1", "startDate": "2026-11-16", "endDate": "2026-11-16"}]
        report = replacement_engine.candidate_assessment(self.employee, shift(emp=""), [], leaves)
        self.assertFalse(report["eligible"])

    def test_candidate_excluded_by_overlapping_shift(self):
        report = replacement_engine.candidate_assessment(
            self.employee, shift(emp=""), [shift(start="11:00", end="15:00", ident="s2")], [],
        )
        self.assertFalse(report["eligible"])

    def test_ranking_prefers_declared_preference(self):
        emps = [self.employee, {"id": "emp2", "name": "Άλλος", "status": "Ενεργός"}]
        eligible, blocked = replacement_engine.rank_candidates(
            shift(emp=""), emps, [], [],
            availability=[rule(kind="preferred", start="08:00", end="14:00")],
        )
        self.assertEqual(eligible[0]["employee_id"], "emp1")


class SchedulingTests(unittest.TestCase):
    def test_leave(self):
        self.assertTrue(scheduling.is_on_leave(
            "emp1", date(2026, 11, 16),
            {"emp1": [{"startDate": date(2026, 11, 15), "endDate": date(2026, 11, 17)}]},
        ))

    def test_conflict_original_semantics(self):
        other = shift(start="09:00", end="12:00")
        self.assertEqual(scheduling.check_and_resolve_conflict(
            "emp1", "10:00", "12:00", [other]
        )[2], True)
        self.assertEqual(scheduling.check_and_resolve_conflict(
            "emp1", "10:00", "13:00", [other]
        )[3], "Allowed Overlap")


def get_source_functions(path, function_names, globals_dict):
    """Execute only pure source function definitions, not Streamlit page side effects."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    selected = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in function_names]
    assert {n.name for n in selected} == set(function_names)
    body = ast.Module(body=selected, type_ignores=[])
    exec(compile(body, str(path), "exec"), globals_dict)
    return globals_dict


class ExportAndGanttTests(unittest.TestCase):
    def test_viber_styling(self):
        env = get_source_functions(
            "pages/3_Viber_Export.py",
            ("_group_after_project_labels", "_format_viber_employees"), {},
        )
        text = env["_format_viber_employees"]([
            "ΜΕΤΑ ΑΠΟ 'ΕΡΓΟ' > ΜΑΡΙΑ", "ΜΕΤΑ ΑΠΟ 'ΕΡΓΟ' > ΓΙΩΡΓΟΣ", "ΑΝΝΑ",
        ])
        self.assertIn("_ΜΕΤΑ ΑΠΟ 'ΕΡΓΟ' >_", text)
        self.assertIn("*ΜΑΡΙΑ, ΓΙΩΡΓΟΣ", text)
        self.assertIn("*ΑΝΝΑ", text)

    def test_excel_day_rows(self):
        # Avoid Streamlit imports; call real pure functions extracted from source.
        import types
        prior = sys.modules.get("utils")
        fake = types.ModuleType("utils")
        fake.safe_date_parse = lambda d: date.fromisoformat(d[:10]) if isinstance(d, str) else d
        sys.modules["utils"] = fake
        try:
            env = get_source_functions(
                "gantt_excel_export.py",
                ("_employee_day_minutes", "build_employee_day_schedule_rows"),
                {"datetime": datetime, "date": date},
            )
            records = [shift(), shift(start="14:00", end="17:00", ident="s2")]
            summaries, details = env["build_employee_day_schedule_rows"](
                records, [{"id": "emp1", "name": "ΑΝΝΑ"}],
                [{"id": "p1", "name": "ΔΟΚΙΜΗ"}], date(2026, 11, 16),
            )
            self.assertEqual(len(summaries), 1)
            self.assertEqual(len(details), 2)
            self.assertEqual(summaries[0]["minutes"], 7 * 60)
        finally:
            if prior is None:
                sys.modules.pop("utils", None)
            else:
                sys.modules["utils"] = prior


if __name__ == "__main__":
    unittest.main()

