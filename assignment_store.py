"""Atomic assignment writes. No client-side destructive compensation."""
from datetime import date, datetime, timedelta
import uuid

from assignment_policy import EDIT_FIELDS, interval, needs_validation, normalized, validate_changes


class AssignmentSaveError(RuntimeError):
    pass


def serial(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: serial(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serial(v) for v in value]
    return value


def preserve_ids(before, proposed):
    """Keep identities for retained workers, then reuse removed workers' slots."""
    available = list(before)
    result = []
    pending = []
    for row in proposed:
        match = next((old for old in available if old.get('employeeId') == row.get('employeeId')), None)
        if match:
            available.remove(match)
            result.append({**row, 'id': match['id']})
        else:
            pending.append(row)
    for row in pending:
        match = available.pop(0) if available else None
        result.append({**row, 'id': match['id'] if match else row['id']})
    return result


def load_context(client, records):
    """One server snapshot, not a truncated REST page or stale session cache."""
    active = [r for r in records if r.get('employeeId') and not r.get('is_cancelled')]
    if not active:
        return {'assignments': [], 'leaves': [], 'employees': [], 'rules': []}
    intervals = [interval(r) for r in active]
    params = {
        'p_employee_ids': sorted({str(r['employeeId']) for r in active}),
        'p_first': (min(a.date() for a, _ in intervals) - timedelta(days=1)).isoformat(),
        'p_last': max(b.date() for _, b in intervals).isoformat(),
    }
    data = client.rpc('assignment_validation_context', params).execute().data
    if not isinstance(data, dict) or not all(k in data for k in ('assignments', 'leaves', 'employees', 'rules', 'employee_ids', 'first', 'last')):
        raise AssignmentSaveError('Δεν φορτώθηκε πλήρης έλεγχος διαθεσιμότητας.')
    return data


def confirmed_result(result, request_id, proposed):
    if not isinstance(result, dict) or result.get('request_id') != request_id:
        return False
    rows = result.get('rows')
    if not isinstance(rows, list) or len(rows) != len(proposed):
        return False
    actual = {str(r.get('id')): r for r in rows if isinstance(r, dict)}
    if len(actual) != len(proposed):
        return False
    for wanted in proposed:
        saved = actual.get(str(wanted['id']))
        if saved is None or any(normalized(k, saved.get(k)) != normalized(k, v)
                                for k, v in wanted.items() if k in EDIT_FIELDS):
            return False
    return True


def save_changes(client, before, proposed, project=None):
    """Validate fresh data, compare snapshots and commit the entire bar/batch.

    The RPC locks the relevant tables and rechecks the validation snapshot.
    The receipt resolves a lost HTTP response without retrying any mutation.
    """
    if client is None:
        raise AssignmentSaveError('Δεν υπάρχει σύνδεση στη Supabase.')
    if not proposed or len(proposed) > (80 if before else 5000) or len(before) > 80:
        raise AssignmentSaveError('Όριο: 80 εγγραφές ανά αλλαγή ή 5000 ανά νέα καταχώρηση.')
    if len({str(r['id']) for r in proposed}) != len(proposed) or len({str(r['id']) for r in before}) != len(before):
        raise AssignmentSaveError('Διπλά αναγνωριστικά βαρδιών.')
    old_by_id = {str(r['id']): r for r in before}
    try:
        remote = []
        if before:
            remote = client.table('assignments').select('*').in_('id', list(old_by_id)).execute().data or []
        if len(remote) != len(before):
            raise AssignmentSaveError('Η μπάρα έχει διαγραφεί ή αλλάξει. Ανανέωσε πριν αποθηκεύσεις.')
        for row in remote:
            expected = old_by_id[str(row['id'])]
            for key in (*EDIT_FIELDS, 'updated_at'):
                if key in expected and normalized(key, expected[key]) != normalized(key, row.get(key)):
                    raise AssignmentSaveError('Η μπάρα άλλαξε από άλλον χρήστη. Ανανέωσε πριν αποθηκεύσεις.')
        changed = [r for r in proposed if needs_validation(old_by_id.get(str(r['id'])), r)]
        context = load_context(client, changed)
        problems = validate_changes(before, proposed, context)
        if problems:
            raise AssignmentSaveError('Δεν έγινε αποθήκευση: ' + ' · '.join(problems[:5]))
    except AssignmentSaveError:
        raise
    except Exception as exc:
        raise AssignmentSaveError('Αδυναμία ελέγχου πριν την αποθήκευση. Ελέγξτε ότι εφαρμόστηκε το sql/atomic_assignment_changes.sql.') from exc

    request_id = str(uuid.uuid4())
    params = {
        'p_request_id': request_id, 'p_expected': remote,
        'p_records': [{k: serial(v) for k, v in r.items() if k in (*EDIT_FIELDS, 'id')} for r in proposed],
        'p_project': serial(project), 'p_context': context if changed else None,
    }
    try:
        result = client.rpc('save_assignment_changes', params).execute().data
        if confirmed_result(result, request_id, proposed):
            return result
    except Exception:
        pass
    # The request may still be in flight: absence of a receipt is NOT failure proof.
    try:
        result = client.rpc('assignment_write_result', {'p_request_id': request_id}).execute().data
        if confirmed_result(result, request_id, proposed):
            return result
    except Exception:
        pass
    raise AssignmentSaveError(
        'Η αποθήκευση δεν επιβεβαιώθηκε (πιθανή ταυτόχρονη αλλαγή ή διακοπή σύνδεσης). '
        'Ανανέωσε και έλεγξε τη μπάρα πριν ξαναδοκιμάσεις. '
        f'Αναφορά: {request_id}'
    )


def undo_actions(before, after):
    old = {str(r['id']): r for r in before}
    new = {str(r['id']): r for r in after}
    actions = []
    kept = old.keys() & new.keys()
    if kept:
        actions.append({'type': 'update', 'table': 'assignments',
                        'old_records': [old[i] for i in sorted(kept)],
                        'new_records': [new[i] for i in sorted(kept)]})
    if old.keys() - new.keys():
        actions.append({'type': 'delete', 'table': 'assignments', 'records': [old[i] for i in old.keys() - new.keys()]})
    if new.keys() - old.keys():
        actions.append({'type': 'insert', 'table': 'assignments', 'records': [new[i] for i in new.keys() - old.keys()]})
    return actions


def load_recurring_context(client, employee_ids, start, end):
    if isinstance(employee_ids, dict):
        employee_ids = [eid for group in employee_ids.values() for eid in group]
    records = [{'employeeId': eid, 'date': day, 'startTime': '00:00', 'endTime': '23:59'}
               for eid in set(employee_ids or []) if eid for day in (start, end)]
    return load_context(client, records)
