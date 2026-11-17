from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import placement_hours as hours
from assignment_audit import format_assignment_changes
from test_placement_details import chart
from test_regression_smoke import get_source_functions


ROOT = Path(__file__).resolve().parents[1]


class ActualHoursTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(id='a', employeeId='e', projectId='p', date='2026-11-16',
                        startTime='09:00', endTime='17:00', notes='Κλειδιά [Επόπτης: Νίκος]')

    def test_override_zero_clear_and_overnight_fallback(self):
        for value, expected in ((None, 8), (6.5, 6.5), (0, 0)):
            saved = {**self.row, 'notes': hours.combine_notes(self.row['notes'], value)}
            self.assertEqual(hours.counted_hours(saved), expected)
            self.assertEqual(hours.combine_notes(saved['notes'], None), self.row['notes'])
        self.assertEqual(hours.counted_hours({**self.row, 'startTime': '22:00', 'endTime': '02:00'}), 4)
        self.assertEqual(hours.counted_hours({**saved, 'is_cancelled': True}), 0)
        self.assertEqual(hours.normalize('6,5'), 6.5)
        for invalid in (-1, 25, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                hours.normalize(invalid)

    def test_different_actual_hours_are_not_merged_or_exposed_as_notes(self):
        first = {**self.row, 'notes': hours.combine_notes('', 6.5)}
        second = {**first, 'id': 'b', 'employeeId': 'e2', 'notes': hours.combine_notes('', 0)}
        _, groups, _ = chart([first, second])
        self.assertEqual(len(groups), 2)
        self.assertEqual({g['ActualHours'] for g in groups.values()}, {0, 6.5})
        self.assertTrue(all('Πραγματικές ώρες' not in g['Notes'] for g in groups.values()))
        log = format_assignment_changes([self.row], [first])
        self.assertIn('Πραγματικές ώρες: (κενό) → 6.5', log)

    def test_employee_and_excel_reports_count_actual_and_zero_hours(self):
        rows = [{**self.row, 'notes': hours.combine_notes('', 6.5)},
                {**self.row, 'id': 'b', 'notes': hours.combine_notes('', 0)},
                {**self.row, 'id': 'c'}]
        env = get_source_functions(ROOT / 'pages/6_Employee_Hours.py', ('_get_employee_assignments',), {
            'st': SimpleNamespace(session_state={'assignments': rows}),
            '_safe_date': date.fromisoformat, '_project_name': lambda _: 'Έργο',
        })
        result = env['_get_employee_assignments']('e')
        self.assertEqual([r['hours'] for r in result], [6.5, 0, 8])
        self.assertEqual([r['actual_hours'] for r in result], [6.5, 0, None])
        excel = get_source_functions(ROOT / 'gantt_excel_export.py',
            ('_employee_day_minutes', 'build_employee_day_schedule_rows'), {'datetime': datetime})
        fake_utils = SimpleNamespace(safe_date_parse=date.fromisoformat)
        with patch.dict('sys.modules', {'utils': fake_utils}):
            summary, details = excel['build_employee_day_schedule_rows'](
                rows, [{'id': 'e', 'name': 'Άννα'}], [{'id': 'p', 'name': 'Έργο'}], date(2026, 11, 16))
        self.assertEqual(len(details), 3)
        self.assertEqual(summary[0]['minutes'], 14.5 * 60)


try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None


@unittest.skipIf(AppTest is None, 'Install Streamlit UI test dependencies')
class ActualHoursFormTests(unittest.TestCase):
    def test_edit_save_reload_and_clear_desktop_and_mobile(self):
        for view in ('desktop', 'mobile'):
            with self.subTest(view=view):
                app = AppTest.from_file(str(ROOT / 'tests/fixtures/gantt_forms_app.py'))
                app.session_state['fixture_headless'] = True
                app.session_state['fixture_persist'] = True
                app.run()
                if view == 'mobile':
                    next(s for s in app.selectbox if s.label == 'Έκδοση').set_value(view).run()
                selector = 'edit_bar_select_widget' if view == 'desktop' else 'mobile_edit_select_widget'
                app.selectbox(key=selector).set_value(app.session_state['fixture_group_keys'][0]).run()
                field = lambda: next(n for n in app.number_input if n.label.startswith('Πραγματικές ώρες'))
                save = lambda: next(b for b in app.button if b.label == '💾 Αποθήκευση').click().run()
                field().set_value(6.5)
                save()
                self.assertFalse(app.exception)
                call = app.session_state['save_calls'][-1]
                self.assertEqual([hours.counted_hours(r) for r in call['new']], [6.5, 6.5])
                app.selectbox(key=selector).set_value(app.session_state['fixture_group_keys'][0]).run()
                self.assertEqual(field().value, 6.5)
                field().set_value(None)
                save()
                self.assertFalse(app.exception)
                call = app.session_state['save_calls'][-1]
                self.assertEqual([hours.counted_hours(r) for r in call['new']], [3, 3])
