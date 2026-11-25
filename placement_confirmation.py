"""Optional customer confirmation stored with the placement's existing metadata."""

from datetime import date, timedelta
import re


PENDING_LABEL = "Αναμένει πελάτη"
_TAG = re.compile(r"\[Επιβεβαίωση πελάτη: αναμονή(?: (\d{4}-\d{2}-\d{2}))?\]")


def split_notes(notes):
    """Return the notes and a follow-up date, empty for pending or None for confirmed."""
    text = notes or ""
    match = _TAG.search(text)
    if match is None:
        return text, None
    return _TAG.sub("", text).strip(), match[1] or ""


def combine_notes(notes, pending):
    clean, _ = split_notes(notes)
    if pending is None:
        return clean
    follow_up = f" {pending}" if pending else ""
    return f"{clean.rstrip()} [Επιβεβαίωση πελάτη: αναμονή{follow_up}]".strip()


def is_pending(assignment):
    return not assignment.get("is_cancelled") and bool(_TAG.search(assignment.get("notes") or ""))


def group_suffix(pending):
    return f"_customer_pending_{pending}" if pending is not None else ""


def follow_up_label(value):
    if value:
        try:
            return f"Επανεπικοινωνία {date.fromisoformat(value):%d/%m/%Y}"
        except ValueError:
            return ""
    return ""


def inputs(*, key, default=None):
    import streamlit as st

    date_key = f"{key}_follow_up"
    if date_key not in st.session_state and default:
        try:
            st.session_state[date_key] = date.fromisoformat(default)
        except ValueError:
            pass

    pending_col, date_col = st.columns(2)
    pending = pending_col.checkbox(PENDING_LABEL, value=default is not None, key=f"{key}_pending")
    follow_up = date_col.date_input(
        "Επανεπικοινωνία (προαιρετικά)", value=None, format="DD/MM/YYYY", key=date_key,
        help="Η ημερομηνία χρησιμοποιείται για μπάρες που αναμένουν επιβεβαίωση πελάτη.",
    )
    return (follow_up.isoformat() if follow_up else "") if pending else None


def render_confirm_button(group, save, clear_selection, *, key):
    import streamlit as st

    pending = group.get("CustomerConfirmation")
    if pending is None or group.get("is_cancelled"):
        return
    follow_up = follow_up_label(pending)
    if follow_up:
        st.caption(follow_up)
    if not st.button("✓ Επιβεβαιώθηκε από τον πελάτη", key=key,
                     help="Επιβεβαιώνει την ήδη αποθηκευμένη μπάρα."):
        return

    ids = set(group["AssignmentIds"])
    before = [row for row in st.session_state.assignments if row["id"] in ids]
    if len(before) != len(ids) or not before or not all(is_pending(row) for row in before):
        st.error("Η μπάρα άλλαξε. Κάνε ανανέωση και επίλεξέ την ξανά.")
        return
    after = [{**row, "notes": combine_notes(row.get("notes"), None)} for row in before]
    if save(before, after) is not None:
        clear_selection()
        st.toast("Η μπάρα επιβεβαιώθηκε.")
        st.rerun()


def render_filter(start_of_week, *, key):
    import streamlit as st

    state = st.session_state
    if state.get(key) or any(
        is_pending(row)
        for offset in range(7)
        for row in state.assignments_by_date.get(start_of_week + timedelta(days=offset), ())
    ):
        return st.checkbox("Μόνο μπάρες που αναμένουν πελάτη", key=key)
    return False


def chart_groups(groups, only_pending):
    if not only_pending:
        return groups
    return {key: group for key, group in groups.items()
            if group.get("CustomerConfirmation") is not None and not group.get("is_cancelled")}
