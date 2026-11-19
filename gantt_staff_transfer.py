"""Assign or move staff on Gantt bars through one atomic save."""
import json
from urllib.parse import unquote
import uuid


SOURCE = "gantt_transfer_source"
TARGET = "gantt_transfer_target"
STAFF = "gantt_transfer_staff"
DROP_PREFIX = "gantt_staff_drop:"


def apply_drop(value, state, safe_mapping, groups, assignments, save):
    """Consume a drag event once. A null source means assignment from the list."""
    if value == state.get("gantt_staff_drop_handled"):
        return False
    state["gantt_staff_drop_handled"] = value
    try:
        if not value.startswith(DROP_PREFIX) or len(value) > 4096:
            raise ValueError
        payload = json.loads(unquote(value[len(DROP_PREFIX):]))
        if not isinstance(payload, dict) or not all(
            isinstance(payload.get(key), str) and payload[key]
            for key in ("token", "target", "employee", "nonce")
        ):
            raise ValueError
        if payload["token"] != state.get("gantt_staff_drag_token"):
            raise ValueError
        source_key = payload["source"]
        source = None if source_key is None else groups[safe_mapping[source_key]]
        target = groups[safe_mapping[payload["target"]]]
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("Η επιλογή μεταφοράς έχει αλλάξει. Δοκίμασε ξανά από το Gantt.") from exc
    employee_ids = [payload["employee"]]
    if source is None:
        before = _rows(target, assignments)
        after = _add_to_bar(before, employee_ids)
    else:
        before, after = plan_transfer(assignments, source, target, employee_ids)
    if save(before, after) is None:
        return False
    state["gantt_transfer_reset"] = True
    return "assigned" if source is None else "moved"


def _rows(group, assignments):
    identifiers = group.get("AssignmentIds", [])
    by_id = {row["id"]: row for row in assignments}
    if not identifiers or any(ident not in by_id for ident in identifiers):
        raise ValueError("Η μπάρα έχει αλλάξει. Κάνε ανανέωση και επίλεξέ την ξανά.")
    rows = [by_id[ident] for ident in identifiers]
    if any(row.get("is_cancelled") for row in rows):
        raise ValueError("Επίλεξε ενεργές μπάρες για τη μεταφορά προσωπικού.")
    return rows


def _add_to_bar(rows, employee_ids):
    assigned = [dict(row) for row in rows if row.get("employeeId")]
    if set(employee_ids) & {row["employeeId"] for row in assigned}:
        raise ValueError("Κάποιος από τους επιλεγμένους βρίσκεται ήδη στη μπάρα προορισμού.")
    vacancies = [row for row in rows if not row.get("employeeId")]
    for index, employee_id in enumerate(employee_ids):
        slot = vacancies[index] if index < len(vacancies) else None
        assigned.append({
            **(slot or rows[0]),
            "id": slot["id"] if slot else str(uuid.uuid4()),
            "employeeId": employee_id,
        })
    return assigned + [dict(row) for row in vacancies[len(employee_ids):]]


def plan_transfer(assignments, source, target, employee_ids):
    """Retain uncovered source work and adopt the destination's placement data."""
    source_rows, target_rows = _rows(source, assignments), _rows(target, assignments)
    if set(source["AssignmentIds"]) & set(target["AssignmentIds"]):
        raise ValueError("Επίλεξε διαφορετική μπάρα προορισμού.")
    selected = list(dict.fromkeys(eid for eid in employee_ids if eid))
    if not selected or not set(selected) <= {row.get("employeeId") for row in source_rows}:
        raise ValueError("Επίλεξε εργαζομένους από την αρχική μπάρα.")

    remaining = [dict(row) for row in source_rows if row.get("employeeId") not in selected]
    if not remaining:
        remaining = [{**source_rows[0], "employeeId": ""}]

    destination = [row for row in _add_to_bar(target_rows, selected) if row.get("employeeId")]
    return source_rows + target_rows, remaining + destination


def pick_bar(state, key, groups):
    """Route chart clicks to the transfer controls instead of the edit form."""
    group = groups.get(key)
    if not group or group.get("is_cancelled"):
        state["gantt_transfer_message"] = "Επίλεξε ενεργή μπάρα."
        return
    if not state.get(SOURCE) or state.get(TARGET):
        if not any(group.get("EmployeeIds", [])):
            state["gantt_transfer_message"] = "Επίλεξε πρώτα μπάρα με προσωπικό."
            return
        state[SOURCE] = key
        state[TARGET] = ""
        state.pop(STAFF, None)
    elif key != state[SOURCE]:
        state[TARGET] = key


def render_mode(clear_selection):
    import streamlit as st

    def reset():
        for key in (SOURCE, TARGET, STAFF, "gantt_transfer_message"):
            st.session_state.pop(key, None)
        clear_selection()

    enabled = st.toggle(
        "Μεταφορά προσωπικού μεταξύ μπαρών", key="gantt_staff_transfer_mode", on_change=reset,
    )
    if enabled:
        st.caption("**Σύρε ένα όνομα** από αριστερά για ανάθεση ή από άλλη μπάρα για μεταφορά. "
                   "Για πολλά άτομα, πάτησε τις δύο μπάρες και επίλεξε προσωπικό παρακάτω.")
    return enabled


def render_transfer(groups, assignments, employees, save, clear_selection):
    import streamlit as st

    state = st.session_state
    if state.pop("gantt_transfer_reset", False):
        for key in (SOURCE, TARGET, STAFF):
            state.pop(key, None)
    notice = state.pop("gantt_transfer_message", "")
    if notice:
        st.info(notice)
    active = {key: group for key, group in groups.items() if not group.get("is_cancelled")}
    sources = {key: group for key, group in active.items() if any(group.get("EmployeeIds", []))}
    if not sources or len(active) < 2:
        st.info("Χρειάζονται δύο ενεργές μπάρες και προσωπικό στην αρχική μπάρα.")
        return
    if state.get(SOURCE) not in sources:
        state[SOURCE] = ""
        state[TARGET] = ""
        state.pop(STAFF, None)

    ordered = sorted(active, key=lambda key: (active[key]["Date"], active[key]["StartTime"], key))
    names = {employee["id"]: employee["name"] for employee in employees}

    def label(key):
        if not key:
            return "Επίλεξε μπάρα"
        group = active[key]
        crew = ", ".join(names.get(eid, eid) for eid in dict.fromkeys(group.get("EmployeeIds", [])) if eid)
        return (f"{group['Date']:%d/%m} · {group.get('ProjectDisplay', group['Project'])} · "
                f"{group['StartTime']}–{group['EndTime']} · {crew or 'Χωρίς προσωπικό'}")

    def change_source():
        state[TARGET] = ""
        state.pop(STAFF, None)

    st.markdown("**Γρήγορη μεταφορά προσωπικού**")
    left, right = st.columns(2)
    source_key = left.selectbox(
        "Από μπάρα", ["", *[key for key in ordered if key in sources]],
        key=SOURCE, format_func=label, on_change=change_source,
    )
    if state.get(TARGET) not in active or state.get(TARGET) == source_key:
        state[TARGET] = ""
    target_key = right.selectbox(
        "Σε μπάρα", ["", *[key for key in ordered if key != source_key]],
        key=TARGET, format_func=label, disabled=not source_key,
    )
    if not source_key:
        return
    options = list(dict.fromkeys(eid for eid in sources[source_key].get("EmployeeIds", []) if eid))
    if STAFF in state and any(eid not in options for eid in state[STAFF]):
        state.pop(STAFF)
    selected = st.multiselect(
        "Εργαζόμενοι για μεταφορά", options,
        default=options if len(options) == 1 else [], format_func=lambda eid: names.get(eid, eid), key=STAFF,
    )
    if target_key and selected:
        target = active[target_key]
        st.caption(f"Μεταφορά {len(selected)} εργαζομένων στις {target['Date']:%d/%m}, "
                   f"{target['StartTime']}–{target['EndTime']}, με τα στοιχεία της μπάρας προορισμού.")
    if st.button("Μεταφορά εργαζομένων", key="gantt_transfer_save", disabled=not target_key or not selected):
        try:
            before, after = plan_transfer(assignments, sources[source_key], active[target_key], selected)
        except ValueError as exc:
            st.error(str(exc))
            return
        if save(before, after) is None:
            return
        # Widget values are cleared before they are created on the following rerun.
        state["gantt_transfer_reset"] = True
        clear_selection()
        st.toast(f"Μεταφέρθηκαν {len(selected)} εργαζόμενοι.")
        st.rerun()
