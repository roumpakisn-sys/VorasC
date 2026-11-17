from copy import deepcopy
from datetime import date
import unittest

from assignment_audit import format_assignment_changes
from placement_details import combine_notes as with_details
from placement_roles import combine_notes as with_roles


class AssignmentAuditTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(id='a', employeeId='e', projectId='p', date='2026-11-17',
                        startTime='09:00', endTime='12:00', notes='παλιά σημείωση')
        self.employees = [{'id': 'e', 'name': 'Μαρία'}, {'id': 'e2', 'name': 'Ελένη'}]
        self.projects = [{'id': 'p', 'name': 'Γυμναστήριο'}]

    def render(self, before, after):
        return format_assignment_changes(before, after, self.employees, self.projects)

    def test_worker_time_and_note_changes_have_old_and_new_values(self):
        old = deepcopy(self.row)
        result = self.render([self.row], [{**self.row, 'employeeId': 'e2',
                            'endTime': '13:00', 'notes': 'νέα σημείωση'}])
        for expected in ('Γυμναστήριο', '17/11/2026', 'Εργαζόμενος: Μαρία → Ελένη',
                         'Λήξη: 12:00 → 13:00', 'Παρατηρήσεις: παλιά σημείωση → νέα σημείωση'):
            self.assertIn(expected, result)
        self.assertEqual(self.row, old)

    def test_contacts_and_details_are_individual_fields_including_clearing(self):
        notes = with_details(with_roles('παλιά σημείωση', {'supervisor': 'Νίκος'}),
                             {'address': 'Εγνατία 10', 'contact_phone': '02310'})
        result = self.render([{**self.row, 'notes': notes}], [self.row])
        for expected in ('Επόπτης: Νίκος → (κενό)', 'Διεύθυνση: Εγνατία 10 → (κενό)',
                         'Τηλ. υπευθύνου: 02310 → (κενό)'):
            self.assertIn(expected, result)
        self.assertNotIn('Παρατηρήσεις:', result)

    def test_added_and_removed_assignments_are_explicit(self):
        result = self.render([self.row], [{**self.row, 'id': 'b', 'employeeId': ''}])
        self.assertIn('Προσθήκη: Γυμναστήριο — Χωρίς προσωπικό', result)
        self.assertIn('Αφαίρεση: Γυμναστήριο — Μαρία', result)

    def test_database_normalization_and_timestamps_are_not_edits(self):
        result = self.render([self.row], [{**self.row, 'date': date(2026, 11, 17),
                            'startTime': '09:00:00', 'updated_at': '2026-11-17T10:00:00Z'}])
        self.assertEqual(result, 'Χωρίς αλλαγές στα στοιχεία των βαρδιών')

    def test_large_batch_does_not_omit_last_employee(self):
        workers = [{'id': str(i), 'name': f'Εργαζόμενος {i}'} for i in range(80)]
        rows = [{**self.row, 'id': str(i), 'employeeId': str(i)} for i in range(80)]
        result = format_assignment_changes([], rows, workers, self.projects)
        self.assertGreater(len(result), 2000)
        self.assertIn('Εργαζόμενος 79', result)
        self.assertEqual(result.count('Προσθήκη:'), 80)
