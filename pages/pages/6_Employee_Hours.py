import streamlit as st
from datetime import date, datetime, timedelta, time
import pandas as pd

import utils


# =========================================================
# EMPLOYEE HOURS PAGE
# Νέα ανεξάρτητη σελίδα για έλεγχο ωρών εργαζομένου.
# Δεν αλλάζει υπάρχον Gantt, Management, Mobile Gantt ή δεδομένα.
# =========================================================

st.set_page_config(page_title="Ώρες Εργαζομένου", page_icon="⏱️", layout="wide")


# --- AUTH / SESSION SAFETY ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.get("authenticated"):
    st.switch_page("streamlit_app.py")
    st.stop()

for key, default in {
    "employees": [],
    "projects": [],
    "assignments": [],
    "leaves": [],
    "recurring_patterns": [],
    "evaluations": [],
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# --- DATA / COMMON SIDEBAR ---
utils.init_data_and_sync()
utils.setup_shared_ui()


def _safe_date(value):
    """Μετατρέπει ασφαλώς date/datetime/string σε date."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        raw = value.split("T")[0][:10]
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
    return None


def _safe_time(value):
    """Μετατρέπει ασφαλώς ώρα τύπου HH:MM σε time."""
    if isinstance(value, time):
        return value
    if value is None:
        return None

    raw = str(value).strip()[:5]
    if not raw:
        return None

    try:
        return datetime.strptime(raw, "%H:%M").time()
    except ValueError:
        return None


def _duration_hours(start_value, end_value):
    """Υπολογίζει διάρκεια σε ώρες. Υποστηρίζει και λήξη μετά τα μεσάνυχτα."""
    start_t = _safe_time(start_value)
    end_t = _safe_time(end_value)

    if not start_t or not end_t:
        return 0.0

    base_day = date(2000, 1, 1)
    start_dt = datetime.combine(base_day, start_t)
    end_dt = datetime.combine(base_day, end_t)

    if end_dt <= start_dt:
        end_dt += timedelta(days=1)

    return round((end_dt - start_dt).total_seconds() / 3600, 2)


def _project_name(project_id):
    for project in st.session_state.get("projects", []):
        if project.get("id") == project_id:
            return project.get("name", "Άγνωστο Έργο")
    return "Άγνωστο Έργο"


def _employee_name(employee_id):
    for employee in st.session_state.get("employees", []):
        if employee.get("id") == employee_id:
            return employee.get("name", "Άγνωστος")
    return "Άγνωστος"


def _format_hours(value):
    return f"{float(value or 0):.2f}"


def _get_employee_assignments(employee_id):
    """Επιστρέφει μόνο πραγματικές, μη ακυρωμένες βάρδιες του εργαζομένου."""
    rows = []

    for assignment in st.session_state.get("assignments", []):
        if not isinstance(assignment, dict):
            continue

        if assignment.get("employeeId") != employee_id:
            continue

        if assignment.get("is_cancelled", False):
            continue

        work_date = _safe_date(assignment.get("date"))
        if not work_date:
            continue

        start_time = str(assignment.get("startTime", "") or "")[:5]
        end_time = str(assignment.get("endTime", "") or "")[:5]
        hours = _duration_hours(start_time, end_time)

        if hours <= 0:
            continue

        rows.append({
            "date": work_date,
            "project_id": assignment.get("projectId"),
            "project": _project_name(assignment.get("projectId")),
            "arrival": str(assignment.get("arrivalTime", "") or "")[:5],
            "start": start_time,
            "end": end_time,
            "hours": hours,
            "notes": assignment.get("notes", "") or "",
            "assignment_id": assignment.get("id"),
        })

    rows.sort(key=lambda r: (r["date"], r["start"], r["project"]))
    return rows


def _filter_rows(rows, mode, selected_day, selected_month_date, selected_week_date):
    if mode == "Σύνολο":
        return rows, "Σύνολο όλων των καταχωρημένων βαρδιών"

    if mode == "Μήνας":
        month_start = date(selected_month_date.year, selected_month_date.month, 1)
        if selected_month_date.month == 12:
            next_month = date(selected_month_date.year + 1, 1, 1)
        else:
            next_month = date(selected_month_date.year, selected_month_date.month + 1, 1)
        month_end = next_month - timedelta(days=1)

        filtered = [
            row for row in rows
            if month_start <= row["date"] <= month_end
        ]
        return filtered, f"Μήνας: {month_start.strftime('%m/%Y')}"

    if mode == "Εβδομάδα":
        week_start = selected_week_date - timedelta(days=selected_week_date.weekday())
        week_end = week_start + timedelta(days=6)

        filtered = [
            row for row in rows
            if week_start <= row["date"] <= week_end
        ]
        return filtered, f"Εβδομάδα: {week_start.strftime('%d/%m/%Y')} - {week_end.strftime('%d/%m/%Y')}"

    if mode == "Συγκεκριμένη μέρα":
        filtered = [
            row for row in rows
            if row["date"] == selected_day
        ]
        return filtered, f"Ημέρα: {selected_day.strftime('%d/%m/%Y')}"

    return rows, ""


def _project_summary(rows):
    if not rows:
        return pd.DataFrame(columns=["Έργο", "Σύνολο Ωρών", "Αριθμός Βαρδιών"])

    df = pd.DataFrame(rows)
    summary = (
        df.groupby("project", as_index=False)
        .agg(
            **{
                "Σύνολο Ωρών": ("hours", "sum"),
                "Αριθμός Βαρδιών": ("assignment_id", "count"),
            }
        )
        .rename(columns={"project": "Έργο"})
        .sort_values("Σύνολο Ωρών", ascending=False)
    )

    summary["Σύνολο Ωρών"] = summary["Σύνολο Ωρών"].map(_format_hours)
    return summary


def _day_summary(rows):
    if not rows:
        return pd.DataFrame(columns=["Ημερομηνία", "Ημέρα", "Σύνολο Ωρών", "Αριθμός Βαρδιών"])

    df = pd.DataFrame(rows)
    summary = (
        df.groupby("date", as_index=False)
        .agg(
            **{
                "Σύνολο Ωρών": ("hours", "sum"),
                "Αριθμός Βαρδιών": ("assignment_id", "count"),
            }
        )
        .sort_values("date")
    )

    greek_days = {
        0: "Δευτέρα",
        1: "Τρίτη",
        2: "Τετάρτη",
        3: "Πέμπτη",
        4: "Παρασκευή",
        5: "Σάββατο",
        6: "Κυριακή",
    }

    summary["Ημερομηνία"] = summary["date"].map(lambda d: d.strftime("%d/%m/%Y"))
    summary["Ημέρα"] = summary["date"].map(lambda d: greek_days.get(d.weekday(), ""))
    summary["Σύνολο Ωρών"] = summary["Σύνολο Ωρών"].map(_format_hours)

    return summary[["Ημερομηνία", "Ημέρα", "Σύνολο Ωρών", "Αριθμός Βαρδιών"]]


def _detail_table(rows):
    if not rows:
        return pd.DataFrame(columns=[
            "Ημερομηνία",
            "Έργο",
            "Ώρα Προσέλευσης",
            "Έναρξη",
            "Λήξη",
            "Ώρες",
            "Παρατηρήσεις",
        ])

    detail_rows = []
    for row in rows:
        detail_rows.append({
            "Ημερομηνία": row["date"].strftime("%d/%m/%Y"),
            "Έργο": row["project"],
            "Ώρα Προσέλευσης": row["arrival"] if row["arrival"] else "-",
            "Έναρξη": row["start"],
            "Λήξη": row["end"],
            "Ώρες": _format_hours(row["hours"]),
            "Παρατηρήσεις": row["notes"],
        })

    return pd.DataFrame(detail_rows)


# --- PAGE UI ---
st.title("⏱️ Ώρες Εργαζομένου")
st.caption("Υπολογισμός ωρών από τις καταχωρημένες βάρδιες. Δεν αλλάζει ή αποθηκεύει δεδομένα.")

employees = [
    employee for employee in st.session_state.get("employees", [])
    if isinstance(employee, dict) and employee.get("id")
]

if not employees:
    st.warning("Δεν υπάρχουν εργαζόμενοι για εμφάνιση.")
    st.stop()

employees = sorted(employees, key=lambda e: e.get("name", "").lower())

col_emp, col_mode = st.columns([2, 1])

with col_emp:
    selected_employee_id = st.selectbox(
        "Εργαζόμενος",
        options=[employee["id"] for employee in employees],
        format_func=_employee_name,
    )

with col_mode:
    period_mode = st.selectbox(
        "Περίοδος",
        options=["Σύνολο", "Μήνας", "Εβδομάδα", "Συγκεκριμένη μέρα"],
    )

today = date.today()
selected_day = today
selected_month_date = today
selected_week_date = today

if period_mode == "Μήνας":
    selected_month_date = st.date_input(
        "Επιλέξτε οποιαδήποτε ημερομηνία μέσα στον μήνα",
        value=today,
    )
elif period_mode == "Εβδομάδα":
    selected_week_date = st.date_input(
        "Επιλέξτε οποιαδήποτε ημερομηνία μέσα στην εβδομάδα",
        value=today,
    )
elif period_mode == "Συγκεκριμένη μέρα":
    selected_day = st.date_input(
        "Επιλέξτε ημέρα",
        value=today,
    )

all_rows = _get_employee_assignments(selected_employee_id)
filtered_rows, period_label = _filter_rows(
    all_rows,
    period_mode,
    selected_day,
    selected_month_date,
    selected_week_date,
)

total_hours = round(sum(row["hours"] for row in filtered_rows), 2)
total_shifts = len(filtered_rows)

st.markdown("---")

metric_1, metric_2, metric_3 = st.columns(3)
metric_1.metric("Σύνολο Ωρών", _format_hours(total_hours))
metric_2.metric("Αριθμός Βαρδιών", total_shifts)
metric_3.metric("Περίοδος", period_label)

st.markdown("---")

if not filtered_rows:
    st.info("Δεν βρέθηκαν βάρδιες για τον εργαζόμενο και την επιλεγμένη περίοδο.")
    st.stop()

st.subheader("Σύνολο ανά έργο")
st.dataframe(
    _project_summary(filtered_rows),
    use_container_width=True,
    hide_index=True,
)

if period_mode != "Συγκεκριμένη μέρα":
    st.subheader("Σύνολο ανά ημέρα")
    st.dataframe(
        _day_summary(filtered_rows),
        use_container_width=True,
        hide_index=True,
    )

st.subheader("Αναλυτικές βάρδιες")
st.dataframe(
    _detail_table(filtered_rows),
    use_container_width=True,
    hide_index=True,
)
