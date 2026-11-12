import unittest
from datetime import date

from assignment_policy import assess_assignment, needs_validation, recurring_assignment, validate_changes
from availability_rules import assess_rules, fetch_rules
from scheduling import check_and_resolve_conflict


def row(**kw):
    return dict(id='a', employeeId='e', projectId='p', date='2026-11-12', startTime='09:00', endTime='12:00', **kw)


def context(**kw):
    return {'assignments': [], 'leaves': [], 'employees': [{'id': 'e', 'name': 'Νίκος', 'status': 'Ενεργός'}], 'rules': [], **kw}


class PolicyTests(unittest.TestCase):
    def assess(self, r=None, **kw):
        c = context(**kw)
        return assess_assignment(r or row(), c['assignments'], c['leaves'], c['employees'], c['rules'])

    def test_available(self):
        self.assertTrue(self.assess()[0])

    def test_unavailable_date(self):
        rule = dict(employee_id='e', scope='date', rule_date='2026-11-12', kind='unavailable')
        self.assertFalse(self.assess(rules=[rule])[0])

    def test_weekday(self):
        rule = dict(employee_id='e', scope='weekday', weekday=3, kind='unavailable')
        self.assertFalse(self.assess(rules=[rule])[0])

    def test_inactive_rule(self):
        rule = dict(employee_id='e', scope='weekday', weekday=3, kind='unavailable', is_active=False)
        self.assertTrue(self.assess(rules=[rule])[0])

    def test_preference_never_blocks(self):
        rule = dict(employee_id='e', scope='weekday', weekday=3, kind='preferred', start_time='15:00', end_time='17:00')
        self.assertTrue(self.assess(rules=[rule])[0])

    def test_allowed_windows_union(self):
        rules = [dict(employee_id='e', scope='weekday', weekday=3, kind='only_available', start_time=a, end_time=b)
                 for a, b in [('09:00', '10:00'), ('10:00', '12:00')]]
        self.assertTrue(self.assess(rules=rules)[0])
        rules[1]['start_time'] = '10:01'
        self.assertFalse(self.assess(rules=rules)[0])

    def test_missing_rules_fails_closed(self):
        self.assertFalse(self.assess(rules=None)[0])

    def test_inactive_and_unknown_employee(self):
        self.assertFalse(self.assess(employees=[])[0])
        self.assertFalse(self.assess(employees=[{'id': 'e', 'status': 'Ανενεργός'}])[0])

    def test_leave_inclusive_dates(self):
        self.assertFalse(self.assess(leaves=[{'employeeId': 'e', 'startDate': '2026-11-12', 'endDate': '2026-11-12'}])[0])

    def test_overnight_leave_next_day(self):
        r = {**row(), 'startTime': '23:00', 'endTime': '02:00'}
        self.assertFalse(self.assess(r, leaves=[{'employeeId': 'e', 'startDate': '2026-11-13', 'endDate': '2026-11-13'}])[0])

    def test_midnight_boundary_does_not_enter_next_day(self):
        r = {**row(), 'startTime': '23:00', 'endTime': '00:00'}
        self.assertTrue(self.assess(r, leaves=[{'employeeId': 'e', 'startDate': '2026-11-13', 'endDate': '2026-11-13'}])[0])

    def test_overnight_rules_next_day(self):
        r = {**row(), 'startTime': '23:00', 'endTime': '02:00'}
        rule = dict(employee_id='e', scope='date', rule_date='2026-11-13', kind='unavailable')
        self.assertFalse(self.assess(r, rules=[rule])[0])

    def test_equal_end_conflicts(self):
        self.assertFalse(self.assess(assignments=[{**row(), 'id': 'b', 'startTime': '10:00'}])[0])

    def test_after_overlap_both_orders(self):
        a, b = row(), {**row(), 'id': 'b', 'endTime': '13:00'}
        self.assertTrue(self.assess(a, assignments=[b])[0])
        self.assertTrue(self.assess(b, assignments=[a])[0])

    def test_touching_shifts(self):
        self.assertTrue(self.assess(assignments=[{**row(), 'id': 'b', 'startTime': '12:00', 'endTime': '14:00'}])[0])

    def test_previous_day_conflict(self):
        a = {**row(), 'startTime': '00:00', 'endTime': '02:00'}
        b = {**row(), 'id': 'b', 'date': '2026-11-11', 'startTime': '23:00', 'endTime': '02:00'}
        self.assertFalse(self.assess(a, assignments=[b])[0])

    def test_cancelled_does_not_reserve_time(self):
        cancelled = {**row(), 'id': 'b', 'is_cancelled': True}
        self.assertTrue(self.assess(assignments=[cancelled])[0])
        self.assertFalse(check_and_resolve_conflict('e', '09:00', '12:00', [cancelled])[2])

    def test_restore_cancelled_revalidates(self):
        before = {**row(), 'is_cancelled': True}
        self.assertTrue(needs_validation(before, row()))
        self.assertFalse(needs_validation(row(), before))

    def test_metadata_only_is_not_reblocked(self):
        before, after = row(), {**row(), 'notes': 'updated'}
        self.assertFalse(needs_validation(before, after))
        self.assertEqual(validate_changes([before], [after], context(employees=[])), [])

    def test_empty_and_cancelled_skip_employee_rules(self):
        self.assertTrue(self.assess({**row(), 'employeeId': ''}, rules=None)[0])
        self.assertTrue(self.assess({**row(), 'is_cancelled': True}, rules=None)[0])

    def test_invalid_time_even_without_rules(self):
        r = {**row(), 'endTime': '09:00'}
        self.assertFalse(self.assess(r)[0])
        self.assertFalse(assess_rules('e', r, [])[0])

    def test_proposed_rows_checked_against_each_other(self):
        self.assertTrue(validate_changes([], [row(), {**row(), 'id': 'b'}], context()))

    def test_replaced_rows_are_excluded(self):
        before = row()
        after = {**row(), 'startTime': '10:00'}
        self.assertEqual(validate_changes([before], [after], context(assignments=[before])), [])

    def test_manual_bulk_recurring_same_eligibility(self):
        for c in [context(), context(employees=[]), context(rules=[dict(employee_id='e', scope='date', rule_date='2026-11-12', kind='unavailable')])]:
            with self.subTest(c=c):
                manual = not validate_changes([], [row()], c)
                bulk = not validate_changes([{**row(), 'startTime': '08:00'}], [row()], c)
                recurring, reason = recurring_assignment(row(), c)
                self.assertEqual(manual, bulk)
                self.assertEqual(manual, bool(recurring['employeeId']))
                self.assertEqual(not manual, bool(reason))

    def test_recurring_keeps_uncovered_slot(self):
        r, reason = recurring_assignment(row(), context(employees=[]))
        self.assertEqual(r['employeeId'], '')
        self.assertEqual(r['date'], row()['date'])
        self.assertIn('Μη διαθέσιμος', r['notes'])

    def test_normalizes_dates_and_time_seconds(self):
        self.assertFalse(needs_validation(row(), {**row(), 'date': date(2026, 11, 12), 'startTime': '09:00:00'}))


class FetchRulesTests(unittest.TestCase):
    def test_pages_and_fails_closed_on_later_page(self):
        class Client:
            def table(self, _): return self
            def select(self, _): return self
            def order(self, _): return self
            def range(self, a, b): self.offset = a; return self
            def execute(self):
                if self.offset == 0:
                    self.data = [{}] * 500
                else:
                    raise RuntimeError('offline')
                return self
        rules, error = fetch_rules(Client())
        self.assertEqual(rules, [])
        self.assertTrue(error)
