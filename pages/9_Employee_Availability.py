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

# Dynamic inputs must NOT be inside st.form: changing the scope or
# "all day" needs to rerender the time/day widgets immediately.
def _rule_signature(row):
    return (
        str(row.get("employee_id") or ""),
        str(row.get("scope") or ""),
        str(row.get("weekday")) if row.get("weekday") is not None else None,
        str(row.get("rule_date") or "")[:10],
        str(row.get("kind") or ""),
        str(row.get("start_time") or "")[:5],
        str(row.get("end_time") or "")[:5],
    )


def _overlaps_existing(candidate, existing, excluding_id=None):
    sig = _rule_signature(candidate)
    return any(
        str(r.get("id")) != str(excluding_id)
        and _rule_signature(r) == sig
        for r in existing
    )


def _t(value, default):
    try:
        return datetime.strptime(str(value or default)[:5], "%H:%M").time()
    except (ValueError, TypeError):
        return datetime.strptime(default, "%H:%M").time()


def _time_inputs(prefix, default_start=None, default_end=None):
    whole_day = st.checkbox(
        "Ολόκληρη ημέρα (χωρίς περιορισμό ωρών)",
        value=default_start is None and default_end is None,
        key=f"{prefix}_whole_day",
    )
    c_start, c_end = st.columns(2)
    start = c_start.time_input(
        "Από ώρα", value=_t(default_start, "08:00"),
        key=f"{prefix}_start", disabled=whole_day,
        step=900,
    )
    end = c_end.time_input(
        "Έως ώρα", value=_t(default_end, "16:00"),
        key=f"{prefix}_end", disabled=whole_day,
        step=900,
    )
    if whole_day:
        return None, None
    return start.strftime("%H:%M"), end.strftime("%H:%M")


def _valid_times(start, end):
    return (start is None and end is None) or (
        start is not None and end is not None and start < end
    )


def _confirm_written(response, expected_ids):
    saved = (response.data or []) if response is not None else []
    return len(saved) == len(expected_ids) and {
        str(r.get("id")) for r in saved
    } == {str(x) for x in expected_ids}


st.subheader("➕ Νέος κανόνας διαθεσιμότητας")
st.caption(
    "Μπορείς να ορίσεις συγκεκριμένο ωράριο και να εφαρμόσεις τον ίδιο κανόνα "
    "σε πολλές ημέρες μαζί. Κάθε ημέρα αποθηκεύεται ως ξεχωριστός κανόνας."
)

new_type = st.selectbox(
    "Τύπος διαθεσιμότητας", list(types),
    format_func=lambda x: types[x],
    key=f"av_new_type_{chosen}",
)
new_scope = st.radio(
    "Επιλογή ημερών",
    ["weekday", "dates", "range"],
    format_func=lambda x: {
        "weekday": "Πολλές ημέρες κάθε εβδομάδα",
        "dates": "Συγκεκριμένες ημερομηνίες",
        "range": "Συνεχόμενες ημερομηνίες",
    }[x],
    horizontal=True,
    key=f"av_new_scope_{chosen}",
)

planned_days = []
if new_scope == "weekday":
    planned_days = st.multiselect(
        "Επίλεξε μία ή περισσότερες ημέρες της εβδομάδας",
        list(range(7)),
        format_func=lambda x: weekdays[x],
        key=f"av_new_weekdays_{chosen}",
    )
elif new_scope == "dates":
    count_dates = st.number_input(
        "Πόσες συγκεκριμένες ημερομηνίες;",
        min_value=1, max_value=20, value=2, step=1,
        key=f"av_new_date_count_{chosen}",
    )
    cols = st.columns(2)
    for i in range(int(count_dates)):
        with cols[i % 2]:
            planned_days.append(
                st.date_input(
                    f"{i+1}η ημερομηνία",
                    value=datetime.now(ZoneInfo("Europe/Athens")).date() + timedelta(days=i),
                    key=f"av_new_date_{chosen}_{i}",
                )
            )
else:
    c_from, c_to = st.columns(2)
    first = c_from.date_input(
        "Από ημερομηνία",
        value=datetime.now(ZoneInfo("Europe/Athens")).date(),
        key=f"av_new_range_from_{chosen}",
    )
    last_day = c_to.date_input(
        "Έως ημερομηνία",
        value=datetime.now(ZoneInfo("Europe/Athens")).date() + timedelta(days=6),
        key=f"av_new_range_to_{chosen}",
    )
    if first <= last_day and (last_day - first).days <= 30:
        planned_days = [first + timedelta(days=i) for i in range((last_day-first).days + 1)]

new_start, new_end = _time_inputs(
    f"av_new_{chosen}", default_start="08:00", default_end="16:00"
)
st.caption(
    "Αν θέλεις συγκεκριμένες ώρες, άφησε απενεργοποιημένο το «Ολόκληρη ημέρα». "
    "Για ωράριο που περνά τα μεσάνυχτα χρειάζονται δύο ξεχωριστοί κανόνες."
)
new_note = st.text_input(
    "Σημείωση (προαιρετική)", max_chars=250, key=f"av_new_note_{chosen}"
)
if st.button("💾 Αποθήκευση σε όλες τις επιλεγμένες ημέρες",
             key=f"av_add_{chosen}", type="primary", use_container_width=True):
    if new_scope == "range" and (
        first > last_day or (last_day - first).days > 30
    ):
        st.error("Το διάστημα πρέπει να είναι από 1 έως 31 ημέρες.")
    elif not planned_days:
        st.error("Επίλεξε τουλάχιστον μία ημέρα.")
    elif len(planned_days) != len(set(planned_days)):
        st.error("Έχεις επιλέξει την ίδια ημέρα περισσότερες από μία φορές.")
    elif not _valid_times(new_start, new_end):
        st.error("Η ώρα «Έως» πρέπει να είναι μετά την ώρα «Από».")
    else:
        records = []
        for day_value in planned_days:
            is_weekday = new_scope == "weekday"
            records.append({
                "id": str(uuid.uuid4()),
                "employee_id": chosen,
                "scope": "weekday" if is_weekday else "date",
                "weekday": int(day_value) if is_weekday else None,
                "rule_date": None if is_weekday else day_value.isoformat(),
                "kind": new_type,
                "start_time": new_start,
                "end_time": new_end,
                "note": new_note.strip(),
                "is_active": True,
            })
        latest, fetch_error = fetch_rules(utils.supabase)
        if fetch_error:
            st.error("Δεν έγινε αποθήκευση: " + fetch_error)
        elif any(_overlaps_existing(row, latest) for row in records):
            st.error(
                "Υπάρχει ήδη ίδιος κανόνας για κάποια από τις επιλεγμένες ημέρες. "
                "Δεν αποθηκεύτηκε κανένας νέος κανόνας."
            )
        else:
            try:
                response = utils.supabase.table(TABLE).insert(records).execute()
                if not _confirm_written(response, [r["id"] for r in records]):
                    st.error(
                        "Η βάση δεν επιβεβαίωσε όλες τις εγγραφές. "
                        "Έλεγξε τους υφιστάμενους κανόνες πριν επιχειρήσεις ξανά."
                    )
                else:
                    utils.touch_app_sync_state()
                    utils.log_activity(
                        "ΔΙΑΘΕΣΙΜΟΤΗΤΑ", TABLE,
                        f"{len(records)} νέοι κανόνες για {names[chosen]}",
                    )
                    st.success(f"Αποθηκεύτηκαν {len(records)} κανόνες.")
                    st.rerun()
            except Exception as exc:
                st.error(f"Αποτυχία αποθήκευσης: {exc}")

if filtered:
    st.divider()
    st.subheader("✏️ Επεξεργασία υφιστάμενου κανόνα")
    indexed_rules = {str(r["id"]): r for r in filtered}
    selected_id = st.selectbox(
        "Επίλεξε τον κανόνα που θέλεις να αλλάξεις",
        list(indexed_rules),
        format_func=lambda rid: next(
            (
                f"{row['Ημέρα']} · {row['Κανόνας']} · {row['Ώρες']}"
                for row in current if row["ID"] == rid
            ), rid
        ),
        key=f"av_existing_selector_{chosen}",
    )
    selected = indexed_rules[selected_id]
    edit_prefix = f"av_edit_{selected_id}"
    edit_type = st.selectbox(
        "Τύπος κανόνα", list(types),
        index=list(types).index(selected["kind"])
              if selected.get("kind") in types else 0,
        format_func=lambda x: types[x],
        key=f"{edit_prefix}_type",
    )
    edit_scope = st.radio(
        "Ισχύει",
        ["weekday", "date"],
        index=0 if selected.get("scope") == "weekday" else 1,
        format_func=lambda x: (
            "Κάθε εβδομάδα" if x == "weekday" else "Συγκεκριμένη ημερομηνία"
        ),
        key=f"{edit_prefix}_scope",
        horizontal=True,
    )
    changed_weekday = None
    changed_date = None
    if edit_scope == "weekday":
        selected_weekday = int(selected.get("weekday") or 0)
        changed_weekday = st.selectbox(
            "Ημέρα εβδομάδας", list(range(7)), index=selected_weekday,
            format_func=lambda x: weekdays[x],
            key=f"{edit_prefix}_weekday",
        )
    else:
        initial = selected.get("rule_date")
        try:
            initial_date = datetime.fromisoformat(str(initial)[:10]).date()
        except (TypeError, ValueError):
            initial_date = datetime.now(ZoneInfo("Europe/Athens")).date()
        changed_date = st.date_input(
            "Ημερομηνία", value=initial_date, key=f"{edit_prefix}_date"
        )
    edit_start, edit_end = _time_inputs(
        edit_prefix,
        default_start=selected.get("start_time"),
        default_end=selected.get("end_time"),
    )
    edit_note = st.text_input(
        "Σημείωση", value=selected.get("note") or "",
        max_chars=250, key=f"{edit_prefix}_note",
    )
    col_save, col_delete = st.columns(2)
    with col_save:
        save_edit = st.button(
            "💾 Αποθήκευση αλλαγών",
            key=f"{edit_prefix}_save", use_container_width=True,
        )
    with col_delete:
        confirm_delete = st.checkbox(
            "Επιβεβαιώνω τη διαγραφή", key=f"{edit_prefix}_confirm"
        )
        delete_edit = st.button(
            "🗑️ Διαγραφή κανόνα",
            key=f"{edit_prefix}_delete",
            disabled=not confirm_delete,
            use_container_width=True,
        )

    if save_edit:
        if not _valid_times(edit_start, edit_end):
            st.error("Η ώρα «Έως» πρέπει να είναι μετά την ώρα «Από».")
        else:
            changes = {
                "scope": edit_scope,
                "weekday": changed_weekday if edit_scope == "weekday" else None,
                "rule_date": changed_date.isoformat() if changed_date else None,
                "kind": edit_type,
                "start_time": edit_start,
                "end_time": edit_end,
                "note": edit_note.strip(),
            }
            candidate = {**selected, **changes}
            latest, fetch_error = fetch_rules(utils.supabase)
            if fetch_error:
                st.error("Δεν έγινε ενημέρωση: " + fetch_error)
            elif not any(
                str(r.get("id")) == selected_id
                and str(r.get("employee_id")) == chosen
                for r in latest
            ):
                st.error("Ο κανόνας έχει ήδη διαγραφεί. Κάνε ανανέωση.")
            elif _overlaps_existing(candidate, latest, selected_id):
                st.error("Υπάρχει ήδη ίδιος κανόνας για τη νέα ημέρα και το ωράριο.")
            else:
                try:
                    response = (
                        utils.supabase.table(TABLE).update(changes)
                        .eq("id", selected_id).eq("employee_id", chosen)
                        .execute()
                    )
                    if not _confirm_written(response, [selected_id]):
                        st.error("Η αποθήκευση δεν επιβεβαιώθηκε.")
                    else:
                        utils.touch_app_sync_state()
                        utils.log_activity(
                            "ΑΛΛΑΓΗ ΔΙΑΘΕΣΙΜΟΤΗΤΑΣ", TABLE,
                            f"Ενημέρωση κανόνα για {names[chosen]}",
                        )
                        st.success("Ο κανόνας ενημερώθηκε.")
                        st.rerun()
                except Exception as exc:
                    st.error(f"Σφάλμα ενημέρωσης: {exc}")

    if delete_edit:
        try:
            response = (
                utils.supabase.table(TABLE).delete()
                .eq("id", selected_id).eq("employee_id", chosen).execute()
            )
            if not _confirm_written(response, [selected_id]):
                st.error("Η διαγραφή δεν επιβεβαιώθηκε.")
            else:
                utils.touch_app_sync_state()
                utils.log_activity(
                    "ΔΙΑΓΡΑΦΗ ΔΙΑΘΕΣΙΜΟΤΗΤΑΣ", TABLE,
                    f"Διαγραφή κανόνα για {names[chosen]}",
                )
                st.success("Ο κανόνας διαγράφηκε.")
                st.rerun()
        except Exception as exc:
            st.error(f"Σφάλμα διαγραφής: {exc}")

st.caption(
    "Προσοχή: οι καταχωρήσεις αυτές δεν μεταβάλλουν αυτόματα τις ήδη προγραμματισμένες "
    "βάρδιες ούτε υποκαθιστούν τις επίσημες άδειες. "
    "Οι κανόνες μίας συγκεκριμένης ημερομηνίας συνυπολογίζονται με τους εβδομαδιαίους."
)
