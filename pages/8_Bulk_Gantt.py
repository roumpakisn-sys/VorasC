"""STAFF.PRO: safe, preview-first bulk edits of Gantt bars.

Uses the shared atomic assignment service and its database migration.
Each visible bar groups its underlying assignment rows using gantt_engine's grouping fields.
"""
import hashlib
import json
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Μαζικές Αλλαγές Gantt | STAFF.PRO", page_icon="🧩", layout="wide")

import utils
from availability_rules import fetch_rules
from assignment_policy import validate_changes

if not st.session_state.get("authenticated"):
    st.switch_page("streamlit_app.py")
    st.stop()
for key in ("employees", "projects", "assignments", "leaves", "recurring_patterns", "evaluations"):
    if key not in st.session_state:
        st.session_state[key] = []
utils.init_data_and_sync()
utils.setup_shared_ui()

TODAY = datetime.now(ZoneInfo("Europe/Athens")).date()
MAX_ROWS = 80  # Maximum number of underlying assignment records in one transaction.



def as_date(value):
    return utils.safe_date_parse(value)


def fmt(value):
    return str(value or "")[:5]


def minutes(value):
    raw = fmt(value)
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError(f"Μη έγκυρη ώρα: {value}")
    h, m = map(int, parts)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Μη έγκυρη ώρα: {value}")
    return 60 * h + m


def shift_times(record, delta):
    original_start = minutes(record.get("startTime"))
    original_end = minutes(record.get("endTime"))
    if original_end <= original_start:
        original_end += 1440
    new_start, new_end = original_start + delta, original_end + delta
    if not 0 <= new_start < 1440 or not new_start < new_end < new_start + 1441:
        raise ValueError("Η μετατόπιση αλλάζει την ημέρα έναρξης ή δημιουργεί μη έγκυρη διάρκεια.")
    output = {
        "startTime": f"{new_start // 60:02d}:{new_start % 60:02d}",
        "endTime": f"{(new_end // 60) % 24:02d}:{new_end % 60:02d}",
    }
    if fmt(record.get("arrivalTime")):
        arrival = minutes(record["arrivalTime"]) + delta
        if not 0 <= arrival < 1440:
            raise ValueError("Η ώρα προσέλευσης μεταφέρεται σε άλλη ημερομηνία.")
        output["arrivalTime"] = f"{arrival // 60:02d}:{arrival % 60:02d}"
    return output




def bar_groups(assignments, projects, start_day, end_day, selected_projects, hide_cancelled):
    project_lookup = {str(p.get("id")): p for p in projects}
    groups = {}
    for a in assignments:
        if not isinstance(a, dict) or not a.get("id"):
            continue
        d = as_date(a.get("date"))
        if not d or not start_day <= d <= end_day:
            continue
        if selected_projects and str(a.get("projectId")) not in selected_projects:
            continue
        if hide_cancelled and a.get("is_cancelled", False):
            continue
        project = project_lookup.get(str(a.get("projectId")), {})
        color = a.get("colorHex") or project.get("color") or "#999999"
        key = (
            d.isoformat(), str(a.get("projectId")), fmt(a.get("startTime")),
            fmt(a.get("endTime")), str(color), bool(a.get("is_cancelled", False)),
            str(a.get("cancel_reason") or ""), fmt(a.get("arrivalTime")),
            bool(a.get("is_general", False)),
        )
        groups.setdefault(key, []).append(a)
    return sorted(groups.values(), key=lambda g: (
        as_date(g[0]["date"]), fmt(g[0].get("startTime")),
        project_lookup.get(str(g[0].get("projectId")), {}).get("name", ""),
    ))


def build_delta(record, operation, options):
    if operation == "Αντικατάσταση εργαζομένου":
        if str(record.get("employeeId") or "") != options["old_employee"]:
            return {}
        return {"employeeId": options["new_employee"]}
    if operation == "Μεταφορά ημερομηνίας":
        day = as_date(record.get("date")) + timedelta(days=options["days"])
        return {"date": day.isoformat()}
    if operation == "Μετατόπιση ωραρίου":
        return shift_times(record, options["minutes"])
    if operation == "Κοινό νέο ωράριο":
        result = {"startTime": options["start"], "endTime": options["end"]}
        if options.get("set_arrival"):
            result["arrivalTime"] = options["arrival"]
        return result
    if operation == "Αλλαγή έργου":
        return {"projectId": options["project"]}
    if operation == "Προσθήκη παρατήρησης":
        previous = str(record.get("notes") or "").strip()
        note = options["notes"].strip()
        return {"notes": f"{previous} | {note}" if previous else note}
    if operation == "Αντικατάσταση παρατήρησης":
        # Preserve special contextual notes produced by leave/conflict handling.
        tags = re.findall(r"\[(?:Άδεια|Εμπλοκή):\s*[^\]]+\]", str(record.get("notes") or ""))
        text = options["notes"].strip()
        for tag in tags:
            if tag not in text:
                text = f"{text} {tag}".strip()
        return {"notes": text}
    raise ValueError("Άγνωστη ενέργεια")


def normalized(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10] if isinstance(value, date) and not isinstance(value, datetime) else value.isoformat()
    if value is None:
        return ""
    return str(value) if not isinstance(value, bool) else value




def build_plan(selected_groups, operation, options):
    old = {}
    new = {}
    deltas = {}
    skipped = 0
    for group in selected_groups:
        group_changed = False
        for original in group:
            rec_id = str(original["id"])
            if rec_id in old:
                continue
            proposed = build_delta(original, operation, options)
            actual = {key: val for key, val in proposed.items()
                      if normalized(original.get(key)) != normalized(val)}
            if actual:
                old[rec_id] = dict(original)
                new[rec_id] = {**original, **actual}
                deltas[rec_id] = actual
                group_changed = True
        if not group_changed:
            skipped += 1
    return {"old": old, "new": new, "deltas": deltas, "skipped": skipped, "operation": operation}


def validate_plan(plan, assignments, employees, leaves, availability=None):
    if len(plan['deltas']) > MAX_ROWS:
        return [f'Το όριο είναι {MAX_ROWS} εγγραφές ανά εφαρμογή. Επίλεξε λιγότερες μπάρες.']
    return validate_changes(list(plan['old'].values()), list(plan['new'].values()), {
        'assignments': assignments, 'employees': employees, 'leaves': leaves, 'rules': availability,
    })





def save_plan(plan):
    """The whole preview commits once or leaves all selected rows unchanged."""
    if not plan['deltas']:
        return False, 'Δεν υπάρχουν πραγματικές αλλαγές.'
    if len(plan['deltas']) > MAX_ROWS:
        return False, f'Το όριο είναι {MAX_ROWS} εγγραφές ανά εφαρμογή.'
    saved = utils.save_assignment_batch(list(plan['old'].values()), list(plan['new'].values()))
    if saved is None:
        return False, 'Δεν επιβεβαιώθηκε η μαζική αλλαγή. Ανανέωσε πριν ξαναδοκιμάσεις.'
    return True, f'Αποθηκεύτηκαν {len(saved)} αλλαγές στη Supabase.'



st.title("🧩 Μαζικές αλλαγές Gantt")
if st.session_state.pop("bulk_gantt_result", None):
    st.success("Οι μαζικές αλλαγές αποθηκεύτηκαν στη Supabase. Άνοιξε το Gantt για να τις δεις.")
st.caption("Επιλέγεις μπάρες, βλέπεις ακριβώς τι θα αλλάξει και επιβεβαιώνεις. Οι επαναλαμβανόμενοι κανόνες δεν τροποποιούνται· μόνο οι συγκεκριμένες βάρδιες.")
if st.session_state.get("current_user") == "TAN":
    st.info("Ο λογαριασμός σου έχει πρόσβαση μόνο για προβολή.")
    st.stop()
if not utils.supabase:
    st.error("Απαιτείται ενεργή σύνδεση με τη Supabase για τις μαζικές αλλαγές.")
    st.stop()

start_col, end_col = st.columns(2)
with start_col:
    from_date = st.date_input("Από ημερομηνία", TODAY, key="bulk_from")
with end_col:
    through_date = st.date_input("Έως ημερομηνία", TODAY + timedelta(days=7), key="bulk_to")
if through_date < from_date or (through_date - from_date).days > 31:
    st.error("Επίλεξε διάστημα 1–32 ημερών (έως 31 ημέρες διαφορά).")
    st.stop()

proj_map = {str(p["id"]): str(p.get("name") or "Άγνωστο") for p in st.session_state.projects}
emp_map = {str(e["id"]): str(e.get("name") or "Άγνωστο") for e in st.session_state.employees}
project_filter = st.multiselect("Έργα (κενό = όλα)", options=sorted(proj_map), format_func=lambda x: proj_map[x], key="bulk_projects")
hide_cancelled = st.checkbox("Απόκρυψη ακυρωμένων", value=True, key="bulk_hide_cancelled")
employee_filter = st.selectbox("Εργαζόμενος (προαιρετικό φίλτρο)",
    [""] + sorted(emp_map, key=lambda eid: emp_map[eid].casefold()),
    format_func=lambda eid: emp_map[eid] if eid else "Όλοι οι εργαζόμενοι",
    key="bulk_employee_filter")
groups = bar_groups(st.session_state.assignments, st.session_state.projects, from_date, through_date, set(project_filter), hide_cancelled)
if employee_filter:
    groups = [g for g in groups if any(str(a.get("employeeId")) == employee_filter for a in g)]
if not groups:
    st.info("Δεν βρέθηκαν μπάρες για αυτά τα φίλτρα.")
    st.stop()

select_all = st.checkbox("Επιλογή όλων των εμφανιζόμενων μπαρών", value=False, key="bulk_select_all")
view_rows = []
for group in groups:
    exemplar = group[0]
    names = ", ".join(emp_map.get(str(a.get("employeeId")), "Χωρίς προσωπικό") if a.get("employeeId") else "Χωρίς προσωπικό" for a in group)
    view_rows.append({
        "Επιλογή": select_all,
        "Ημερομηνία": as_date(exemplar["date"]).strftime("%d/%m/%Y"),
        "Έργο": proj_map.get(str(exemplar.get("projectId")), "Άγνωστο έργο"),
        "Ωράριο": f"{fmt(exemplar.get('startTime'))}–{fmt(exemplar.get('endTime'))}",
        "Εργαζόμενοι": names,
        "Εγγραφές": len(group),
    })
st.write(f"**Βρέθηκαν {len(groups)} μπάρες.** Επίλεξε όσες θέλεις από την πρώτη στήλη.")
filter_signature = hashlib.sha1(json.dumps([str(from_date), str(through_date), sorted(project_filter), hide_cancelled, employee_filter, select_all, [sorted(str(a['id']) for a in g) for g in groups]], ensure_ascii=False).encode()).hexdigest()[:12]
table = st.data_editor(pd.DataFrame(view_rows), hide_index=True, use_container_width=True,
    disabled=["Ημερομηνία", "Έργο", "Ωράριο", "Εργαζόμενοι", "Εγγραφές"],
    key=f"bulk_table_{filter_signature}",
    column_config={"Επιλογή": st.column_config.CheckboxColumn("Επιλογή", required=True)})
chosen = [group for idx, group in enumerate(groups) if bool(table.iloc[idx]["Επιλογή"])]
selected_count = sum(len(g) for g in chosen)
st.caption(f"Επιλεγμένες μπάρες: {len(chosen)} · Υποκείμενες εγγραφές εργαζομένων: {selected_count}")

operations = [
    "Αντικατάσταση εργαζομένου", "Μεταφορά ημερομηνίας", "Μετατόπιση ωραρίου",
    "Κοινό νέο ωράριο", "Αλλαγή έργου", "Προσθήκη παρατήρησης",
    "Αντικατάσταση παρατήρησης",
]
operation = st.selectbox("Τύπος μαζικής αλλαγής", operations, key="bulk_operation")
options = {}
if operation == "Αντικατάσταση εργαζομένου":
    old_ids = sorted({str(a.get("employeeId") or "") for g in chosen for a in g})
    active = sorted([str(e["id"]) for e in st.session_state.employees if e.get("status", "Ενεργός") == "Ενεργός"], key=lambda x: emp_map[x].casefold())
    if old_ids and active:
        old = st.selectbox("Ποιον εργαζόμενο αντικαθιστούμε μέσα στις επιλεγμένες μπάρες;", old_ids,
            format_func=lambda x: emp_map.get(x, "Χωρίς προσωπικό") if x else "Χωρίς προσωπικό", key="bulk_old_employee")
        new = st.selectbox("Νέος εργαζόμενος", active, format_func=lambda x: emp_map[x], key="bulk_new_employee")
        options = {"old_employee": old, "new_employee": new}
        st.caption("Σε μπάρες με πολλούς εργαζομένους αντικαθίσταται μόνο ο συγκεκριμένος εργαζόμενος. Οι υπόλοιποι μένουν όπως είναι.")
    else:
        st.info("Επίλεξε μπάρες και βεβαιώσου ότι υπάρχει ενεργός εργαζόμενος.")
elif operation == "Μεταφορά ημερομηνίας":
    options = {"days": st.number_input("Μεταφορά κατά ημέρες (+ ή −)", -60, 60, 1, step=1, key="bulk_days")}
elif operation == "Μετατόπιση ωραρίου":
    options = {"minutes": st.number_input("Μετατόπιση κατά λεπτά (+ ή −)", -360, 360, 30, step=15, key="bulk_minutes")}
elif operation == "Κοινό νέο ωράριο":
    c1, c2 = st.columns(2)
    with c1:
        start_time = st.time_input("Νέα ώρα έναρξης", time(8, 0), key="bulk_start_time")
    with c2:
        end_time = st.time_input("Νέα ώρα λήξης", time(16, 0), key="bulk_end_time")
    set_arrival = st.checkbox("Νέα κοινή ώρα προσέλευσης", value=False, key="bulk_set_arrival")
    arrival_time = st.time_input("Ώρα προσέλευσης", time(7, 30), disabled=not set_arrival, key="bulk_arrival_time")
    options = {"start": start_time.strftime("%H:%M"), "end": end_time.strftime("%H:%M"),
               "set_arrival": set_arrival, "arrival": arrival_time.strftime("%H:%M")}
elif operation == "Αλλαγή έργου":
    if proj_map:
        target_project = st.selectbox("Νέο έργο", sorted(proj_map), format_func=lambda x: proj_map[x], key="bulk_new_project")
        options = {"project": target_project}
    else:
        st.error("Δεν υπάρχουν έργα.")
else:
    options = {"notes": st.text_area("Κείμενο παρατήρησης", key="bulk_notes", placeholder="Γράψε το κείμενο...")}
    if operation == "Αντικατάσταση παρατήρησης":
        st.caption("Οι ειδικές σημειώσεις [Άδεια: …] και [Εμπλοκή: …] διατηρούνται.")

signature = hashlib.sha256(json.dumps({"groups": [sorted(str(a["id"]) for a in g) for g in chosen],
    "operation": operation, "options": options}, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
if st.button("🔎 Προεπισκόπηση αλλαγών", type="primary", disabled=not chosen or not options, key="bulk_preview_btn"):
    if (operation in ("Προσθήκη παρατήρησης", "Αντικατάσταση παρατήρησης") and not options.get("notes", "").strip()):
        st.error("Συμπλήρωσε παρατήρηση.")
    elif operation == "Κοινό νέο ωράριο" and options["start"] == options["end"]:
        st.error("Η έναρξη και η λήξη δεν μπορούν να είναι ίδιες.")
    elif operation == "Αντικατάσταση εργαζομένου" and options["old_employee"] == options["new_employee"]:
        st.error("Επίλεξε διαφορετικό εργαζόμενο.")
    else:
        try:
            candidate = build_plan(chosen, operation, options)
            latest_rules, availability_error = fetch_rules(utils.supabase)
            if availability_error:
                st.error("Αδυναμία ελέγχου διαθεσιμότητας: " + availability_error)
                st.session_state.pop("bulk_gantt_preview", None)
                st.stop()
            problems = validate_plan(
                candidate, st.session_state.assignments,
                st.session_state.employees, st.session_state.leaves,
                availability=latest_rules,
            )
            if not candidate["deltas"]:
                st.warning("Δεν προέκυψε καμία αλλαγή στις επιλεγμένες μπάρες.")
                st.session_state.pop("bulk_gantt_preview", None)
            elif problems:
                for message in problems[:8]:
                    st.error(message)
                st.session_state.pop("bulk_gantt_preview", None)
            else:
                st.session_state.bulk_gantt_preview = {"signature": signature, "plan": candidate}
        except Exception as exc:
            st.error(f"Δεν δημιουργήθηκε προεπισκόπηση: {exc}")
            st.session_state.pop("bulk_gantt_preview", None)

preview = st.session_state.get("bulk_gantt_preview")
if preview:
    if preview["signature"] != signature:
        st.info("Οι επιλογές άλλαξαν. Πάτησε ξανά «Προεπισκόπηση αλλαγών».")
    else:
        plan = preview["plan"]
        st.divider()
        st.subheader(f"Προεπισκόπηση — {len(plan['deltas'])} εγγραφές")
        if plan["skipped"]:
            st.warning(f"{plan['skipped']} επιλεγμένες μπάρες δεν είχαν σχετική αλλαγή και θα παραμείνουν ως έχουν.")
        rows = []
        for rid, after in plan["new"].items():
            before = plan["old"][rid]
            rows.append({"Ημερομηνία πριν": str(as_date(before.get("date"))),
                         "Έργο πριν": proj_map.get(str(before.get("projectId")), "Άγνωστο"),
                         "Εργαζόμενος πριν": emp_map.get(str(before.get("employeeId")), "Χωρίς προσωπικό"),
                         "Ωράριο πριν": f"{fmt(before.get('startTime'))}–{fmt(before.get('endTime'))}",
                         "Ημερομηνία μετά": str(as_date(after.get("date"))),
                         "Έργο μετά": proj_map.get(str(after.get("projectId")), "Άγνωστο"),
                         "Εργαζόμενος μετά": emp_map.get(str(after.get("employeeId")), "Χωρίς προσωπικό"),
                         "Ωράριο μετά": f"{fmt(after.get('startTime'))}–{fmt(after.get('endTime'))}",
                         "Παρατηρήσεις μετά": str(after.get("notes") or "")})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption("Για λόγους ασφάλειας, δεν εφαρμόζονται αλλαγές σε πρότυπα επανάληψης. Μόνο οι επιλεγμένες εγγραφές θα ενημερωθούν.")
        confirm = st.checkbox("Έλεγξα την προεπισκόπηση και επιβεβαιώνω τις αλλαγές", value=False, key="bulk_confirm")
        if st.button("💾 Εφαρμογή επιλεγμένων αλλαγών", disabled=not confirm, key="bulk_apply_btn"):
            if st.session_state.get("current_user") == "TAN":
                st.error("Δεν έχεις δικαίωμα επεξεργασίας.")
            else:
                with st.spinner("Αποθήκευση στη Supabase και επαλήθευση..."):
                    ok, message = save_plan(plan)
                if ok:
                    st.session_state.pop("bulk_gantt_preview", None)
                    st.session_state.bulk_gantt_result = message
                    st.rerun()
                else:
                    st.error(message)
