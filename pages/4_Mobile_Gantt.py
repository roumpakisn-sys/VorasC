import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, timedelta
import uuid
import hashlib
import re

import config
import utils
import gantt_live_view
import gantt_search
import placement_roles
import placement_details
import placement_confirmation
import placement_hours
from gantt_helpers import get_local_today, normalize_id_list, clean_conflict_leave_notes
from periodic_visits_runtime import load_periodic_visits

periodic_visits = load_periodic_visits()


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

if "mobile_app_scale_pct" not in st.session_state:
    st.session_state.mobile_app_scale_pct = 90


def clear_mobile_selection():
    st.session_state.pop("mobile_search_target", None)
    st.session_state.mobile_clicked_key = None
    st.session_state.mobile_last_clicked_safe_id = ""
    # Reset before the widget is created on the next run (also after a save).
    st.session_state.mobile_reset_edit_select_next_run = True
    st.session_state.mobile_detector_version = st.session_state.get("mobile_detector_version", 0) + 1


def open_search_result(day, assignment_id):
    clear_mobile_selection()
    st.session_state.mobile_view_date = day
    st.session_state.mobile_week_date_input = day
    st.session_state.mobile_search_target = (day, assignment_id)
    st.session_state.mobile_search_pending = True
    st.session_state.pop("mobile_customer_pending_only", None)


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
        return project_id, None

    existing = next(
        (
            p for p in st.session_state.get("projects", [])
            if p.get("name", "").strip().lower() == custom_name.lower()
        ),
        None,
    )
    if existing:
        return existing["id"], None

    new_project_id = str(uuid.uuid4())
    new_project = {
        "id": new_project_id,
        "name": custom_name,
        "color": config.BASIC_COLORS[color_name],
    }
    return new_project_id, new_project


def _normalize_mobile_project_list(values, allowed_ids):
    allowed = set(allowed_ids or [])
    clean = []

    for value in values or []:
        if value in allowed and value not in clean:
            clean.append(value)

    return clean


def _get_mobile_recurring_project_ids(projects, recurring_patterns):
    import periodic_visits
    project_ids = []
    known_project_ids = {p.get("id") for p in projects or [] if isinstance(p, dict)}

    for pattern in recurring_patterns or []:
        if not isinstance(pattern, dict) or periodic_visits.is_target(pattern):
            continue

        project_id = pattern.get("projectId")
        if project_id and project_id in known_project_ids and project_id not in project_ids:
            project_ids.append(project_id)

    project_ids.sort(key=lambda pid: utils.get_project_name(pid).lower())
    return project_ids


def _load_mobile_hidden_recurring_projects(recurring_project_ids):
    """
    Η mobile σελίδα δεν έχει δικό της φίλτρο.
    Διαβάζει τις ίδιες αποθηκευμένες επιλογές που χρησιμοποιεί το κεντρικό Gantt.
    """
    preference_key = "gantt_hidden_recurring_project_ids"
    username = st.session_state.get("current_user") or ""

    hidden_from_session = st.session_state.get(preference_key)
    loaded_for_user = st.session_state.get("mobile_recurring_filter_loaded_for_user")

    if loaded_for_user == username and hidden_from_session is not None:
        return _normalize_mobile_project_list(hidden_from_session, recurring_project_ids)

    hidden_ids = []
    if username and utils.supabase:
        try:
            res = (
                utils.supabase
                .table("user_preferences")
                .select("preference_value")
                .eq("username", username)
                .eq("preference_key", preference_key)
                .limit(1)
                .execute()
            )

            rows = res.data or []
            if rows and isinstance(rows[0].get("preference_value"), list):
                hidden_ids = rows[0].get("preference_value") or []
        except Exception as e:
            print(f"Could not load mobile recurring filter preference: {e}")
            hidden_ids = hidden_from_session or []

    hidden_ids = _normalize_mobile_project_list(hidden_ids, recurring_project_ids)

    st.session_state[preference_key] = hidden_ids
    st.session_state["mobile_recurring_filter_loaded_for_user"] = username

    return hidden_ids


def _get_mobile_visible_recurring_project_ids(projects, recurring_patterns):
    """
    Επιστρέφει τα recurring project ids που πρέπει να φαίνονται στο Mobile Gantt,
    με βάση τις αποθηκευμένες επιλογές του κεντρικού Gantt.
    """
    recurring_project_ids = _get_mobile_recurring_project_ids(projects, recurring_patterns)

    # Το apply_recurring_project_visibility_filter χρειάζεται να ξέρει ποια έργα
    # θεωρούνται recurring. Το σετάρουμε εδώ χωρίς να εμφανίσουμε δεύτερο φίλτρο.
    st.session_state["gantt_known_recurring_project_ids"] = list(recurring_project_ids)

    if not recurring_project_ids:
        return []

    hidden_ids = _load_mobile_hidden_recurring_projects(recurring_project_ids)

    return [
        project_id
        for project_id in recurring_project_ids
        if project_id not in hidden_ids
    ]


# --- HEADER / CONTROLS ---
st.title("📱 Mobile Gantt")
gantt_search.render_schedule_search(st.session_state, get_local_today(), open_search_result, key="mobile_search")

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

st.caption("🔎 Το Zoom Gantt αλλάζει μόνο το πλάτος του διαγράμματος. Το App scale μικραίνει/μεγαλώνει όλη τη mobile σελίδα.")

scale_minus, scale_slider, scale_plus = st.columns([0.9, 2.4, 0.9])

with scale_minus:
    if st.button("➖", key="mobile_app_scale_minus", use_container_width=True, help="Σμίκρυνση όλης της mobile σελίδας"):
        st.session_state.mobile_app_scale_pct = max(65, int(st.session_state.mobile_app_scale_pct) - 5)
        clear_mobile_selection()
        st.rerun()

with scale_slider:
    st.session_state.mobile_app_scale_pct = st.slider(
        "App scale / Γενικό unzoom",
        min_value=65,
        max_value=115,
        value=int(st.session_state.mobile_app_scale_pct),
        step=5,
        key="mobile_app_scale_pct_slider",
        help="Μικραίνει ή μεγαλώνει γενικά τα στοιχεία της mobile σελίδας.",
    )

with scale_plus:
    if st.button("➕", key="mobile_app_scale_plus", use_container_width=True, help="Μεγέθυνση όλης της mobile σελίδας"):
        st.session_state.mobile_app_scale_pct = min(115, int(st.session_state.mobile_app_scale_pct) + 5)
        clear_mobile_selection()
        st.rerun()

app_scale = max(0.65, min(1.15, int(st.session_state.mobile_app_scale_pct) / 100.0))
zoom_factor = max(0.5, min(1.7, int(st.session_state.mobile_zoom_pct) / 100.0))

st.markdown(
    f"""
    <style>
    /* Mobile-only γενικό unzoom της σελίδας */
    .block-container {{
        font-size: {app_scale:.2f}rem !important;
        padding-top: {0.75 * app_scale:.2f}rem !important;
        padding-left: {0.55 * app_scale:.2f}rem !important;
        padding-right: {0.55 * app_scale:.2f}rem !important;
    }}

    .block-container h1 {{
        font-size: {2.0 * app_scale:.2f}rem !important;
        margin-bottom: {0.6 * app_scale:.2f}rem !important;
    }}

    .block-container h2 {{
        font-size: {1.55 * app_scale:.2f}rem !important;
    }}

    .block-container h3 {{
        font-size: {1.25 * app_scale:.2f}rem !important;
    }}

    .block-container p,
    .block-container label,
    .block-container span,
    .block-container div {{
        line-height: {1.35 * app_scale:.2f} !important;
    }}

    .stButton > button,
    .stDownloadButton > button,
    div[data-testid="stFormSubmitButton"] button {{
        min-height: {2.75 * app_scale:.2f}rem !important;
        font-size: {1.0 * app_scale:.2f}rem !important;
        padding: {0.45 * app_scale:.2f}rem {0.75 * app_scale:.2f}rem !important;
        border-radius: {12 * app_scale:.0f}px !important;
    }}

    div[data-testid="stForm"] {{
        padding: {0.75 * app_scale:.2f}rem !important;
        border-radius: {14 * app_scale:.0f}px !important;
    }}

    div[data-testid="stExpander"] summary {{
        font-size: {1.0 * app_scale:.2f}rem !important;
        min-height: {2.5 * app_scale:.2f}rem !important;
    }}

    .mobile-tip {{
        font-size: {0.92 * app_scale:.2f}rem !important;
        padding: {0.65 * app_scale:.2f}rem {0.8 * app_scale:.2f}rem !important;
        border-radius: {12 * app_scale:.0f}px !important;
        margin-bottom: {0.75 * app_scale:.2f}rem !important;
    }}

    input, textarea, select {{
        font-size: max(14px, {16 * app_scale:.0f}px) !important;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

start_of_week = _start_of_week(st.session_state.mobile_view_date)
gantt_height_px = int(560 * app_scale)


# --- ΚΑΘΡΕΦΤΗΣ ΦΙΛΤΡΟΥ ΚΕΝΤΡΙΚΟΥ GANTT ---
# Η mobile σελίδα δεν εμφανίζει δεύτερο ανεξάρτητο φίλτρο.
# Διαβάζει τις αποθηκευμένες επιλογές του χρήστη και δείχνει τις ίδιες μπάρες
# με το κεντρικό Gantt για τα επαναλαμβανόμενα έργα.
visible_recurring_project_ids = _get_mobile_visible_recurring_project_ids(
    projects=st.session_state.projects,
    recurring_patterns=st.session_state.recurring_patterns,
)

only_pending = placement_confirmation.render_filter(start_of_week, key="mobile_customer_pending_only")
detector_key = (
    f"mobile_gantt_detector_{st.session_state.mobile_detector_version}"
    f"_{gantt_height_px}_{zoom_factor}_{app_scale}"
)
if not is_full_admin:
    gantt_live_view.render(
        start_of_week, zoom_factor, gantt_height_px,
        visible_recurring_project_ids, search_prefix="mobile",
        detector_key=detector_key, only_pending=only_pending,
    )
    st.info("Ο συγκεκριμένος χρήστης έχει μόνο προβολή.")
    st.stop()

search_target = st.session_state.get("mobile_search_target")
week = gantt_live_view.week_data(start_of_week, zoom_factor, visible_recurring_project_ids, search_target)
_, wk_groups, _ = week

search_bar_key = gantt_search.find_search_bar(wk_groups, search_target)
opening_search_result = st.session_state.pop("mobile_search_pending", False)
if opening_search_result and search_bar_key:
    st.session_state.mobile_reset_edit_select_next_run = False
    st.session_state.mobile_clicked_key = search_bar_key
    st.session_state.mobile_edit_select_widget = search_bar_key


def handle_chart_click(clicked_safe_id, safe_mapping):
    if clicked_safe_id:
        real_clicked_key = safe_mapping.get(clicked_safe_id)
        if real_clicked_key and clicked_safe_id != st.session_state.mobile_last_clicked_safe_id:
            st.session_state.mobile_last_clicked_safe_id = clicked_safe_id
            st.session_state.mobile_clicked_key = real_clicked_key
            st.session_state.mobile_edit_select_widget = real_clicked_key
            st.session_state.skip_remote_sync_once = True
            st.rerun()


gantt_live_view.render(
    start_of_week, zoom_factor, gantt_height_px,
    visible_recurring_project_ids, search_prefix="mobile", detector_key=detector_key,
    initial_week=week, opening_search=opening_search_result, on_click=handle_chart_click,
    can_refresh=lambda: not st.session_state.get("mobile_clicked_key"),
    only_pending=only_pending, email_menu=True,
)

if st.session_state.get("mobile_clicked_key"):
    st.markdown('<div id="is_editing_flag" style="display:none;"></div>', unsafe_allow_html=True)


st.divider()


# =========================================================
# NEW ASSIGNMENT
# =========================================================
with st.expander("➕ Νέα Τοποθέτηση", expanded=False):
    qa_rc = st.session_state.mobile_qa_rc

    with st.form("mobile_quick_add", clear_on_submit=False):
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

        add_project_details = placement_details.inputs(key=f"mqa_details_{qa_rc}", stacked=True)
        add_periodic_task = periodic_visits.inputs(key=f"mqa_periodic_{qa_rc}", project_id=proj_choice)

        emp_choices = st.multiselect(
            "Προσωπικό",
            options=active_employee_ids,
            format_func=utils.get_employee_name,
            key=f"mqa_emps_{qa_rc}",
        )

        add_support_roles = placement_roles.inputs(key=f"mqa_roles_{qa_rc}", stacked=True)
        add_actual_hours = placement_hours.inputs(key=f"mqa_actual_hours_{qa_rc}")

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

        add_confirmation = placement_confirmation.inputs(key=f"mqa_customer_{qa_rc}")
        submit_add = st.form_submit_button("Καταχώρηση", use_container_width=True)
        add_spacing_key = f"mobile_add_{qa_rc}"
        add_spacing_override = periodic_visits.spacing_review_control(add_spacing_key)

        if submit_add or add_spacing_override:
            str_arrival = _time_to_str(t_arrival) if use_arr else ""
            str_start = _time_to_str(t_start)
            str_end = _time_to_str(t_end)

            if str_start >= str_end:
                st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
            else:
                final_proj_id, pending_new_project = _make_or_get_project(proj_choice, custom_proj_name, color_choice)
                emps_to_process = emp_choices if emp_choices else [""]
                new_assigns = []

                try:
                    visit_links = periodic_visits.links_for_dates(
                        add_periodic_task, final_proj_id, st.session_state.get("recurring_patterns", []),
                        [add_date + timedelta(days=i) for i in range(int(duration_days))],
                    )
                except ValueError as exc:
                    st.error(str(exc))
                    st.stop()
                for day_offset in range(int(duration_days)):
                    current_assign_date = add_date + timedelta(days=day_offset)
                    valid_assignments = []

                    valid_assignments = [
                        {"eid": eid, "start": str_start, "end": str_end, "msg": "",
                         "emp_name": utils.get_employee_name(eid) if eid else ""}
                        for eid in emps_to_process
                    ]

                    for va in valid_assignments:
                        if va["msg"] == "Allowed Overlap":
                            st.toast(
                                f"ℹ️ Επιτράπηκε επικάλυψη για {va['emp_name']}.",
                                icon="ℹ️",
                            )

                        final_notes = add_notes
                        if va["msg"] and va["msg"] != "Allowed Overlap":
                            final_notes = f"{add_notes} {va['msg']}".strip()

                        new_assignment = {
                            "id": str(uuid.uuid4()),
                            "employeeId": va["eid"],
                            "projectId": final_proj_id,
                            "date": current_assign_date,
                            "arrivalTime": str_arrival,
                            "startTime": va["start"],
                            "endTime": va["end"],
                            "colorName": color_choice,
                            "colorHex": config.BASIC_COLORS[color_choice],
                            "notes": periodic_visits.combine_notes(
                                placement_hours.combine_notes(
                                    placement_details.combine_notes(
                                        placement_roles.combine_notes(final_notes, add_support_roles), add_project_details
                                    ), add_actual_hours
                                ), visit_links[current_assign_date]
                            ),
                            "is_cancelled": False,
                            "cancel_reason": "",
                            "recurring_id": None,
                            "is_general": bool(is_general),
                        }
                        new_assignment["notes"] = placement_confirmation.combine_notes(
                            new_assignment["notes"], add_confirmation,
                        )
                        new_assigns.append(new_assignment)

                periodic_visits.confirm_spacing([], new_assigns, add_spacing_key, override=add_spacing_override)
                saved = utils.save_assignment_batch([], new_assigns, project=pending_new_project)
                if saved is not None:
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

        options_for_select = [""] + group_keys
        if st.session_state.mobile_edit_select_widget not in options_for_select:
            st.session_state.mobile_edit_select_widget = ""

        selected_key = st.selectbox(
            "Μπάρα",
            options=options_for_select,
            key="mobile_edit_select_widget",
            format_func=lambda x: "Επιλέξτε..." if x == "" else f"{wk_groups[x]['Date'].strftime('%d/%m')} | {wk_groups[x].get('ProjectDisplay', wk_groups[x]['Project'])} | {wk_groups[x]['StartTime']}-{wk_groups[x]['EndTime']}",
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
                f"{target_group.get('ProjectDisplay', target_group['Project'])} | "
                f"{target_group['StartTime']}-{target_group['EndTime']}"
            )

            edit_suffix = "_" + hashlib.sha1(selected_key.encode()).hexdigest()[:12]
            placement_confirmation.render_confirm_button(
                target_group, utils.save_assignment_batch, clear_mobile_selection,
                key=f"mobile_confirm_customer{edit_suffix}",
            )
            with st.form("mobile_quick_edit" + edit_suffix):
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

                _, target_project_details = placement_details.split_notes(
                    target_group.get("Notes_Raw") or target_group.get("Notes", "")
                )
                target_project_details = target_group.get("ProjectDetails", target_project_details)
                edit_project_details = placement_details.inputs(
                    key="mobile_edit_details" + edit_suffix, defaults=target_project_details, stacked=True
                )

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

                target_free_notes, target_support_roles = placement_roles.split_notes(target_group.get("Notes", ""))
                target_support_roles = target_group.get("SupportRoles", target_support_roles)
                target_free_notes, _ = placement_details.split_notes(target_free_notes)
                target_free_notes, _ = placement_hours.split_notes(target_free_notes)
                target_free_notes, _ = periodic_visits.split_notes(target_free_notes)
                target_visit_link = periodic_visits.split_notes(target_group.get("Notes_Raw", ""))[1]
                edit_periodic_task = periodic_visits.inputs(
                    key=f"mobile_edit_periodic{edit_suffix}", project_id=edit_proj,
                    default=target_visit_link['task_id'] if target_visit_link else None,
                )
                edit_actual_hours = placement_hours.inputs(
                    key=f"mobile_edit_actual_hours{edit_suffix}",
                    default=placement_hours.split_notes(
                        target_group.get("Notes_Raw") or target_group.get("Notes", "")
                    )[1],
                )
                edit_support_roles = placement_roles.inputs(
                    key="mobile_edit_roles_" + hashlib.sha1(selected_key.encode()).hexdigest()[:12],
                    defaults=target_support_roles, stacked=True,
                )
                target_clean_note = clean_conflict_leave_notes(target_free_notes)
                edit_notes = st.text_input("Παρατηρήσεις", value=target_clean_note)

                existing_arr = target_group.get("ArrivalTime", "")
                use_arr_edit = st.checkbox("Με προσέλευση", value=bool(existing_arr), key=f"mobile_edit_use_arr{edit_suffix}")

                def_arr = (
                    datetime.strptime(existing_arr, "%H:%M").time()
                    if existing_arr
                    else datetime.strptime(str(target_group["StartTime"])[:5], "%H:%M").time()
                )

                new_t_arrival = st.time_input("Ώρα προσέλευσης", value=def_arr, key=f"mobile_edit_arrival{edit_suffix}")
                new_t_start = st.time_input(
                    "Έναρξη",
                    value=datetime.strptime(str(target_group["StartTime"])[:5], "%H:%M").time(),
                    key=f"mobile_edit_start{edit_suffix}",
                )
                new_t_end = st.time_input(
                    "Λήξη",
                    value=datetime.strptime(str(target_group["EndTime"])[:5], "%H:%M").time(),
                    key=f"mobile_edit_end{edit_suffix}",
                )

                e_is_general = st.checkbox(
                    "Γενικός",
                    value=bool(target_group.get("IsGeneral", False)),
                    key=f"mobile_edit_is_general{edit_suffix}",
                )

                e_is_cancelled = st.checkbox(
                    "Ακυρωμένη",
                    value=bool(target_group.get("is_cancelled", False)),
                    key=f"mobile_edit_is_cancelled{edit_suffix}",
                )

                e_cancel_reason = st.text_input(
                    "Λόγος ακύρωσης",
                    value=target_group.get("cancel_reason", ""),
                    key=f"mobile_edit_cancel_reason{edit_suffix}",
                )

                edit_confirmation = placement_confirmation.inputs(
                    key=f"mobile_edit_customer{edit_suffix}", default=target_group.get("CustomerConfirmation"),
                )
                if e_is_cancelled:
                    edit_confirmation = None

                save_edit = st.form_submit_button("💾 Αποθήκευση", use_container_width=True)
                delete_edit = st.form_submit_button("🗑️ Οριστική Διαγραφή", use_container_width=True)
                edit_spacing_key = f"mobile_edit{edit_suffix}"
                edit_spacing_override = periodic_visits.spacing_review_control(edit_spacing_key)

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

                if save_edit or edit_spacing_override:
                    str_arrival = _time_to_str(new_t_arrival) if use_arr_edit else ""
                    str_start = _time_to_str(new_t_start)
                    str_end = _time_to_str(new_t_end)

                    if str_start >= str_end:
                        st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                    else:
                        selected_emp_ids = normalize_id_list(edit_emps)
                        original_emp_ids = normalize_id_list([eid for eid in target_group["EmployeeIds"] if eid])
                        final_edit_proj_id, pending_new_project = _make_or_get_project(edit_proj, edit_custom_proj_name, edit_color)
                        emps_to_process = selected_emp_ids if selected_emp_ids else [""]

                        normalized_cancel_reason = e_cancel_reason if e_is_cancelled else ""
                        try:
                            edit_visit_link = periodic_visits.make_link(
                                edit_periodic_task, final_edit_proj_id,
                                st.session_state.get("recurring_patterns", []), target_visit_link,
                            )
                        except ValueError as exc:
                            st.error(str(exc))
                            st.stop()

                        valid_assignments = []
                        has_blocking_error = False

                        valid_assignments = [
                            {"eid": eid, "start": str_start, "end": str_end, "msg": "",
                             "emp_name": utils.get_employee_name(eid) if eid else ""}
                            for eid in emps_to_process
                        ]

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

                                new_assignment = {
                                    "id": str(uuid.uuid4()),
                                    "employeeId": va["eid"],
                                    "projectId": final_edit_proj_id,
                                    "date": edit_date,
                                    "arrivalTime": str_arrival,
                                    "startTime": va["start"],
                                    "endTime": va["end"],
                                    "colorName": edit_color,
                                    "colorHex": config.BASIC_COLORS[edit_color],
                                    "notes": periodic_visits.combine_notes(
                                        placement_hours.combine_notes(
                                            placement_details.combine_notes(
                                                placement_roles.combine_notes(final_notes, edit_support_roles), edit_project_details
                                            ), edit_actual_hours
                                        ), edit_visit_link
                                    ),
                                    "is_cancelled": bool(e_is_cancelled),
                                    "cancel_reason": normalized_cancel_reason,
                                    "recurring_id": target_group.get("RecurringId"),
                                    "is_general": bool(e_is_general),
                                }
                                new_assignment["notes"] = placement_confirmation.combine_notes(
                                    new_assignment["notes"], edit_confirmation,
                                )
                                new_assigns.append(new_assignment)

                            periodic_visits.confirm_spacing(
                                old_assigns, new_assigns, edit_spacing_key, override=edit_spacing_override,
                            )
                            if utils.save_assignment_batch(
                                old_assigns, new_assigns, project=pending_new_project,
                                keep_worker_ids=True,
                            ) is None:
                                st.stop()
                            clear_mobile_selection()
                            st.success("Η μπάρα αποθηκεύτηκε.")
                            st.rerun()

