"""Real Viber page with synthetic data, no connection to production services."""
from datetime import date
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import streamlit as st

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
import placement_roles
import placement_details
today = date.today()
empty = {"id": "empty", "employeeId": "", "projectId": "p1", "date": today,
         "startTime": "09:00", "endTime": "12:00", "arrivalTime": "",
         "notes": "[Άδεια: Μαρία]"}
assignments = [empty]
if st.session_state.get("fixture_covered", True):
    assignments.append({**empty, "id": "replacement", "employeeId": "e2",
                        "notes": placement_details.combine_notes(placement_roles.combine_notes(
                            st.session_state.get("fixture_notes", "Κλειδιά στη ρεσεψιόν"),
                            st.session_state.get("fixture_contacts", {})),
                            st.session_state.get("fixture_project_details", {}))})
    if st.session_state.get("fixture_duplicate_worker"):
        assignments.append({**assignments[-1], "id": "second", "employeeId": "e3"})
st.session_state.setdefault("authenticated", True)
st.session_state.setdefault("assignments", assignments)
st.session_state.setdefault("leaves", [{"id": "leave", "employeeId": "e1",
    "startDate": today, "endDate": today, "substituteId": "e2"}])
names = {"e1": "Μαρία", "e2": "Άννα", "e3": "Ελένη"}
fake_utils = SimpleNamespace(
    init_data_and_sync=lambda: None, setup_shared_ui=lambda **kwargs: None,
    get_project_info=lambda pid: {"name": "Έργο"},
    get_employee_name=lambda eid: names.get(eid, "Χωρίς Προσωπικό"),
)
path = root / "pages/3_Viber_Export.py"
with patch.dict(sys.modules, {"utils": fake_utils}):
    exec(compile(path.read_text(), str(path), "exec"), globals())
