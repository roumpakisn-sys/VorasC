import ast
from copy import deepcopy
from datetime import date
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from assignment_store import AssignmentSaveError, confirmed_result
from test_assignment_policy import row, context

ROOT = Path(__file__).resolve().parents[1]


class State(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc
    def __setattr__(self, name, value): self[name] = value


class SessionTests(unittest.TestCase):
    def wrapper(self):
        node = next(n for n in ast.parse((ROOT / 'utils.py').read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'save_assignment_batch')
        self.state = State(assignments=[row()], projects=[])
        self.history = Mock()
        env = {'st': SimpleNamespace(session_state=self.state, error=Mock()),
               'supabase': object(), 'safe_date_parse': date.fromisoformat,
               'add_transaction': self.history, 'mark_data_changed': Mock(),
               'touch_app_sync_state': Mock(), 'log_activity': Mock()}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'utils.py', 'exec'), env)
        return env['save_assignment_batch']

    def test_failure_leaves_session_and_undo_untouched(self):
        save = self.wrapper()
        original = deepcopy(self.state)
        with patch('assignment_store.save_changes', side_effect=AssignmentSaveError('offline')):
            self.assertIsNone(save([row()], [{**row(), 'notes': 'new'}], project={'id': 'p2'}))
        self.assertEqual(self.state.assignments, original['assignments'])
        self.assertEqual(self.state.projects, [])
        self.history.assert_not_called()

    def test_success_uses_confirmed_rows_and_updates_undo_once(self):
        save = self.wrapper()
        saved = {**row(), 'notes': 'confirmed', 'updated_at': '2026-11-12T12:00:00Z'}
        with patch('assignment_store.save_changes', return_value={'rows': [saved]}):
            result = save([row()], [{**row(), 'notes': 'confirmed'}])
        self.assertEqual(result[0]['notes'], 'confirmed')
        self.assertEqual(self.state.assignments[0]['updated_at'], saved['updated_at'])
        self.history.assert_called_once()

    def test_receipt_with_missing_or_wrong_rows_is_not_success(self):
        self.assertFalse(confirmed_result({'request_id': 'r'}, 'r', [row()]))
        self.assertFalse(confirmed_result({'request_id': 'r', 'rows': [{**row(), 'id': 'wrong'}]}, 'r', [row()]))
        self.assertFalse(confirmed_result({'request_id': 'r', 'rows': [{**row(), 'endTime': '13:00'}]}, 'r', [row()]))
        self.assertTrue(confirmed_result({'request_id': 'r', 'rows': [row()]}, 'r', [row()]))


class RecurringFlowTests(unittest.TestCase):
    def setup_flow(self, ok=True):
        self.state = State(recurring_patterns=[{'id': 'series', 'employeeIds': ['e'],
                           'type': 'Εβδομαδιαία', 'startDate': date.today(), 'projectId': 'p',
                           'startTime': '09:00', 'endTime': '12:00'}],
                           assignments=[], assignments_by_date={})
        self.utils = SimpleNamespace(supabase=object(), safe_date_parse=lambda d: d if isinstance(d, date) else date.fromisoformat(d),
                                     db_insert=Mock(return_value=ok), mark_data_changed=Mock())
        st = SimpleNamespace(session_state=self.state, warning=Mock())
        spec = importlib.util.spec_from_file_location('recurring_under_test', ROOT / 'recurring_service.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'streamlit': st, 'utils': self.utils}):
            spec.loader.exec_module(module)
        return module

    def test_rules_failure_does_not_generate_or_write_anything(self):
        module = self.setup_flow()
        with patch.dict(sys.modules, {'utils': self.utils}), patch.object(module, 'load_recurring_context', side_effect=RuntimeError('offline')):
            module.auto_extend_recurring_patterns()
        self.assertEqual(self.state.assignments, [])
        self.utils.db_insert.assert_not_called()

    def test_insert_failure_does_not_create_local_ghost_rows(self):
        module = self.setup_flow(ok=False)
        with patch.dict(sys.modules, {'utils': self.utils}), patch.object(module, 'load_recurring_context', return_value=context()):
            module.auto_extend_recurring_patterns()
        self.assertEqual(self.state.assignments, [])
        self.assertEqual(self.state.assignments_by_date, {})

    def test_unavailable_worker_becomes_unstaffed_on_auto_extension(self):
        module = self.setup_flow()
        c = context(rules=[dict(employee_id='e', scope='weekday', weekday=d, kind='unavailable') for d in range(7)])
        with patch.dict(sys.modules, {'utils': self.utils}), patch.object(module, 'load_recurring_context', return_value=c):
            module.auto_extend_recurring_patterns()
        self.assertGreater(len(self.state.assignments), 1)
        self.assertTrue(all(r['employeeId'] == '' for r in self.state.assignments))
        self.assertEqual(sum(len(v) for v in self.state.assignments_by_date.values()), len(self.state.assignments))

    def test_automatic_extension_checks_staged_patterns(self):
        module = self.setup_flow()
        self.state.recurring_patterns.append({**self.state.recurring_patterns[0], 'id': 'second'})
        with patch.dict(sys.modules, {'utils': self.utils}), patch.object(module, 'load_recurring_context', return_value=context()):
            module.auto_extend_recurring_patterns()
        first = [r for r in self.state.assignments if r['recurring_id'] == 'series']
        second = [r for r in self.state.assignments if r['recurring_id'] == 'second']
        self.assertTrue(all(r['employeeId'] == 'e' for r in first))
        self.assertTrue(all(r['employeeId'] == '' for r in second))
