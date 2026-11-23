"""Periodic visit targets and placement links using the existing database schema."""
import base64
import json
import re
import uuid
from datetime import date, datetime, time, timedelta

TARGET_TYPE = 'Μηνιαίος στόχος επισκέψεων'
MENU = 'Περιοδικές Εργασίες'
FREQUENCIES = {1: 'Κάθε μήνα', 2: 'Ανά δίμηνο', 6: 'Ανά εξάμηνο'}
SEMIANNUAL_NOTICE_DAYS = 30
_TAG = re.compile(r'\[Περιοδική επίσκεψη: ([A-Za-z0-9_=-]+)\]')


def is_target(pattern):
    return pattern.get('type') == TARGET_TYPE


def as_day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def get_targets(patterns):
    tasks = []
    for pattern in patterns:
        if not is_target(pattern):
            continue
        try:
            info = json.loads(pattern.get('notes') or '')
            count = int(info.get('visit_target', info.get('monthly_target')))
            months = int(info.get('period_months', 1))
            if not info['name'].strip() or count < 1 or months not in FREQUENCIES:
                continue
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
        tasks.append({**info, 'visit_target': count, 'period_months': months,
                      'id': pattern['id'], 'project_id': pattern['projectId'],
                      'start': as_day(pattern.get('startDate')), 'record': pattern})
    return tasks


def split_notes(notes):
    link = None
    text = notes or ''

    def extract(match):
        nonlocal link
        try:
            candidate = json.loads(base64.urlsafe_b64decode(match[1]).decode('utf-8'))
            uuid.UUID(candidate['task_id'])
            uuid.UUID(candidate['visit_id'])
            if not isinstance(candidate['name'], str):
                return match[0]
        except (ValueError, TypeError, KeyError, UnicodeError):
            return match[0]
        link = candidate
        return ''

    clean = _TAG.sub(extract, text)
    return (clean.strip() if clean != text else text), link


def combine_notes(notes, link):
    clean, _ = split_notes(notes)
    if not link:
        return clean
    payload = json.dumps(link, ensure_ascii=False, sort_keys=True).encode('utf-8')
    tag = base64.urlsafe_b64encode(payload).decode('ascii')
    return f'{clean.rstrip()} [Περιοδική επίσκεψη: {tag}]'.strip()


def make_link(task_id, project_id, patterns, previous=None):
    if not task_id:
        return None
    task = next((task for task in get_targets(patterns) if task['id'] == task_id), None)
    if not task or task['project_id'] != project_id:
        raise ValueError('Η περιοδική εργασία πρέπει να ανήκει στο επιλεγμένο έργο.')
    visit_id = previous['visit_id'] if previous else str(uuid.uuid4())
    return {'task_id': task_id, 'visit_id': visit_id, 'name': task['name']}


def group_suffix(notes):
    link = split_notes(notes)[1]
    return f"_visit_{link['task_id']}_{link['visit_id']}" if link else ''


def links_for_dates(task_id, project_id, patterns, days, previous=None):
    return {day: make_link(task_id, project_id, patterns, previous if index == 0 else None)
            for index, day in enumerate(days)}


def _month_start(index):
    year, offset = divmod(index, 12)
    return date(year, offset + 1, 1)


def period_bounds(task, month):
    """Return the start and exclusive end of the cycle containing the selected month."""
    anchor = task['start'] or date(month.year, 1, 1)
    anchor_index = anchor.year * 12 + anchor.month - 1
    month_index = month.year * 12 + month.month - 1
    if month_index < anchor_index:
        return None
    length = task['period_months']
    start_index = anchor_index + ((month_index - anchor_index) // length) * length
    return _month_start(start_index), _month_start(start_index + length)


def _period_key(bounds):
    start, end = bounds
    return f'{start.isoformat()}/{end.isoformat()}'


def period_exception(task, bounds):
    return task.get('period_exceptions', {}).get(_period_key(bounds))


def target_for_period(task, bounds):
    exception = period_exception(task, bounds)
    waived = exception['visits'] if exception else 0
    return max(0, task['visit_target'] - waived)


def updated_exception(task, bounds, visits, reason):
    """Return updated exceptions without changing the recurring target or other periods."""
    exceptions = dict(task.get('period_exceptions', {}))
    key = _period_key(bounds)
    if visits == 0:
        exceptions.pop(key, None)
    elif 1 <= visits <= task['visit_target'] and reason.strip():
        exceptions[key] = {'visits': visits, 'reason': reason.strip()}
    else:
        raise ValueError('Ορίστε πόσες επισκέψεις εξαιρούνται και συμπληρώστε την αιτιολογία.')
    return exceptions


def _gap_limits(task):
    return task.get('min_gap_days', 0), task.get('max_gap_days', 0)


def spacing_warnings(patterns, assignments, before, after):
    """Find newly introduced gaps between consecutive non-cancelled visits."""
    tasks = {task['id']: task for task in get_targets(patterns)
             if task.get('active', True) and any(_gap_limits(task))}
    if not tasks:
        return []

    def occurrence(row):
        if row.get('is_cancelled'):
            return None
        link = split_notes(row.get('notes'))[1]
        task = tasks.get(link['task_id']) if link else None
        if task and row.get('projectId') == task['project_id']:
            day = as_day(row.get('date'))
            if day:
                return task['id'], day, link['visit_id']
        return None

    removed = {visit for row in before if (visit := occurrence(row)) is not None}
    added = {visit for row in after if (visit := occurrence(row)) is not None}
    changed = {task_id for task_id, _, _ in removed ^ added}
    if not changed:
        return []

    replaced_rows = {str(row['id']) for row in before}
    original = {task_id: set() for task_id in changed}
    proposed = {task_id: set() for task_id in changed}
    projects = {tasks[task_id]['project_id'] for task_id in changed}
    for row in assignments:
        if row.get('projectId') not in projects:
            continue
        visit = occurrence(row)
        if visit and visit[0] in changed:
            task_id, day, visit_id = visit
            original[task_id].add((day, visit_id))
            if str(row['id']) not in replaced_rows:
                proposed[task_id].add((day, visit_id))
    for task_id, day, visit_id in added:
        if task_id in changed:
            proposed[task_id].add((day, visit_id))

    warnings = []
    for task_id in sorted(changed):
        task = tasks[task_id]
        minimum, maximum = _gap_limits(task)
        previous = sorted(original[task_id])
        old_pairs = set(zip(previous, previous[1:]))
        visits = sorted(proposed[task_id])
        for first, second in zip(visits, visits[1:]):
            if (first, second) in old_pairs:
                continue
            first_day, second_day = first[0], second[0]
            days = (second_day - first_day).days
            if minimum and days < minimum:
                limit = f'ελάχιστο {minimum}'
            elif maximum and days > maximum:
                limit = f'μέγιστο {maximum}'
            else:
                continue
            warnings.append(f"{task['name']} · {first_day:%d/%m/%Y} → {second_day:%d/%m/%Y} · "
                            f"Απόσταση {days} ημερών ({limit}).")
    return warnings


def spacing_review_control(key, *, in_form=True):
    import streamlit as st

    review = st.session_state.get('periodic_spacing_review')
    if not review or review[0] != key:
        return False
    st.warning('\n\n'.join(review[1]))
    if in_form:
        return st.form_submit_button('Αποθήκευση με απόκλιση')
    return st.checkbox('Επιτρέπω την απόκλιση και επαναλαμβάνω τη μετακίνηση', key=key + '_confirm')


def confirm_spacing(before, after, key, *, override=False):
    import streamlit as st

    state = st.session_state
    warnings = spacing_warnings(state.get('recurring_patterns', []), state.get('assignments', []), before, after)
    if warnings and not (override and state.get('periodic_spacing_review') == (key, warnings)):
        state.periodic_spacing_review = (key, warnings)
        st.rerun()
    if state.get('periodic_spacing_review', (None,))[0] == key:
        state.pop('periodic_spacing_review')


def _linked_visits(task, assignments, start, end):
    """All crew rows sharing an occurrence count once per date, across bar splits."""
    visits = {}
    for row in assignments:
        if row.get('projectId') != task['project_id'] or row.get('is_cancelled'):
            continue
        day = as_day(row.get('date'))
        if not day or not start <= day < end:
            continue
        link = split_notes(row.get('notes'))[1]
        if link and link['task_id'] == task['id']:
            visits.setdefault((day, link['visit_id']), []).append(row)
    return visits


def _scheduled_visits(task, assignments, start, end):
    visits = _linked_visits(task, assignments, start, end)
    return sorted(visits.items(), key=lambda item: (item[0][0], str(item[1][0].get('startTime') or '')))


def count_visits(task, assignments, month):
    bounds = period_bounds(task, month)
    if bounds is None:
        return []
    return _scheduled_visits(task, assignments, *bounds)


def previous_month_visits(task, assignments, month):
    month_start = month.replace(day=1)
    previous_start = (month_start - timedelta(days=1)).replace(day=1)
    return _scheduled_visits(task, assignments, previous_start, month_start)


def remaining_visits(tasks, assignments, month):
    remaining = 0
    for task in tasks:
        bounds = period_bounds(task, month)
        if task.get('active', True) and bounds is not None:
            remaining += max(0, target_for_period(task, bounds) - len(_linked_visits(task, assignments, *bounds)))
    return remaining


def semiannual_deadlines(tasks, assignments, today):
    """Return shortfalls for upcoming deadlines and for any past six-month cycle."""
    notices = []
    for task in tasks:
        if task['period_months'] != 6 or not task.get('active', True):
            continue
        current = period_bounds(task, today)
        if current is None:
            continue
        current_start, current_end = current
        start = (task['start'] or current_start).replace(day=1)
        counts = {}
        for day, _ in _linked_visits(task, assignments, start, current_end):
            cycle_start, _ = period_bounds(task, day)
            counts[cycle_start] = counts.get(cycle_start, 0) + 1

        while start <= current_start:
            _, end = period_bounds(task, start)
            deadline = end - timedelta(days=1)
            days_left = (deadline - today).days
            remaining = target_for_period(task, (start, end)) - counts.get(start, 0)
            if days_left <= SEMIANNUAL_NOTICE_DAYS and remaining > 0:
                notices.append({'task': task, 'start': start, 'deadline': deadline,
                                'days_left': days_left, 'remaining': remaining})
            start = end

    return sorted(notices, key=lambda notice: (notice['days_left'] < 0, abs(notice['days_left']),
                                               notice['task']['name'].casefold()))


def inputs(*, key, project_id, default=None):
    import streamlit as st

    tasks = get_targets(st.session_state.get('recurring_patterns', []))
    available = [task for task in tasks if task.get('active', True) or task['id'] == default]
    available.sort(key=lambda task: (task['project_id'] != project_id, task['name'].casefold()))
    projects = {p['id']: p['name'] for p in st.session_state.get('projects', [])}
    names = {task['id']: projects.get(task['project_id'], 'Έργο') + ' — ' + task['name'] for task in available}
    if default and default not in names:
        names[default] = 'Προηγούμενη σύνδεση — επιλέξτε εργασία ή Χωρίς σύνδεση'
    if not names:
        return None
    options = ['', *names]
    selected = st.selectbox('Περιοδική εργασία (προαιρετικό)', options,
                            index=options.index(default) if default in options else 0,
                            format_func=lambda value: names.get(value, 'Χωρίς σύνδεση'), key=key)
    return selected or None


def prepare_new_placement(task, month):
    import streamlit as st
    from gantt_helpers import get_local_today

    today = get_local_today()
    first = max(today, month) if (today.year, today.month) == (month.year, month.month) else month
    st.session_state.qa_form_prefill = {
        **task.get('placement_defaults', {}),
        'first_date': first, 'project_id': task['project_id'], 'periodic_task_id': task['id'],
    }
    st.session_state.qa_rc = st.session_state.get('qa_rc', 0) + 1
    st.session_state.view_week_date = first
    st.session_state.date_picker = first
    st.session_state.gantt_presentation_mode = False
    st.session_state.pop('gantt_search_target', None)
    st.session_state.clicked_key = None
    st.session_state.reset_edit_bar_select_next_run = True
    st.switch_page('pages/1_Gantt_Dashboard.py')


def open_placement(day, assignment_id):
    import streamlit as st

    st.session_state.view_week_date = day
    st.session_state.date_picker = day
    st.session_state.gantt_presentation_mode = False
    st.session_state.gantt_search_target = (day, str(assignment_id))
    st.session_state.gantt_search_pending = True
    st.session_state.suppress_next_detector_click = True
    st.session_state.detector_version = st.session_state.get('detector_version', 0) + 1
    st.session_state.pop('edit_form_prefill', None)
    st.switch_page('pages/1_Gantt_Dashboard.py')


def render_deadlines(tasks, assignments, today, project_names, *, is_admin):
    import streamlit as st

    if not any(task['period_months'] == 6 and task.get('active', True) for task in tasks):
        return
    st.subheader('Ειδοποιήσεις εξαμηνιαίων εργασιών')
    notices = semiannual_deadlines(tasks, assignments, today)
    if not notices:
        st.caption('Δεν εκκρεμούν εξαμηνιαίες επισκέψεις με προθεσμία εντός 30 ημερών ή παλαιότερη.')
        return

    def show_period(start):
        st.session_state.periodic_month = start

    for notice in notices:
        task = notice['task']
        project = project_names.get(task['project_id'], 'Άγνωστο έργο')
        deadline = notice['deadline']
        days_left = notice['days_left']
        remaining = notice['remaining']
        label = f"{project} — {task['name']} · {remaining} {'επίσκεψη' if remaining == 1 else 'επισκέψεις'} προς προγραμματισμό"
        key = f"periodic_deadline_{task['id']}_{deadline.isoformat()}"
        message, action = st.columns([4, 1.6])
        if days_left < 0:
            message.error(f"**Εκπρόθεσμη** · {label} · Προθεσμία {deadline:%d/%m/%Y}")
            action.button('Δες περίοδο', key=key, on_click=show_period, args=(notice['start'],))
        else:
            if days_left == 0:
                timing = 'Λήγει σήμερα'
            elif days_left == 1:
                timing = 'Λήγει αύριο'
            else:
                timing = f'Λήγει σε {days_left} ημέρες'
            message.warning(f"**{timing}** · {label} · Έως {deadline:%d/%m/%Y}")
            if is_admin and action.button('Προγραμμάτισε', key=key):
                prepare_new_placement(task, today.replace(day=1))


def _spacing_inputs(task=None):
    import streamlit as st

    minimum, maximum = _gap_limits(task or {})
    low, high = st.columns(2)
    minimum = low.number_input('Ελάχιστη απόσταση (ημέρες)', min_value=0, value=minimum, step=1)
    maximum = high.number_input('Μέγιστη απόσταση (ημέρες)', min_value=0, value=maximum, step=1)
    st.caption('Βάλτε 0 για να αφήσετε ένα όριο κενό. Μετρούν οι ημέρες ανάμεσα σε διαδοχικές επισκέψεις.')
    return minimum, maximum


def _placement_defaults_inputs(active_employee_names, defaults=None):
    import streamlit as st

    defaults = defaults or {}
    first, last = st.columns(2)
    start = first.time_input(
        'Ώρα έναρξης (προαιρετικό)',
        value=time.fromisoformat(defaults['start_time']) if defaults.get('start_time') else None,
        step=300,
    )
    end = last.time_input(
        'Ώρα λήξης (προαιρετικό)',
        value=time.fromisoformat(defaults['end_time']) if defaults.get('end_time') else None,
        step=300,
    )
    staff = st.multiselect(
        'Προσωπικό (προαιρετικό)', list(active_employee_names),
        default=[eid for eid in defaults.get('employee_ids', []) if eid in active_employee_names],
        format_func=active_employee_names.get,
    )
    st.caption('Οι προεπιλογές συμπληρώνονται όταν πατήσετε «Προγραμμάτισε».')
    return start, end, staff


def _placement_defaults(start, end, staff):
    if (start is None) != (end is None):
        raise ValueError('Συμπληρώστε και τις δύο ώρες ή αφήστε τες κενές.')
    if start is not None and start >= end:
        raise ValueError('Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.')
    defaults = {'employee_ids': staff} if staff else {}
    if start is not None:
        defaults.update(start_time=start.strftime('%H:%M'), end_time=end.strftime('%H:%M'))
    return defaults


def _render_visit_list(visits, employee_names, *, section):
    import streamlit as st

    for (day, _), rows in visits:
        row = rows[0]
        names = list(dict.fromkeys(employee_names.get(r.get('employeeId'), 'Χωρίς προσωπικό') for r in rows))
        st.write(f"{day:%d/%m/%Y} · {row.get('startTime', '')}–{row.get('endTime', '')}")
        st.caption(', '.join(names))
        if st.button('Άνοιγμα μπάρας', key=f"periodic_open_{section}_{row['id']}"):
            open_placement(day, row['id'])


def render_management(is_admin):
    import streamlit as st
    import utils
    from gantt_helpers import get_local_today

    st.title('📌 Περιοδικές Εργασίες')
    today = get_local_today()
    tasks = get_targets(st.session_state.recurring_patterns)
    assignments = st.session_state.assignments
    project_names = {p['id']: p['name'] for p in st.session_state.projects}
    employee_names = {e['id']: e['name'] for e in st.session_state.employees}
    active_employee_names = {e['id']: e['name'] for e in st.session_state.employees
                             if e.get('status', 'Ενεργός') == 'Ενεργός'}
    month = st.date_input('Μήνας αναφοράς', value=today.replace(day=1),
                          key='periodic_month').replace(day=1)
    if tasks:
        st.metric('Σύνολο επισκέψεων που απομένουν', remaining_visits(tasks, assignments, month),
                  help='Για τις περιόδους των ενεργών εργασιών που περιλαμβάνουν τον μήνα αναφοράς.')
    render_deadlines(tasks, assignments, today, project_names, is_admin=is_admin)
    st.caption('Για κάθε εργασία εμφανίζεται η περίοδος που περιλαμβάνει τον μήνα αναφοράς. '
               'Μετρούν οι καταχωρισμένες επισκέψεις που δεν έχουν ακυρωθεί.')

    def save_project(project):
        if not utils.supabase:
            st.error('Απαιτείται σύνδεση στη βάση για αποθήκευση.')
            return False
        try:
            result = utils.supabase.table('projects').insert(project).execute()
            if not result.data:
                st.error('Δεν επιβεβαιώθηκε η δημιουργία του έργου.')
                return False
        except Exception as exc:
            st.error(f'Δεν αποθηκεύτηκε το νέο έργο: {exc}')
            return False
        st.session_state.projects = [*st.session_state.projects, project]
        project_names[project['id']] = project['name']
        return True

    def save_target(record, original=None, *, project=None):
        if not utils.supabase:
            st.error('Απαιτείται σύνδεση στη βάση για αποθήκευση.')
            return
        if project is not None and not save_project(project):
            return
        try:
            if original:
                result = utils.supabase.table('recurring_patterns').update({'notes': record['notes']}).eq(
                    'id', record['id']).eq('notes', original['notes']).execute()
            else:
                result = utils.supabase.table('recurring_patterns').insert(utils.serialize_dates(record)).execute()
            if not result.data:
                st.error('Δεν επιβεβαιώθηκε η αποθήκευση. Ανανεώστε τη λίστα και δοκιμάστε ξανά.')
        except Exception as exc:
            st.error(f'Δεν αποθηκεύτηκε η περιοδική εργασία: {exc}')
            result = None
        if project is not None:
            utils.log_activity('ΠΡΟΣΘΗΚΗ', 'projects', project['name'])
        if result is None or not result.data:
            if project is not None:
                utils.mark_data_changed()
                utils.touch_app_sync_state()
                st.info('Το νέο έργο δημιουργήθηκε. Μπορείτε να ξαναδοκιμάσετε την αποθήκευση της εργασίας.')
            return
        records = st.session_state.recurring_patterns
        st.session_state.recurring_patterns = [p for p in records if p['id'] != record['id']] + [record]
        utils.mark_data_changed()
        utils.touch_app_sync_state()
        utils.log_activity('ΠΕΡΙΟΔΙΚΗ ΕΡΓΑΣΙΑ', 'recurring_patterns',
                           f"{project_names.get(record['projectId'], '')} · {json.loads(record['notes'])['name']}")
        if original is None:
            st.session_state.periodic_new_counter = st.session_state.get('periodic_new_counter', 0) + 1
        st.rerun()

    def update_target(task, **changes):
        record = task['record']
        info = json.loads(record['notes'])
        info.update(changes)
        save_target({**record, 'notes': json.dumps(info, ensure_ascii=False)}, record)

    if st.button('🔄 Ανανέωση μετρητή'):
        st.session_state.last_sync_time = None
        st.rerun()

    if is_admin:
        with st.expander('➕ Νέα περιοδική εργασία'):
            form_key = f"periodic_new_{st.session_state.get('periodic_new_counter', 0)}"
            with st.form(form_key):
                project_id = st.selectbox('Έργο', list(project_names), format_func=project_names.get)
                new_project_name = st.text_input('Όνομα νέου έργου (προαιρετικό)',
                                                 help='Συμπληρώστε το για να χρησιμοποιήσετε νέο έργο.')
                name = st.text_input('Περιγραφή εργασίας', placeholder='π.χ. Καθαρισμός υαλοπινάκων')
                frequency = st.selectbox('Συχνότητα', list(FREQUENCIES), format_func=FREQUENCIES.get)
                target = st.number_input('Επισκέψεις ανά περίοδο', min_value=1, value=1, step=1)
                minimum, maximum = _spacing_inputs()
                start = st.date_input('Μήνας έναρξης', value=month,
                                      help='Η πρώτη περίοδος ξεκινά την πρώτη ημέρα αυτού του μήνα.')
                defaults_input = _placement_defaults_inputs(active_employee_names)
                if st.form_submit_button('Δημιουργία'):
                    project = None
                    new_project_name = new_project_name.strip()
                    if new_project_name:
                        project_id = next((pid for pid, project_name in project_names.items()
                                           if project_name.strip().casefold() == new_project_name.casefold()), None)
                        if project_id is None:
                            project_id = str(uuid.uuid4())
                            project = {'id': project_id, 'name': new_project_name, 'color': '#4a86e8'}
                    if not name.strip():
                        st.error('Συμπληρώστε περιγραφή εργασίας.')
                    elif project_id is None:
                        st.error('Επιλέξτε ένα έργο ή συμπληρώστε όνομα νέου έργου.')
                    elif maximum and minimum > maximum:
                        st.error('Η ελάχιστη απόσταση πρέπει να είναι έως τη μέγιστη.')
                    elif any(t['project_id'] == project_id and t['name'].strip().casefold() == name.strip().casefold()
                             for t in tasks):
                        st.error('Υπάρχει ήδη αυτή η περιοδική εργασία στο έργο.')
                    else:
                        try:
                            defaults = _placement_defaults(*defaults_input)
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            info = {'name': name.strip(), 'visit_target': int(target),
                                    'period_months': frequency, 'active': True,
                                    'min_gap_days': minimum, 'max_gap_days': maximum,
                                    'placement_defaults': defaults}
                            save_target({'id': str(uuid.uuid4()), 'projectId': project_id, 'type': TARGET_TYPE,
                                         'notes': json.dumps(info, ensure_ascii=False), 'employeeIds': [],
                                         'weekdays': [], 'startDate': start.replace(day=1),
                                         'startTime': '09:00', 'endTime': '17:00', 'arrivalTime': '',
                                         'colorName': 'Προεπιλογή'}, project=project)

    include_inactive = st.checkbox('Εμφάνιση ανενεργών εργασιών')
    for task in tasks:
        if not include_inactive and not task.get('active', True):
            continue
        bounds = period_bounds(task, month)
        if bounds is None:
            continue
        start, end = bounds
        last_day = end - timedelta(days=1)
        visits = count_visits(task, assignments, month)
        count = len(visits)
        adjusted_target = target_for_period(task, bounds)
        exception = period_exception(task, bounds)
        remaining = max(0, adjusted_target - count)
        cols = st.columns([3, 1, 1.5, 1, 2])
        cols[0].write(f"{project_names.get(task['project_id'], 'Άγνωστο έργο')} — {task['name']}")
        cols[0].caption(f"{FREQUENCIES[task['period_months']]} · {start:%d/%m/%Y}–{last_day:%d/%m/%Y}")
        cols[1].metric('Στόχος', adjusted_target)
        if exception:
            cols[0].caption(f"Εξαιρούνται {task['visit_target'] - adjusted_target} από {task['visit_target']} επισκέψεις · "
                            f"{exception['reason']}")
        with cols[2]:
            with st.expander(f'Στο πρόγραμμα · {count}'):
                _render_visit_list(visits, employee_names, section='period')
                previous = previous_month_visits(task, assignments, month)
                previous_start = (month - timedelta(days=1)).replace(day=1)
                st.markdown(f'**Προηγούμενος μήνας · {previous_start:%m/%Y} · {len(previous)}**')
                if previous:
                    _render_visit_list(previous, employee_names, section='previous')
                else:
                    st.caption('Δεν υπάρχουν προγραμματισμένες επισκέψεις για αυτόν τον μήνα.')
        cols[3].metric('Απομένουν', remaining)
        if is_admin and task.get('active', True) and cols[4].button('Προγραμμάτισε', key=f"periodic_add_{task['id']}"):
            prepare_new_placement(task, month)
        if count > adjusted_target:
            st.caption(f"Επισκέψεις πάνω από τον στόχο: {count} από {adjusted_target}")
        if is_admin:
            with st.expander('Εξαίρεση περιόδου · ' + task['name']):
                with st.form(f"periodic_exception_{task['id']}_{start.isoformat()}_{end.isoformat()}"):
                    st.caption(f'Περίοδος {start:%d/%m/%Y}–{last_day:%d/%m/%Y}')
                    waived = st.number_input('Επισκέψεις που εξαιρούνται', min_value=1,
                                             max_value=task['visit_target'], step=1,
                                             value=max(1, task['visit_target'] - adjusted_target))
                    reason = st.text_input('Αιτιολογία', value=exception['reason'] if exception else '')
                    save_exception = st.form_submit_button('Αποθήκευση εξαίρεσης')
                    remove_exception = exception and st.form_submit_button('Αφαίρεση εξαίρεσης')
                    if remove_exception:
                        update_target(task, period_exceptions=updated_exception(task, bounds, 0, ''))
                    elif save_exception:
                        try:
                            exceptions = updated_exception(task, bounds, waived, reason)
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            update_target(task, period_exceptions=exceptions)
            with st.expander('⚙️ Ρύθμιση · ' + task['name']):
                with st.form('periodic_edit_' + task['id']):
                    edited_name = st.text_input('Περιγραφή εργασίας', value=task['name'])
                    edited_frequency = st.selectbox(
                        'Συχνότητα', list(FREQUENCIES), index=list(FREQUENCIES).index(task['period_months']),
                        format_func=FREQUENCIES.get,
                        help='Αν αλλάξετε συχνότητα, οι περίοδοι υπολογίζονται ξανά από τον αρχικό μήνα έναρξης.',
                    )
                    edited_target = st.number_input('Επισκέψεις ανά περίοδο', min_value=1,
                                                    value=task['visit_target'], step=1)
                    minimum, maximum = _spacing_inputs(task)
                    active = st.checkbox('Ενεργή', value=task.get('active', True))
                    defaults_input = _placement_defaults_inputs(active_employee_names, task.get('placement_defaults'))
                    if st.form_submit_button('Αποθήκευση ρύθμισης'):
                        if not edited_name.strip():
                            st.error('Συμπληρώστε περιγραφή εργασίας.')
                        elif maximum and minimum > maximum:
                            st.error('Η ελάχιστη απόσταση πρέπει να είναι έως τη μέγιστη.')
                        elif any(t['id'] != task['id'] and t['project_id'] == task['project_id'] and
                                 t['name'].strip().casefold() == edited_name.strip().casefold() for t in tasks):
                            st.error('Υπάρχει ήδη αυτή η περιοδική εργασία στο έργο.')
                        else:
                            try:
                                defaults = _placement_defaults(*defaults_input)
                            except ValueError as exc:
                                st.error(str(exc))
                            else:
                                update_target(task, name=edited_name.strip(), visit_target=int(edited_target),
                                              period_months=edited_frequency, active=active,
                                              min_gap_days=minimum, max_gap_days=maximum, placement_defaults=defaults)
        st.divider()
    if not tasks:
        st.info('Προσθέστε περιοδική εργασία για να ορίσετε τη συχνότητα και τον στόχο επισκέψεων.')
