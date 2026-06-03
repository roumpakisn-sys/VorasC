import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, timedelta
import uuid
import hashlib
import re

from st_click_detector import click_detector

import config
import utils
import scheduling
import gantt_engine
import gantt_html
import gantt_filters
from gantt_helpers import get_local_today, normalize_id_list, clean_conflict_leave_notes


# =========================================================
# MOBILE GANTT PAGE
# Νέα ανεξάρτητη σελίδα για κινητό.
# Δεν αλλάζει το desktop Gantt.
# =========================================================

st.set_page_config(page_title="Mobile Gantt", page_icon="📱", layout="wide")


# --- ΑΣΠΙΔΑ SESSION / AUTH ---
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


# --- DATA / UI ---
utils.init_data_and_sync()
utils.setup_shared_ui()

# Στη mobile έκδοση αφαιρούμε το πάνω δεξιά ρολόι που προσθέτει το κοινό ui_shell.
# Δεν επηρεάζει το desktop Gantt.
st.markdown(
    """
    <style>
    #staff_pro_clock {
        display: none !important;
        visibility: hidden !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

components.html(
    """
    <script>
    (function () {
        const doc = window.parent.document;
        const clock = doc.getElementById("staff_pro_clock");
        if (clock) clock.remove();

        // Αν το κοινό ui_shell το ξαναδημιουργήσει μετά από rerun,
        // το καθαρίζουμε διακριτικά μόνο στη mobile σελίδα.
        if (!window.parent.staffProMobileClockCleanerStarted) {
            window.parent.staffProMobileClockCleanerStarted = true;
            setInterval(function () {
                const c = doc.getElementById("staff_pro_clock");
                if (c) c.remove();
            }, 1000);
        }
    })();
    </script>
    """,
    height=0,
    width=0,
)

is_full_admin = st.session_state.get("current_user") != "TAN"
active_employee_ids = [
    e["id"]
    for e in st.session_state.get("employees", [])
    if e.get("status", "Ενεργός") == "Ενεργός"
]


# --- MOBILE CSS ---
st.markdown(
    """
    <style>
    .block-container {
        padding-top: 0.75rem !important;
        padding-left: 0.55rem !important;
        padding-right: 0.55rem !important;
        max-width: 100% !important;
    }

    h1, h2, h3 {
        letter-spacing: -0.02em;
    }

    div[data-testid="stForm"] {
        border: 1px solid #cbd5e1;
        border-radius: 14px;
        padding: 0.75rem;
        background: #ffffff;
        box-shadow: 0 6px 18px rgba(15,23,42,0.08);
    }

    div[data-testid="stExpander"] {
        border-radius: 14px !important;
        overflow: hidden;
    }

    .mobile-tip {
        background: #eff6ff;
        border: 1px solid #bfdbfe;
        color: #1e3a8a;
        padding: 0.65rem 0.8rem;
        border-radius: 12px;
        font-size: 0.92rem;
        margin-bottom: 0.75rem;
    }

    @media (max-width: 768px) {
        [data-testid="stSidebar"] {
            width: 18rem !important;
        }

        .stButton > button,
        .stDownloadButton > button {
            min-height: 2.75rem !important;
            font-size: 1rem !important;
            border-radius: 12px !important;
        }

        input, textarea, select {
            font-size: 16px !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# --- MOBILE STATE ---
if "mobile_view_date" not in st.session_state:
    st.session_state.mobile_view_date = get_local_today()

if "mobile_clicked_key" not in st.session_state:
    st.session_state.mobile_clicked_key = None

if "mobile_last_clicked_safe_id" not in st.session_state:
    st.session_state.mobile_last_clicked_safe_id = ""

if "mobile_detector_version" not in st.session_state:
    st.session_state.mobile_detector_version = 0

if "mobile_edit_select_widget" not in st.session_state:
    st.session_state.mobile_edit_select_widget = ""

if "mobile_reset_edit_select_next_run" not in st.session_state:
    st.session_state.mobile_reset_edit_select_next_run = False

if "mobile_qa_rc" not in st.session_state:
    st.session_state.mobile_qa_rc = 0

if "mobile_zoom_pct" not in st.session_state:
    st.session_state.mobile_zoom_pct = 90


def clear_mobile_selection():
    st.session_state.mobile_clicked_key = None
    st.session_state.mobile_last_clicked_safe_id = ""
    st.session_state.mobile_edit_select_widget = ""
    st.session_state.mobile_reset_edit_select_next_run = True
    st.session_state.mobile_detector_version = st.session_state.get("mobile_detector_version", 0) + 1


def _start_of_week(d):
    return d - timedelta(days=d.weekday())


def _time_to_str(t):
    return t.strftime("%H:%M")


def _rebuild_assignment_indexes():
    assign_date_map = {}
    for a in st.session_state.get("assignments", []):
        d = a.get("date")
        if d:
            assign_date_map.setdefault(d, []).append(a)
    st.session_state.assignments_by_date = assign_date_map


def _add_assignment_to_local_indexes(assignments):
    if not isinstance(assignments, list):
        assignments = [assignments]

    st.session_state.assignments.extend(assignments)

    if "assignments_by_date" not in st.session_state:
        st.session_state.assignments_by_date = {}

    for a in assignments:
        d = a.get("date")
        if d:
            st.session_state.assignments_by_date.setdefault(d, []).append(a)


def _replace_local_assignments(old_ids, new_assigns=None):
    old_ids = set(old_ids or [])
    st.session_state.assignments = [
        a for a in st.session_state.get("assignments", [])
        if a.get("id") not in old_ids
    ]

    if new_assigns:
        st.session_state.assignments.extend(new_assigns)

    _rebuild_assignment_indexes()


def _make_or_get_project(project_id, custom_name, color_name):
    custom_name = (custom_name or "").strip()
    if not custom_name:
        return project_id

    existing = next(
        (
            p for p in st.session_state.get("projects", [])
            if p.get("name", "").strip().lower() == custom_name.lower()
        ),
        None,
    )
    if existing:
        return existing["id"]

    new_project_id = str(uuid.uuid4())
    new_project = {
        "id": new_project_id,
        "name": custom_name,
        "color": config.BASIC_COLORS[color_name],
    }
    st.session_state.projects.append(new_project)
    utils.db_insert("projects", new_project, track=False)
    return new_project_id


# --- HEADER / CONTROLS ---
st.title("📱 Mobile Gantt")

st.markdown(
    """
    <div class="mobile-tip">
    Σύρε το Gantt δεξιά/αριστερά με το δάχτυλο. Πάτησε πάνω σε μπάρα για επεξεργασία.
    </div>
    """,
    unsafe_allow_html=True,
)

ctrl_prev, ctrl_date, ctrl_next = st.columns([1, 2, 1])
with ctrl_prev:
    if st.button("⬅️", use_container_width=True):
        st.session_state.mobile_view_date = st.session_state.mobile_view_date - timedelta(days=7)
        clear_mobile_selection()
        st.rerun()

with ctrl_date:
    selected_mobile_date = st.date_input(
        "Εβδομάδα",
        value=st.session_state.mobile_view_date,
        key="mobile_week_date_input",
    )
    if selected_mobile_date != st.session_state.mobile_view_date:
        st.session_state.mobile_view_date = selected_mobile_date
        clear_mobile_selection()
        st.rerun()

with ctrl_next:
    if st.button("➡️", use_container_width=True):
        st.session_state.mobile_view_date = st.session_state.mobile_view_date + timedelta(days=7)
        clear_mobile_selection()
        st.rerun()

ctrl_today, ctrl_zoom_minus, ctrl_zoom_slider, ctrl_zoom_plus = st.columns([1.1, 0.9, 2.2, 0.9])
with ctrl_today:
    if st.button("Σήμερα", use_container_width=True):
        st.session_state.mobile_view_date = get_local_today()
        clear_mobile_selection()
        st.rerun()

with ctrl_zoom_minus:
    if st.button("➖", use_container_width=True, help="Σμίκρυνση Gantt"):
        st.session_state.mobile_zoom_pct = max(50, int(st.session_state.mobile_zoom_pct) - 10)
        clear_mobile_selection()
        st.rerun()

with ctrl_zoom_slider:
    st.session_state.mobile_zoom_pct = st.slider(
        "Zoom Gantt",
        min_value=50,
        max_value=170,
        value=int(st.session_state.mobile_zoom_pct),
        step=5,
        key="mobile_zoom_pct_slider",
        help="Μεγέθυνση/σμίκρυνση του οριζόντιου χρόνου στο διάγραμμα.",
    )

with ctrl_zoom_plus:
    if st.button("➕", use_container_width=True, help="Μεγέθυνση Gantt"):
        st.session_state.mobile_zoom_pct = min(170, int(st.session_state.mobile_zoom_pct) + 10)
        clear_mobile_selection()
        st.rerun()

zoom_factor = max(0.5, min(1.7, int(st.session_state.mobile_zoom_pct) / 100.0))

start_of_week = _start_of_week(st.session_state.mobile_view_date)
gantt_height_px = 560


# --- ΦΙΛΤΡΟ ΟΡΑΤΟΤΗΤΑΣ ΕΠΑΝΑΛΑΜΒΑΝΟΜΕΝΩΝ ΕΡΓΩΝ ---
# Η mobile σελίδα σέβεται τις ίδιες επιλογές που έχει ο χρήστης
# από το κεντρικό Gantt/sidebar για τα επαναλαμβανόμενα έργα.
visible_recurring_project_ids = gantt_filters.render_recurring_project_visibility_filter(
    projects=st.session_state.projects,
    recurring_patterns=st.session_state.recurring_patterns,
    on_change=clear_mobile_selection,
)

filtered_assignments_by_date = gantt_filters.apply_recurring_project_visibility_filter(
    assignments_by_date=st.session_state.assignments_by_date,
    visible_project_ids=visible_recurring_project_ids,
)

recurring_filter_version = gantt_filters.get_recurring_filter_version(visible_recurring_project_ids)


# --- GANTT DATA ---
@st.cache_data(show_spinner=False, max_entries=5)
def get_mobile_cached_data(
    start_of_week,
    zoom_factor,
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
        False,
        data_version,
        _assignments_by_date,
        _leaves,
        _employees,
        _projects,
        _emp_map,
        _proj_map,
    )
    return wk_groups, export_data


wk_groups, export_data = get_mobile_cached_data(
    start_of_week,
    zoom_factor,
    f"{st.session_state.get('local_gantt_version', 0)}_{start_of_week.isoformat()}_{zoom_factor}_{recurring_filter_version}",
    filtered_assignments_by_date,
    st.session_state.leaves,
    st.session_state.employees,
    st.session_state.projects,
    st.session_state.emp_map,
    st.session_state.proj_map,
)

safe_mapping = {}
key_to_safe_id = {}

for real_key in wk_groups.keys():
    safe_id = "mobile_bar_" + hashlib.md5(real_key.encode("utf-8")).hexdigest()
    safe_mapping[safe_id] = real_key
    key_to_safe_id[real_key] = safe_id


# --- RENDER GANTT ---
html_chart = gantt_html.build_html_gantt(
    wk_groups,
    start_of_week,
    zoom_factor,
    key_to_safe_id,
    gantt_height_px,
)

clicked_safe_id = click_detector(
    html_chart,
    key=f"mobile_gantt_detector_{st.session_state.mobile_detector_version}_{gantt_height_px}_{zoom_factor}",
)

if clicked_safe_id:
    real_clicked_key = safe_mapping.get(clicked_safe_id)
    if real_clicked_key and clicked_safe_id != st.session_state.mobile_last_clicked_safe_id:
        st.session_state.mobile_last_clicked_safe_id = clicked_safe_id
        st.session_state.mobile_clicked_key = real_clicked_key
        st.session_state.mobile_edit_select_widget = real_clicked_key
        st.session_state.skip_remote_sync_once = True
        st.rerun()

if st.session_state.get("mobile_clicked_key"):
    st.markdown('<div id="is_editing_flag" style="display:none;"></div>', unsafe_allow_html=True)


# --- MOBILE FORMS ---
if not is_full_admin:
    st.info("Ο συγκεκριμένος χρήστης έχει μόνο προβολή.")
    st.stop()


st.divider()


# =========================================================
# NEW ASSIGNMENT
# =========================================================
with st.expander("➕ Νέα Τοποθέτηση", expanded=False):
    qa_rc = st.session_state.mobile_qa_rc

    with st.form("mobile_quick_add", clear_on_submit=True):
        add_date = st.date_input(
            "Ημερομηνία",
            value=st.session_state.mobile_view_date,
            key=f"mqa_date_{qa_rc}",
        )

        duration_days = st.number_input(
            "Διάρκεια σε συνεχόμενες ημέρες",
            min_value=1,
            max_value=365,
            value=1,
            step=1,
            key=f"mqa_dur_{qa_rc}",
        )

        proj_ids = [p["id"] for p in st.session_state.get("projects", [])]
        proj_choice = st.selectbox(
            "Έργο",
            options=proj_ids,
            format_func=utils.get_project_name,
            key=f"mqa_proj_{qa_rc}",
        )

        custom_proj_name = st.text_input(
            "Νέο έργο αντί επιλογής από λίστα",
            key=f"mqa_custom_proj_{qa_rc}",
        )

        emp_choices = st.multiselect(
            "Προσωπικό",
            options=active_employee_ids,
            format_func=utils.get_employee_name,
            key=f"mqa_emps_{qa_rc}",
        )

        color_choice = st.selectbox(
            "Χρώμα",
            options=list(config.BASIC_COLORS.keys()),
            key=f"mqa_color_{qa_rc}",
        )

        add_notes = st.text_input(
            "Παρατηρήσεις",
            key=f"mqa_notes_{qa_rc}",
        )

        is_general = st.checkbox("Γενικός", key=f"mqa_general_{qa_rc}")

        use_arr = st.checkbox("Με προσέλευση", key=f"mqa_use_arr_{qa_rc}")
        t_arrival = st.time_input(
            "Ώρα προσέλευσης",
            value=datetime.strptime("08:00", "%H:%M").time(),
            key=f"mqa_arrival_{qa_rc}",
        )
        t_start = st.time_input(
            "Έναρξη",
            value=datetime.strptime("09:00", "%H:%M").time(),
            key=f"mqa_start_{qa_rc}",
        )
        t_end = st.time_input(
            "Λήξη",
            value=datetime.strptime("17:00", "%H:%M").time(),
            key=f"mqa_end_{qa_rc}",
        )

        submit_add = st.form_submit_button("Καταχώρηση", use_container_width=True)

        if submit_add:
            str_arrival = _time_to_str(t_arrival) if use_arr else ""
            str_start = _time_to_str(t_start)
            str_end = _time_to_str(t_end)

            if str_start >= str_end:
                st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
            else:
                final_proj_id = _make_or_get_project(proj_choice, custom_proj_name, color_choice)
                emps_to_process = emp_choices if emp_choices else [""]
                new_assigns = []

                for day_offset in range(int(duration_days)):
                    current_assign_date = add_date + timedelta(days=day_offset)
                    valid_assignments = []

                    for eid in emps_to_process:
                        if eid:
                            emp_name = utils.get_employee_name(eid)

                            if scheduling.is_on_leave(eid, current_assign_date, st.session_state.leaves_by_emp):
                                valid_assignments.append({
                                    "eid": "",
                                    "start": str_start,
                                    "end": str_end,
                                    "msg": f"[Άδεια: {emp_name}]",
                                    "emp_name": emp_name,
                                })
                                st.toast(
                                    f"Ο/Η {emp_name} έχει άδεια στις {current_assign_date.strftime('%d/%m')}. Καταχωρήθηκε ως χωρίς προσωπικό.",
                                    icon="⚠️",
                                )
                            else:
                                day_assigns = st.session_state.assignments_by_date.get(current_assign_date, [])
                                adj_start, adj_end, is_conflict, msg = scheduling.check_and_resolve_conflict(
                                    eid,
                                    str_start,
                                    str_end,
                                    day_assigns,
                                )

                                if is_conflict:
                                    valid_assignments.append({
                                        "eid": "",
                                        "start": str_start,
                                        "end": str_end,
                                        "msg": f"[Εμπλοκή: {emp_name}]",
                                        "emp_name": emp_name,
                                    })
                                    st.toast(
                                        f"Διπλοκράτηση {emp_name} στις {current_assign_date.strftime('%d/%m')}. Καταχωρήθηκε ως χωρίς προσωπικό.",
                                        icon="⚠️",
                                    )
                                else:
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

                    for va in valid_assignments:
                        if va["msg"] == "Allowed Overlap":
                            st.toast(
                                f"ℹ️ Επιτράπηκε επικάλυψη για {va['emp_name']}.",
                                icon="ℹ️",
                            )

                        final_notes = add_notes
                        if va["msg"] and va["msg"] != "Allowed Overlap":
                            final_notes = f"{add_notes} {va['msg']}".strip()

                        new_assigns.append({
                            "id": str(uuid.uuid4()),
                            "employeeId": va["eid"],
                            "projectId": final_proj_id,
                            "date": current_assign_date,
                            "arrivalTime": str_arrival,
                            "startTime": va["start"],
                            "endTime": va["end"],
                            "colorName": color_choice,
                            "colorHex": config.BASIC_COLORS[color_choice],
                            "notes": final_notes,
                            "is_cancelled": False,
                            "cancel_reason": "",
                            "recurring_id": None,
                            "is_general": bool(is_general),
                        })

                insert_ok = utils.db_insert("assignments", new_assigns, track=False)

                if insert_ok:
                    _add_assignment_to_local_indexes(new_assigns)
                    utils.mark_data_changed()
                    st.session_state.mobile_qa_rc += 1
                    clear_mobile_selection()
                    st.session_state.skip_remote_sync_once = True
                    st.success("Η τοποθέτηση καταχωρήθηκε.")
                    st.rerun()
                else:
                    st.error("Δεν έγινε αποθήκευση στη βάση.")


# =========================================================
# EDIT ASSIGNMENT BAR
# =========================================================
with st.expander("✏️ Επεξεργασία Μπάρας", expanded=bool(st.session_state.get("mobile_clicked_key"))):
    if not wk_groups:
        st.info("Δεν υπάρχουν μπάρες αυτή την εβδομάδα.")
    else:
        group_keys = list(wk_groups.keys())
        group_keys.sort(key=lambda k: (wk_groups[k]["Date"], wk_groups[k]["StartTime"]))

        if st.session_state.get("mobile_reset_edit_select_next_run"):
            st.session_state.mobile_edit_select_widget = ""
            st.session_state.mobile_reset_edit_select_next_run = False

        if st.session_state.mobile_clicked_key and st.session_state.mobile_clicked_key in group_keys:
            st.session_state.mobile_edit_select_widget = st.session_state.mobile_clicked_key

        options_for_select = [""] + group_keys
        if st.session_state.mobile_edit_select_widget not in options_for_select:
            st.session_state.mobile_edit_select_widget = ""

        selected_key = st.selectbox(
            "Μπάρα",
            options=options_for_select,
            key="mobile_edit_select_widget",
            format_func=lambda x: "Επιλέξτε..." if x == "" else f"{wk_groups[x]['Date'].strftime('%d/%m')} | {wk_groups[x]['Project']} | {wk_groups[x]['StartTime']}-{wk_groups[x]['EndTime']}",
        )

        if selected_key == "" and st.session_state.mobile_clicked_key is not None:
            clear_mobile_selection()
            st.rerun()

        if selected_key != "" and selected_key != st.session_state.mobile_clicked_key:
            st.session_state.mobile_clicked_key = selected_key
            st.session_state.skip_remote_sync_once = True
            st.rerun()

        if selected_key != "":
            target_group = wk_groups[selected_key]

            st.caption(
                f"{target_group['Date'].strftime('%d/%m/%Y')} | "
                f"{target_group['Project']} | "
                f"{target_group['StartTime']}-{target_group['EndTime']}"
            )

            with st.form("mobile_quick_edit"):
                edit_date = st.date_input("Ημερομηνία", value=target_group["Date"])

                proj_ids = [p["id"] for p in st.session_state.get("projects", [])]
                default_proj_idx = proj_ids.index(target_group["ProjectId"]) if target_group["ProjectId"] in proj_ids else 0

                edit_proj = st.selectbox(
                    "Έργο",
                    options=proj_ids,
                    index=default_proj_idx,
                    format_func=utils.get_project_name,
                )

                edit_custom_proj_name = st.text_input("Νέο έργο αντί επιλογής από λίστα")

                valid_emp_ids = normalize_id_list([eid for eid in target_group["EmployeeIds"] if eid])
                note_emp_ids = []

                for note in target_group.get("Notes_List", []):
                    matches = re.findall(r"\[(?:Άδεια|Εμπλοκή):\s*(.*?)\]", note)
                    for match in matches:
                        name_to_find = match.strip()
                        for emp in st.session_state.employees:
                            if emp["name"].strip() == name_to_find and emp["id"] not in note_emp_ids:
                                note_emp_ids.append(emp["id"])
                                break

                edit_options = normalize_id_list(active_employee_ids + valid_emp_ids + note_emp_ids)

                edit_emps = st.multiselect(
                    "Προσωπικό",
                    options=edit_options,
                    default=valid_emp_ids,
                    format_func=utils.get_employee_name,
                )

                default_color_idx = (
                    list(config.BASIC_COLORS.keys()).index(target_group["ColorName"])
                    if target_group["ColorName"] in config.BASIC_COLORS
                    else 0
                )

                edit_color = st.selectbox(
                    "Χρώμα",
                    options=list(config.BASIC_COLORS.keys()),
                    index=default_color_idx,
                )

                target_clean_note = clean_conflict_leave_notes(target_group.get("Notes", ""))
                edit_notes = st.text_input("Παρατηρήσεις", value=target_clean_note)

                existing_arr = target_group.get("ArrivalTime", "")
                use_arr_edit = st.checkbox("Με προσέλευση", value=bool(existing_arr), key="mobile_edit_use_arr")

                def_arr = (
                    datetime.strptime(existing_arr, "%H:%M").time()
                    if existing_arr
                    else datetime.strptime(str(target_group["StartTime"])[:5], "%H:%M").time()
                )

                new_t_arrival = st.time_input("Ώρα προσέλευσης", value=def_arr, key="mobile_edit_arrival")
                new_t_start = st.time_input(
                    "Έναρξη",
                    value=datetime.strptime(str(target_group["StartTime"])[:5], "%H:%M").time(),
                    key="mobile_edit_start",
                )
                new_t_end = st.time_input(
                    "Λήξη",
                    value=datetime.strptime(str(target_group["EndTime"])[:5], "%H:%M").time(),
                    key="mobile_edit_end",
                )

                e_is_general = st.checkbox(
                    "Γενικός",
                    value=bool(target_group.get("IsGeneral", False)),
                    key="mobile_edit_is_general",
                )

                e_is_cancelled = st.checkbox(
                    "Ακυρωμένη",
                    value=bool(target_group.get("is_cancelled", False)),
                    key="mobile_edit_is_cancelled",
                )

                e_cancel_reason = st.text_input(
                    "Λόγος ακύρωσης",
                    value=target_group.get("cancel_reason", ""),
                    key="mobile_edit_cancel_reason",
                )

                save_edit = st.form_submit_button("💾 Αποθήκευση", use_container_width=True)
                delete_edit = st.form_submit_button("🗑️ Οριστική Διαγραφή", use_container_width=True)

                if delete_edit:
                    old_assigns = [
                        a for a in st.session_state.assignments
                        if a.get("id") in target_group["AssignmentIds"]
                    ]

                    _replace_local_assignments(target_group["AssignmentIds"], [])
                    utils.db_delete_in(
                        "assignments",
                        "id",
                        target_group["AssignmentIds"],
                        deleted_records=old_assigns,
                    )
                    clear_mobile_selection()
                    st.success("Η μπάρα διαγράφηκε.")
                    st.rerun()

                if save_edit:
                    str_arrival = _time_to_str(new_t_arrival) if use_arr_edit else ""
                    str_start = _time_to_str(new_t_start)
                    str_end = _time_to_str(new_t_end)

                    if str_start >= str_end:
                        st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                    else:
                        final_edit_proj_id = _make_or_get_project(edit_proj, edit_custom_proj_name, edit_color)

                        selected_emp_ids = normalize_id_list(edit_emps)
                        emps_to_process = selected_emp_ids if selected_emp_ids else [""]

                        normalized_cancel_reason = e_cancel_reason if e_is_cancelled else ""

                        valid_assignments = []
                        has_blocking_error = False

                        for eid in emps_to_process:
                            if eid:
                                emp_name = utils.get_employee_name(eid)

                                if scheduling.is_on_leave(eid, edit_date, st.session_state.leaves_by_emp):
                                    st.error(f"Δεν έγινε αποθήκευση: Ο/Η {emp_name} έχει άδεια.")
                                    has_blocking_error = True
                                    break

                                day_assigns = st.session_state.assignments_by_date.get(edit_date, [])
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

                        if not has_blocking_error:
                            old_assigns = [
                                a for a in st.session_state.assignments
                                if a.get("id") in target_group["AssignmentIds"]
                            ]

                            new_assigns = []
                            for va in valid_assignments:
                                if va["msg"] == "Allowed Overlap":
                                    st.toast(
                                        f"ℹ️ Επιτράπηκε επικάλυψη: {va['emp_name']}.",
                                        icon="ℹ️",
                                    )

                                final_notes = edit_notes
                                if va["msg"] and va["msg"] != "Allowed Overlap":
                                    final_notes = f"{edit_notes} {va['msg']}".strip()

                                new_assigns.append({
                                    "id": str(uuid.uuid4()),
                                    "employeeId": va["eid"],
                                    "projectId": final_edit_proj_id,
                                    "date": edit_date,
                                    "arrivalTime": str_arrival,
                                    "startTime": va["start"],
                                    "endTime": va["end"],
                                    "colorName": edit_color,
                                    "colorHex": config.BASIC_COLORS[edit_color],
                                    "notes": final_notes,
                                    "is_cancelled": bool(e_is_cancelled),
                                    "cancel_reason": normalized_cancel_reason,
                                    "recurring_id": target_group.get("RecurringId"),
                                    "is_general": bool(e_is_general),
                                })

                            _replace_local_assignments(target_group["AssignmentIds"], new_assigns)

                            utils.db_delete_in(
                                "assignments",
                                "id",
                                target_group["AssignmentIds"],
                                deleted_records=old_assigns,
                                track=False,
                            )
                            utils.db_insert("assignments", new_assigns, track=False)

                            utils.mark_data_changed()
                            clear_mobile_selection()
                            st.success("Η μπάρα αποθηκεύτηκε.")
                            st.rerun()
