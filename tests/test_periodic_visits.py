from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import periodic_visits as visits
from periodic_visits_runtime import load_periodic_visits
import placement_details
import placement_hours
import placement_roles
from test_placement_details import chart
from test_regression_smoke import get_source_functions


ROOT = Path(__file__).resolve().parents[1]


class PeriodicVisitRuntimeTests(unittest.TestCase):
    def test_live_update_loads_missing_features_from_disk_only_once(self):
        stale = ModuleType('periodic_visits')
        stale.render_management = lambda _: None
        with patch.dict('sys.modules', {'periodic_visits': stale}):
            loaded = load_periodic_visits()
            self.assertIs(loaded, stale)
            self.assertTrue(callable(loaded.spacing_review_control))
            self.assertTrue(callable(loaded.confirm_spacing))
            self.assertTrue(callable(loaded.target_for_period))
            with patch('periodic_visits_runtime.reload', side_effect=AssertionError('unexpected reload')):
                self.assertIs(load_periodic_visits(), loaded)


class PeriodicVisitTests(unittest.TestCase):
    def setUp(self):
        self.task_id = str(uuid.uuid4())
        self.pattern = {'id': self.task_id, 'projectId': 'p', 'type': visits.TARGET_TYPE,
                        'startDate': '2026-11-01',
                        'notes': json.dumps({'name': 'Υαλοπίνακες', 'monthly_target': 2, 'active': True})}
        self.task = visits.get_targets([self.pattern])[0]
        self.day = date(2026, 11, 18)
        self.link = visits.make_link(self.task_id, 'p', [self.pattern])
        self.row = dict(id='a', employeeId='e', projectId='p', date=self.day,
                        startTime='09:00', endTime='12:00', notes=visits.combine_notes('', self.link))

    def test_crew_bar_splits_and_vacancies_count_once_and_separate_visits_count_twice(self):
        rows = [self.row, {**self.row, 'id': 'b', 'employeeId': 'e2', 'endTime': '13:00'},
                {**self.row, 'id': 'vacancy', 'employeeId': ''}]
        self.assertEqual(len(visits.count_visits(self.task, rows, self.day)), 1)
        other = visits.make_link(self.task_id, 'p', [self.pattern])
        rows.append({**self.row, 'id': 'c', 'notes': visits.combine_notes('', other)})
        self.assertEqual(len(visits.count_visits(self.task, rows, self.day)), 2)
        self.assertEqual(visits.remaining_visits([self.task], rows, self.day), 0)
        self.assertEqual(len(chart(rows)[1]), 3)  # one hours split plus a separate visit

    def test_cancel_delete_move_month_and_unlink_recalculate_from_assignments(self):
        self.assertEqual(self.task['period_months'], 1)  # persisted monthly-only format
        self.assertEqual(visits.remaining_visits([self.task], [self.row], self.day), 1)
        for rows in ([], [{**self.row, 'is_cancelled': True}],
                     [{**self.row, 'date': date(2026, 12, 1)}],
                     [{**self.row, 'notes': visits.combine_notes(self.row['notes'], None)}],
                     [{**self.row, 'projectId': 'other'}]):
            self.assertEqual(visits.remaining_visits([self.task], rows, self.day), 2)
        moved = [{**self.row, 'date': date(2026, 12, 1)}]
        self.assertEqual(visits.remaining_visits([self.task], moved, date(2026, 12, 1)), 1)
        self.assertEqual(visits.remaining_visits([self.task], [], date(2026, 10, 1)), 0)

    def test_bimonthly_visits_count_in_either_month_and_reset_at_the_boundary(self):
        task = {**self.task, 'start': date(2026, 12, 1), 'period_months': 2, 'visit_target': 1}
        december = date(2026, 12, 31)
        january = date(2027, 1, 31)
        february = date(2027, 2, 1)
        row = {**self.row, 'date': january}
        self.assertEqual(visits.period_bounds(task, january), (date(2026, 12, 1), february))
        self.assertEqual(visits.remaining_visits([task], [row], december), 0)
        self.assertEqual(visits.remaining_visits([task], [row], january), 0)
        self.assertEqual(visits.remaining_visits([task], [row], february), 1)

    def test_semiannual_counter_includes_the_last_day_and_excludes_neighboring_periods(self):
        task = {**self.task, 'period_months': 6}
        days = [date(2026, 10, 31), date(2026, 11, 1), date(2027, 4, 30), date(2027, 5, 1)]
        rows = [{**self.row, 'date': day, 'id': str(i)} for i, day in enumerate(days)]
        self.assertEqual(visits.count_visits(task, rows, days[0]), [])
        cycle = visits.count_visits(task, rows, date(2027, 2, 15))
        self.assertEqual([day for (day, _), _ in cycle], days[1:3])
        self.assertEqual(visits.remaining_visits([task], rows, days[-1]), 1)

    def test_semiannual_deadline_is_shown_from_30_days_and_only_for_missing_visits(self):
        task = {**self.task, 'period_months': 6}
        first_notice_day = date(2027, 3, 31)
        self.assertEqual(visits.semiannual_deadlines([task], [], date(2027, 3, 30)), [])
        row = {**self.row, 'date': date(2027, 4, 30)}
        crew = [row, {**row, 'id': 'b', 'employeeId': 'e2'}]
        notice, = visits.semiannual_deadlines([task], crew, first_notice_day)
        self.assertEqual(notice['deadline'], row['date'])
        self.assertEqual(notice['days_left'], 30)
        self.assertEqual(notice['remaining'], 1)
        fulfilled = {**task, 'visit_target': 1}
        self.assertEqual(visits.semiannual_deadlines([fulfilled], crew, first_notice_day), [])
        cancelled = [{**row, 'is_cancelled': True}]
        notice, = visits.semiannual_deadlines([fulfilled], cancelled, row['date'])
        self.assertEqual(notice['days_left'], 0)

    def test_overdue_cycle_survives_reset_even_if_next_cycle_is_scheduled(self):
        task = {**self.task, 'period_months': 6, 'visit_target': 1}
        today = date(2027, 5, 1)
        row = {**self.row, 'date': date(2027, 5, 2)}
        notice, = visits.semiannual_deadlines([task], [row], today)
        self.assertEqual(notice['start'], date(2026, 11, 1))
        self.assertEqual(notice['deadline'], date(2027, 4, 30))
        self.assertEqual(notice['days_left'], -1)
        self.assertEqual(notice['remaining'], 1)
        inactive = {**task, 'active': False}
        self.assertEqual(visits.semiannual_deadlines([inactive, self.task], [], today), [])

    def test_exception_changes_only_selected_cycle_and_its_deadline_notice(self):
        task = {**self.task, 'period_months': 6, 'visit_target': 1}
        bounds = visits.period_bounds(task, self.day)
        with self.assertRaises(ValueError):
            visits.updated_exception(task, bounds, 1, ' ')
        task['period_exceptions'] = visits.updated_exception(task, bounds, 1, 'Κλειστό το έργο')
        self.assertEqual(visits.remaining_visits([task], [], date(2027, 4, 1)), 0)
        self.assertEqual(visits.remaining_visits([task], [], date(2027, 5, 1)), 1)
        self.assertEqual(visits.semiannual_deadlines([task], [], date(2027, 5, 1)), [])
        task['period_exceptions'] = visits.updated_exception(task, bounds, 0, '')
        self.assertEqual(len(visits.semiannual_deadlines([task], [], date(2027, 5, 1))), 1)

    def test_spacing_checks_neighbors_across_months_and_ignores_crew_duplicates(self):
        info = json.loads(self.pattern['notes'])
        info.update(min_gap_days=10, max_gap_days=20)
        pattern = {**self.pattern, 'notes': json.dumps(info)}
        next_link = visits.make_link(self.task_id, 'p', [pattern])
        existing = [self.row, {**self.row, 'id': 'b', 'employeeId': 'e2'}]
        candidate = {**self.row, 'id': 'next', 'notes': visits.combine_notes('', next_link)}
        for target, expected in ((date(2026, 11, 25), 'ελάχιστο 10'),
                                 (date(2026, 11, 28), None),
                                 (date(2026, 12, 8), None),
                                 (date(2026, 12, 9), 'μέγιστο 20')):
            warnings = visits.spacing_warnings([pattern], existing, [], [{**candidate, 'date': target}])
            if expected:
                warning, = warnings
                self.assertIn(expected, warning)
            else:
                self.assertEqual(warnings, [])
        self.assertEqual(visits.spacing_warnings([pattern], existing, [], [{**candidate, 'is_cancelled': True}]), [])

    def test_spacing_detects_new_gap_after_rescheduling_or_cancelling(self):
        info = json.loads(self.pattern['notes'])
        info.update(max_gap_days=20)
        pattern = {**self.pattern, 'notes': json.dumps(info)}
        middle = {**self.row, 'id': 'middle', 'date': date(2026, 12, 1),
                  'notes': visits.combine_notes('', visits.make_link(self.task_id, 'p', [pattern]))}
        last = {**self.row, 'id': 'last', 'date': date(2026, 12, 16),
                'notes': visits.combine_notes('', visits.make_link(self.task_id, 'p', [pattern]))}
        before = [self.row, middle, last]
        cancelled = {**middle, 'is_cancelled': True}
        warning, = visits.spacing_warnings([pattern], before, [middle], [cancelled])
        self.assertIn('Απόσταση 28 ημερών (μέγιστο 20)', warning)
        self.assertEqual(visits.spacing_warnings([pattern], before, [middle], [{**middle, 'employeeId': 'e2'}]), [])

    def test_note_updates_preserve_metadata_and_multiday_copy_uses_new_visits(self):
        notes = placement_hours.combine_notes(placement_roles.combine_notes(
            placement_details.combine_notes('Κλειδιά [Άδεια: Άννα]', {'address': 'Εγνατία 10'}),
            {'supervisor': 'Νίκος'}), 6.5)
        linked = visits.combine_notes(notes, self.link)
        self.assertEqual(visits.split_notes(linked), (notes, self.link))
        self.assertEqual(visits.combine_notes(linked, None), notes)
        bulk = get_source_functions(ROOT / 'pages/8_Bulk_Gantt.py', ('build_delta',), {
            'placement_roles': placement_roles, 'placement_details': placement_details, 're': __import__('re')})
        updated = bulk['build_delta']({'notes': linked}, 'Αντικατάσταση παρατήρησης', {'notes': 'Νέα'})['notes']
        self.assertEqual(visits.split_notes(updated)[1], self.link)
        links = visits.links_for_dates(self.task_id, 'p', [self.pattern], [self.day, date(2026, 11, 19)], self.link)
        self.assertEqual(links[self.day], self.link)
        self.assertNotEqual(links[self.day]['visit_id'], links[date(2026, 11, 19)]['visit_id'])
        with self.assertRaises(ValueError):
            visits.make_link(self.task_id, 'other', [self.pattern])

    def test_target_is_not_a_fixed_recurring_schedule(self):
        from test_ui_storage import RecurringFlowTests
        flow = RecurringFlowTests()
        module = flow.setup_flow()
        flow.state.recurring_patterns = [deepcopy(self.pattern)]
        with patch.dict('sys.modules', {'utils': flow.utils}), patch.object(module, 'load_recurring_context') as load:
            module.auto_extend_recurring_patterns()
        load.assert_not_called()
        self.assertEqual(flow.state.assignments, [])


try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None


@unittest.skipIf(AppTest is None, 'Install Streamlit UI dependencies')
class PeriodicVisitFormTests(unittest.TestCase):
    def test_changed_gap_requires_a_fresh_confirmation_before_saving(self):
        source = '''
from datetime import date
import json
import streamlit as st
import periodic_visits as visits
task_id = '00000000-0000-4000-8000-000000000001'
st.session_state.recurring_patterns = [dict(
    id=task_id, projectId='p', type=visits.TARGET_TYPE, startDate='2026-11-01',
    notes=json.dumps(dict(name='Υαλοπίνακες', visit_target=2, min_gap_days=10)))]
link = dict(task_id=task_id, visit_id='00000000-0000-4000-8000-000000000002', name='Υαλοπίνακες')
st.session_state.assignments = [dict(id='a', projectId='p', date=date(2026, 11, 16),
    notes=visits.combine_notes('', link))]
st.session_state.setdefault('saved_days', [])
with st.form('placement'):
    day = st.date_input('Ημερομηνία', value=date(2026, 11, 18))
    save = st.form_submit_button('Καταχώρηση')
    override = visits.spacing_review_control('placement')
    if save or override:
        next_link = visits.make_link(task_id, 'p', st.session_state.recurring_patterns)
        row = dict(id='b', projectId='p', date=day, notes=visits.combine_notes('', next_link))
        visits.confirm_spacing([], [row], 'placement', override=override)
        st.session_state.saved_days.append(day)
'''
        app = AppTest.from_string(source).run()
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['saved_days'], [])
        self.assertIn('Απόσταση 2 ημερών', app.warning[0].value)
        app.date_input[0].set_value(date(2026, 11, 20))
        next(b for b in app.button if b.label == 'Αποθήκευση με απόκλιση').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['saved_days'], [])
        self.assertIn('Απόσταση 4 ημερών', app.warning[0].value)
        next(b for b in app.button if b.label == 'Αποθήκευση με απόκλιση').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['saved_days'], [date(2026, 11, 20)])

    def test_management_confirms_storage_before_showing_new_target(self):
        source = '''
import streamlit as st
from types import SimpleNamespace
from unittest.mock import patch
import periodic_visits
st.session_state.setdefault('recurring_patterns', [])
st.session_state.setdefault('projects', [{'id': 'p', 'name': 'ISOMAT'}])
st.session_state.setdefault('employees', [])
st.session_state.setdefault('assignments', [])
st.checkbox('Αποτυχία βάσης', key='fail_db')
class Query:
    def insert(self, data):
        self.data = data
        return self
    def execute(self):
        if st.session_state.fail_db:
            raise RuntimeError('offline')
        return SimpleNamespace(data=[self.data])
fake = SimpleNamespace(supabase=SimpleNamespace(table=lambda _: Query()),
    serialize_dates=lambda data: data, mark_data_changed=lambda: None,
    touch_app_sync_state=lambda: None, log_activity=lambda *args: None)
with patch.dict('sys.modules', {'utils': fake}):
    periodic_visits.render_management(True)
'''
        app = AppTest.from_string(source).run()
        app.checkbox(key='fail_db').set_value(True).run()
        next(t for t in app.text_input if t.label == 'Περιγραφή εργασίας').set_value('Υαλοπίνακες')
        next(b for b in app.button if b.label == 'Δημιουργία').click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.error)
        self.assertEqual(app.session_state['recurring_patterns'], [])
        app.checkbox(key='fail_db').set_value(False).run()
        next(t for t in app.text_input if t.label == 'Περιγραφή εργασίας').set_value('Υαλοπίνακες')
        next(s for s in app.selectbox if s.label == 'Συχνότητα').set_value(6)
        next(b for b in app.button if b.label == 'Δημιουργία').click().run()
        self.assertFalse(app.exception)
        tasks = visits.get_targets(app.session_state['recurring_patterns'])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]['visit_target'], 1)
        self.assertEqual(tasks[0]['period_months'], 6)
        self.assertTrue(any(metric.label == 'Απομένουν' and metric.value == '1' for metric in app.metric))
        self.assertTrue(any('Ανά εξάμηνο' in caption.value for caption in app.caption))

    def test_link_existing_crew_reload_and_unlink_in_both_forms(self):
        for view in ('desktop', 'mobile'):
            with self.subTest(view=view):
                setup = PeriodicVisitTests()
                setup.setUp()
                pattern = {**setup.pattern, 'projectId': 'p1'}
                def app_for(records=None):
                    app = AppTest.from_file(str(ROOT / 'tests/fixtures/gantt_forms_app.py'))
                    app.session_state['fixture_headless'] = True
                    app.session_state['fixture_persist'] = True
                    app.session_state['recurring_patterns'] = [pattern]
                    if records is not None:
                        app.session_state['assignments'] = records
                    app.run()
                    if view == 'mobile':
                        next(s for s in app.selectbox if s.label == 'Έκδοση').set_value(view).run()
                    key = 'edit_bar_select_widget' if view == 'desktop' else 'mobile_edit_select_widget'
                    app.selectbox(key=key).set_value(app.session_state['fixture_group_keys'][0]).run()
                    self.assertFalse(app.exception)
                    return app
                app = app_for()
                selector = lambda: next(s for s in app.selectbox if s.label.startswith('Περιοδική εργασία'))
                selector().set_value(setup.task_id)
                next(b for b in app.button if b.label == '💾 Αποθήκευση').click().run()
                self.assertFalse(app.exception)
                rows = app.session_state['save_calls'][-1]['new']
                links = [visits.split_notes(row['notes'])[1] for row in rows]
                self.assertEqual(links[0], links[1])
                self.assertEqual(links[0]['task_id'], setup.task_id)
                app = app_for(app.session_state['assignments'])
                self.assertEqual(selector().value, setup.task_id)
                selector().set_value('')
                next(b for b in app.button if b.label == '💾 Αποθήκευση').click().run()
                self.assertFalse(app.exception)
                self.assertTrue(all(visits.split_notes(r['notes'])[1] is None
                                    for r in app.session_state['save_calls'][-1]['new']))
