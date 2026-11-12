"""STAFF.PRO | Employee work availability (not statutory leave)."""
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Διαθεσιμότητα Προσωπικού | STAFF.PRO", page_icon="🗓️", layout="wide")
import utils
from availability_rules import TABLE, fetch_rules, save_rule, delete_rule

if not st.session_state.get("authenticated", False):
    st.switch_page("streamlit_app.py")
    st.stop()
for key in ("employees", "projects", "assignments", "leaves", "recurring_patterns", "evaluations"):
    if key not in st.session_state:
        st.session_state[key] = []
utils.init_data_and_sync()
utils.setup_shared_ui()

st.title("🗓️ Προσωπικό ημερολόγιο διαθεσιμότητας")
st.caption(
    "Ξεχωριστό από τις επίσημες άδειες. Οι μη διαθέσιμες ώρες αποκλείουν "
    "προτάσεις αντικατάστασης· οι προτιμώμενες ώρες δίνουν μόνο προτεραιότητα."
)
if not utils.supabase:
    st.error("Απαιτείται Supabase για να αποθηκεύονται οι κανόνες.")
    st.stop()
rules, error = fetch_rules(utils.supabase)
if error:
    st.error(error)
    st.info("Εκτέλεσε πρώτα το αρχείο sql/employee_availability_rules.sql στον SQL Editor της Supabase.")
    st.stop()

employees = sorted(
    [e for e in st.session_state.employees if e.get("id")],
    key=lambda x: str(x.get("name", "")).casefold(),
)
if not employees:
    st.info("Δεν υπάρχουν εργαζόμενοι.")
    st.stop()
emp_ids = [str(e["id"]) for e in employees]
names = {str(e["id"]): e.get("name", "Χωρίς όνομα") for e in employees}
chosen = st.selectbox("Εργαζόμενος", emp_ids, format_func=lambda x: names[x])
filtered = [r for r in rules if str(r.get("employee_id")) == chosen]
weekdays = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
types = {
    "unavailable": "Δεν μπορεί να εργαστεί",
    "only_available": "Μπορεί μόνο στις συγκεκριμένες ώρες",
    "preferred": "Προτιμά αυτές τις ώρες",
}
current = []
for r in filtered:
    where = weekdays[int(r["weekday"])] if r.get("scope") == "weekday" and r.get("weekday") is not None else str(r.get("rule_date") or "")
    hours = (
        "Ολόκληρη ημέρα"
        if not r.get("start_time") and not r.get("end_time")
        else f"{str(r.get('start_time'))[:5]}–{str(r.get('end_time'))[:5]}"
    )
    current.append({
        "Ημέρα": where,
        "Κανόνας": types.get(r.get("kind"), "Άγνωστο"),
        "Ώρες": hours,
        "Σημείωση": r.get("note") or "",
        "ID": str(r.get("id")),
    })

st.subheader("Υφιστάμενοι κανόνες")
if current:
    st.dataframe(
        pd.DataFrame([{k: v for k, v in x.items() if k != "ID"} for x in current]),
        hide_index=True, use_container_width=True,
    )
else:
    st.info("Δεν έχουν καταχωρηθεί περιορισμοί ή προτιμήσεις για αυτόν τον εργαζόμενο.")

read_only = st.session_state.get("current_user") == "TAN"
if read_only:
    st.info("Ο συγκεκριμένος χρήστης έχει δικαιώματα προβολής μόνο.")
    st.stop()

with st.expander("➕ Νέος κανόνας διαθεσιμότητας", expanded=True):
    with st.form("new_availability_rule"):
        kind = st.selectbox("Τύπος", list(types), format_func=lambda x: types[x])
        scope = st.radio("Ισχύει", ["weekday", "date"], format_func=lambda x: "Κάθε εβδομάδα" if x == "weekday" else "Μία συγκεκριμένη ημέρα", horizontal=True)
        weekday = None
        selected_date = None
        if scope == "weekday":
            weekday = st.selectbox("Ημέρα εβδομάδας", list(range(7)), format_func=lambda x: weekdays[x])
        else:
            selected_date = st.date_input("Ημερομηνία", value=datetime.now(ZoneInfo("Europe/Athens")).date())
        whole_day = st.checkbox("Ολόκληρη ημέρα", value=(kind != "preferred"))
        start = end = None
        if not whole_day:
            c1, c2 = st.columns(2)
            start = c1.time_input("Από", value=datetime.strptime("08:00", "%H:%M").time())
            end = c2.time_input("Έως", value=datetime.strptime("16:00", "%H:%M").time())
        note = st.text_input("Σημείωση (προαιρετική)", max_chars=250)
        submitted = st.form_submit_button("💾 Αποθήκευση κανόνα", use_container_width=True)
    if submitted:
        if start is not None and start >= end:
            st.error("Η ώρα λήξης πρέπει να είναι αργότερα από την έναρξη.")
        else:
            record = {
                "id": str(uuid.uuid4()),
                "employee_id": chosen,
                "scope": scope,
                "weekday": weekday,
                "rule_date": selected_date.isoformat() if selected_date else None,
                "kind": kind,
                "start_time": start.strftime("%H:%M") if start else None,
                "end_time": end.strftime("%H:%M") if end else None,
                "note": note.strip(),
                "is_active": True,
            }
            try:
                response = save_rule(utils.supabase, record)
                if not response.data:
                    st.error("Η αποθήκευση δεν επιβεβαιώθηκε.")
                else:
                    utils.touch_app_sync_state()
                    utils.log_activity("ΔΙΑΘΕΣΙΜΟΤΗΤΑ", TABLE, f"Νέος κανόνας για {names[chosen]}")
                    st.success("Ο κανόνας αποθηκεύτηκε.")
                    st.rerun()
            except Exception as exc:
                st.error(f"Αποτυχία αποθήκευσης: {exc}")

if filtered:
    with st.expander("🗑️ Διαγραφή κανόνα"):
        selected_rule = st.selectbox(
            "Κανόνας", current,
            format_func=lambda x: f"{x['Ημέρα']} · {x['Κανόνας']} · {x['Ώρες']}",
            key="rule_to_delete",
        )
        confirm = st.checkbox("Επιβεβαιώνω τη διαγραφή αυτού του κανόνα.")
        if st.button("Διαγραφή κανόνα", disabled=not confirm):
            try:
                result = delete_rule(utils.supabase, selected_rule["ID"])
                if not result.data:
                    st.error("Δεν επιβεβαιώθηκε η διαγραφή.")
                else:
                    utils.touch_app_sync_state()
                    utils.log_activity("ΔΙΑΓΡΑΦΗ ΔΙΑΘΕΣΙΜΟΤΗΤΑΣ", TABLE, f"Διαγραφή κανόνα για {names[chosen]}")
                    st.success("Ο κανόνας διαγράφηκε.")
                    st.rerun()
            except Exception as exc:
                st.error(f"Σφάλμα διαγραφής: {exc}")

st.caption(
    "Προσοχή: οι καταχωρήσεις αυτές δεν μεταβάλλουν αυτόματα τις ήδη προγραμματισμένες "
    "βάρδιες ούτε υποκαθιστούν τις επίσημες άδειες. "
    "Οι κανόνες μίας συγκεκριμένης ημερομηνίας συνυπολογίζονται με τους εβδομαδιαίους."
)
