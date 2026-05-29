import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from datetime import datetime, date, timedelta
import uuid
import io
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


def sync_from_widget():
    st.session_state.view_week_date = st.session_state.date_picker
    clear_bar_selection()


def go_prev_week():
    new_date = st.session_state.view_week_date - timedelta(days=7)
    st.session_state.view_week_date = new_date
    st.session_state.date_picker = new_date
    clear_bar_selection()


def go_next_week():
    new_date = st.session_state.view_week_date + timedelta(days=7)
    st.session_state.view_week_date = new_date
    st.session_state.date_picker = new_date
    clear_bar_selection()


def go_to_today():
    new_date = get_local_today()
    st.session_state.view_week_date = new_date
    st.session_state.date_picker = new_date
    clear_bar_selection()


# Η επιλογή του selectbox διαχειρίζεται inline πιο κάτω, χωρίς on_change callback.

# --- ΣΥΜΠΙΕΣΗ ΤΟΥ ΠΑΝΩ ΜΕΡΟΥΣ ΣΕ ΜΙΑ ΣΥΜΠΑΓΗ ΓΡΑΜΜΗ (Compact UI) ---
st.markdown(
    """
<style>
.block-container, [data-testid="block-container"] {
    max-width: 98% !important;
    padding-top: 0.5rem !important;
    padding-bottom: 0.5rem !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
}
div[data-testid="stNotification"], .stAlert {
    padding: 2px 10px !important;
    margin-top: 0px !important;
    margin-bottom: 2px !important;
}
div[data-testid="stNotification"] p, .stAlert p {
    margin: 0 !important;
    font-size: 13px !important;
}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    "<h3 style='margin-top: -30px; margin-bottom: 5px;'>📊 Εβδομαδιαίο Χρονοδιάγραμμα Πόρων</h3>",
    unsafe_allow_html=True,
)

col_date, col_nav1, col_nav2, col_today, col_zoom, col_pres = st.columns([1.5, 0.8, 0.8, 0.8, 1.5, 1.5])
with col_date:
    selected_date = st.date_input(
        "Εβδομάδα",
        value=st.session_state.view_week_date,
        key="date_picker",
        on_change=sync_from_widget,
        label_visibility="collapsed",
    )
    start_of_week = st.session_state.view_week_date - timedelta(days=st.session_state.view_week_date.weekday())
with col_nav1:
    st.button("⬅️ Πριν", on_click=go_prev_week, use_container_width=True)
with col_nav2:
    st.button("Μετά ➡️", on_click=go_next_week, use_container_width=True)
with col_today:
    st.button("📅 Σήμερα", on_click=go_to_today, use_container_width=True)
with col_zoom:
    if "gantt_zoom_level" not in st.session_state:
        st.session_state.gantt_zoom_level = 100
    zoom_level = st.slider(
        "Ζουμ",
        min_value=50,
        max_value=200,
        value=st.session_state.gantt_zoom_level,
        step=5,
        label_visibility="collapsed",
        key="gantt_zoom_slider",
    )
    st.session_state.gantt_zoom_level = zoom_level
with col_pres:
    presentation_mode = st.checkbox("📺 Πλήρης Προβολή")

if "gantt_height_px" not in st.session_state:
    st.session_state.gantt_height_px = 650

gantt_height_px = st.slider(
    "Ύψος Gantt",
    min_value=400,
    max_value=1200,
    value=st.session_state.gantt_height_px,
    step=25,
    help="Αυξομείωση του κάθετου μεγέθους του παραθύρου Gantt.",
    key="gantt_height_slider",
)

# Όταν αλλάζει το ύψος, ανανεώνουμε το component key του Gantt.
# Το st_click_detector μερικές φορές κρατάει παλιό iframe αν το key μείνει ίδιο.
if st.session_state.get("last_gantt_height_px") != gantt_height_px:
    st.session_state.gantt_height_px = gantt_height_px
    st.session_state.last_gantt_height_px = gantt_height_px
    st.session_state.suppress_next_detector_click = True
    st.session_state.detector_version = st.session_state.get("detector_version", 0) + 1
else:
    st.session_state.gantt_height_px = gantt_height_px

zoom_factor = zoom_level / 100.0

# --- ΕΞΑΓΩΓΗ ΔΕΔΟΜΕΝΩΝ ΑΠΟ ΤΟ ENGINE ---
@st.cache_data(show_spinner=False, max_entries=5)
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
    st.session_state.get("local_gantt_version", 0),
    st.session_state.assignments_by_date,
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
            st.rerun()

if st.session_state.get("clicked_key"):
    st.markdown('<div id="is_editing_flag" style="display:none;"></div>', unsafe_allow_html=True)

# --- ΕΝΟΤΗΤΑ ΕΞΑΓΩΓΗΣ EXCEL ---
hint_text = "💡 *Συμβουλές:* **1)** Κάντε κλικ σε μια μπάρα για επεξεργασία. **2)** Κρατήστε αριστερό κλικ και κάντε drag μέσα στο gantt για κίνηση δεξιά/αριστερά. **3)** Σύρετε με τη ροδέλα πάνω-κάτω για τις ημέρες. **4)** Ρυθμίστε το κάθετο μέγεθος από το slider 'Ύψος Gantt'."
if export_data:
    col_hint, col_btn = st.columns([3, 1])
    with col_hint:
        st.caption(hint_text)
    with col_btn:
        df_export = pd.DataFrame(export_data)
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df_export.to_excel(writer, index=False, sheet_name="Πρόγραμμα")
        st.download_button(
            label="📥 Εξαγωγή (Excel)",
            data=buffer.getvalue(),
            file_name=f"Gantt_Programma_{start_of_week.strftime('%d_%m_%Y')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
else:
    st.caption(hint_text)

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

            with st.form("quick_add", clear_on_submit=True):
                c_date, c_dur = st.columns(2)
                with c_date:
                    add_date = st.date_input("Ημερομηνία", value=st.session_state.view_week_date, key=f"qa_date_{qa_rc}")
                with c_dur:
                    duration_days = st.number_input(
                        "Διάρκεια (Συνεχόμενες Ημέρες)",
                        min_value=1,
                        max_value=365,
                        value=1,
                        step=1,
                        key=f"qa_dur_{qa_rc}",
                    )

                proj_choice = st.selectbox(
                    "Επιλογή Έργου (Από Λίστα)",
                    options=[p["id"] for p in st.session_state.projects],
                    format_func=utils.get_project_name,
                    key=f"qa_proj_{qa_rc}",
                )
                custom_proj_name = st.text_input(
                    "Ή πληκτρολογήστε Νέο Έργο (Αν συμπληρωθεί, αγνοεί την παραπάνω λίστα)",
                    key=f"qa_cproj_{qa_rc}",
                )
                emp_choices = st.multiselect(
                    "Προσωπικό (Προαιρετικό - Μόνο Ενεργοί)",
                    options=active_employee_ids,
                    format_func=utils.get_employee_name,
                    key=f"qa_emps_{qa_rc}",
                )

                c_color, c_notes = st.columns(2)
                with c_color:
                    color_choice = st.selectbox("Χρώμα Μπάρας", options=list(config.BASIC_COLORS.keys()), key=f"qa_color_{qa_rc}")
                with c_notes:
                    add_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", key=f"qa_notes_{qa_rc}")

                c_arr, c_start, c_end = st.columns(3)
                with c_arr:
                    use_arr = st.checkbox("Προσέλευση;", key=f"chk_arr_{qa_rc}")
                    t_arrival = st.time_input("Ώρα Προσέλευσης", value=datetime.strptime("08:00", "%H:%M").time(), key=f"qa_arrival_{qa_rc}")
                with c_start:
                    t_start = st.time_input("Έναρξη", value=datetime.strptime("09:00", "%H:%M").time(), key=f"qa_start_{qa_rc}")
                with c_end:
                    t_end = st.time_input("Λήξη", value=datetime.strptime("17:00", "%H:%M").time(), key=f"qa_end_{qa_rc}")

                if st.form_submit_button("Καταχώρηση"):
                    str_arrival = t_arrival.strftime("%H:%M") if use_arr else ""
                    str_start = t_start.strftime("%H:%M")
                    str_end = t_end.strftime("%H:%M")

                    if str_start >= str_end:
                        st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
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

                        for day_offset in range(duration_days):
                            current_assign_date = add_date + timedelta(days=day_offset)
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
                                }
                                new_assigns.append(new_assign)

                        insert_ok = utils.db_insert("assignments", new_assigns, track=False)

                        if insert_ok:
                            st.session_state.assignments.extend(new_assigns)
                            st.success(f"Η ανάθεση ολοκληρώθηκε επιτυχώς για {duration_days} ημέρα/ες!")
                            time.sleep(0.4)
                            utils.mark_data_changed()
                            utils.init_data_and_sync()

                            st.session_state.qa_rc += 1
                            clear_bar_selection()
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
                    st.rerun()

                if selected_key != "":
                    target_group = wk_groups[selected_key]
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

                    with st.form("quick_edit"):
                        edit_date = st.date_input("Αλλαγή Ημερομηνίας", value=target_group["Date"])
                        proj_ids = [p["id"] for p in st.session_state.projects]
                        default_proj_idx = proj_ids.index(target_group["ProjectId"]) if target_group["ProjectId"] in proj_ids else 0
                        edit_proj = st.selectbox(
                            "Αλλαγή Έργου (Από Λίστα)",
                            options=proj_ids,
                            index=default_proj_idx,
                            format_func=utils.get_project_name,
                        )
                        edit_custom_proj_name = st.text_input("Ή πληκτρολογήστε Νέο Έργο (προαιρετικό)")

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
                        edit_emps = st.multiselect(
                            "Αλλαγή Προσωπικού (Προαιρετικό)",
                            options=edit_options,
                            default=valid_emp_ids,
                            format_func=utils.get_employee_name,
                        )

                        e_color_col, e_notes_col = st.columns(2)
                        with e_color_col:
                            default_color_idx = list(config.BASIC_COLORS.keys()).index(target_group["ColorName"]) if target_group["ColorName"] in config.BASIC_COLORS else 0
                            edit_color = st.selectbox("Αλλαγή Χρώματος", options=list(config.BASIC_COLORS.keys()), index=default_color_idx)
                        with e_notes_col:
                            target_clean_note = clean_conflict_leave_notes(target_group.get("Notes", ""))
                            edit_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", value=target_clean_note)

                        e_arr, e_start, e_end = st.columns(3)
                        existing_arr = target_group.get("ArrivalTime", "")
                        with e_arr:
                            use_arr_edit = st.checkbox("Με Προσέλευση", value=bool(existing_arr), key="edit_use_arr")
                            def_arr = datetime.strptime(existing_arr, "%H:%M").time() if existing_arr else datetime.strptime(str(target_group["StartTime"])[:5], "%H:%M").time()
                            new_t_arrival = st.time_input("Ώρα Προσ.", value=def_arr, key="edit_arrival_time")
                        with e_start:
                            new_t_start = st.time_input("Νέα Έναρξη", value=datetime.strptime(str(target_group["StartTime"])[:5], "%H:%M").time())
                        with e_end:
                            new_t_end = st.time_input("Νέα Λήξη", value=datetime.strptime(str(target_group["EndTime"])[:5], "%H:%M").time())

                        st.markdown("---")
                        st.write("🛑 **Ακύρωση / Διαγραφή Βάρδιας (Διαγράμμιση)**")
                        c_canc1, c_canc2 = st.columns([1, 2])
                        with c_canc1:
                            e_is_cancelled = st.checkbox("Επισήμανση ως Ακυρωμένη", value=target_group.get("is_cancelled", False))
                        with c_canc2:
                            e_cancel_reason = st.text_input("Λόγος Ακύρωσης (Συμπληρώστε αν ακυρώνετε)", value=target_group.get("cancel_reason", ""))

                        st.markdown("---")
                        col_btn1, col_btn2 = st.columns(2)
                        with col_btn1:
                            save_edit = st.form_submit_button("💾 Αποθήκευση")
                        with col_btn2:
                            del_edit = st.form_submit_button("🗑️ Οριστική Διαγραφή Μπάρας")

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

                            if str_start >= str_end:
                                st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                            else:
                                # Υπολογισμός έργου ΠΡΙΝ από conflict check και ΠΡΙΝ από delete/insert.
                                pending_new_project = None
                                if edit_custom_proj_name.strip():
                                    c_name = edit_custom_proj_name.strip()
                                    existing_p = next(
                                        (p for p in st.session_state.projects if p["name"].strip().lower() == c_name.lower()),
                                        None,
                                    )
                                    if existing_p:
                                        final_edit_proj_id = existing_p["id"]
                                    else:
                                        final_edit_proj_id = str(uuid.uuid4())
                                        pending_new_project = {"id": final_edit_proj_id, "name": c_name, "color": config.BASIC_COLORS[edit_color]}
                                else:
                                    final_edit_proj_id = edit_proj

                                selected_emp_ids = normalize_id_list(edit_emps)
                                original_emp_ids = normalize_id_list(valid_emp_ids)
                                normalized_cancel_reason = e_cancel_reason if e_is_cancelled else ""
                                target_cancel_reason = target_group.get("cancel_reason", "") if target_group.get("is_cancelled", False) else ""

                                # Αν ο χρήστης απλώς πάτησε Αποθήκευση χωρίς πραγματική αλλαγή,
                                # δεν κάνουμε ούτε delete ούτε insert. Έτσι δεν γεννιούνται δεύτερες μπάρες.
                                is_noop_save = (
                                    not edit_custom_proj_name.strip()
                                    and edit_date == target_group["Date"]
                                    and final_edit_proj_id == target_group["ProjectId"]
                                    and str_arrival == target_group.get("ArrivalTime", "")
                                    and str_start == str(target_group["StartTime"])[:5]
                                    and str_end == str(target_group["EndTime"])[:5]
                                    and edit_color == target_group["ColorName"]
                                    and edit_notes == target_clean_note
                                    and bool(e_is_cancelled) == bool(target_group.get("is_cancelled", False))
                                    and normalized_cancel_reason == target_cancel_reason
                                    and selected_emp_ids == original_emp_ids
                                )

                                if is_noop_save:
                                    clear_bar_selection()
                                    st.rerun()

                                emps_to_process = selected_emp_ids if selected_emp_ids else [""]
                                valid_assignments = []
                                has_blocking_error = False

                                for eid in emps_to_process:
                                    if eid:
                                        emp_name = utils.get_employee_name(eid)

                                        if scheduling.is_on_leave(eid, edit_date, st.session_state.leaves_by_emp):
                                            st.error(f"Δεν έγινε αποθήκευση: Ο/Η {emp_name} έχει άδεια σε αυτή την ημερομηνία.")
                                            st.toast(f"Ακύρωση αποθήκευσης: Ο/Η {emp_name} έχει άδεια.", icon="⚠️")
                                            has_blocking_error = True
                                            break

                                        day_assigns = st.session_state.assignments_by_date.get(edit_date, [])

                                        # Αν επεξεργαζόμαστε μεμονωμένη μπάρα από επαναλαμβανόμενη εργασία,
                                        # αγνοούμε και τυχόν συγγενικές εγγραφές της ίδιας σειράς που αντιστοιχούν
                                        # στην ίδια αρχική μπάρα. Έτσι η μπάρα δεν κάνει conflict με τον εαυτό της.
                                        edit_exclude_ids = list(target_group["AssignmentIds"])
                                        target_recurring_id = target_group.get("RecurringId")

                                        if target_recurring_id:
                                            for a in day_assigns:
                                                if (
                                                    a.get("recurring_id") == target_recurring_id
                                                    and a.get("projectId") == target_group["ProjectId"]
                                                    and str(a.get("startTime", ""))[:5] == str(target_group["StartTime"])[:5]
                                                    and str(a.get("endTime", ""))[:5] == str(target_group["EndTime"])[:5]
                                                    and str(a.get("arrivalTime", ""))[:5] == str(target_group.get("ArrivalTime", ""))[:5]
                                                ):
                                                    if a.get("id") not in edit_exclude_ids:
                                                        edit_exclude_ids.append(a.get("id"))

                                        adj_start, adj_end, is_conflict, msg = scheduling.check_and_resolve_conflict(
                                            eid,
                                            str_start,
                                            str_end,
                                            day_assigns,
                                            exclude_ids=edit_exclude_ids,
                                        )

                                        if is_conflict:
                                            st.error(f"Δεν έγινε αποθήκευση: Διπλοκράτηση για {emp_name}.")
                                            st.toast(f"Ακύρωση αποθήκευσης: Διπλοκράτηση {emp_name}.", icon="⚠️")
                                            has_blocking_error = True
                                            break

                                        valid_assignments.append({
                                            "eid": eid,
                                            "start": adj_start,
                                            "end": adj_end,
                                            "msg": msg,
                                            "emp_name": emp_name,
                                        })
                                    else:
                                        valid_assignments.append({
                                            "eid": "",
                                            "start": str_start,
                                            "end": str_end,
                                            "msg": "",
                                            "emp_name": "",
                                        })

                                if has_blocking_error:
                                    st.stop()

                                if pending_new_project:
                                    st.session_state.projects.append(pending_new_project)
                                    utils.db_insert("projects", pending_new_project, track=False)

                                old_assigns = [a for a in st.session_state.assignments if a["id"] in target_group["AssignmentIds"]]
                                st.session_state.assignments = [a for a in st.session_state.assignments if a["id"] not in target_group["AssignmentIds"]]
                                utils.db_delete_in("assignments", "id", target_group["AssignmentIds"], deleted_records=old_assigns, track=False)

                                new_assigns = []
                                for va in valid_assignments:
                                    if va["msg"] == "Allowed Overlap":
                                        st.toast(f"ℹ️ Επιτράπηκε επικάλυψη ωραρίου: {va['emp_name']} ({va['start']})", icon="ℹ️")

                                    c_notes = edit_notes
                                    if va["msg"] and va["msg"] != "Allowed Overlap":
                                        c_notes = f"{edit_notes} {va['msg']}".strip()

                                    new_a = {
                                        "id": str(uuid.uuid4()),
                                        "employeeId": va["eid"],
                                        "projectId": final_edit_proj_id,
                                        "date": edit_date,
                                        "arrivalTime": str_arrival,
                                        "startTime": va["start"],
                                        "endTime": va["end"],
                                        "colorName": edit_color,
                                        "colorHex": config.BASIC_COLORS[edit_color],
                                        "notes": c_notes,
                                        "is_cancelled": e_is_cancelled,
                                        "cancel_reason": normalized_cancel_reason,
                                        "recurring_id": target_group.get("RecurringId"),
                                    }
                                    new_assigns.append(new_a)
                                    st.session_state.assignments.append(new_a)

                                utils.db_insert("assignments", new_assigns, track=False)
                                clear_bar_selection()
                                st.rerun()
