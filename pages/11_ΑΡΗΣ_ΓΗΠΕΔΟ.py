from datetime import date, timedelta
from hashlib import sha256

import pandas as pd
import streamlit as st

import gantt_engine
from gantt_helpers import get_local_today
import stadium_fixtures as fixtures
import stadium_tracking as tracking
import utils


st.set_page_config(page_title="ΑΡΗΣ ΓΗΠΕΔΟ", layout="wide")
if not st.session_state.get("authenticated"):
    st.switch_page("streamlit_app.py")
    st.stop()

state = st.session_state
if state.get("current_user") == "TAN":
    st.error("Η παρακολούθηση έργου είναι διαθέσιμη στους χρήστες διαχείρισης έργων.")
    st.stop()

for key in ("employees", "projects", "assignments", "leaves", "recurring_patterns", "evaluations"):
    state.setdefault(key, [])
utils.init_data_and_sync()
utils.setup_shared_ui()
st.title("ΑΡΗΣ ΓΗΠΕΔΟ")

client = utils.supabase
if client is None:
    st.warning("Απαιτείται σύνδεση με τη βάση για την παρακολούθηση του έργου.")
    st.stop()

today = get_local_today()
day = st.date_input("Ημερομηνία παρουσιών και μήνας σύνοψης", today, format="DD/MM/YYYY")
month_start, next_month = tracking.month_bounds(day)
try:
    attendance = tracking.period_rows(
        client, "stadium_attendance", ("work_date", "assignment_id", "employee_id", "project_id"),
        "work_date", month_start, next_month,
    )
    tasks = tracking.period_rows(client, "stadium_tasks", ("work_date", "id"), "work_date", month_start, next_month)
    saved_matches = tracking.period_rows(
        client, "stadium_matches", ("match_date", "competition"), "match_date", month_start, next_month,
    )
except Exception as exc:
    if getattr(exc, "code", "") in ("PGRST205", "42P01"):
        st.warning("Η βάση δεν έχει ακόμη τους πίνακες παρακολούθησης του έργου.")
    else:
        st.error("Δεν φορτώθηκαν τα στοιχεία του έργου. Δοκίμασε ξανά.")
    st.stop()

save_notice = st.empty()
if message := state.pop("stadium_saved", ""):
    save_notice.success(message)

summary_tab, attendance_tab, matches_tab = st.tabs(["Σύνοψη", "Παρουσίες", "Αγώνες"])


@st.cache_resource(show_spinner=False)
def fixture_cache():
    return fixtures.ScheduleCache()


refresh = matches_tab.button("Ανανέωση από ΠΑΕ ΑΡΗΣ")
schedules, sources_failed = fixture_cache().get(refresh=refresh)
matches = fixtures.match_rows(saved_matches, schedules, month_start, next_month)


def _duration(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _on_date(rows, field="work_date"):
    return [row for row in rows if str(row[field]) == day.isoformat()]


def render_summary():
    result = tracking.summary(attendance, tasks, matches, day)
    daily = result["daily"]
    total_people, total_hours, total_tasks, workdays = st.columns(4)
    total_people.metric("Εργαζόμενοι μήνα", len(result["workers"]))
    total_hours.metric("Ώρες εργασίας", _duration(sum(row[3] for row in daily)))
    total_tasks.metric("Ολοκληρωμένες εργασίες", sum(row[4] for row in daily))
    workdays.metric("Ημέρες εργασίας", sum(row[3] > 0 for row in daily))

    month_view, day_view = st.columns([3, 2])
    with month_view:
        st.subheader(f"Ημερήσια εικόνα · {day:%m/%Y}")
        st.dataframe(pd.DataFrame([
            (f"{work_day:%d/%m/%Y}", "★" if match else "", people, _duration(minutes), completed)
            for work_day, match, people, minutes, completed in daily
        ], columns=["Ημερομηνία", "Αγώνας", "Εργαζόμενοι", "Ώρες", "Εργασίες"]), hide_index=True, width="stretch")
    with day_view:
        st.subheader(f"Ομάδα ημέρας · {day:%d/%m/%Y}")
        st.dataframe(pd.DataFrame([
            (name, _duration(minutes)) for name, minutes in result["selected"]
        ], columns=["Εργαζόμενος", "Ώρες ημέρας"]), hide_index=True, width="stretch")
        st.subheader("Ομάδα μήνα")
        st.dataframe(pd.DataFrame([
            (name, days, _duration(minutes)) for name, days, minutes in result["workers"]
        ], columns=["Εργαζόμενος", "Ημέρες παρουσίας", "Ώρες μήνα"]), hide_index=True, width="stretch")


def save_attendance(entries, work_day):
    try:
        saved = client.rpc("record_stadium_attendance", {"p_entries": entries}).execute().data
        if saved != len(entries):
            st.error("Η βάση δεν επιβεβαίωσε την καταχώριση. Ανανέωσε πριν δοκιμάσεις ξανά.")
            return
    except Exception as exc:
        if "Stale" in str(exc):
            st.warning("Η μπάρα ή οι παρουσίες άλλαξαν. Ανανέωσε τη σελίδα και διάλεξε ξανά τη βάρδια.")
        else:
            st.error("Η αποθήκευση παρουσιών δεν επιβεβαιώθηκε. Ανανέωσε πριν δοκιμάσεις ξανά.")
        return

    utils.mark_data_changed()
    utils.touch_app_sync_state()
    worked = sum(entry["did_work"] for entry in entries)
    absent = saved - worked
    details = f"{worked} παρουσίες και {absent} απουσίες"
    utils.log_activity("ΚΑΤΑΧΩΡΙΣΗ ΠΑΡΟΥΣΙΩΝ", "stadium_attendance", f"{work_day:%d/%m/%Y} · {details}")
    state.stadium_saved = f"Αποθηκεύτηκαν {details}."
    st.rerun()


def bars_for_day(work_day, scheduled, *, include_unstaffed=False):
    if not scheduled:
        return []
    _, groups, _ = gantt_engine.generate_gantt_chart(
        work_day - timedelta(days=work_day.weekday()), 1.0, False, state.get("local_gantt_version", 0),
        {work_day: scheduled}, state.leaves, state.employees, state.projects, state.emp_map, state.proj_map,
    )
    return tracking.stadium_bars(groups, work_day, include_unstaffed=include_unstaffed)


def render_attendance(work_day, day_records, *, initial_bar=None):
    scheduled = state.assignments_by_date.get(work_day, [])
    bars = {bar["Key"]: bar for bar in bars_for_day(work_day, scheduled)}
    by_id = {row["id"]: row for row in scheduled if row.get("employeeId") and not row.get("is_cancelled")}
    widget_scope = f"{work_day}_{initial_bar}" if initial_bar is not None else "day"
    if bars:
        selected = st.selectbox(
            "Μπάρα από το Gantt", bars,
            index=list(bars).index(initial_bar) if initial_bar in bars else None,
            placeholder="Επίλεξε έργο και ωράριο",
            key=f"stadium_attendance_bar_{widget_scope}",
            format_func=lambda key: (
                f"{bars[key]['StartTime']}–{bars[key]['EndTime']} · {bars[key]['ProjectDisplay']} · "
                f"{', '.join(state.emp_map.get(e, {}).get('name', 'Άγνωστος') for e in bars[key]['EmployeeIds'] if e)}"
            ),
        )
        if selected is not None:
            roster = [by_id[key] for key in bars[selected]["AssignmentIds"] if key in by_id]
            render_attendance_form(roster, work_day, day_records, widget_scope)
    else:
        st.info("Δεν βρέθηκαν για αυτή την ημέρα κίτρινες μπάρες με προσωπικό και τίτλο που περιέχει ΓΗΠΕΔΟ, ΑΡΗΣ ή ΑΓΩΝΑΣ.")

    saved = [row for row in day_records if row.get("did_work", True)]
    if saved:
        st.subheader("Καταχωρισμένες παρουσίες")
        st.dataframe(pd.DataFrame([
            (row["employee_name"], row["arrival"][:5], row["departure"][:5], row["break_minutes"],
             _duration(row["worked_minutes"]), row["area"], row["notes"]) for row in saved
        ], columns=["Εργαζόμενος", "Προσέλευση", "Αποχώρηση", "Διάλειμμα (λ.)", "Ώρες", "Χώρος", "Παρατηρήσεις"]),
            hide_index=True, width="stretch")
    absent = [row["employee_name"] for row in day_records if not row.get("did_work", True)]
    if absent:
        st.caption("Απουσίες βαρδιών · " + ", ".join(dict.fromkeys(absent)))


def render_attendance_form(roster, work_day, day_records, widget_scope):
    previous = {tracking.attendance_key(row): row for row in day_records}
    people = []
    for assignment in roster:
        employee = assignment["employeeId"]
        previous_row = previous.get(tracking.assignment_attendance_key(assignment), {})
        name = state.emp_map.get(employee, {}).get("name") or previous_row.get("employee_name") or employee
        people.append((assignment, name, previous_row))
    if not people:
        return

    versions = [(a["id"], a.get("updated_at"), p.get("updated_at")) for a, _, p in people]
    form_key = "stadium_" + sha256(repr((work_day, versions, widget_scope)).encode()).hexdigest()[:20]
    with st.form(form_key):
        st.caption("Έλεγξε το ωράριο της μπάρας και σημείωσε όσους δεν εργάστηκαν.")
        values = []
        for index, (assignment, name, row) in enumerate(people):
            prefix = f"{form_key}_{index}"
            name_col, absent_col = st.columns([3, 2])
            name_col.markdown(f"**{name}**")
            absent = absent_col.checkbox("Δεν εργάστηκε", value=not row.get("did_work", True), key=f"{prefix}_absent")
            start_col, end_col, pause_col, area_col = st.columns([2, 2, 2, 3])
            default_in, default_out = tracking.attendance_time_defaults(assignment, row)
            clock_in = start_col.time_input("Προσέλευση", default_in, step=60, key=f"{prefix}_in")
            clock_out = end_col.time_input("Αποχώρηση", default_out, step=60, key=f"{prefix}_out")
            pause = pause_col.number_input("Διάλειμμα (λεπτά)", 0, 1439, value=row.get("break_minutes", 0),
                                          key=f"{prefix}_pause")
            area = area_col.text_input("Χώρος / τμήμα", row.get("area", ""), key=f"{prefix}_area")
            notes = st.text_input("Παρατηρήσεις", row.get("notes", ""), key=f"{prefix}_notes")
            values.append((assignment, name, clock_in, clock_out, pause, area, notes, row, not absent))
        if st.form_submit_button("Αποθήκευση παρουσιών", type="primary"):
            entries = []
            try:
                for assignment, name, clock_in, clock_out, pause, area, notes, row, did_work in values:
                    if did_work and (clock_in is None or clock_out is None):
                        raise ValueError(f"{name} · Συμπλήρωσε προσέλευση και αποχώρηση.")
                    entries.append(tracking.attendance_payload(
                        assignment, name, clock_in, clock_out, pause, area, notes, row, did_work=did_work,
                    ))
            except ValueError as exc:
                st.warning(str(exc))
                return
            save_attendance(entries, work_day)


def save_matches(rows):
    try:
        client.table("stadium_matches").upsert(
            rows, on_conflict="match_date,competition", ignore_duplicates=True,
        ).execute()
    except Exception:
        st.error("Δεν επιβεβαιώθηκε η αποθήκευση των αγώνων.")
        return
    state.stadium_saved = "Οι ημερομηνίες αγώνων αποθηκεύτηκαν."
    st.rerun()


@st.dialog("Παρουσίες αγώνα", width="large")
def open_match_attendance(match_day, day_records, bar_key):
    st.caption(f"{match_day:%d/%m/%Y}")
    render_attendance(match_day, day_records, initial_bar=bar_key)


def match_table(rows, readiness, attendance_by_day, section):
    widths = [2, 1, 3, 2, 3]
    headings = ("Ημερομηνία αγώνα", "Ώρα", "Αντίπαλος", "Διοργάνωση", "Ετοιμότητα")
    for col, label in zip(st.columns(widths), headings):
        col.markdown(f"**{label}**")
    for row in rows:
        match_day = date.fromisoformat(row["match_date"])
        columns = st.columns(widths, vertical_alignment="center")
        details = (f"{match_day:%d/%m/%Y}", row.get("kickoff") or "—",
                   row.get("opponent") or "—", row["competition"])
        for col, detail in zip(columns, details):
            col.write(detail)
        if match_day not in readiness:
            columns[-1].write("—")
            continue
        status, bar = readiness[match_day]
        button_key = f"stadium_readiness_{section}_{match_day}_{row['competition']}"
        attendance_status = status in (tracking.MATCH_PENDING, tracking.MATCH_COMPLETE)
        help_text = "Άνοιγμα παρουσιών της βάρδιας" if attendance_status else "Άνοιγμα στο Gantt"
        if columns[-1].button(status, key=button_key, width="stretch", help=help_text):
            if attendance_status:
                open_match_attendance(match_day, attendance_by_day.get(row["match_date"], []), bar["Key"])
            else:
                assignment_id = str(bar["AssignmentIds"][0]) if bar else None
                state.stadium_gantt_target = (match_day, assignment_id)
                st.switch_page("pages/1_Gantt_Dashboard.py")


def render_matches():
    st.caption("Κλεάνθης Βικελίδης · Επίσημο πρόγραμμα ΠΑΕ ΑΡΗΣ")
    if sources_failed:
        st.warning(
            f"Προσωρινή αδυναμία ενημέρωσης ({', '.join(sources_failed)}). "
            "Εμφανίζονται οι τελευταίες διαθέσιμες ημερομηνίες."
        )
    upcoming = fixtures.match_rows(saved_matches, schedules, today, date.max)
    match_days = {date.fromisoformat(row["match_date"]) for row in (*upcoming, *matches)}
    scheduled = {match_day: state.assignments_by_date.get(match_day, []) for match_day in match_days}
    bars = {match_day: bars_for_day(match_day, rows, include_unstaffed=True) for match_day, rows in scheduled.items()}
    extra_days = {
        match_day for match_day, groups in bars.items()
        if not month_start <= match_day < next_month and groups and all(bar["HasAssignedEmployee"] for bar in groups)
    }
    attendance_by_day = {}
    for row in attendance:
        attendance_by_day.setdefault(str(row["work_date"]), []).append(row)

    unverified_days = set()
    if extra_days:
        try:
            extra_attendance = tracking.period_rows(
                client, "stadium_attendance", ("work_date", "assignment_id", "employee_id", "project_id"),
                "work_date", min(extra_days), max(extra_days) + timedelta(days=1),
            )
        except Exception:
            st.warning("Δεν φορτώθηκαν οι παρουσίες ορισμένων επόμενων αγώνων.")
            unverified_days = extra_days
        else:
            extra_dates = {d.isoformat() for d in extra_days}
            for row in extra_attendance:
                work_date = str(row["work_date"])
                if work_date in extra_dates:
                    attendance_by_day.setdefault(work_date, []).append(row)

    readiness = {}
    for match_day, groups in bars.items():
        if match_day not in unverified_days:
            recorded = {tracking.attendance_key(row) for row in attendance_by_day.get(match_day.isoformat(), ())}
            readiness[match_day] = tracking.match_readiness(groups, scheduled[match_day], recorded)

    st.subheader("Επόμενοι αγώνες")
    if upcoming:
        match_table(upcoming, readiness, attendance_by_day, "upcoming")
    else:
        st.info("Δεν υπάρχει διαθέσιμη ημερομηνία επόμενου αγώνα στο γήπεδο.")
    pending = sum(f.date is None for schedule in schedules.values() for f in schedule.fixtures)
    if pending:
        st.caption(f"Αγώνες στο γήπεδο με ημερομηνία προς ανακοίνωση: {pending}")

    st.subheader(f"Αγώνες μήνα · {day:%m/%Y}")
    if matches:
        match_table(matches, readiness, attendance_by_day, "month")
    else:
        st.info("Δεν υπάρχουν καταχωρισμένοι αγώνες γι’ αυτόν τον μήνα.")

    fallback = [
        kind for kind in tracking.COMPETITIONS
        if kind not in schedules or schedules[kind].season != fixtures.season_for(day)
    ]
    if fallback:
        with st.expander("Χειροκίνητη καταχώριση ημερομηνίας εφεδρείας"):
            with st.form("stadium_match"):
                competition = st.selectbox("Διοργάνωση για την επιλεγμένη ημερομηνία", fallback)
                if st.form_submit_button("Καταχώριση αγώνα"):
                    save_matches([{"match_date": day.isoformat(), "competition": competition}])


with summary_tab:
    render_summary()
with attendance_tab:
    render_attendance(day, _on_date(attendance))
with matches_tab:
    render_matches()
