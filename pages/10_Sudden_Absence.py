"""STAFF.PRO | Sudden absence and batch replacement planning.

The page does NOT remove historical assignments or recurring patterns.
It applies guarded one-row-at-a-time updates after explicit confirmation.
Supabase REST is not a multi-row transaction; best-effort rollback is used
if a write fails, and the UI asks for reconciliation if rollback is incomplete.
"""
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Ξαφνική Απουσία | STAFF.PRO", page_icon="🚨", layout="wide")
import utils
from availability_rules import fetch_rules
from replacement_engine import as_date, is_cancelled, rank_candidates, candidate_assessment

if not st.session_state.get("authenticated", False):
    st.switch_page("streamlit_app.py")
    st.stop()
for key in ("employees", "projects", "assignments", "leaves", "recurring_patterns", "evaluations"):
    if key not in st.session_state:
        st.session_state[key] = []
utils.init_data_and_sync()
utils.setup_shared_ui()

def today():
    return datetime.now(ZoneInfo("Europe/Athens")).date()

def names_by_id(records):
    return {str(row.get("id")): str(row.get("name") or "Άγνωστο") for row in records}

def shift_key(row):
    return str(row.get("id") or "")

def shift_label(row, projects):
    day = as_date(row.get("date"))
    return f"{day:%d/%m/%Y} · {projects.get(str(row.get('projectId')), 'Άγνωστο έργο')} · {str(row.get('startTime'))[:5]}–{str(row.get('endTime'))[:5]}"

def fetch_page(table, start, finish):
    """Fetch all date-scoped rows, paging to avoid a silent 1000-row truncation."""
    all_rows = []
    for offset in range(0, 20000, 1000):
        q = (
            utils.supabase.table(table).select("*")
            .gte("date", start.isoformat()).lte("date", finish.isoformat())
            .order("date").range(offset, offset + 999)
        )
        page = list(q.execute().data or [])
        all_rows.extend(page)
        if len(page) < 1000:
            return all_rows
    raise RuntimeError("Πάρα πολλές εγγραφές για ασφαλή έλεγχο. Περιόρισε τις ημερομηνίες.")

def fetch_leaves(start, finish):
    return list((
        utils.supabase.table("leaves").select("*")
        .lte("startDate", finish.isoformat())
        .gte("endDate", start.isoformat()).execute()
    ).data or [])

def overlaps_leave(leave, eid, start, finish):
    left, right = as_date(leave.get("startDate")), as_date(leave.get("endDate"))
    return str(leave.get("employeeId")) == str(eid) and left and right and left <= finish and right >= start

def stable_same(fresh, original):
    fields = ("id", "employeeId", "projectId", "startTime", "endTime", "date", "is_cancelled")
    for field in fields:
        a, b = fresh.get(field), original.get(field)
        if field == "date":
            if as_date(a) != as_date(b):
                return False
        elif field in ("startTime", "endTime"):
            if str(a or "")[:5] != str(b or "")[:5]:
                return False
        elif str(a or "") != str(b or ""):
            return False
    return True

def apply_absence(emp_id, dates, affected, choices, max_hours, buffer, create_leave):
    if not utils.supabase:
        st.error("Απαιτείται σύνδεση Supabase.")
        return
    if st.session_state.get("current_user") == "TAN":
        st.error("Ο χρήστης έχει δικαιώματα προβολής μόνο.")
        return
    first, last = dates
    try:
        fresh_rules, err = fetch_rules(utils.supabase)
        if err:
            st.error("Δεν εφαρμόστηκαν αλλαγές: " + err)
            return
        fresh_people = utils.fetch_paginated("employees")
        employees = {str(e.get("id")): e for e in fresh_people}
        if emp_id not in employees:
            st.error("Ο εργαζόμενος δεν υπάρχει πλέον.")
            return

        # Refresh all rows, including previous-day overnight shifts and future shifts.
        current_rows = fetch_page("assignments", first - timedelta(days=1), last + timedelta(days=1))
        current_by_id = {str(a.get("id")): a for a in current_rows}
        original_by_id = {str(a.get("id")): a for a in affected}
        if not all(rid in current_by_id and stable_same(current_by_id[rid], old)
                   for rid, old in original_by_id.items()):
            st.error("Κάποια βάρδια άλλαξε από άλλον χρήστη. Ανανέωσε και φτιάξε νέο σχέδιο.")
            return
        fresh_leaves = fetch_leaves(first - timedelta(days=1), last + timedelta(days=1))
        if create_leave and any(overlaps_leave(lv, emp_id, first, last) for lv in fresh_leaves):
            st.error("Υπάρχει ήδη άδεια για αυτόν τον εργαζόμενο που καλύπτει μέρος του διαστήματος. Δεν καταχωρήθηκε διπλή άδεια.")
            return

        # Simulate all assignments together: a candidate chosen twice must be
        # checked against the first newly scheduled replacement.
        simulated = [a for a in current_rows if str(a.get("id")) not in original_by_id]
        changes = []
        for original in sorted(affected, key=lambda a: (as_date(a.get("date")), str(a.get("startTime"))[:5], shift_key(a))):
            rid = str(original["id"])
            new_id = str(choices.get(rid) or "")
            after = dict(current_by_id[rid])
            after["employeeId"] = new_id
            if new_id:
                chosen = employees.get(new_id)
                if not chosen or new_id == emp_id:
                    st.error("Η επιλεγμένη αντικατάσταση δεν είναι πλέον έγκυρη.")
                    return
                report = candidate_assessment(
                    chosen, after, simulated, fresh_leaves,
                    maximum_day_hours=max_hours,
                    travel_buffer_minutes=buffer,
                    availability=fresh_rules,
                    today=today(),
                )
                if not report["eligible"]:
                    st.error(f"Δεν εφαρμόστηκε το σχέδιο: {chosen.get('name', '')} · {report['reason']} · {as_date(after.get('date')):%d/%m/%Y}")
                    return
            simulated.append(after)
            changes.append((dict(current_by_id[rid]), after))

        # Guard against an overlapping sick leave that arrived during preflight.
        leave_record = None
        if create_leave:
            leave_record = {
                "id": str(uuid.uuid4()), "employeeId": emp_id,
                "startDate": first.isoformat(), "endDate": last.isoformat(),
                "leaveType": "Αναρρωτική Άδεια", "substituteId": None,
            }
        applied = []
        try:
            for previous, modified in changes:
                query = (
                    utils.supabase.table("assignments")
                    .update({"employeeId": modified["employeeId"]})
                    .eq("id", previous["id"])
                    .eq("employeeId", emp_id)
                    .eq("date", str(previous["date"])[:10])
                    .eq("startTime", previous["startTime"])
                    .eq("endTime", previous["endTime"])
                    .eq("projectId", previous["projectId"])
                )
                updated = list(query.execute().data or [])
                if len(updated) != 1 or str(updated[0].get("employeeId") or "") != modified["employeeId"]:
                    raise RuntimeError("Η βάρδια τροποποιήθηκε από άλλον χρήστη ή δεν αποθηκεύτηκε.")
                applied.append((previous, modified))
            if leave_record:
                inserted = list(utils.supabase.table("leaves").insert(leave_record).execute().data or [])
                if len(inserted) != 1:
                    raise RuntimeError("Η καταχώρηση αναρρωτικής άδειας δεν επιβεβαιώθηκε.")
        except Exception as err:
            rollback_errors = []
            for before, after in reversed(applied):
                try:
                    res = (
                        utils.supabase.table("assignments")
                        .update({"employeeId": before["employeeId"]})
                        .eq("id", before["id"])
                        .eq("employeeId", after["employeeId"]).execute()
                    )
                    if len(res.data or []) != 1:
                        rollback_errors.append(str(before["id"]))
                except Exception:
                    rollback_errors.append(str(before["id"]))
            st.session_state.last_sync_time = None
            if rollback_errors:
                st.error("Απαιτείται χειροκίνητος έλεγχος στη Supabase: η επαναφορά δεν ολοκληρώθηκε για " + ", ".join(rollback_errors))
            st.error(f"Η διαδικασία απέτυχε: {err}. Δεν θεωρείται ολοκληρωμένη.")
            return

        before_rows = []
        after_rows = []
        for before, after in changes:
            local = next((a for a in st.session_state.assignments if str(a.get("id")) == str(before["id"])), None)
            if local is not None:
                old_local = dict(local)
                local["employeeId"] = after["employeeId"]
                before_rows.append(old_local)
                after_rows.append(dict(local))
            else:
                b = dict(before); b["date"] = as_date(b.get("date"))
                a = dict(after); a["date"] = as_date(a.get("date"))
                before_rows.append(b)
                after_rows.append(a)
                st.session_state.assignments.append(a)
        acts = [{"type": "update", "table": "assignments", "old_records": before_rows, "new_records": after_rows}]
        if leave_record:
            l = dict(leave_record)
            l["startDate"] = first
            l["endDate"] = last
            st.session_state.leaves.append(l)
            acts.append({"type": "insert", "table": "leaves", "records": [l]})
        utils.add_transaction(acts)
        utils.mark_data_changed()
        utils.touch_app_sync_state()
        utils.log_activity(
            "ΞΑΦΝΙΚΗ ΑΠΟΥΣΙΑ", "assignments",
            f"Επαναπρογραμματισμός {len(changes)} βαρδιών ({first:%d/%m/%Y}–{last:%d/%m/%Y}).",
        )
        st.session_state["sudden_absence_success"] = (
            f"Ενημερώθηκαν {len(changes)} βάρδιες. "
            f"Ακάλυπτες: {sum(not x[1]['employeeId'] for x in changes)}."
        )
        st.session_state.last_sync_time = None
        st.rerun()
    except Exception as err:
        st.error(f"Δεν εφαρμόστηκε το σχέδιο: {err}. Ανανέωσε και έλεγξε τη βάση.")

st.title("🚨 Διαχείριση ξαφνικής απουσίας")
st.caption(
    "Εντοπισμός όλων των βαρδιών ενός εργαζομένου για συγκεκριμένες ημέρες. "
    "Προτάσεις αντικαταστάσεων και μαζική εφαρμογή μετά από επιβεβαίωση. "
    "Δεν διαγράφονται βάρδιες ή επαναλαμβανόμενοι κανόνες."
)
if msg := st.session_state.pop("sudden_absence_success", ""):
    st.success(msg)
if not utils.supabase:
    st.error("Απαιτείται Supabase.")
    st.stop()
availability, rule_error = fetch_rules(utils.supabase)
if rule_error:
    st.error(rule_error)
    st.info("Εκτέλεσε πρώτα το sql/employee_availability_rules.sql στη Supabase.")
    st.stop()

employees = sorted(
    [e for e in st.session_state.employees if e.get("id")],
    key=lambda e: str(e.get("name", "")).casefold(),
)
if not employees:
    st.info("Δεν υπάρχουν εργαζόμενοι.")
    st.stop()
employee_names = names_by_id(employees)
project_names = names_by_id(st.session_state.projects)
emp_id = st.selectbox("Εργαζόμενος που απουσιάζει", list(employee_names),
                      format_func=lambda x: employee_names[x], key="absence_employee")
d1, d2 = st.columns(2)
with d1:
    start_date = st.date_input("Από", value=today(), min_value=today(), key="absence_from")
with d2:
    end_date = st.date_input("Έως", value=today() + timedelta(days=2), min_value=today(), key="absence_to")
if start_date > end_date:
    st.error("Η ημερομηνία «Έως» πρέπει να είναι μεταγενέστερη ή ίση.")
    st.stop()
if (end_date - start_date).days > 30:
    st.error("Για ασφάλεια, η μαζική διαδικασία καλύπτει έως 31 ημερολογιακές ημέρες.")
    st.stop()

affected = sorted([
    a for a in st.session_state.assignments
    if isinstance(a, dict)
    and str(a.get("employeeId") or "") == emp_id
    and not is_cancelled(a)
    and (d := as_date(a.get("date"))) is not None and start_date <= d <= end_date
    and a.get("id")
], key=lambda a: (as_date(a.get("date")), str(a.get("startTime"))[:5], shift_key(a)))
if len(affected) > 150:
    st.error("Πάνω από 150 επηρεαζόμενες βάρδιες. Περιόρισε το διάστημα.")
    st.stop()

st.metric("Επηρεαζόμενες βάρδιες", len(affected))
if not affected:
    st.info("Δεν βρέθηκαν μελλοντικές ενεργές βάρδιες σε αυτό το διάστημα. Μπορείς να καταχωρήσεις την αναρρωτική από τη Διαχείριση Αδειών.")
    st.stop()

st.dataframe(pd.DataFrame([
    {"Ημερομηνία": as_date(a["date"]).strftime("%d/%m/%Y"),
     "Έργο": project_names.get(str(a.get("projectId")), "Άγνωστο έργο"),
     "Ωράριο": f"{str(a.get('startTime'))[:5]}–{str(a.get('endTime'))[:5]}"}
    for a in affected
]), hide_index=True, use_container_width=True)
c1, c2 = st.columns(2)
with c1:
    buffer = st.selectbox("Ελάχιστο κενό μεταξύ βαρδιών", [0, 15, 30, 60, 90], index=2,
                          format_func=lambda v: f"{v} λεπτά", key="absence_buffer")
with c2:
    hours = st.selectbox("Μέγιστες ώρες/ημέρα", [8.0, 9.0, 10.0, 12.0], index=2,
                         format_func=lambda v: f"{v:g} ώρες", key="absence_hours")
st.markdown("### Πρόγραμμα αντικαταστάσεων")
st.caption(
    "Η πρώτη επιλογή είναι προτεινόμενη. Μπορείς να επιλέξεις διαφορετικό διαθέσιμο "
    "εργαζόμενο ή «Χωρίς αντικαταστάτη». Ακάλυπτες βάρδιες θα συνεχίσουν να εμφανίζονται στο Gantt."
)

excluded_ids = {shift_key(a) for a in affected}
simulation = [dict(a) for a in st.session_state.assignments if shift_key(a) not in excluded_ids]
choices = {}
for idx, original in enumerate(affected, start=1):
    eligible, blocked = rank_candidates(
        original, employees, simulation, st.session_state.leaves,
        travel_buffer_minutes=buffer, maximum_day_hours=hours,
        availability=availability, today=today(),
    )
    suggestions = [str(e["employee_id"]) for e in eligible if str(e["employee_id"]) != emp_id]
    options = [""] + suggestions
    top = suggestions[0] if suggestions else ""
    label = shift_label(original, project_names)
    chosen = st.selectbox(
        f"{idx}. {label}", options,
        index=options.index(top),
        format_func=lambda x: ("— Χωρίς αντικαταστάτη —" if not x
                               else f"{employee_names.get(x, x)} · {next((r['score'] for r in eligible if r['employee_id'] == x), 0)} βαθμοί"),
        key=f"absence_choice_{emp_id}_{shift_key(original)}",
    )
    choices[shift_key(original)] = chosen
    if chosen:
        # Simulate suggested plan; final choices are revalidated as a batch before saving.
        planned = dict(original)
        planned["employeeId"] = chosen
        simulation.append(planned)
    if not eligible:
        st.caption("Δεν βρέθηκε διαθέσιμος αντικαταστάτης. Η θέση θα παραμείνει ακάλυπτη.")

st.markdown("### Προεπισκόπηση αλλαγών")
preview = pd.DataFrame([
    {"Ημερομηνία": as_date(a["date"]).strftime("%d/%m/%Y"),
     "Έργο": project_names.get(str(a.get("projectId")), "Άγνωστο έργο"),
     "Ωράριο": f"{str(a.get('startTime'))[:5]}–{str(a.get('endTime'))[:5]}",
     "Αντικατάσταση": employee_names.get(choices[shift_key(a)], "ΑΚΑΛΥΠΤΗ")}
    for a in affected
])
st.dataframe(preview, hide_index=True, use_container_width=True)

already_leave = any(overlaps_leave(lv, emp_id, start_date, end_date)
                    for lv in st.session_state.leaves)
with st.form("absence_apply"):
    record_leave = st.checkbox(
        "Καταχώρηση αναρρωτικής άδειας για το επιλεγμένο διάστημα",
        value=not already_leave,
        disabled=already_leave,
        help="Οι επίσημες αναρρωτικές άδειες παραμένουν στη Διαχείριση Αδειών.",
    )
    if already_leave:
        st.caption("Υπάρχει ήδη άδεια που επικαλύπτεται με το διάστημα. Δεν δημιουργούμε δεύτερη.")
    confirmed = st.checkbox(
        "Επιβεβαιώνω τις αλλαγές όλων των παραπάνω βαρδιών και τυχόν ακάλυπτες θέσεις."
    )
    submitted = st.form_submit_button(
        "✅ Εφαρμογή σχεδίου αντικαταστάσεων",
        use_container_width=True,
        disabled=st.session_state.get("current_user") == "TAN",
    )
if submitted:
    if not confirmed:
        st.warning("Απαιτείται ρητή επιβεβαίωση.")
    else:
        apply_absence(
            emp_id, (start_date, end_date), affected, choices, hours, buffer, record_leave
        )
st.caption(
    "Δεν πρόκειται για αυτόματη νομική διαχείριση άδειας. "
    "Οι κανόνες διαθεσιμότητας είναι επιχειρησιακοί και ελέγχονται μαζί με τα "
    "ωράρια, τις επίσημες άδειες και τις επικαλύψεις. "
    "Η εγγραφή πολλών βαρδιών γίνεται διαδοχικά στη Supabase: σε σφάλμα γίνεται "
    "προσπάθεια επαναφοράς, αλλά ενδέχεται να απαιτηθεί χειροκίνητος έλεγχος."
)
