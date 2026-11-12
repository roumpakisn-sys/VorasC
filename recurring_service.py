from assignment_policy import recurring_assignment
from assignment_store import load_recurring_context
import ast
import calendar
import uuid
from datetime import date, timedelta

import streamlit as st

import config


def auto_extend_recurring_patterns():
    """
    Αυτόματη επέκταση επαναλαμβανόμενων εργασιών.

    Οι νέες βάρδιες ελέγχονται με τους κοινούς κανόνες διαθεσιμότητας.
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

            if not dates_to_assign:
                continue
            try:
                recurring_context = load_recurring_context(
                    utils.supabase, r_emps, min(dates_to_assign), max(dates_to_assign),
                )
            except Exception as exc:
                st.warning(f"Δεν έγινε αυτόματη επέκταση: αδυναμία ελέγχου διαθεσιμότητας ({exc}).")
                return

            for d in dates_to_assign:
                if r_type == "Επιλεγμένες Μέρες Εβδομάδας":
                    d_name = day_map_inv[d.weekday()]
                    emps_to_process = r_emps.get(d_name, []) if isinstance(r_emps, dict) else r_emps
                else:
                    emps_to_process = r_emps

                emps_to_process = emps_to_process if emps_to_process else [""]

                for eid in emps_to_process:
                    final_eid = eid
                    final_start = str_start
                    final_end = str_end
                    combined_notes = r_notes

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
                        'is_general': False,
                    }

                    new_assign, _ = recurring_assignment(new_assign, recurring_context, new_assignments_batch)
                    new_assignments_batch.append(new_assign)

    if new_assignments_batch:
        # Confirm persistence before extending session state. No optimistic background writes.
        if not utils.db_insert('assignments', new_assignments_batch, track=False):
            st.session_state.last_sync_time = None
            return
        st.session_state.assignments.extend(new_assignments_batch)
        for row in new_assignments_batch:
            st.session_state.setdefault('assignments_by_date', {}).setdefault(row['date'], []).append(row)
        utils.mark_data_changed()
