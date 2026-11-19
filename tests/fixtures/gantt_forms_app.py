"""Run the real edit blocks with synthetic records and an in-memory save spy.

No config/database modules or credentials are imported. Suitable for AppTest
and manual layout QA: streamlit run tests/fixtures/gantt_forms_app.py.
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
import placement_roles
import placement_details
import placement_hours
import placement_text
import periodic_visits
import gantt_staff_transfer
from gantt_helpers import normalize_id_list, clean_conflict_leave_notes, get_local_today

st.set_page_config(layout="wide")
st.title("Δοκιμή φορμών Gantt — συνθετικά δεδομένα")
view = st.sidebar.selectbox("Έκδοση", ["desktop", "mobile"])
st.sidebar.checkbox("Προσομοίωση αποτυχίας αποθήκευσης", key="fail_save")
for key, value in {
    "clicked_key": None, "mobile_clicked_key": None, "trigger_scroll": False,
    "edit_bar_select_widget": "", "mobile_edit_select_widget": "",
    "reset_edit_bar_select_next_run": False, "mobile_reset_edit_select_next_run": False,
    "save_calls": [], "employees": [{"id": "e1", "name": "Εργαζόμενος Α"},
                                       {"id": "e2", "name": "Εργαζόμενος Β"},
                                       {"id": "e3", "name": "Εργαζόμενος Γ"}],
    "projects": [{"id": "p1", "name": "Δοκιμαστικό έργο"}],
    "view_week_date": date(2026, 11, 16), "mobile_view_date": date(2026, 11, 16),
    "mobile_qa_rc": 0,
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
     "startTime": g["StartTime"], "endTime": g["EndTime"], "notes": g["Notes"],
     "colorName": g["ColorName"], "colorHex": "#15803d"}
    for g in wk_groups.values() for ident, eid in zip(g["AssignmentIds"], g["EmployeeIds"])
])
if st.session_state.get("fixture_persist"):
    from gantt_engine import generate_gantt_chart
    by_day = {}
    for row in st.session_state.assignments:
        by_day.setdefault(row["date"], []).append(row)
    _, wk_groups, _ = generate_gantt_chart(
        date(2026, 11, 16), 1, False, 0, by_day, [],
        st.session_state.employees, st.session_state.projects,
        {e["id"]: e for e in st.session_state.employees},
        {p["id"]: p for p in st.session_state.projects},
    )
st.session_state["fixture_group_keys"] = sorted(wk_groups, key=lambda key: (wk_groups[key]["Date"], wk_groups[key]["StartTime"]))


def save_batch(old, new, **kwargs):
    st.session_state.save_calls.append(deepcopy({"old": old, "new": new, **kwargs}))
    if st.session_state.fail_save:
        st.error("Δοκιμαστική αποτυχία: δεν αποθηκεύτηκε τίποτα.")
        return None
    if st.session_state.get("fixture_persist"):
        from assignment_store import preserve_ids
        if kwargs.get("keep_worker_ids"):
            new = preserve_ids(old, new)
        old_ids = {r["id"] for r in old}
        st.session_state.assignments = [r for r in st.session_state.assignments if r["id"] not in old_ids] + deepcopy(new)
    return new


employee_names = {e["id"]: e["name"] for e in st.session_state.employees}
utils = SimpleNamespace(
    get_employee_name=employee_names.__getitem__,
    get_project_name=lambda pid: "Δοκιμαστικό έργο", supabase=object(),
    safe_date_parse=lambda value: value if isinstance(value, date) else date.fromisoformat(value) if value else None,
    save_assignment_batch=save_batch,
    mark_data_changed=lambda: None,
    db_delete_in=lambda *args, **kwargs: st.error("Η διαγραφή δεν υποστηρίζεται στη δοκιμή."),
)

path = ROOT / "pages" / ("1_Gantt_Dashboard.py" if view == "desktop" else "4_Mobile_Gantt.py")
tree = ast.parse(path.read_text())
names = {"clear_bar_selection", "preserve_context_notes", "_form_time", "_form_prefill_date",
         "_save_placement_clipboard", "_form_clipboard_payload", "clear_mobile_selection",
         "_time_to_str", "_make_or_get_project", "_replace_local_assignments", "_gantt_target_dates"}
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in names:
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), globals())
GANTT_DATES_CONTINUOUS = "Συνεχόμενες ημέρες"
GANTT_DATES_SPECIFIC = "Συγκεκριμένες ημερομηνίες"
prefix = "bar_" if view == "desktop" else "mobile_bar_"
mapping = {prefix + hashlib.md5(k.encode()).hexdigest(): k for k in wk_groups}
links = ''.join(f'<a class="mygantt-bar" id="{ident}" href="#" style="display:block;padding:14px;margin:8px;background:#15803d;color:white">{key} · Έργο · Α, Β</a>' for ident,key in mapping.items())
clicked = "" if st.session_state.get("fixture_headless") else click_detector('<div>'+links+'</div>', key="fixture_bars")
state_key = "clicked_key" if view == "desktop" else "mobile_clicked_key"
select_key = "edit_bar_select_widget" if view == "desktop" else "mobile_edit_select_widget"
if clicked and clicked != st.session_state.get("fixture_last"):
    st.session_state.fixture_last = clicked
    st.session_state[state_key] = mapping[clicked]
    st.session_state[select_key] = mapping[clicked]
    st.rerun()
st.caption("Οι πραγματικές φόρμες ακολουθούν. Καμία σύνδεση σε βάση δεδομένων.")

if st.session_state.get("fixture_transfer"):
    transfer_mode = gantt_staff_transfer.render_mode(clear_bar_selection)
    if transfer_mode:
        transfer_panel = next(n for n in tree.body if isinstance(n, ast.If)
                              and isinstance(n.test, ast.Name) and n.test.id == "transfer_mode"
                              and any(isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
                                      and ast.unparse(stmt.value.func) == "gantt_staff_transfer.render_transfer"
                                      for stmt in n.body))
        exec(compile(ast.Module(body=[transfer_panel], type_ignores=[]), str(path), "exec"), globals())
    st.stop()

if view == "desktop":
    col_add, col_edit = st.columns(2)
    if st.session_state.get("fixture_show_add"):
        add = next(n for n in ast.walk(tree) if isinstance(n, ast.With)
                   and isinstance(n.items[0].context_expr, ast.Name)
                   and n.items[0].context_expr.id == "col_add")
        exec(compile(ast.Module(body=[add], type_ignores=[]), str(path), "exec"), globals())
    else:
        with col_add:
            st.info("Χώρος υπάρχουσας φόρμας νέας τοποθέτησης")
    edit = next(n for n in ast.walk(tree) if isinstance(n, ast.With)
                and isinstance(n.items[0].context_expr, ast.Name)
                and n.items[0].context_expr.id == "col_edit")
else:
    if st.session_state.get("fixture_show_add"):
        add = next(n for n in tree.body if isinstance(n, ast.With)
                   and isinstance(n.items[0].context_expr, ast.Call)
                   and ast.unparse(n.items[0].context_expr.func) == "st.expander"
                   and n.items[0].context_expr.args[0].value == "➕ Νέα Τοποθέτηση")
        exec(compile(ast.Module(body=[add], type_ignores=[]), str(path), "exec"), globals())
    edit = next(n for n in tree.body if isinstance(n, ast.With)
                and isinstance(n.items[0].context_expr, ast.Call)
                and ast.unparse(n.items[0].context_expr.func) == "st.expander"
                and n.items[0].context_expr.args[0].value == "✏️ Επεξεργασία Μπάρας")
exec(compile(ast.Module(body=[edit], type_ignores=[]), str(path), "exec"), globals())
