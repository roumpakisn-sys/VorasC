from datetime import datetime, time, timedelta, timezone
from hashlib import sha256

import pandas as pd
import streamlit as st

import gantt_engine
from gantt_helpers import get_local_today
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

day = st.date_input("Ημερομηνία παρουσιών και μήνας σύνοψης", get_local_today(), format="DD/MM/YYYY")
month_start, next_month = tracking.month_bounds(day)
try:
    attendance = tracking.period_rows(
        client, "stadium_attendance", ("work_date", "assignment_id", "employee_id", "project_id"),
        "work_date", month_start, next_month,
    )
    tasks = tracking.period_rows(client, "stadium_tasks", ("work_date", "id"), "work_date", month_start, next_month)
    matches = tracking.period_rows(
        client, "stadium_matches", ("match_date", "competition"), "match_date", month_start, next_month,
    )
except Exception as exc:
    if getattr(exc, "code", "") in ("PGRST205", "42P01"):
        st.warning("Η βάση δεν έχει ακόμη τους πίνακες παρακολούθησης του έργου.")
    else:
        st.error("Δεν φορτώθηκαν τα στοιχεία του έργου. Δοκίμασε ξανά.")
    st.stop()

if message := state.pop("stadium_saved", ""):
    st.success(message)

summary_tab, attendance_tab, tasks_tab, matches_tab = st.tabs(
    ["Σύνοψη", "Παρουσίες", "Εργασίες", "Αγώνες"]
)


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


def save_attendance(entries):
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
    utils.log_activity("ΚΑΤΑΧΩΡΙΣΗ ΠΑΡΟΥΣΙΩΝ", "stadium_attendance", f"{day:%d/%m/%Y} · {saved} παρουσίες")
    state.stadium_saved = f"Αποθηκεύτηκαν {saved} παρουσίες."
    st.rerun()


def render_attendance():
    scheduled = state.assignments_by_date.get(day, [])
    _, groups, _ = gantt_engine.generate_gantt_chart(
        day - timedelta(days=day.weekday()), 1.0, False, state.get("local_gantt_version", 0),
        {day: scheduled}, state.leaves, state.employees, state.projects, state.emp_map, state.proj_map,
    )
    bars = {bar["Key"]: bar for bar in tracking.stadium_bars(groups, day)}
    by_id = {row["id"]: row for row in scheduled if row.get("employeeId") and not row.get("is_cancelled")}
    if bars:
        selected = st.selectbox(
            "Μπάρα από το Gantt", bars, index=None, placeholder="Επίλεξε έργο και ωράριο",
            format_func=lambda key: (
                f"{bars[key]['StartTime']}–{bars[key]['EndTime']} · {bars[key]['ProjectDisplay']} · "
                f"{', '.join(state.emp_map.get(e, {}).get('name', 'Άγνωστος') for e in bars[key]['EmployeeIds'] if e)}"
            ),
        )
        if selected is not None:
            roster = [by_id[key] for key in bars[selected]["AssignmentIds"] if key in by_id]
            render_attendance_form(roster)
    else:
        st.info("Δεν βρέθηκαν για αυτή την ημέρα κίτρινες μπάρες με προσωπικό και τίτλο που περιέχει ΓΗΠΕΔΟ, ΑΡΗΣ ή ΑΓΩΝΑΣ.")

    saved = _on_date(attendance)
    if saved:
        st.subheader("Καταχωρισμένες παρουσίες")
        st.dataframe(pd.DataFrame([
            (row["employee_name"], row["arrival"][:5], row["departure"][:5], row["break_minutes"],
             _duration(row["worked_minutes"]), row["area"], row["notes"]) for row in saved
        ], columns=["Εργαζόμενος", "Προσέλευση", "Αποχώρηση", "Διάλειμμα (λ.)", "Ώρες", "Χώρος", "Παρατηρήσεις"]),
            hide_index=True, width="stretch")


def render_attendance_form(roster):
    previous = {tracking.attendance_key(row): row for row in _on_date(attendance)}
    people = []
    for assignment in roster:
        employee = assignment["employeeId"]
        previous_row = previous.get((assignment["id"], assignment["projectId"], employee, day.isoformat()), {})
        name = state.emp_map.get(employee, {}).get("name") or previous_row.get("employee_name") or employee
        people.append((assignment, name, previous_row))
    if not people:
        return

    versions = [(a["id"], a.get("updated_at"), p.get("updated_at")) for a, _, p in people]
    form_key = "stadium_" + sha256(repr((day, versions)).encode()).hexdigest()[:20]
    with st.form(form_key):
        st.caption("Συμπλήρωσε προσέλευση και αποχώρηση μόνο για τις παρουσίες που καταχωρείς.")
        values = []
        for index, (assignment, name, row) in enumerate(people):
            st.markdown(f"**{name}**")
            start_col, end_col, pause_col, area_col = st.columns([2, 2, 2, 3])
            prefix = f"{form_key}_{index}"
            clock_in = start_col.time_input("Προσέλευση", time.fromisoformat(row["arrival"]) if row else None,
                                            step=60, key=f"{prefix}_in")
            clock_out = end_col.time_input("Αποχώρηση", time.fromisoformat(row["departure"]) if row else None,
                                           step=60, key=f"{prefix}_out")
            pause = pause_col.number_input("Διάλειμμα (λεπτά)", 0, 1439, value=row.get("break_minutes", 0),
                                          key=f"{prefix}_pause")
            area = area_col.text_input("Χώρος / τμήμα", row.get("area", ""), key=f"{prefix}_area")
            notes = st.text_input("Παρατηρήσεις", row.get("notes", ""), key=f"{prefix}_notes")
            values.append((assignment, name, clock_in, clock_out, pause, area, notes, row))
        if st.form_submit_button("Αποθήκευση παρουσιών", type="primary"):
            entries = []
            try:
                for assignment, name, clock_in, clock_out, pause, area, notes, row in values:
                    if clock_in is None and clock_out is None and not (pause or area.strip() or notes.strip()):
                        continue
                    if clock_in is None or clock_out is None:
                        raise ValueError(f"{name} · Συμπλήρωσε προσέλευση και αποχώρηση.")
                    entries.append(tracking.attendance_payload(
                        assignment, name, clock_in, clock_out, pause, area, notes, row,
                    ))
            except ValueError as exc:
                st.warning(str(exc))
                return
            if entries:
                save_attendance(entries)
            else:
                st.info("Συμπλήρωσε τουλάχιστον μία παρουσία.")


def render_tasks():
    today_tasks = {row["id"]: row for row in _on_date(tasks)}
    selected = st.selectbox(
        "Καταχώριση ή επεξεργασία εργασίας", [None, *today_tasks],
        format_func=lambda key: (
            "Νέα εργασία" if key is None else f"{today_tasks[key]['area']} · {today_tasks[key]['category']}"
        ),
    )
    current = today_tasks.get(selected, {})
    with st.form(f"stadium_task_{day}_{selected}_{current.get('updated_at', '')}"):
        area = st.text_input("Χώρος / τμήμα", current.get("area", ""))
        category = st.selectbox("Εργασία", tracking.CATEGORIES,
                                index=tracking.CATEGORIES.index(current.get("category", tracking.CATEGORIES[0])))
        description = st.text_area("Περιγραφή εργασιών", current.get("description", ""))
        team = st.text_input("Συνεργείο / υπεύθυνος", current.get("team", ""))
        status = st.selectbox("Κατάσταση", tracking.STATUSES,
                              index=tracking.STATUSES.index(current.get("status", tracking.STATUSES[0])))
        notes = st.text_input("Παρατηρήσεις / εκκρεμότητες", current.get("notes", ""))
        if st.form_submit_button("Αποθήκευση εργασίας", type="primary"):
            if not area.strip() or not description.strip():
                st.warning("Συμπλήρωσε τον χώρο και την περιγραφή της εργασίας.")
            else:
                record = dict(work_date=day.isoformat(), area=area.strip(), category=category,
                              description=description.strip(), team=team.strip(), status=status, notes=notes.strip())
                try:
                    query = client.table("stadium_tasks")
                    if selected:
                        record["updated_at"] = datetime.now(timezone.utc).isoformat()
                        result = query.update(record).eq("id", selected).eq("updated_at", current["updated_at"])
                    else:
                        result = query.insert(record)
                    if not result.execute().data:
                        st.error("Η βάση δεν επιβεβαίωσε την αποθήκευση της εργασίας.")
                        return
                except Exception:
                    st.error("Δεν επιβεβαιώθηκε η αποθήκευση της εργασίας.")
                    return
                state.stadium_saved = "Η εργασία αποθηκεύτηκε."
                st.rerun()
    if today_tasks:
        st.dataframe(pd.DataFrame([
            (row["area"], row["category"], row["description"], row["team"], row["status"], row["notes"])
            for row in today_tasks.values()
        ], columns=["Χώρος", "Εργασία", "Περιγραφή", "Συνεργείο", "Κατάσταση", "Παρατηρήσεις"]),
            hide_index=True, width="stretch")


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


def render_matches():
    if matches:
        st.dataframe(pd.DataFrame([
            (utils.safe_date_parse(row["match_date"]).strftime("%d/%m/%Y"), row["competition"])
            for row in matches
        ], columns=["Ημερομηνία αγώνα", "Διοργάνωση"]), hide_index=True, width="stretch")
    with st.form("stadium_match"):
        competition = st.selectbox("Διοργάνωση για την επιλεγμένη ημερομηνία", tracking.COMPETITIONS)
        if st.form_submit_button("Καταχώριση αγώνα"):
            save_matches([{"match_date": day.isoformat(), "competition": competition}])
    uploaded = st.file_uploader("Προσθήκη αγώνων από Πρωτάθλημα και Κύπελλο (Excel)", type="xlsx")
    if uploaded:
        try:
            imported = tracking.matches_from_excel(uploaded)
        except Exception:
            st.error("Το αρχείο Excel δεν διαβάστηκε.")
            return
        if imported:
            st.dataframe(pd.DataFrame([
                (f"{match_day:%d/%m/%Y}", competition) for match_day, competition in imported
            ], columns=["Ημερομηνία αγώνα", "Διοργάνωση"]), hide_index=True, width="stretch")
            if st.button("Προσθήκη ημερομηνιών αγώνων"):
                save_matches([
                    {"match_date": match_day.isoformat(), "competition": competition}
                    for match_day, competition in imported
                ])
        else:
            st.info("Δεν βρέθηκαν αγώνες στο Κλεάνθης Βικελίδης στα δύο φύλλα.")


with summary_tab:
    render_summary()
with attendance_tab:
    render_attendance()
with tasks_tab:
    render_tasks()
with matches_tab:
    render_matches()
