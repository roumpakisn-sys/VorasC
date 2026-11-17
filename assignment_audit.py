"""Readable before/after audit details for confirmed Gantt saves."""
from datetime import date

import placement_details
import placement_roles


def format_assignment_changes(before, after, employees=(), projects=()):
    employee_names = {str(r['id']): r.get('name') for r in employees}
    project_names = {str(r['id']): r.get('name') for r in projects}

    def name(value, names, empty):
        return str(names.get(str(value)) or value or empty)

    def day(value):
        text = str(value or '').split('T')[0]
        try:
            return date.fromisoformat(text).strftime('%d/%m/%Y')
        except ValueError:
            return text

    def clock(value):
        return str(value or '')[:5]

    def fields(row):
        notes, roles = placement_roles.split_notes(row.get('notes'))
        notes, details = placement_details.split_notes(notes)
        return {
            'Εργαζόμενος': name(row.get('employeeId'), employee_names, 'Χωρίς προσωπικό'),
            'Έργο': name(row.get('projectId'), project_names, 'Άγνωστο έργο'),
            'Ημερομηνία': day(row.get('date')),
            'Έναρξη': clock(row.get('startTime')),
            'Λήξη': clock(row.get('endTime')),
            'Προσέλευση': clock(row.get('arrivalTime')),
            'Χρώμα': row.get('colorName') or '',
            'Κωδικός χρώματος': row.get('colorHex') or '',
            'Ακύρωση': 'Ναι' if row.get('is_cancelled') else 'Όχι',
            'Αιτία ακύρωσης': row.get('cancel_reason') or '',
            'Γενικός καθαρισμός': 'Ναι' if row.get('is_general') else 'Όχι',
            'Επαναλαμβανόμενη σειρά': row.get('recurring_id') or '',
            'Παρατηρήσεις': notes,
            **{label: roles[key] for key, label in placement_roles.LABELS.items()},
            **{label: details[key] for key, label in placement_details.LABELS.items()},
        }

    def heading(values):
        return (f"{values['Έργο']} — {values['Εργαζόμενος']} "
                f"({values['Ημερομηνία']}, {values['Έναρξη']}–{values['Λήξη']})")

    def snapshot(action, values):
        extra = [f'{key}: {value}' for key, value in list(values.items())[5:]
                 if value and value != 'Όχι']
        return f'{action}: {heading(values)}' + ('; ' + '; '.join(extra) if extra else '')

    old_by_id = {str(row['id']): row for row in before}
    new_ids = {str(row['id']) for row in after}
    lines = []
    for row in after:
        old = old_by_id.get(str(row['id']))
        current = fields(row)
        if old is None:
            lines.append(snapshot('Προσθήκη', current))
            continue
        previous = fields(old)
        changes = [f'{key}: {previous[key] or "(κενό)"} → {value or "(κενό)"}'
                   for key, value in current.items() if value != previous[key]]
        if changes:
            lines.append(f'Αλλαγή: {heading(previous)}; ' + '; '.join(changes))
    for row in before:
        if str(row['id']) not in new_ids:
            lines.append(snapshot('Αφαίρεση', fields(row)))
    return ' | '.join(lines) or 'Χωρίς αλλαγές στα στοιχεία των βαρδιών'
