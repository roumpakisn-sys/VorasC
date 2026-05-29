import ast
import calendar
import uuid
from datetime import date, timedelta

import streamlit as st

import config
import scheduling


def auto_extend_recurring_patterns():
    """
    Αυτόματη επέκταση επαναλαμβανόμενων εργασιών.

    Μεταφέρθηκε από το utils.py χωρίς αλλαγή λειτουργικότητας.
    """
    import utils

    if not st.session_state.get('recurring_patterns'):
        return

    max_dates = {}
    for a in st.session_state.get('assignments', []):
        if not isinstance(a, dict):
            continue

        rid = a.get('recurring_id')
        if rid:
            d = utils.safe_date_parse(a.get('date'))
            if d:
                if rid not in max_dates or d > max_dates[rid]:
                    max_dates[rid] = d

    new_assignments_batch = []
    today = date.today()

    for pat in st.session_state.get('recurring_patterns', []):
        if not isinstance(pat, dict):
            continue

        rid = pat.get('id')
        if not rid:
            continue

        latest_date = max_dates.get(rid)

        if not latest_date:
            pat_start = utils.safe_date_parse(pat.get('startDate'))
            if pat_start:
                latest_date = pat_start - timedelta(days=1)
            else:
                latest_date = today - timedelta(days=1)

        if (latest_date - today).days <= 30:
            start_ext_date = latest_date + timedelta(days=1)
            target_end_date = today + timedelta(days=365)
            end_ext_date = max(start_ext_date + timedelta(days=30), target_end_date)

            if start_ext_date > end_ext_date:
                continue

            r_type = pat.get('type')

            r_emps_raw = pat.get('employeeIds', [])
            if isinstance(r_emps_raw, str):
                try:
                    r_emps = ast.literal_eval(r_emps_raw)
                except Exception:
                    r_emps = []
            else:
                r_emps = r_emps_raw

            r_proj = pat.get('projectId')
            r_color = pat.get('colorName')
            c_hex = config.BASIC_COLORS.get(r_color, "#999999")
            r_notes = pat.get('notes', "")
            str_arrival = pat.get('arrivalTime', "")
            str_start = str(pat.get('startTime'))[:5] if pat.get('startTime') else "09:00"
            str_end = str(pat.get('endTime'))[:5] if pat.get('endTime') else "17:00"

            weekdays_raw = pat.get('weekdays', [])
            if isinstance(weekdays_raw, str):
                try:
                    selected_weekdays = ast.literal_eval(weekdays_raw)
                except Exception:
                    selected_weekdays = []
            else:
                selected_weekdays = weekdays_raw

            dates_to_assign = []
            curr_date = start_ext_date
            day_map_inv = {
                0: "Δευτέρα",
                1: "Τρίτη",
                2: "Τετάρτη",
                3: "Πέμπτη",
                4: "Παρασκευή",
                5: "Σάββατο",
                6: "Κυριακή",
            }
            day_map = {v: k for k, v in day_map_inv.items()}

            selected_weekday_ints = []
            if selected_weekdays:
                for d_val in selected_weekdays:
                    if isinstance(d_val, int):
                        selected_weekday_ints.append(d_val)
                    elif d_val in day_map:
                        selected_weekday_ints.append(day_map[d_val])

            while curr_date <= end_ext_date:
                if r_type == "Εβδομαδιαία":
                    dates_to_assign.append(curr_date)
                    curr_date += timedelta(days=7)

                elif r_type == "Μηνιαία":
                    dates_to_assign.append(curr_date)
                    month = curr_date.month
                    year = curr_date.year

                    if month == 12:
                        month = 1
                        year += 1
                    else:
                        month += 1

                    try:
                        curr_date = curr_date.replace(year=year, month=month)
                    except ValueError:
                        last_day = calendar.monthrange(year, month)[1]
                        curr_date = curr_date.replace(year=year, month=month, day=last_day)

                elif r_type == "Επιλεγμένες Μέρες Εβδομάδας":
                    if curr_date.weekday() in selected_weekday_ints:
                        dates_to_assign.append(curr_date)
                    curr_date += timedelta(days=1)

                else:
                    curr_date += timedelta(days=1)

            for d in dates_to_assign:
                if r_type == "Επιλεγμένες Μέρες Εβδομάδας":
                    d_name = day_map_inv[d.weekday()]
                    emps_to_process = r_emps.get(d_name, []) if isinstance(r_emps, dict) else r_emps
                else:
                    emps_to_process = r_emps

                emps_to_process = emps_to_process if emps_to_process else [""]
                leaves_dict = st.session_state.get('leaves_by_emp', {})
                day_assigns = st.session_state.get('assignments_by_date', {}).get(d, [])

                for eid in emps_to_process:
                    final_eid = eid
                    final_start = str_start
                    final_end = str_end
                    conflict_note = ""

                    if eid:
                        if scheduling.is_on_leave(eid, d, leaves_dict):
                            final_eid = ""
                            emp_name = utils.get_employee_name(eid)
                            conflict_note = f"[Άδεια: {emp_name}]"
                        else:
                            adj_start, adj_end, is_conflict, msg = scheduling.check_and_resolve_conflict(
                                eid,
                                str_start,
                                str_end,
                                day_assigns,
                            )
                            if is_conflict:
                                final_eid = ""
                                emp_name = utils.get_employee_name(eid)
                                conflict_note = f"[Εμπλοκή: {emp_name}]"
                            else:
                                final_start = adj_start
                                final_end = adj_end

                    combined_notes = r_notes
                    if conflict_note:
                        combined_notes = f"{r_notes} {conflict_note}".strip()

                    new_assign = {
                        'id': str(uuid.uuid4()),
                        'recurring_id': rid,
                        'employeeId': final_eid,
                        'projectId': r_proj,
                        'date': d,
                        'arrivalTime': str_arrival,
                        'startTime': final_start,
                        'endTime': final_end,
                        'colorName': r_color,
                        'colorHex': c_hex,
                        'notes': combined_notes,
                        'is_cancelled': False,
                        'cancel_reason': "",
                    }

                    new_assignments_batch.append(new_assign)

                    if 'assignments_by_date' not in st.session_state:
                        st.session_state.assignments_by_date = {}
                    if d not in st.session_state.assignments_by_date:
                        st.session_state.assignments_by_date[d] = []
                    st.session_state.assignments_by_date[d].append(new_assign)

    if new_assignments_batch:
        if 'assignments' not in st.session_state:
            st.session_state.assignments = []

        st.session_state.assignments.extend(new_assignments_batch)
        st.session_state.data_dirty = True
        st.session_state.local_gantt_version = st.session_state.get('local_gantt_version', 0) + 1

        utils.db_insert_bulk_background(
            'assignments',
            new_assignments_batch,
            "ΑΥΤΟΜΑΤΗ ΕΠΕΚΤΑΣΗ",
            f"Επεκτάθηκαν {len(new_assignments_batch)} βάρδιες στο παρασκήνιο",
        )
