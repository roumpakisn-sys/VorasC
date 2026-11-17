"""Search scheduled assignments and open their existing Gantt bar."""

import unicodedata


def _search_text(value):
    return ''.join(c for c in unicodedata.normalize('NFD', str(value or '').casefold())
                   if not unicodedata.combining(c))


def find_placements(assignments_by_date, projects, employees, query, from_date=None):
    words = _search_text(query).split()
    if not words:
        return []

    project_names = {pid: row.get('name') or 'Άγνωστο έργο' for pid, row in projects.items()}
    employee_names = {eid: row.get('name') or 'Άγνωστος εργαζόμενος' for eid, row in employees.items()}
    project_text = {pid: _search_text(name) for pid, name in project_names.items()}
    employee_text = {eid: _search_text(name) for eid, name in employee_names.items()}
    results = []
    for day in sorted(assignments_by_date):
        if from_date is not None and day < from_date:
            continue
        matches = []
        for row in assignments_by_date[day]:
            assignment_id = row.get('id')
            if not assignment_id:
                continue
            pid, eid = row.get('projectId'), row.get('employeeId')
            searchable = f'{project_text.get(pid, "")} {employee_text.get(eid, "")}'
            if not all(word in searchable for word in words):
                continue
            project = project_names.get(pid, 'Άγνωστο έργο')
            employee = employee_names.get(eid, 'Άγνωστος εργαζόμενος' if eid else 'Χωρίς προσωπικό')
            start = str(row.get('startTime') or '')[:5]
            end = str(row.get('endTime') or '')[:5]
            cancelled = ' · Ακυρωμένη' if row.get('is_cancelled') else ''
            label = f'{day:%d/%m/%Y} · {start}–{end} · {project} · {employee}{cancelled}'
            matches.append((start, project.casefold(), employee.casefold(), str(assignment_id), label))
        results.extend((day, assignment_id, label) for _, _, _, assignment_id, label in sorted(matches))
    return results


def reveal_search_project(filtered, unfiltered, target):
    """Temporarily show the project on the selected date if its bar is hidden."""
    if not target:
        return filtered
    day, assignment_id = target
    if any(str(row.get('id')) == assignment_id for row in filtered.get(day, ())):
        return filtered
    original = unfiltered.get(day, ())
    match = next((row for row in original if str(row.get('id')) == assignment_id), None)
    if match is None:
        return filtered

    visible_ids = {row.get('id') for row in filtered.get(day, ())}
    return {**filtered, day: [row for row in original if row.get('id') in visible_ids
                              or row.get('projectId') == match.get('projectId')]}


def find_search_bar(groups, target):
    if not target:
        return None
    day, assignment_id = target
    return next((key for key, group in groups.items() if group['Date'] == day and
                 any(str(row_id) == assignment_id for row_id in group['AssignmentIds'])), None)


def render_schedule_search(state, today, on_open, *, key):
    import streamlit as st

    page_key = f'{key}_page'

    def reset_page():
        state[page_key] = 1

    with st.expander('🔎 Αναζήτηση σε όλο το πρόγραμμα'):
        query = st.text_input('Εργαζόμενος ή έργο', placeholder='π.χ. Μαρία ή ISOMAT',
                              key=f'{key}_query', on_change=reset_page)
        if not query.strip():
            return
        include_past = st.checkbox('Να εμφανίζονται και παλιότερες τοποθετήσεις',
                                   key=f'{key}_past', on_change=reset_page)
        matches = find_placements(state.assignments_by_date, state.proj_map, state.emp_map,
                                  query, from_date=None if include_past else today)
        if not matches:
            st.info('Δεν βρέθηκαν τοποθετήσεις για αυτή την αναζήτηση.')
            return

        page_size = 12
        page_count = (len(matches) + page_size - 1) // page_size
        st.caption(f'Τοποθετήσεις που βρέθηκαν: {len(matches)}')
        if page_count > 1:
            if not 1 <= state.get(page_key, 1) <= page_count:
                state[page_key] = 1
            page = st.number_input('Σελίδα αποτελεσμάτων', min_value=1, max_value=page_count,
                                   step=1, key=page_key)
        else:
            page = 1
        first = (page - 1) * page_size
        for day, assignment_id, label in matches[first:first + page_size]:
            st.button(label, key=f'{key}_result_{assignment_id}', use_container_width=True,
                      on_click=on_open, args=(day, assignment_id))
