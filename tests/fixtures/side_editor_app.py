"""Run the real edit blocks with synthetic records and an in-memory save spy.

No config/database modules or credentials are imported. Suitable for AppTest
and manual layout QA: streamlit run tests/fixtures/side_editor_app.py.
"""
import ast
from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import uuid

import streamlit as st
import streamlit.components.v1 as components
from st_click_detector import click_detector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import gantt_side_editor
from gantt_helpers import normalize_id_list, clean_conflict_leave_notes

st.set_page_config(layout="wide")
st.title("Δοκιμή πλαϊνής επεξεργασίας — συνθετικά δεδομένα")
view = st.sidebar.selectbox("Έκδοση", ["desktop", "mobile"])
side_editor_enabled = gantt_side_editor.render_toggle()
st.sidebar.checkbox("Προσομοίωση αποτυχίας αποθήκευσης", key="fail_save")
for key, value in {
    "clicked_key": None, "mobile_clicked_key": None, "trigger_scroll": False,
    "edit_bar_select_widget": "", "mobile_edit_select_widget": "",
    "reset_edit_bar_select_next_run": False, "mobile_reset_edit_select_next_run": False,
    "save_calls": [], "employees": [{"id": "e1", "name": "Εργαζόμενος Α"},
                                       {"id": "e2", "name": "Εργαζόμενος Β"},
                                       {"id": "e3", "name": "Εργαζόμενος Γ"}],
    "projects": [{"id": "p1", "name": "Δοκιμαστικό έργο"}],
}.items():
    st.session_state.setdefault(key, value)
active_employee_ids = ["e1", "e2", "e3"]
config = SimpleNamespace(BASIC_COLORS={"Πράσινο": "#15803d", "Μπλε": "#2563eb"})
wk_groups = {key: {
    "Date": date(2026, 11, 16 + i), "Project": "Δοκιμαστικό έργο", "ProjectId": "p1",
    "StartTime": "09:00" if i == 0 else "14:00", "EndTime": "12:00" if i == 0 else "16:00",
    "EmployeeIds": ["e1", "e2"], "AssignmentIds": [key + "-1", key + "-2"],
    "Notes": "Αρχική σημείωση " + key, "Notes_List": [], "ColorName": "Πράσινο",
} for i, key in enumerate(["bar-a", "bar-b"])}
st.session_state.setdefault("assignments", [
    {"id": ident, "employeeId": eid, "projectId": g["ProjectId"], "date": g["Date"],
     "startTime": g["StartTime"], "endTime": g["EndTime"], "notes": g["Notes"]}
    for g in wk_groups.values() for ident, eid in zip(g["AssignmentIds"], g["EmployeeIds"])
])


def save_batch(old, new, **kwargs):
    st.session_state.save_calls.append(deepcopy({"old": old, "new": new, **kwargs}))
    if st.session_state.fail_save:
        st.error("Δοκιμαστική αποτυχία: δεν αποθηκεύτηκε τίποτα.")
        return None
    return new


employee_names = {e["id"]: e["name"] for e in st.session_state.employees}
utils = SimpleNamespace(
    get_employee_name=employee_names.__getitem__,
    get_project_name=lambda pid: "Δοκιμαστικό έργο", supabase=object(),
    safe_date_parse=lambda value: value if isinstance(value, date) else date.fromisoformat(value) if value else None,
    save_assignment_batch=save_batch,
    db_delete_in=lambda *args, **kwargs: st.error("Η διαγραφή δεν υποστηρίζεται στη δοκιμή."),
)

path = ROOT / "pages" / ("1_Gantt_Dashboard.py" if view == "desktop" else "4_Mobile_Gantt.py")
tree = ast.parse(path.read_text())
names = {"clear_bar_selection", "preserve_context_notes", "_form_time", "_form_prefill_date",
         "_save_placement_clipboard", "_form_clipboard_payload", "clear_mobile_selection",
         "_time_to_str", "_make_or_get_project", "_replace_local_assignments"}
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in names:
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), globals())
GANTT_DATES_CONTINUOUS = "Συνεχόμενες ημέρες"
prefix = "bar_" if view == "desktop" else "mobile_bar_"
mapping = {prefix + hashlib.md5(k.encode()).hexdigest(): k for k in wk_groups}
links = ''.join(f'<a class="mygantt-bar" id="{ident}" href="#" style="display:block;padding:14px;margin:8px;background:#15803d;color:white">{key} · Έργο · Α, Β</a>' for ident,key in mapping.items())
clicked = "" if st.session_state.get("fixture_headless") else click_detector('<div>'+links+'</div><script>document.addEventListener("click", function(e) {const a=e.target.closest("a"); const guard=window.parent.staffProSideEditor; if(a && guard && !guard.allowLeave(a.id)){e.preventDefault();e.stopImmediatePropagation();}},true);</script>', key="fixture_bars")
state_key = "clicked_key" if view == "desktop" else "mobile_clicked_key"
select_key = "edit_bar_select_widget" if view == "desktop" else "mobile_edit_select_widget"
if clicked and clicked != st.session_state.get("fixture_last"):
    st.session_state.fixture_last = clicked
    st.session_state[state_key] = mapping[clicked]
    st.session_state[select_key] = mapping[clicked]
    st.rerun()
st.caption("Οι πραγματικές φόρμες ακολουθούν. Καμία σύνδεση σε βάση δεδομένων.")

if view == "desktop":
    col_add, col_edit = st.columns(2)
    with col_add:
        st.info("Χώρος υπάρχουσας φόρμας νέας τοποθέτησης")
    edit = next(n for n in ast.walk(tree) if isinstance(n, ast.With)
                and isinstance(n.items[0].context_expr, ast.Name)
                and n.items[0].context_expr.id == "col_edit")
else:
    edit = next(n for n in tree.body if isinstance(n, ast.With)
                and isinstance(n.items[0].context_expr, ast.Call)
                and ast.unparse(n.items[0].context_expr.func) == "gantt_side_editor.editor")
exec(compile(ast.Module(body=[edit], type_ignores=[]), str(path), "exec"), globals())
