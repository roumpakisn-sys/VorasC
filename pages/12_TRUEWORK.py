from collections import Counter, defaultdict
from datetime import date

import pandas as pd
import streamlit as st

import stadium_tracking
import truework_report as report
import utils
from gantt_helpers import get_local_today
from ui_shell import render_page_title_with_background


st.set_page_config(page_title="TRUEWORK", layout="wide")
state = st.session_state
if not state.get("authenticated"):
    st.switch_page("streamlit_app.py")
    st.stop()
if state.get("current_user") == "TAN":
    st.error("Η αναφορά είναι διαθέσιμη στους χρήστες διαχείρισης έργων.")
    st.stop()

for key in ("employees", "projects", "assignments", "leaves", "recurring_patterns", "evaluations"):
    state.setdefault(key, [])
utils.init_data_and_sync()
utils.setup_shared_ui()
render_page_title_with_background(
    "TRUEWORK", "truework-background.webp", key="truework_title", position="72% center",
)

months = (
    "Ιανουάριος", "Φεβρουάριος", "Μάρτιος", "Απρίλιος", "Μάιος", "Ιούνιος",
    "Ιούλιος", "Αύγουστος", "Σεπτέμβριος", "Οκτώβριος", "Νοέμβριος", "Δεκέμβριος",
)
today = get_local_today()
month_col, year_col = st.columns(2)
month = month_col.selectbox("Μήνας", range(1, 13), index=today.month - 1, format_func=lambda m: months[m - 1])
year = year_col.number_input("Έτος", min_value=1900, max_value=9998, value=today.year, step=1)
first, end = stadium_tracking.month_bounds(date(year, month, 1))

assignments = report.month_assignments(state.assignments_by_date, state.proj_map, first, end)
if not assignments:
    st.info("Δεν υπάρχουν κίτρινες βάρδιες για τον επιλεγμένο μήνα.")
    st.stop()

attendance = []
if utils.supabase is not None:
    try:
        attendance = stadium_tracking.period_rows(
            utils.supabase, "stadium_attendance", ("work_date", "assignment_id", "employee_id", "project_id"),
            "work_date", first, end,
        )
    except Exception as exc:
        if getattr(exc, "code", "") not in ("PGRST205", "42P01"):
            st.warning("Δεν φορτώθηκαν οι καταχωρίσεις παρουσιών του γηπέδου.")

employees = {str(row["id"]): row.get("name") for row in state.employees}
project_names = {str(row["id"]): row.get("name") for row in state.projects}
shifts = report.month_shifts(assignments, employees, state.leaves, attendance)
by_project = defaultdict(list)
for shift in shifts:
    by_project[shift.project_id].append(shift)


def project_name(project_id):
    return project_names.get(project_id) or "Άγνωστο έργο"


def status_counts(rows):
    return Counter(shift.status for shift in rows)


def names(values):
    return ", ".join(sorted(values, key=str.casefold)) or "—"


st.caption("Η κάλυψη προκύπτει από τις αναθέσεις και τις διαθέσιμες παρουσίες. "
           "Οι απουσίες εμφανίζονται όταν συνδέονται με συγκεκριμένη βάρδια.")
projects = sorted(by_project, key=lambda pid: project_name(pid).casefold())
counts = status_counts(shifts)
project_count, shift_count, absence_count, vacancy_count = st.columns(4)
project_count.metric("Έργα", len(by_project))
shift_count.metric("Βάρδιες", len(shifts))
absence_count.metric("Βάρδιες με απουσίες", sum(bool(shift.absences) for shift in shifts))
vacancy_count.metric("Ακάλυπτες ή μερικώς ακάλυπτες", counts[report.UNSTAFFED] + counts[report.PARTIAL])

summary, detail = st.tabs(["Σύνοψη μήνα", "Ανά έργο"])
with summary:
    rows = []
    for project_id in projects:
        project_shifts = by_project[project_id]
        status = status_counts(project_shifts)
        rows.append({
            "Έργο": project_name(project_id),
            "Βάρδιες": len(project_shifts),
            "Με προσωπικό": status[report.COVERED],
            "Με απουσίες": sum(bool(shift.absences) for shift in project_shifts),
            "Μερικώς ακάλυπτες": status[report.PARTIAL],
            "Ακάλυπτες": status[report.UNSTAFFED],
            "Ακυρωμένες": status[report.CANCELLED],
            "Αναμένουν πελάτη": status[report.PENDING],
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

with detail:
    project_col, filter_col = st.columns([3, 2])
    project_id = project_col.selectbox("Έργο", projects, format_func=project_name)
    view = filter_col.selectbox("Εμφάνιση", ("Όλες οι βάρδιες", "Με απουσίες", "Ακάλυπτες ή μερικώς ακάλυπτες"))
    selected_shifts = by_project[project_id]
    if view == "Με απουσίες":
        selected_shifts = [shift for shift in selected_shifts if shift.absences]
    elif view == "Ακάλυπτες ή μερικώς ακάλυπτες":
        selected_shifts = [shift for shift in selected_shifts if shift.status in (report.UNSTAFFED, report.PARTIAL)]

    if selected_shifts:
        st.dataframe(pd.DataFrame([{
            "Ημερομηνία": shift.day.strftime("%d/%m/%Y"),
            "Ωράριο": f"{shift.start}–{shift.end}",
            "Προσέλευση": shift.arrival or "—",
            "Διεύθυνση": shift.address or "—",
            "Κάλυψη": shift.status,
            "Προσωπικό": names(shift.workers),
            "Απουσίες": names(shift.absences),
            "Αντικαταστάσεις": names(shift.replacements),
            "Κενές θέσεις": shift.vacancies,
            "Αιτία ακύρωσης": shift.cancel_reason or "—",
        } for shift in selected_shifts]), hide_index=True, width="stretch")
    else:
        st.info("Δεν υπάρχουν βάρδιες που να ταιριάζουν στο φίλτρο.")
