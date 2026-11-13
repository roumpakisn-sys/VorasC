"""Optional presentation for the existing Gantt forms; no storage operations.

Disable per session with the sidebar switch, or globally with
STAFFPRO_SIDE_EDITOR_ENABLED=0. The original forms remain the only save path.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path


def feature_available(environ=None):
    value = (os.environ if environ is None else environ).get(
        "STAFFPRO_SIDE_EDITOR_ENABLED", "1"
    )
    return str(value).strip().lower() not in {"0", "false", "off", "no"}


def render_toggle(allowed=True):
    import streamlit as st

    if not allowed or not feature_available():
        return False
    return st.sidebar.toggle(
        "Πλαϊνή επεξεργασία μπάρας", value=False,
        key="gantt_side_editor_enabled",
        help="Προαιρετικό παράθυρο δίπλα στο Gantt. Κλείστε τον διακόπτη για την αρχική διάταξη.",
    )


@contextmanager
def editor(enabled, selected_key, *, page, on_close):
    """Wrap, never duplicate, the existing form. Disabled mode emits nothing."""
    if not enabled or not selected_key:
        yield
        return

    import streamlit as st
    import streamlit.components.v1 as components

    pane_key = f"gantt_side_editor_{page}"
    identity = hashlib.sha256(str(selected_key).encode()).hexdigest()
    bar_prefix = "mobile_bar_" if page == "mobile" else "bar_"
    config = json.dumps({"selector": f".st-key-{pane_key}", "identity": identity,
                         "barId": bar_prefix + hashlib.md5(str(selected_key).encode()).hexdigest()})
    script = Path(__file__).with_suffix(".js").read_text(encoding="utf-8")
    with st.container(key=pane_key):
        # Installed before the form so validation st.stop() cannot skip the guard.
        components.html(
            f"<script>{script}\nStaffProSideEditor.install(window, {config});</script>",
            height=0, width=0,
        )
        if st.button("✕ Κλείσιμο επεξεργασίας", key=f"{pane_key}_close"):
            on_close()
            st.session_state.skip_remote_sync_once = True
            st.rerun()
        st.caption("Οι αλλαγές εφαρμόζονται μόνο με «Αποθήκευση». Κλείσιμο: επιστροφή στο Gantt.")
        yield


def changes(original, proposed):
    """Human-readable, deterministic preview. Does not normalize or save rows."""
    return [
        {"Πεδίο": label, "Πριν": str(original.get(label, "")), "Μετά": str(value)}
        for label, value in proposed.items()
        if original.get(label, "") != value
    ]


def preview(original, proposed):
    import streamlit as st

    if st.form_submit_button("🔎 Προεπισκόπηση αλλαγών", use_container_width=True):
        rows = changes(original, proposed)
        if rows:
            st.table(rows)
            st.caption("Δεν αποθηκεύτηκε τίποτα. Οι έλεγχοι διαθεσιμότητας γίνονται στην Αποθήκευση.")
        else:
            st.info("Δεν υπάρχουν αλλαγές στα στοιχεία της μπάρας.")


def preview_bar(group, *, bar_key, employee_name, original_notes, **draft):
    import streamlit as st

    # The marker follows all input fields. The client must not take a baseline
    # from the previous bar while Streamlit streams the replacement form.
    identity = hashlib.sha256(str(bar_key).encode()).hexdigest()
    st.markdown(f'<span data-staffpro-form="{identity}" hidden></span>', unsafe_allow_html=True)
    preview(summary(
        day=group["Date"], project=group["Project"],
        employees=[employee_name(e) for e in group["EmployeeIds"] if e],
        arrival=group.get("ArrivalTime", ""), start=group["StartTime"],
        end=group["EndTime"], color=group["ColorName"], notes=original_notes,
        general=group.get("IsGeneral", False), cancelled=group.get("is_cancelled", False),
        reason=group.get("cancel_reason", ""),
    ), summary(**draft))


def summary(*, day, project, employees, arrival, start, end, color, notes,
            general, cancelled, reason):
    return {
        "Ημερομηνία": day.strftime("%d/%m/%Y"), "Έργο": project,
        "Προσωπικό": ", ".join(sorted(employees)) or "Χωρίς ανάθεση",
        "Προσέλευση": arrival or "—", "Έναρξη": str(start)[:5],
        "Λήξη": str(end)[:5], "Χρώμα": color, "Παρατηρήσεις": notes or "",
        "Γενικός": "Ναι" if general else "Όχι",
        "Ακυρωμένη": "Ναι" if cancelled else "Όχι",
        "Λόγος ακύρωσης": (reason or "") if cancelled else "",
    }
