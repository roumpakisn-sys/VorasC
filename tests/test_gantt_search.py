from datetime import date
import unittest

from gantt_search import find_placements, find_search_bar, reveal_search_project


class GanttSearchTests(unittest.TestCase):
    def test_accent_insensitive_search_crosses_weeks_and_can_include_history(self):
        previous, today, later = [date(2026, 11, d) for d in (16, 17, 25)]
        row = {'projectId': 'p', 'employeeId': 'e', 'startTime': '09:00', 'endTime': '12:00'}
        assignments = {later: [{**row, 'id': 'next'}],
                       previous: [{**row, 'id': 'old'}],
                       today: [{**row, 'id': 'today'}, {**row, 'id': 'vacancy', 'employeeId': ''}]}
        projects, employees = {'p': {'name': 'ISOMAT'}}, {'e': {'name': 'Μαρία Νικολάου'}}
        upcoming = find_placements(assignments, projects, employees, 'μαρια ΝΙΚΟΛΑΟΥ', today)
        self.assertEqual([(day, ident) for day, ident, _ in upcoming], [(today, 'today'), (later, 'next')])
        all_dates = find_placements(assignments, projects, employees, 'isomat')
        self.assertEqual([ident for _, ident, _ in all_dates], ['old', 'today', 'vacancy', 'next'])
        self.assertIn('Χωρίς προσωπικό', all_dates[2][2])

    def test_hidden_project_reveals_crew_and_selects_bar_by_assignment_id(self):
        day = date(2026, 11, 25)
        shown = {'id': 'a', 'projectId': 'shown'}
        worker = {'id': 'b', 'projectId': 'hidden'}
        colleague = {'id': 'c', 'projectId': 'hidden'}
        unrelated = {'id': 'd', 'projectId': 'other-hidden'}
        filtered = {day: [shown]}
        unfiltered = {day: [shown, worker, colleague, unrelated]}
        target = (day, 'b')
        self.assertEqual(reveal_search_project(filtered, unfiltered, target), {day: [shown, worker, colleague]})
        self.assertEqual(filtered, {day: [shown]})
        groups = {'same-time': {'Date': day, 'AssignmentIds': ['a']},
                  'matched-bar': {'Date': day, 'AssignmentIds': ['c', 'b']}}
        self.assertEqual(find_search_bar(groups, target), 'matched-bar')
        self.assertIsNone(find_search_bar(groups, (day, 'd')))
