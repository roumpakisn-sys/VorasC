import unittest
from types import SimpleNamespace

from assignment_store import AssignmentSaveError, preserve_ids, save_changes
from test_assignment_policy import row, context


class Client:
    def __init__(self, rows=(), mode='ok'):
        self.rows, self.mode, self.calls = list(rows), mode, []
        self.receipt = None
        self.ctx = context(employee_ids=['e'], first='2026-11-11', last='2026-11-12')
    def table(self, name): self.calls.append(('table', name)); return self
    def select(self, _): return self
    def in_(self, _, ids): self.ids = ids; return self
    def execute(self): return SimpleNamespace(data=[r for r in self.rows if str(r['id']) in self.ids])
    def rpc(self, name, params):
        self.calls.append((name, params))
        def execute():
            if name == 'assignment_validation_context':
                if self.mode == 'context_error': raise RuntimeError('offline')
                return SimpleNamespace(data=self.ctx)
            if name == 'assignment_write_result':
                if self.mode == 'all_offline': raise RuntimeError('offline')
                return SimpleNamespace(data=self.receipt)
            if name == 'save_assignment_changes':
                if self.mode in ('all_offline', 'rejected'): raise RuntimeError('failed')
                self.receipt = dict(request_id=params['p_request_id'], rows=params['p_records'], deleted_ids=[])
                if self.mode == 'lost_response': raise RuntimeError('lost response after commit')
                return SimpleNamespace(data=self.receipt)
            raise AssertionError(name)
        return SimpleNamespace(execute=execute)


class StoreTests(unittest.TestCase):
    def test_preserves_worker_ids_and_reuses_removed_slot(self):
        before = [row(), {**row(), 'id': 'b', 'employeeId': 'other'}]
        proposed = [{**row(), 'id': 'new1', 'employeeId': 'new'}, {**row(), 'id': 'new2'}]
        saved = preserve_ids(before, proposed)
        self.assertEqual({r['employeeId']: r['id'] for r in saved}, {'e': 'a', 'new': 'b'})

    def test_added_and_removed_workers(self):
        self.assertEqual(preserve_ids([row()], [{**row(), 'id': 'new'}, {**row(), 'id': 'b', 'employeeId': 'e2'}])[1]['id'], 'b')
        self.assertEqual(len(preserve_ids([row(), {**row(), 'id': 'b'}], [row()])), 1)

    def test_one_atomic_mutation(self):
        c = Client([row()])
        result = save_changes(c, [row()], [{**row(), 'notes': 'new'}])
        self.assertEqual(result['rows'][0]['id'], 'a')
        self.assertEqual(sum(name == 'save_assignment_changes' for name, _ in c.calls), 1)
        self.assertFalse(any(name == 'assignment_validation_context' for name, _ in c.calls))

    def test_stale_snapshot_blocks_write(self):
        c = Client([{**row(), 'notes': 'someone else'}])
        with self.assertRaises(AssignmentSaveError): save_changes(c, [{**row(), 'notes': ''}], [row()])
        self.assertFalse(any(name == 'save_assignment_changes' for name, _ in c.calls))

    def test_missing_original_blocks_write(self):
        with self.assertRaises(AssignmentSaveError): save_changes(Client(), [row()], [row()])

    def test_lost_response_recovers_receipt_without_retry(self):
        c = Client([row()], 'lost_response')
        result = save_changes(c, [row()], [{**row(), 'notes': 'new'}])
        self.assertEqual(result['rows'][0]['notes'], 'new')
        self.assertEqual(sum(name == 'save_assignment_changes' for name, _ in c.calls), 1)

    def test_unknown_outcome_no_compensating_writes(self):
        c = Client([row()], 'all_offline')
        with self.assertRaisesRegex(AssignmentSaveError, 'Ανανέωσε'):
            save_changes(c, [row()], [{**row(), 'notes': 'new'}])
        self.assertEqual([name for name, _ in c.calls], ['table', 'save_assignment_changes', 'assignment_write_result'])

    def test_rules_fetch_failure_blocks_before_mutation(self):
        c = Client(mode='context_error')
        with self.assertRaises(AssignmentSaveError): save_changes(c, [], [row()])
        self.assertFalse(any(name == 'save_assignment_changes' for name, _ in c.calls))

    def test_rule_rejection_blocks_before_mutation(self):
        c = Client()
        c.ctx['rules'] = [dict(employee_id='e', scope='date', rule_date='2026-11-12', kind='unavailable')]
        with self.assertRaisesRegex(AssignmentSaveError, 'μη διαθεσιμότητα'):
            save_changes(c, [], [row()])
        self.assertFalse(any(name == 'save_assignment_changes' for name, _ in c.calls))

    def test_restore_cancelled_checks_rules(self):
        c = Client([{**row(), 'is_cancelled': True}])
        c.ctx['employees'] = []
        with self.assertRaises(AssignmentSaveError): save_changes(c, c.rows, [row()])

    def test_multiple_workers_preflight_before_project(self):
        c = Client()
        with self.assertRaises(AssignmentSaveError):
            save_changes(c, [], [row(), {**row(), 'id': 'b', 'employeeId': 'missing'}], project={'id': 'p'})
        self.assertFalse(any(name == 'save_assignment_changes' for name, _ in c.calls))

    def test_limits_and_duplicate_ids(self):
        for before, proposed in [([], []), ([], [row(), row()]), ([row()] * 81, [row()])]:
            with self.subTest(size=len(proposed)), self.assertRaises(AssignmentSaveError):
                save_changes(Client(), before, proposed)

    def test_no_connection(self):
        with self.assertRaises(AssignmentSaveError): save_changes(None, [], [row()])
