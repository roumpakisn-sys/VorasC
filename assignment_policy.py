"""Shared, UI-free eligibility policy for every assignment entry point."""
from datetime import datetime, time, timedelta

from availability_rules import as_day, assess_rules, mins

SCHEDULE_FIELDS = ('employeeId', 'date', 'startTime', 'endTime')
EDIT_FIELDS = (
    *SCHEDULE_FIELDS, 'projectId', 'arrivalTime', 'notes', 'colorName', 'colorHex',
    'is_cancelled', 'cancel_reason', 'is_general', 'recurring_id',
)


def normalized(key, value):
    if key == 'date':
        return as_day(value)
    if key in ('startTime', 'endTime', 'arrivalTime'):
        return mins(value)
    if key == 'updated_at' and value:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return '' if value is None else value


def needs_validation(before, after):
    if after.get('is_cancelled') or not after.get('employeeId'):
        return False
    return (before is None or before.get('is_cancelled') or any(
        normalized(key, before.get(key)) != normalized(key, after.get(key))
        for key in SCHEDULE_FIELDS
    ))


def interval(record):
    day = as_day(record.get('date'))
    start, end = mins(record.get('startTime')), mins(record.get('endTime'))
    if day is None or start is None or end is None or start == end:
        raise ValueError('Μη έγκυρη ημερομηνία ή ώρα βάρδιας')
    base = datetime.combine(day, time.min)
    return base + timedelta(minutes=start), base + timedelta(minutes=end + (1440 if end < start else 0))


def assess_assignment(record, assignments, leaves, employees, rules, exclude_ids=()):
    """Same rules for manual, bulk and recurring work; preferred is advisory.

    Preserve STAFF.PRO's ΜΕΤΑ ΑΠΟ convention: overlapping intervals with
    different ends are allowed. Cancelled work never reserves an employee.
    """
    try:
        start, end = interval(record)
    except ValueError as exc:
        return False, str(exc)
    eid = str(record.get('employeeId') or '')
    if not eid or record.get('is_cancelled'):
        return True, ''
    employee = next((e for e in employees if str(e.get('id')) == eid), None)
    if not employee or employee.get('status', 'Ενεργός') != 'Ενεργός':
        return False, 'Ανενεργός/άγνωστος εργαζόμενος'
    if rules is None:
        return False, 'Δεν έχουν φορτωθεί οι κανόνες διαθεσιμότητας'
    allowed, reason, _ = assess_rules(eid, record, rules)
    if not allowed:
        return False, reason
    last_day = (end - timedelta(microseconds=1)).date()
    for leave in leaves:
        if str(leave.get('employeeId')) != eid:
            continue
        first, last = as_day(leave.get('startDate')), as_day(leave.get('endDate'))
        if first is None or last is None:
            return False, 'Μη έγκυρη καταχώρηση άδειας'
        if first <= last_day and last >= start.date():
            return False, 'Άδεια'
    excluded = {str(i) for i in exclude_ids}
    if record.get('id'):
        excluded.add(str(record['id']))
    for other in assignments:
        if (str(other.get('id')) in excluded or other.get('is_cancelled')
                or str(other.get('employeeId')) != eid):
            continue
        try:
            other_start, other_end = interval(other)
        except ValueError:
            return False, 'Μη έγκυρη υπάρχουσα βάρδια'
        if start < other_end and other_start < end and end == other_end:
            return False, 'Επικάλυψη με ίδια ώρα λήξης'
    return True, ''


def validate_changes(before, after, context):
    previous = {str(r['id']): r for r in before}
    combined = [r for r in context['assignments'] if str(r['id']) not in previous] + after
    problems = []
    for row in after:
        # Always reject invalid intervals, including empty/cancelled placements.
        try:
            interval(row)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if not needs_validation(previous.get(str(row['id'])), row):
            continue
        ok, reason = assess_assignment(row, combined, context['leaves'], context['employees'], context['rules'])
        if not ok:
            employee = next((e for e in context['employees'] if str(e['id']) == str(row['employeeId'])), {})
            problems.append(f"{employee.get('name', row['employeeId'])} · {row['date']} · {reason}")
    return list(dict.fromkeys(problems))


def recurring_assignment(record, context, staged=()):
    """Keep an uncovered occurrence visible, without assigning unavailable staff."""
    ok, reason = assess_assignment(record, context['assignments'] + list(staged),
                                   context['leaves'], context['employees'], context['rules'])
    if ok:
        return record, ''
    if not record.get('employeeId'):
        raise ValueError(reason)
    employee = next((e for e in context['employees'] if str(e['id']) == str(record['employeeId'])), {})
    name = employee.get('name', record['employeeId'])
    return {**record, 'employeeId': '',
            'notes': f"{record.get('notes', '')} [Μη διαθέσιμος: {name} — {reason}]".strip()}, reason
