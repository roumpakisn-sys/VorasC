"""Monthly visit targets and placement links using the existing database schema."""
import base64
import json
import re
import uuid
from datetime import date, datetime

TARGET_TYPE = 'Μηνιαίος στόχος επισκέψεων'
MENU = 'Περιοδικές Εργασίες'
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
            count = int(info['monthly_target'])
            if not info['name'].strip() or count < 1:
                continue
        except (ValueError, TypeError, KeyError):
            continue
        tasks.append({**info, 'monthly_target': count, 'id': pattern['id'], 'project_id': pattern['projectId'],
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


def count_visits(task, assignments, month):
    """All crew rows sharing an occurrence count once per date, across bar splits."""
    visits = {}
    for row in assignments:
        day = as_day(row.get('date'))
        if not day or (day.year, day.month) != (month.year, month.month) or row.get('is_cancelled'):
            continue
        if row.get('projectId') != task['project_id']:
            continue
        link = split_notes(row.get('notes'))[1]
        if link and link['task_id'] == task['id']:
            visits.setdefault((day, link['visit_id']), []).append(row)
    return sorted(visits.items(), key=lambda item: (item[0][0], str(item[1][0].get('startTime') or '')))


def remaining_visits(tasks, assignments, month):
    return sum(max(0, task['monthly_target'] - len(count_visits(task, assignments, month)))
               for task in tasks if task.get('active', True) and
               (not task['start'] or task['start'] <= month.replace(day=1)))


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


def render_gantt_summary(today, *, key):
    import streamlit as st

    tasks = get_targets(st.session_state.get('recurring_patterns', []))
    if not tasks:
        return
    count = remaining_visits(tasks, st.session_state.assignments, today)
    if st.button(f'📌 Απομένουν {count} περιοδικές επισκέψεις αυτόν τον μήνα',
                 key=key, use_container_width=True):
        st.session_state.management_menu = MENU
        st.session_state.periodic_month = today.replace(day=1)
        st.switch_page('pages/2_Management.py')


def render_management(is_admin):
    import streamlit as st
    import utils
    from gantt_helpers import get_local_today

    st.title('📌 Περιοδικές Εργασίες')
    tasks = get_targets(st.session_state.recurring_patterns)
    project_names = {p['id']: p['name'] for p in st.session_state.projects}
    month = st.date_input('Μήνας παρακολούθησης', value=get_local_today().replace(day=1),
                          key='periodic_month').replace(day=1)
    st.caption('Ο μετρητής περιλαμβάνει τις καταχωρισμένες, μη ακυρωμένες επισκέψεις του μήνα.')

    def save_target(record, original=None):
        if not utils.supabase:
            st.error('Απαιτείται σύνδεση στη βάση για αποθήκευση.')
            return
        try:
            if original:
                result = utils.supabase.table('recurring_patterns').update({'notes': record['notes']}).eq(
                    'id', record['id']).eq('notes', original['notes']).execute()
            else:
                result = utils.supabase.table('recurring_patterns').insert(utils.serialize_dates(record)).execute()
            if not result.data:
                st.error('Δεν επιβεβαιώθηκε η αποθήκευση. Ανανεώστε τη λίστα και δοκιμάστε ξανά.')
                return
        except Exception as exc:
            st.error(f'Δεν αποθηκεύτηκε η περιοδική εργασία: {exc}')
            return
        records = st.session_state.recurring_patterns
        st.session_state.recurring_patterns = [p for p in records if p['id'] != record['id']] + [record]
        utils.mark_data_changed()
        utils.touch_app_sync_state()
        utils.log_activity('ΠΕΡΙΟΔΙΚΗ ΕΡΓΑΣΙΑ', 'recurring_patterns',
                           f"{project_names.get(record['projectId'], '')} · {json.loads(record['notes'])['name']}")
        st.rerun()

    if st.button('🔄 Ανανέωση μετρητή'):
        st.session_state.last_sync_time = None
        st.rerun()

    if is_admin and project_names:
        with st.expander('➕ Νέα περιοδική εργασία'):
            with st.form('periodic_new', clear_on_submit=True):
                project_id = st.selectbox('Έργο', list(project_names), format_func=project_names.get)
                name = st.text_input('Περιγραφή εργασίας', placeholder='π.χ. Καθαρισμός υαλοπινάκων')
                target = st.number_input('Επισκέψεις ανά μήνα', min_value=1, value=2, step=1)
                start = st.date_input('Έναρξη παρακολούθησης', value=month)
                if st.form_submit_button('Δημιουργία'):
                    if not name.strip():
                        st.error('Συμπληρώστε περιγραφή εργασίας.')
                    elif any(t['project_id'] == project_id and t['name'].strip().casefold() == name.strip().casefold()
                             for t in tasks):
                        st.error('Υπάρχει ήδη αυτή η περιοδική εργασία στο έργο.')
                    else:
                        info = {'name': name.strip(), 'monthly_target': int(target), 'active': True}
                        save_target({'id': str(uuid.uuid4()), 'projectId': project_id, 'type': TARGET_TYPE,
                                     'notes': json.dumps(info, ensure_ascii=False), 'employeeIds': [],
                                     'weekdays': [], 'startDate': start.replace(day=1),
                                     'startTime': '09:00', 'endTime': '17:00', 'arrivalTime': '',
                                     'colorName': 'Προεπιλογή'})

    include_inactive = st.checkbox('Εμφάνιση ανενεργών εργασιών')
    for task in tasks:
        if not include_inactive and not task.get('active', True):
            continue
        if task['start'] and task['start'] > month:
            continue
        visits = count_visits(task, st.session_state.assignments, month)
        count = len(visits)
        remaining = max(0, task['monthly_target'] - count)
        cols = st.columns([3, 1, 1.5, 1, 2])
        cols[0].write(f"{project_names.get(task['project_id'], 'Άγνωστο έργο')} — {task['name']}")
        cols[1].metric('Στόχος', task['monthly_target'])
        with cols[2]:
            with st.expander(f'Στο πρόγραμμα · {count}'):
                for (day, _), rows in visits:
                    employee_names = {e['id']: e['name'] for e in st.session_state.employees}
                    names = list(dict.fromkeys(employee_names.get(r.get('employeeId'), 'Χωρίς προσωπικό') for r in rows))
                    st.write(f"{day:%d/%m/%Y} · {rows[0].get('startTime', '')}–{rows[0].get('endTime', '')}")
                    st.caption(', '.join(names))
                    if st.button('Άνοιγμα μπάρας', key=f"periodic_open_{rows[0]['id']}"):
                        open_placement(day, rows[0]['id'])
        cols[3].metric('Απομένουν', remaining)
        if is_admin and task.get('active', True) and cols[4].button('Προγραμμάτισε', key=f"periodic_add_{task['id']}"):
            prepare_new_placement(task, month)
        if count > task['monthly_target']:
            st.caption(f"Επισκέψεις πάνω από τον στόχο: {count} από {task['monthly_target']}")
        if is_admin:
            with st.expander('⚙️ Ρύθμιση · ' + task['name']):
                with st.form('periodic_edit_' + task['id']):
                    edited_name = st.text_input('Περιγραφή εργασίας', value=task['name'])
                    edited_target = st.number_input('Επισκέψεις ανά μήνα', min_value=1,
                                                    value=task['monthly_target'], step=1)
                    active = st.checkbox('Ενεργή', value=task.get('active', True))
                    if st.form_submit_button('Αποθήκευση ρύθμισης'):
                        if not edited_name.strip():
                            st.error('Συμπληρώστε περιγραφή εργασίας.')
                        elif any(t['id'] != task['id'] and t['project_id'] == task['project_id'] and
                                 t['name'].strip().casefold() == edited_name.strip().casefold() for t in tasks):
                            st.error('Υπάρχει ήδη αυτή η περιοδική εργασία στο έργο.')
                        else:
                            info = {'name': edited_name.strip(), 'monthly_target': int(edited_target), 'active': active}
                            save_target({**task['record'], 'notes': json.dumps(info, ensure_ascii=False)}, task['record'])
        st.divider()
    if not tasks:
        st.info('Προσθέστε περιοδική εργασία για να ορίσετε τον μηνιαίο στόχο επισκέψεων.')
