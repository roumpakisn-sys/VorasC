import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, date, timedelta
import uuid
import textwrap
import time
import re
import hashlib
import base64
from st_click_detector import click_detector

# --- INITIALIZATION & ΑΣΠΙΔΑ ΑΣΦΑΛΕΙΑΣ ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "employees" not in st.session_state:
    st.session_state.employees = []
if "projects" not in st.session_state:
    st.session_state.projects = []
if "assignments" not in st.session_state:
    st.session_state.assignments = []
if "leaves" not in st.session_state:
    st.session_state.leaves = []
if "recurring_patterns" not in st.session_state:
    st.session_state.recurring_patterns = []
if "evaluations" not in st.session_state:
    st.session_state.evaluations = []

if not st.session_state.get("authenticated"):
    st.switch_page("streamlit_app.py")
    st.stop()

import config
import utils
import scheduling
import gantt_engine
import gantt_html
import gantt_controls
import gantt_export
import gantt_excel_export
import gantt_filters
from gantt_helpers import get_local_today, normalize_id_list, clean_conflict_leave_notes


# Οι βοηθητικές συναρτήσεις Gantt μεταφέρθηκαν στο gantt_helpers.py.
# Κρατάμε εδώ μόνο τις κλήσεις τους, χωρίς αλλαγή λειτουργικότητας.





utils.init_data_and_sync()

total_indexed = sum(len(v) for v in st.session_state.get("assignments_by_date", {}).values())
if total_indexed != len(st.session_state.get("assignments", [])):
    utils.mark_data_changed()
    utils.init_data_and_sync()

utils.setup_shared_ui()

is_full_admin = st.session_state.get("current_user") != "TAN"
active_employee_ids = [e["id"] for e in st.session_state.employees if e.get("status", "Ενεργός") == "Ενεργός"]

if "clicked_key" not in st.session_state:
    st.session_state.clicked_key = None
if "trigger_scroll" not in st.session_state:
    st.session_state.trigger_scroll = False
if "edit_bar_select_widget" not in st.session_state:
    st.session_state.edit_bar_select_widget = ""
if "last_clicked_safe_id" not in st.session_state:
    st.session_state.last_clicked_safe_id = ""
if "reset_edit_bar_select_next_run" not in st.session_state:
    st.session_state.reset_edit_bar_select_next_run = False
if "suppress_next_detector_click" not in st.session_state:
    st.session_state.suppress_next_detector_click = False
if "detector_version" not in st.session_state:
    st.session_state.detector_version = 0

# --- ΜΗΧΑΝΙΣΜΟΣ ΗΜΕΡΟΜΗΝΙΑΣ ΚΑΙ ΕΚΚΑΘΑΡΙΣΗ ΚΛΙΚ ---
if "view_week_date" not in st.session_state:
    st.session_state.view_week_date = get_local_today()


def clear_bar_selection():
    st.session_state.clicked_key = None
    st.session_state.trigger_scroll = False
    st.session_state.last_clicked_safe_id = ""
    st.session_state.suppress_next_detector_click = True
    st.session_state.reset_edit_bar_select_next_run = True
    st.session_state.detector_version = st.session_state.get("detector_version", 0) + 1


def preserve_context_notes(original_notes, edited_notes):
    """
    Κρατάει τις κρυφές πληροφορίες συμφραζομένων από τις παρατηρήσεις
    όταν γίνεται επεξεργασία μπάρας.

    Το πεδίο Παρατηρήσεις εμφανίζει καθαρισμένο κείμενο, χωρίς tags τύπου:
    [Άδεια: Όνομα] ή [Εμπλοκή: Όνομα].
    Όταν ο χρήστης προσθέτει νέα παρατήρηση ή νέο προσωπικό, αυτά τα tags
    δεν πρέπει να χάνονται από την παλιά μπάρα.
    """
    result = (edited_notes or "").strip()
    original = original_notes or ""

    preserved_tags = re.findall(r"\[(?:Άδεια|Εμπλοκή):\s*[^\]]+\]", original)
    for tag in preserved_tags:
        if tag and tag not in result:
            result = f"{result} {tag}".strip()

    return result


# Το πάνω control panel του Gantt μεταφέρθηκε στο gantt_controls.py.
# Επιστρέφει τις ίδιες τιμές που υπολογίζονταν πριν μέσα στη σελίδα.
start_of_week, zoom_level, zoom_factor, presentation_mode, gantt_height_px = gantt_controls.render_gantt_controls(clear_bar_selection)

# --- ΦΙΛΤΡΟ ΟΡΑΤΟΤΗΤΑΣ ΕΠΑΝΑΛΑΜΒΑΝΟΜΕΝΩΝ ΕΡΓΩΝ ---
# Κρύβει/εμφανίζει μόνο τις μπάρες που προέρχονται από επαναλαμβανόμενες εργασίες.
# Δεν διαγράφει, δεν τροποποιεί και δεν σταματά καμία επαναλαμβανόμενη εργασία.
visible_recurring_project_ids = gantt_filters.render_recurring_project_visibility_filter(
    projects=st.session_state.projects,
    recurring_patterns=st.session_state.recurring_patterns,
    on_change=clear_bar_selection,
)
filtered_assignments_by_date = gantt_filters.apply_recurring_project_visibility_filter(
    assignments_by_date=st.session_state.assignments_by_date,
    visible_project_ids=visible_recurring_project_ids,
)
recurring_filter_version = gantt_filters.get_recurring_filter_version(visible_recurring_project_ids)


# --- ΕΞΑΓΩΓΗ ΔΕΔΟΜΕΝΩΝ ΑΠΟ ΤΟ ENGINE ---
# ΠΡΟΣΟΧΗ:
# Δεν κάνουμε cache τα δεδομένα του Gantt εδώ.
# Τα assignments/projects/employees περνάνε ως ορίσματα με "_" για λόγους hashability,
# άρα το Streamlit δεν τα συμπεριλαμβάνει στο cache key.
# Αυτό μπορούσε να κάνει διαφορετικούς χρήστες να βλέπουν διαφορετική/παλιά εικόνα.
def get_cached_data(
    start_of_week,
    zoom_factor,
    presentation_mode,
    data_version,
    _assignments_by_date,
    _leaves,
    _employees,
    _projects,
    _emp_map,
    _proj_map,
):
    _, wk_groups, export_data = gantt_engine.generate_gantt_chart(
        start_of_week,
        zoom_factor,
        presentation_mode,
        data_version,
        _assignments_by_date,
        _leaves,
        _employees,
        _projects,
        _emp_map,
        _proj_map,
    )
    return wk_groups, export_data


wk_groups, export_data = get_cached_data(
    start_of_week,
    zoom_factor,
    presentation_mode,
    f"{st.session_state.get('local_gantt_version', 0)}_{recurring_filter_version}",
    filtered_assignments_by_date,
    st.session_state.leaves,
    st.session_state.employees,
    st.session_state.projects,
    st.session_state.emp_map,
    st.session_state.proj_map,
)

# Φτιάχνουμε απόλυτα ΜΟΝΑΔΙΚΑ IDs χρησιμοποιώντας HASH, αποκλείοντας συγκρούσεις!
safe_mapping = {}
key_to_safe_id = {}
for real_key in wk_groups.keys():
    safe_id = "bar_" + hashlib.md5(real_key.encode("utf-8")).hexdigest()
    safe_mapping[safe_id] = real_key
    key_to_safe_id[real_key] = safe_id


# --- NATIVE HTML GANTT CHART BUILDER ---
# Η υλοποίηση μεταφέρθηκε στο gantt_html.py.
# Κρατάμε εδώ μόνο την κλήση, ώστε να μη αλλάξει η λειτουργία της σελίδας.


# --- ΕΜΦΑΝΙΣΗ ΚΑΙ ΕΝΤΟΠΙΣΜΟΣ ΚΛΙΚ ---
html_chart = gantt_html.build_html_gantt(wk_groups, start_of_week, zoom_factor, key_to_safe_id, gantt_height_px)
clicked_safe_id = click_detector(
    html_chart,
    key=f"gantt_detector_{st.session_state.detector_version}_{st.session_state.gantt_height_px}",
)

# --- ΕΞΑΓΩΓΗ GANTT ΣΕ HTML ---
downloadable_gantt_html = f"""<!doctype html>
<html lang="el">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Gantt Πρόγραμμα - {start_of_week.strftime('%d/%m/%Y')}</title>
    <style>
        body {{
            margin: 0;
            padding: 18px;
            background: #f8fafc;
            font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
        }}
        .export-title {{
            margin: 0 0 12px 0;
            color: #0f172a;
            font-size: 22px;
            font-weight: 800;
        }}
        .export-subtitle {{
            margin: 0 0 18px 0;
            color: #475569;
            font-size: 14px;
        }}
        #gantt-master-container {{
            height: calc(100vh - 110px) !important;
            max-height: none !important;
        }}
    </style>
</head>
<body>
    <h1 class="export-title">Πρόγραμμα Gantt</h1>
    <div class="export-subtitle">
        Εβδομάδα: {start_of_week.strftime('%d/%m/%Y')} - {(start_of_week + timedelta(days=6)).strftime('%d/%m/%Y')}
    </div>
    {html_chart}
</body>
</html>
"""

st.download_button(
    "🌐 Εξαγωγή Gantt σε HTML",
    data=downloadable_gantt_html.encode("utf-8"),
    file_name=f"gantt_programma_{start_of_week.strftime('%Y_%m_%d')}.html",
    mime="text/html",
    use_container_width=True,
)

if st.session_state.get("suppress_next_detector_click", False):
    st.session_state.suppress_next_detector_click = False
elif clicked_safe_id:
    real_clicked_key = safe_mapping.get(clicked_safe_id, None)

    if clicked_safe_id != st.session_state.last_clicked_safe_id:
        st.session_state.last_clicked_safe_id = clicked_safe_id

        if real_clicked_key:
            st.session_state.clicked_key = real_clicked_key
            st.session_state.edit_bar_select_widget = real_clicked_key
            st.session_state.trigger_scroll = True
            st.session_state.skip_remote_sync_once = True
            st.rerun()

if st.session_state.get("clicked_key"):
    st.markdown('<div id="is_editing_flag" style="display:none;"></div>', unsafe_allow_html=True)

# --- ΕΝΟΤΗΤΑ ΕΞΑΓΩΓΗΣ EXCEL ---
# Η απλή εξαγωγή παραμένει στο gantt_export.py.
# Η οπτική εξαγωγή με συγχωνευμένα κελιά μπαίνει σε ξεχωριστό module,
# ώστε να μην αλλάξει η λειτουργία του Gantt.
gantt_excel_export.render_employee_day_excel_export(get_local_today())
gantt_excel_export.render_visual_gantt_month_export(filtered_assignments_by_date, start_of_week)
gantt_excel_export.render_visual_gantt_excel_export(wk_groups, start_of_week)
gantt_export.render_gantt_export(export_data, start_of_week)

# --- ΠΡΟΣΩΡΙΝΗ ΑΝΤΙΓΡΑΦΗ ΣΤΟΙΧΕΙΩΝ ΦΟΡΜΩΝ / ΕΠΙΛΟΓΗ ΗΜΕΡΟΜΗΝΙΩΝ ---
# Το πρόχειρο παραμένει μόνο στο session του χρήστη. Δεν γράφει στη Supabase.
GANTT_DATES_CONTINUOUS = "Συνεχόμενες ημέρες"
GANTT_DATES_SPECIFIC = "Συγκεκριμένες ημερομηνίες"


def _form_time(value, fallback="09:00"):
    """Accept stored HH:MM values or datetime.time for st.time_input."""
    raw = str(value or fallback)[:5]
    try:
        return datetime.strptime(raw, "%H:%M").time()
    except ValueError:
        return datetime.strptime(fallback, "%H:%M").time()


def _gantt_target_dates(first_date, mode, duration, additional_dates):
    """Return explicit dates; duplicates are errors, never silent extra jobs."""
    if mode == GANTT_DATES_CONTINUOUS:
        dates = [first_date + timedelta(days=i) for i in range(int(duration))]
    else:
        dates = [first_date] + list(additional_dates)
    if not dates or len(dates) != len(set(dates)):
        raise ValueError("Υπάρχουν ίδιες ημερομηνίες. Κάθε ημερομηνία πρέπει να είναι διαφορετική.")
    return dates


def _save_placement_clipboard(payload):
    """Copy editable form values, not Supabase credentials/row identities."""
    st.session_state["gantt_placement_clipboard"] = dict(payload)
    st.toast("📋 Τα στοιχεία αντιγράφηκαν. Μπορείς να τα επικολλήσεις και στην άλλη φόρμα.", icon="📋")


def _form_prefill_date(raw, fallback):
    return utils.safe_date_parse(raw) or fallback


def _form_clipboard_payload(*, first_date, mode, duration, extra_dates,
                            project_id, custom_project, employee_ids, color_name,
                            notes, is_general, use_arrival, arrival_time,
                            start_time, end_time, is_cancelled=False, cancel_reason=""):
    return {
        "first_date": first_date,
        "mode": mode,
        "duration": int(duration),
        "extra_dates": list(extra_dates),
        "project_id": project_id,
        "custom_project": custom_project,
        "employee_ids": list(employee_ids),
        "color": color_name,
        "notes": notes,
        "is_general": bool(is_general),
        "use_arrival": bool(use_arrival),
        "arrival_time": arrival_time.strftime("%H:%M"),
        "start_time": start_time.strftime("%H:%M"),
        "end_time": end_time.strftime("%H:%M"),
        "is_cancelled": bool(is_cancelled),
        "cancel_reason": cancel_reason or "",
    }


# --- ΦΟΡΜΕΣ ΠΡΟΣΘΗΚΗΣ ΚΑΙ ΕΠΕΞΕΡΓΑΣΙΑΣ ΜΠΑΡΑΣ ---
if not presentation_mode:
    st.divider()
    if is_full_admin:
        col_add, col_edit = st.columns(2)

        with col_add:
            st.subheader("➕ Νέα Τοποθέτηση")
            if "qa_rc" not in st.session_state:
                st.session_state.qa_rc = 0
            qa_rc = st.session_state.qa_rc
            clipboard = st.session_state.get("gantt_placement_clipboard")
            if st.button(
                "📥 Επικόλληση όλων των στοιχείων",
                key="qa_paste_from_clipboard",
                disabled=not clipboard,
                use_container_width=True,
                help="Συμπληρώνει τη φόρμα, χωρίς να καταχωρεί εργασίες.",
            ):
                st.session_state["qa_form_prefill"] = dict(clipboard)
                st.session_state["qa_date_mode"] = clipboard.get("mode", GANTT_DATES_CONTINUOUS)
                st.session_state["qa_specific_count"] = max(2, len(clipboard.get("extra_dates", [])) + 1)
                st.session_state.qa_rc += 1
                st.rerun()

            qa_prefill = st.session_state.get("qa_form_prefill") or {}
            qa_date_mode = st.radio(
                "Τρόπος επιλογής ημερών νέας τοποθέτησης",
                [GANTT_DATES_CONTINUOUS, GANTT_DATES_SPECIFIC],
                horizontal=True,
                key="qa_date_mode",
            )
            qa_specific_count = 1
            if qa_date_mode == GANTT_DATES_SPECIFIC:
                qa_specific_count = st.number_input(
                    "Πόσες συγκεκριμένες ημερομηνίες;",
                    min_value=2, max_value=20, value=2, step=1,
                    key="qa_specific_count",
                )
                st.caption("Συμπλήρωσε την πρώτη ημερομηνία και τις επιπλέον, ακόμη κι αν δεν είναι συνεχόμενες.")

            with st.form("quick_add", clear_on_submit=False):
                qa_first_default = _form_prefill_date(
                    qa_prefill.get("first_date"), st.session_state.view_week_date
                )
                add_date = st.date_input(
                    "Πρώτη ημερομηνία", value=qa_first_default, key=f"qa_date_{qa_rc}"
                )
                duration_days = 1
                extra_add_dates = []
                if qa_date_mode == GANTT_DATES_CONTINUOUS:
                    duration_days = st.number_input(
                        "Διάρκεια (Συνεχόμενες Ημέρες)",
                        min_value=1, max_value=365,
                        value=max(1, min(365, int(qa_prefill.get("duration", 1)))),
                        step=1, key=f"qa_dur_{qa_rc}",
                    )
                else:
                    saved_extra = qa_prefill.get("extra_dates", [])
                    for i in range(int(qa_specific_count) - 1):
                        initial_day = (
                            _form_prefill_date(saved_extra[i], add_date + timedelta(days=i + 1))
                            if i < len(saved_extra) else add_date + timedelta(days=i + 1)
                        )
                        extra_add_dates.append(
                            st.date_input(
                                f"{i + 2}η ημερομηνία", value=initial_day,
                                key=f"qa_specific_{qa_rc}_{i}",
                            )
                        )

                proj_choice = st.selectbox(
                    "Επιλογή Έργου (Από Λίστα)",
                    options=[p["id"] for p in st.session_state.projects],
                    format_func=utils.get_project_name,
                    index=(
                        [p["id"] for p in st.session_state.projects].index(qa_prefill.get("project_id"))
                        if qa_prefill.get("project_id") in [p["id"] for p in st.session_state.projects]
                        else 0
                    ),
                    key=f"qa_proj_{qa_rc}",
                )
                custom_proj_name = st.text_input(
                    "Ή πληκτρολογήστε Νέο Έργο (Αν συμπληρωθεί, αγνοεί την παραπάνω λίστα)",
                    value=str(qa_prefill.get("custom_project") or ""),
                    key=f"qa_cproj_{qa_rc}",
                )
                emp_choices = st.multiselect(
                    "Προσωπικό (Προαιρετικό - Μόνο Ενεργοί)",
                    options=active_employee_ids,
                    default=[eid for eid in qa_prefill.get("employee_ids", []) if eid in active_employee_ids],
                    format_func=utils.get_employee_name,
                    key=f"qa_emps_{qa_rc}",
                )

                c_color, c_notes = st.columns(2)
                with c_color:
                    color_choice = st.selectbox(
                        "Χρώμα Μπάρας", options=list(config.BASIC_COLORS.keys()),
                        index=(list(config.BASIC_COLORS.keys()).index(qa_prefill["color"])
                               if qa_prefill.get("color") in config.BASIC_COLORS else 0),
                        key=f"qa_color_{qa_rc}",
                    )
                with c_notes:
                    add_notes = st.text_input(
                        "Παρατηρήσεις (Προαιρετικό)",
                        value=str(qa_prefill.get("notes") or ""),
                        key=f"qa_notes_{qa_rc}",
                    )

                is_general = st.checkbox(
                    "Γενικός", value=bool(qa_prefill.get("is_general", False)),
                    key=f"qa_general_{qa_rc}",
                )

                c_arr, c_start, c_end = st.columns(3)
                with c_arr:
                    use_arr = st.checkbox(
                        "Προσέλευση;", value=bool(qa_prefill.get("use_arrival", False)),
                        key=f"chk_arr_{qa_rc}",
                    )
                    t_arrival = st.time_input(
                        "Ώρα Προσέλευσης", value=_form_time(qa_prefill.get("arrival_time"), "08:00"),
                        key=f"qa_arrival_{qa_rc}",
                    )
                with c_start:
                    t_start = st.time_input(
                        "Έναρξη", value=_form_time(qa_prefill.get("start_time"), "09:00"),
                        key=f"qa_start_{qa_rc}",
                    )
                with c_end:
                    t_end = st.time_input(
                        "Λήξη", value=_form_time(qa_prefill.get("end_time"), "17:00"),
                        key=f"qa_end_{qa_rc}",
                    )

                c_add_save, c_add_copy = st.columns(2)
                with c_add_save:
                    submit_new = st.form_submit_button("✅ Καταχώρηση", use_container_width=True)
                with c_add_copy:
                    copy_new = st.form_submit_button("📋 Αντιγραφή στοιχείων", use_container_width=True)

                if copy_new:
                    _save_placement_clipboard(_form_clipboard_payload(
                        first_date=add_date, mode=qa_date_mode,
                        duration=duration_days, extra_dates=extra_add_dates,
                        project_id=proj_choice, custom_project=custom_proj_name,
                        employee_ids=emp_choices, color_name=color_choice,
                        notes=add_notes, is_general=is_general,
                        use_arrival=use_arr, arrival_time=t_arrival,
                        start_time=t_start, end_time=t_end,
                    ))

                if submit_new:
                    str_arrival = t_arrival.strftime("%H:%M") if use_arr else ""
                    str_start = t_start.strftime("%H:%M")
                    str_end = t_end.strftime("%H:%M")

                    try:
                        new_target_dates = _gantt_target_dates(
                            add_date, qa_date_mode, duration_days, extra_add_dates
                        )
                    except ValueError as exc:
                        st.error(str(exc))
                        new_target_dates = []

                    if str_start >= str_end:
                        st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                    elif not new_target_dates:
                        pass  # Η επιλογή ημερομηνιών απέτυχε: δεν γίνεται αποθήκευση.
                    else:
                        emps_to_process = emp_choices if emp_choices else [""]
                        new_assigns = []

                        if custom_proj_name.strip():
                            c_name = custom_proj_name.strip()
                            existing_p = next(
                                (p for p in st.session_state.projects if p["name"].strip().lower() == c_name.lower()),
                                None,
                            )
                            if existing_p:
                                final_proj_id = existing_p["id"]
                            else:
                                final_proj_id = str(uuid.uuid4())
                                new_p = {"id": final_proj_id, "name": c_name, "color": config.BASIC_COLORS[color_choice]}
                                st.session_state.projects.append(new_p)
                                utils.db_insert("projects", new_p, track=False)
                        else:
                            final_proj_id = proj_choice

                        for current_assign_date in new_target_dates:
                            valid_assignments = []

                            for eid in emps_to_process:
                                if eid:
                                    emp_name = utils.get_employee_name(eid)
                                    if scheduling.is_on_leave(eid, current_assign_date, st.session_state.leaves_by_emp):
                                        valid_assignments.append(
                                            {"eid": "", "start": str_start, "end": str_end, "msg": f"[Άδεια: {emp_name}]", "emp_name": emp_name}
                                        )
                                        st.toast(
                                            f"Ο/Η {emp_name} έχει άδεια στις {current_assign_date.strftime('%d/%m')}. Καταχωρήθηκε ως 'Χωρίς Προσωπικό'.",
                                            icon="⚠️",
                                        )
                                    else:
                                        day_assigns = st.session_state.assignments_by_date.get(current_assign_date, [])
                                        adj_start, adj_end, is_conflict, msg = scheduling.check_and_resolve_conflict(
                                            eid, str_start, str_end, day_assigns
                                        )
                                        if is_conflict:
                                            valid_assignments.append(
                                                {"eid": "", "start": str_start, "end": str_end, "msg": f"[Εμπλοκή: {emp_name}]", "emp_name": emp_name}
                                            )
                                            st.toast(
                                                f"Διπλοκράτηση {emp_name} στις {current_assign_date.strftime('%d/%m')}. Καταχωρήθηκε ως 'Χωρίς Προσωπικό'.",
                                                icon="⚠️",
                                            )
                                        else:
                                            valid_assignments.append({"eid": eid, "start": adj_start, "end": adj_end, "msg": msg, "emp_name": emp_name})
                                else:
                                    valid_assignments.append({"eid": "", "start": str_start, "end": str_end, "msg": "", "emp_name": ""})

                            for va in valid_assignments:
                                if va["msg"] == "Allowed Overlap":
                                    st.toast(
                                        f"ℹ️ Επιτράπηκε επικάλυψη ωραρίου για τον/την {va['emp_name']} στις {current_assign_date.strftime('%d/%m')}.",
                                        icon="ℹ️",
                                    )

                                c_notes = add_notes
                                if va["msg"] and va["msg"] != "Allowed Overlap":
                                    c_notes = f"{add_notes} {va['msg']}".strip()

                                new_assign = {
                                    "id": str(uuid.uuid4()),
                                    "employeeId": va["eid"],
                                    "projectId": final_proj_id,
                                    "date": current_assign_date,
                                    "arrivalTime": str_arrival,
                                    "startTime": va["start"],
                                    "endTime": va["end"],
                                    "colorName": color_choice,
                                    "colorHex": config.BASIC_COLORS[color_choice],
                                    "notes": c_notes,
                                    "is_cancelled": False,
                                    "cancel_reason": "",
                                    "recurring_id": None,
                                    "is_general": bool(is_general),
                                }
                                new_assigns.append(new_assign)

                        insert_ok = utils.db_insert("assignments", new_assigns, track=False)

                        if insert_ok:
                            st.session_state.assignments.extend(new_assigns)

                            for new_a in new_assigns:
                                d = new_a.get("date")
                                if d:
                                    if "assignments_by_date" not in st.session_state:
                                        st.session_state.assignments_by_date = {}
                                    if d not in st.session_state.assignments_by_date:
                                        st.session_state.assignments_by_date[d] = []
                                    st.session_state.assignments_by_date[d].append(new_a)

                            st.success(f"Η ανάθεση ολοκληρώθηκε επιτυχώς για {len(new_target_dates)} ημέρα/ες!")
                            utils.mark_data_changed()

                            st.session_state.qa_rc += 1
                            st.session_state.pop("qa_form_prefill", None)
                            clear_bar_selection()
                            st.session_state.skip_remote_sync_once = True
                            st.rerun()
                        else:
                            st.error("Δεν έγινε αποθήκευση στη βάση. Δοκιμάστε ξανά ή πατήστε Άμεση Ανανέωση πριν ξανακαταχωρήσετε.")

        with col_edit:
            st.subheader("✏️ Επεξεργασία Μπάρας της Εβδομάδας")

            if st.session_state.get("trigger_scroll"):
                components.html(
                    f"""
                    <script>
                        // Μοναδικό ID Εκτέλεσης: {uuid.uuid4()}
                        setTimeout(function() {{
                            const headers = window.parent.document.querySelectorAll('h3');
                            for (let i = 0; i < headers.length; i++) {{
                                if(headers[i].innerText && headers[i].innerText.includes('Επεξεργασία Μπάρας')) {{
                                    headers[i].scrollIntoView({{behavior: 'smooth', block: 'start'}});
                                    break;
                                }}
                            }}
                        }}, 200);
                    </script>
                    """,
                    height=0,
                    width=0,
                )
                st.session_state.trigger_scroll = False

            if not wk_groups:
                st.info("Δεν υπάρχουν μπάρες για επεξεργασία αυτή την εβδομάδα.")
            else:
                group_keys = list(wk_groups.keys())
                group_keys.sort(key=lambda k: (wk_groups[k]["Date"], wk_groups[k]["StartTime"]))

                if st.session_state.get("reset_edit_bar_select_next_run"):
                    st.session_state.edit_bar_select_widget = ""
                    st.session_state.reset_edit_bar_select_next_run = False

                if st.session_state.clicked_key and st.session_state.clicked_key in group_keys:
                    st.session_state.edit_bar_select_widget = st.session_state.clicked_key

                options_for_select = [""] + group_keys
                if st.session_state.edit_bar_select_widget not in options_for_select:
                    st.session_state.edit_bar_select_widget = ""

                selected_key = st.selectbox(
                    "Επιλέξτε Μπάρα (Ημέρα & Έργο)",
                    options=options_for_select,
                    key="edit_bar_select_widget",
                    format_func=lambda x: "Επιλέξτε..." if x == "" else f"{wk_groups[x]['Date'].strftime('%d/%m')} - {wk_groups[x]['Project']} ({wk_groups[x]['StartTime']}-{wk_groups[x]['EndTime']})",
                )

                if selected_key == "" and st.session_state.clicked_key is not None:
                    clear_bar_selection()
                    st.rerun()

                if selected_key != "" and selected_key != st.session_state.clicked_key:
                    st.session_state.clicked_key = selected_key
                    st.session_state.trigger_scroll = True
                    st.session_state.skip_remote_sync_once = True
                    st.session_state.pop("edit_form_prefill", None)
                    st.rerun()

                if selected_key != "":
                    target_group = wk_groups[selected_key]
                    edit_clip = st.session_state.get("gantt_placement_clipboard")
                    if st.button(
                        "📥 Επικόλληση όλων των στοιχείων",
                        key="edit_paste_from_clipboard", disabled=not edit_clip,
                        use_container_width=True,
                        help="Συμπληρώνει τη φόρμα επεξεργασίας χωρίς αποθήκευση.",
                    ):
                        st.session_state["edit_form_prefill"] = dict(edit_clip)
                        st.session_state["edit_form_revision"] = st.session_state.get("edit_form_revision", 0) + 1
                        st.rerun()
                    edit_prefill = st.session_state.get("edit_form_prefill") or {}
                    # Η επεξεργασία μπάρας αφορά αποκλειστικά μία ημερομηνία.
                    edit_form_revision = st.session_state.get("edit_form_revision", 0)
                    edit_key = hashlib.sha1(selected_key.encode("utf-8")).hexdigest()[:12]
                    edit_key = f"{edit_key}_{edit_form_revision}"
                    st.markdown("⚡ **Γρήγορη Μετακίνηση**")
                    qm_c1, qm_c2, qm_c3, qm_c4 = st.columns(4)
                    move_m_day = qm_c1.button("⬅️ -1 Μέρα", use_container_width=True)
                    move_p_day = qm_c2.button("➡️ +1 Μέρα", use_container_width=True)
                    move_m_hour = qm_c3.button("🔼 -1 Ώρα", use_container_width=True)
                    move_p_hour = qm_c4.button("🔽 +1 Ώρα", use_container_width=True)

                    if any([move_m_day, move_p_day, move_m_hour, move_p_hour]):
                        delta_days = -1 if move_m_day else (1 if move_p_day else 0)
                        delta_hours = -1 if move_m_hour else (1 if move_p_hour else 0)
                        has_error = False
                        new_assigns, old_assigns = [], []

                        for a_id in target_group["AssignmentIds"]:
                            orig_a = next((a for a in st.session_state.assignments if a["id"] == a_id), None)
                            if not orig_a:
                                continue

                            new_a = dict(orig_a)
                            if delta_days != 0:
                                new_a["date"] = orig_a["date"] + timedelta(days=delta_days)
                            if delta_hours != 0:
                                dummy_date = datetime(2000, 1, 1)
                                s_dt = datetime.combine(dummy_date, datetime.strptime(str(orig_a["startTime"])[:5], "%H:%M").time())
                                e_dt = datetime.combine(dummy_date, datetime.strptime(str(orig_a["endTime"])[:5], "%H:%M").time())
                                new_s_dt = s_dt + timedelta(hours=delta_hours)
                                new_e_dt = e_dt + timedelta(hours=delta_hours)
                                if new_s_dt.date() != dummy_date.date() or new_e_dt.date() != dummy_date.date():
                                    st.error("Η αλλαγή ώρας ξεπερνάει τα όρια της ημέρας.")
                                    has_error = True
                                    break
                                new_a["startTime"] = new_s_dt.strftime("%H:%M")
                                new_a["endTime"] = new_e_dt.strftime("%H:%M")
                                if orig_a.get("arrivalTime"):
                                    arr_dt = datetime.combine(dummy_date, datetime.strptime(str(orig_a["arrivalTime"])[:5], "%H:%M").time())
                                    new_arr_dt = arr_dt + timedelta(hours=delta_hours)
                                    if new_arr_dt.date() != dummy_date.date():
                                        st.error("Η αλλαγή ώρας προσέλευσης ξεπερνάει τα όρια της ημέρας.")
                                        has_error = True
                                        break
                                    new_a["arrivalTime"] = new_arr_dt.strftime("%H:%M")

                            if new_a["employeeId"]:
                                emp_name = utils.get_employee_name(new_a["employeeId"])
                                if scheduling.is_on_leave(new_a["employeeId"], new_a["date"], st.session_state.leaves_by_emp):
                                    st.toast(f"Αδύνατη μετακίνηση: Ο/Η {emp_name} έχει άδεια!", icon="❌")
                                    has_error = True
                                    break

                                day_assigns = st.session_state.assignments_by_date.get(new_a["date"], [])
                                adj_start, adj_end, is_conflict, msg = scheduling.check_and_resolve_conflict(
                                    new_a["employeeId"],
                                    new_a["startTime"],
                                    new_a["endTime"],
                                    day_assigns,
                                    exclude_ids=target_group["AssignmentIds"],
                                )
                                if is_conflict:
                                    st.toast(f"Αδύνατη μετακίνηση: Διπλοκράτηση {emp_name}!", icon="⚠️")
                                    has_error = True
                                    break
                                new_a["startTime"], new_a["endTime"] = adj_start, adj_end
                                if msg == "Allowed Overlap":
                                    st.toast(f"ℹ️ Επιτράπηκε επικάλυψη ωραρίου ({emp_name}).", icon="ℹ️")

                            old_assigns.append(orig_a)
                            new_assigns.append(new_a)

                        if not has_error and old_assigns:
                            for old_a, new_a in zip(old_assigns, new_assigns):
                                utils.db_update("assignments", new_a["id"], new_a, old_data=old_a, track=False)
                            st.session_state.assignments = [a for a in st.session_state.assignments if a["id"] not in target_group["AssignmentIds"]]
                            st.session_state.assignments.extend(new_assigns)
                            clear_bar_selection()
                            st.rerun()

                    with st.form(f"quick_edit_{edit_key}"):
                        edit_date = st.date_input(
                            "Αλλαγή Ημερομηνίας",
                            value=_form_prefill_date(edit_prefill.get("first_date"), target_group["Date"]),
                            key=f"edit_date_{edit_key}",
                        )
                        proj_ids = [p["id"] for p in st.session_state.projects]
                        default_proj_idx = proj_ids.index(target_group["ProjectId"]) if target_group["ProjectId"] in proj_ids else 0
                        edit_proj = st.selectbox(
                            "Αλλαγή Έργου (Από Λίστα)",
                            options=proj_ids,
                            index=(
                                proj_ids.index(edit_prefill["project_id"])
                                if edit_prefill.get("project_id") in proj_ids else default_proj_idx
                            ),
                            format_func=utils.get_project_name,
                            key=f"edit_proj_{edit_key}",
                        )
                        edit_custom_proj_name = st.text_input(
                            "Ή πληκτρολογήστε Νέο Έργο (προαιρετικό)",
                            value=str(edit_prefill.get("custom_project") or ""),
                            key=f"edit_custom_project_{edit_key}",
                        )

                        # Μόνο οι πραγματικά τοποθετημένοι υπάλληλοι μπαίνουν ως προεπιλογή.
                        # Όσοι αναφέρονται μέσα σε notes τύπου [Άδεια: ...] / [Εμπλοκή: ...]
                        # μπαίνουν μόνο ως διαθέσιμες επιλογές, όχι ως ήδη επιλεγμένοι.
                        valid_emp_ids = normalize_id_list([eid for eid in target_group["EmployeeIds"] if eid])
                        note_emp_ids = []

                        for note in target_group.get("Notes_List", []):
                            matches = re.findall(r"\[(?:Άδεια|Εμπλοκή):\s*(.*?)\]", note)
                            for match in matches:
                                name_to_find = match.strip()
                                for emp in st.session_state.employees:
                                    if emp["name"].strip() == name_to_find:
                                        if emp["id"] not in note_emp_ids:
                                            note_emp_ids.append(emp["id"])
                                        break

                        edit_options = normalize_id_list(active_employee_ids + valid_emp_ids + note_emp_ids)
                        pasted_emp_ids = [
                            eid for eid in edit_prefill.get("employee_ids", []) if eid in edit_options
                        ]
                        edit_emps = st.multiselect(
                            "Αλλαγή Προσωπικού (Προαιρετικό)",
                            options=edit_options,
                            default=(pasted_emp_ids if edit_prefill else valid_emp_ids),
                            format_func=utils.get_employee_name,
                            key=f"edit_emps_{edit_key}",
                        )

                        e_color_col, e_notes_col = st.columns(2)
                        with e_color_col:
                            default_color_idx = list(config.BASIC_COLORS.keys()).index(target_group["ColorName"]) if target_group["ColorName"] in config.BASIC_COLORS else 0
                            edit_color = st.selectbox(
                                "Αλλαγή Χρώματος", options=list(config.BASIC_COLORS.keys()),
                                index=(list(config.BASIC_COLORS.keys()).index(edit_prefill["color"])
                                       if edit_prefill.get("color") in config.BASIC_COLORS else default_color_idx),
                                key=f"edit_color_{edit_key}",
                            )
                        with e_notes_col:
                            target_clean_note = clean_conflict_leave_notes(target_group.get("Notes", ""))
                            edit_notes = st.text_input(
                                "Παρατηρήσεις (Προαιρετικό)",
                                value=str(edit_prefill.get("notes", target_clean_note)),
                                key=f"edit_notes_{edit_key}",
                            )

                        e_arr, e_start, e_end = st.columns(3)
                        existing_arr = target_group.get("ArrivalTime", "")
                        with e_arr:
                            use_arr_edit = st.checkbox(
                                "Με Προσέλευση", value=bool(edit_prefill.get("use_arrival", bool(existing_arr))),
                                key=f"edit_use_arr_{edit_key}",
                            )
                            def_arr = _form_time(existing_arr or target_group["StartTime"])
                            new_t_arrival = st.time_input(
                                "Ώρα Προσ.", value=_form_time(edit_prefill.get("arrival_time"), def_arr.strftime("%H:%M")),
                                key=f"edit_arrival_{edit_key}",
                            )
                        with e_start:
                            new_t_start = st.time_input(
                                "Νέα Έναρξη", value=_form_time(edit_prefill.get("start_time"), target_group["StartTime"]),
                                key=f"edit_start_{edit_key}",
                            )
                        with e_end:
                            new_t_end = st.time_input(
                                "Νέα Λήξη", value=_form_time(edit_prefill.get("end_time"), target_group["EndTime"]),
                                key=f"edit_end_{edit_key}",
                            )

                        st.markdown("---")
                        e_is_general = st.checkbox(
                            "Γενικός",
                            value=bool(edit_prefill.get("is_general", target_group.get("IsGeneral", False))),
                            key=f"edit_is_general_{edit_key}",
                        )

                        st.markdown("---")
                        st.write("🛑 **Ακύρωση / Διαγραφή Βάρδιας (Διαγράμμιση)**")
                        c_canc1, c_canc2 = st.columns([1, 2])
                        with c_canc1:
                            e_is_cancelled = st.checkbox(
                                "Επισήμανση ως Ακυρωμένη",
                                value=bool(edit_prefill.get("is_cancelled", target_group.get("is_cancelled", False))),
                                key=f"edit_is_cancelled_{edit_key}",
                            )
                        with c_canc2:
                            e_cancel_reason = st.text_input(
                                "Λόγος Ακύρωσης (Συμπληρώστε αν ακυρώνετε)",
                                value=str(edit_prefill.get("cancel_reason", target_group.get("cancel_reason", "")) or ""),
                                key=f"edit_cancel_reason_{edit_key}",
                            )

                        st.markdown("---")
                        col_btn1, col_btn2, col_btn3 = st.columns(3)
                        with col_btn1:
                            save_edit = st.form_submit_button("💾 Αποθήκευση", use_container_width=True)
                        with col_btn2:
                            del_edit = st.form_submit_button("🗑️ Οριστική Διαγραφή", use_container_width=True)
                        with col_btn3:
                            copy_edit = st.form_submit_button("📋 Αντιγραφή στοιχείων", use_container_width=True)

                        if copy_edit:
                            _save_placement_clipboard(_form_clipboard_payload(
                                first_date=edit_date, mode=GANTT_DATES_CONTINUOUS,
                                duration=1, extra_dates=[],
                                project_id=edit_proj, custom_project=edit_custom_proj_name,
                                employee_ids=edit_emps, color_name=edit_color,
                                notes=edit_notes, is_general=e_is_general,
                                use_arrival=use_arr_edit, arrival_time=new_t_arrival,
                                start_time=new_t_start, end_time=new_t_end,
                                is_cancelled=e_is_cancelled, cancel_reason=e_cancel_reason,
                            ))

                        if del_edit:
                            old_assigns = [a for a in st.session_state.assignments if a["id"] in target_group["AssignmentIds"]]
                            st.session_state.assignments = [a for a in st.session_state.assignments if a["id"] not in target_group["AssignmentIds"]]
                            utils.db_delete_in("assignments", "id", target_group["AssignmentIds"], deleted_records=old_assigns)
                            clear_bar_selection()
                            st.rerun()

                        if save_edit:
                            str_arrival = new_t_arrival.strftime("%H:%M") if use_arr_edit else ""
                            str_start = new_t_start.strftime("%H:%M")
                            str_end = new_t_end.strftime("%H:%M")
                            edit_target_dates = [edit_date]

                            if str_start >= str_end:
                                st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                                st.stop()
                            # Resolve project before calculating anything; don't create it until
                            # all dates/employees have passed the blocking validation.
                            pending_new_project = None
                            if edit_custom_proj_name.strip():
                                c_name = edit_custom_proj_name.strip()
                                existing_p = next(
                                    (p for p in st.session_state.projects
                                     if p["name"].strip().lower() == c_name.lower()), None
                                )
                                if existing_p:
                                    final_edit_proj_id = existing_p["id"]
                                else:
                                    final_edit_proj_id = str(uuid.uuid4())
                                    pending_new_project = {
                                        "id": final_edit_proj_id, "name": c_name,
                                        "color": config.BASIC_COLORS[edit_color]
                                    }
                            else:
                                final_edit_proj_id = edit_proj

                            selected_emp_ids = normalize_id_list(edit_emps)
                            original_emp_ids = normalize_id_list(valid_emp_ids)
                            normalized_cancel_reason = e_cancel_reason if e_is_cancelled else ""
                            target_cancel_reason = (
                                target_group.get("cancel_reason", "")
                                if target_group.get("is_cancelled", False) else ""
                            )
                            # No work if the existing bar has not changed and only one date is selected.
                            is_noop_save = (
                                len(edit_target_dates) == 1
                                and not edit_custom_proj_name.strip()
                                and edit_date == target_group["Date"]
                                and final_edit_proj_id == target_group["ProjectId"]
                                and str_arrival == target_group.get("ArrivalTime", "")
                                and str_start == str(target_group["StartTime"])[:5]
                                and str_end == str(target_group["EndTime"])[:5]
                                and edit_color == target_group["ColorName"]
                                and edit_notes == target_clean_note
                                and bool(e_is_cancelled) == bool(target_group.get("is_cancelled", False))
                                and normalized_cancel_reason == target_cancel_reason
                                and bool(e_is_general) == bool(target_group.get("IsGeneral", False))
                                and selected_emp_ids == original_emp_ids
                            )
                            if is_noop_save:
                                clear_bar_selection()
                                st.rerun()

                            # Keep current weekly Gantt conflict semantics: allow only overlaps
                            # which the existing scheduling helper already accepts.
                            original_ids = list(target_group["AssignmentIds"])
                            old_assigns = [
                                dict(a) for a in st.session_state.assignments
                                if a.get("id") in original_ids
                            ]
                            if not old_assigns or len(old_assigns) != len(original_ids):
                                st.error("Η αρχική μπάρα έχει αλλάξει. Κάνε ανανέωση πριν από αποθήκευση.")
                                st.stop()

                            edit_exclude_ids = set(original_ids)
                            target_recurring_id = target_group.get("RecurringId")
                            if target_recurring_id:
                                for a in st.session_state.assignments_by_date.get(target_group["Date"], []):
                                    if (
                                        a.get("recurring_id") == target_recurring_id
                                        and a.get("projectId") == target_group["ProjectId"]
                                        and str(a.get("startTime", ""))[:5] == str(target_group["StartTime"])[:5]
                                        and str(a.get("endTime", ""))[:5] == str(target_group["EndTime"])[:5]
                                        and str(a.get("arrivalTime", ""))[:5] == str(target_group.get("ArrivalTime", ""))[:5]
                                    ):
                                        edit_exclude_ids.add(a.get("id"))

                            new_assigns = []
                            has_blocking_error = False
                            emps_to_process = selected_emp_ids if selected_emp_ids else [""]
                            for current_edit_date in edit_target_dates:
                                for eid in emps_to_process:
                                    if eid:
                                        emp_name = utils.get_employee_name(eid)
                                        if scheduling.is_on_leave(
                                            eid, current_edit_date, st.session_state.leaves_by_emp
                                        ):
                                            st.error(
                                                f"Δεν έγινε αποθήκευση: Ο/Η {emp_name} έχει άδεια "
                                                f"στις {current_edit_date:%d/%m/%Y}."
                                            )
                                            has_blocking_error = True
                                            break

                                        # Exclude only original bar/sibling rows; no unrelated
                                        # assignments are ever removed from the day.
                                        day_assigns = [
                                            a for a in st.session_state.assignments_by_date.get(current_edit_date, [])
                                            if a.get("id") not in edit_exclude_ids
                                            and not a.get("is_cancelled", False)
                                        ]
                                        day_assigns += [
                                            a for a in new_assigns if a.get("date") == current_edit_date
                                        ]
                                        adj_start, adj_end, is_conflict, msg = scheduling.check_and_resolve_conflict(
                                            eid, str_start, str_end, day_assigns
                                        )
                                        if is_conflict:
                                            st.error(
                                                f"Δεν έγινε αποθήκευση: Διπλοκράτηση του/της {emp_name} "
                                                f"στις {current_edit_date:%d/%m/%Y}."
                                            )
                                            has_blocking_error = True
                                            break
                                    else:
                                        adj_start, adj_end, msg = str_start, str_end, ""

                                    c_notes = preserve_context_notes(
                                        target_group.get("Notes", ""), edit_notes
                                    )
                                    if msg and msg != "Allowed Overlap":
                                        c_notes = f"{c_notes} {msg}".strip()

                                    new_assigns.append({
                                        "id": str(uuid.uuid4()),
                                        "employeeId": eid,
                                        "projectId": final_edit_proj_id,
                                        "date": current_edit_date,
                                        "arrivalTime": str_arrival,
                                        "startTime": adj_start,
                                        "endTime": adj_end,
                                        "colorName": edit_color,
                                        "colorHex": config.BASIC_COLORS[edit_color],
                                        "notes": c_notes,
                                        "is_cancelled": e_is_cancelled,
                                        "cancel_reason": normalized_cancel_reason,
                                        # Additional dates are independent placements, not
                                        # changes to the recurring series/template.
                                        "recurring_id": (
                                            target_recurring_id if current_edit_date == edit_date else None
                                        ),
                                        "is_general": bool(e_is_general),
                                    })
                                if has_blocking_error:
                                    break

                            if has_blocking_error:
                                st.stop()
                            if not utils.supabase:
                                st.error("Απαιτείται σύνδεση στη Supabase για ασφαλή αποθήκευση.")
                                st.stop()

                            # Save new rows first, then remove ONLY the original bar.
                            # This avoids deleting history if an insert fails.
                            if pending_new_project:
                                if not utils.db_insert("projects", pending_new_project, track=False):
                                    st.error("Δεν δημιουργήθηκε το νέο έργο. Η μπάρα έμεινε ανέπαφη.")
                                    st.stop()
                                st.session_state.projects.append(pending_new_project)

                            if not utils.db_insert("assignments", new_assigns, track=False):
                                st.error("Δεν δημιουργήθηκαν οι νέες τοποθετήσεις. Η παλιά μπάρα έμεινε ανέπαφη.")
                                st.stop()

                            try:
                                response = (
                                    utils.supabase.table("assignments")
                                    .delete().in_("id", original_ids).execute()
                                )
                                remaining = (
                                    utils.supabase.table("assignments")
                                    .select("id").in_("id", original_ids).execute()
                                )
                                if remaining.data:
                                    raise RuntimeError("Δεν διαγράφηκαν όλες οι παλιές εγγραφές.")
                            except Exception as exc:
                                # Best-effort compensation. Supabase REST does not offer a
                                # transaction across separate insert/delete requests.
                                restore_failed = False
                                try:
                                    existing = (
                                        utils.supabase.table("assignments")
                                        .select("id").in_("id", original_ids).execute()
                                    )
                                    still_present = {
                                        str(a["id"]) for a in (existing.data or [])
                                    }
                                    missing_original = [
                                        a for a in old_assigns
                                        if str(a["id"]) not in still_present
                                    ]
                                    if missing_original:
                                        utils.supabase.table("assignments").upsert(
                                            utils.serialize_dates(missing_original)
                                        ).execute()
                                except Exception:
                                    restore_failed = True
                                try:
                                    utils.supabase.table("assignments").delete().in_(
                                        "id", [a["id"] for a in new_assigns]
                                    ).execute()
                                except Exception:
                                    restore_failed = True
                                if restore_failed:
                                    st.error(
                                        "Απαιτείται έλεγχος στη Supabase: η αυτόματη "
                                        "επαναφορά δεν ολοκληρώθηκε."
                                    )
                                st.error(f"Η αντικατάσταση δεν ολοκληρώθηκε: {exc}.")
                                st.session_state.last_sync_time = None
                                st.stop()

                            for a in old_assigns:
                                utils.track_deletion("assignments", a["id"])
                            utils.add_transaction([
                                {"type": "delete", "table": "assignments", "records": old_assigns},
                                {"type": "insert", "table": "assignments", "records": new_assigns},
                            ])
                            st.session_state.assignments = [
                                a for a in st.session_state.assignments
                                if a.get("id") not in original_ids
                            ] + new_assigns
                            utils.mark_data_changed()
                            utils.touch_app_sync_state()
                            utils.log_activity(
                                "ΕΠΕΞΕΡΓΑΣΙΑ ΜΠΑΡΑΣ", "assignments",
                                f"Αλλαγή μπάρας στις {len(edit_target_dates)} ημερομηνίες: "
                                + ", ".join(d.strftime("%d/%m/%Y") for d in edit_target_dates)
                            )
                            st.session_state.pop("edit_form_prefill", None)
                            st.session_state.last_sync_time = None
                            st.success(f"Αποθηκεύτηκαν {len(new_assigns)} τοποθετήσεις σε {len(edit_target_dates)} ημερομηνίες.")
                            clear_bar_selection()
                            st.rerun()
