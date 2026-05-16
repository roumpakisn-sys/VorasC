import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from datetime import datetime, date, timedelta
import uuid
import calendar
import textwrap
import threading
import re
import ast
import time

try:
    from supabase import create_client
    SUPABASE_INSTALLED = True
except ImportError:
    SUPABASE_INSTALLED = False

# --- 10 Βασικά Χρώματα ---
BASIC_COLORS = {
    "Μπλε": "#4a86e8",
    "Κόκκινο": "#e00000",
    "Πράσινο": "#6aa84f",
    "Κίτρινο": "#f1c232",
    "Μωβ": "#8e7cc3",
    "Πορτοκαλί": "#e69138",
    "Γαλάζιο": "#00ffff",
    "Ροζ": "#c90076",
    "Σκούρο Πράσινο": "#38761d",
    "Γκρι": "#999999"
}

# --- SETUP SUPABASE ---
try:
    HAS_SECRETS = "SUPABASE_URL" in st.secrets and "SUPABASE_KEY" in st.secrets
except Exception:
    HAS_SECRETS = False

@st.cache_resource
def init_supabase():
    if not SUPABASE_INSTALLED or not HAS_SECRETS:
        return None
    try:
        return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except Exception:
        return None

supabase = init_supabase()

# --- ΣΥΣΤΗΜΑ UNDO/REDO ---
def init_undo_stack():
    if "undo_stack" not in st.session_state:
        st.session_state.undo_stack = []
    if "redo_stack" not in st.session_state:
        st.session_state.redo_stack = []

def add_transaction(actions):
    init_undo_stack()
    st.session_state.undo_stack.append(actions)
    st.session_state.redo_stack.clear()
    if len(st.session_state.undo_stack) > 30:
        st.session_state.undo_stack.pop(0)

# --- ΒΑΣΗ ΔΕΔΟΜΕΝΩΝ - HELPERS ---
def mark_data_changed():
    st.session_state.local_gantt_version = st.session_state.get('local_gantt_version', 0) + 1
    st.session_state.data_dirty = True

def fetch_paginated(table):
    if not supabase: return []
    all_rows = []
    offset = 0
    limit = 1000
    while True:
        try:
            data = supabase.table(table).select("*").range(offset, offset + limit - 1).execute().data
            if data:
                all_rows.extend(data)
            if not data or len(data) < limit:
                break
            offset += limit
        except Exception:
            break
    return all_rows

def serialize_dates(data):
    if isinstance(data, list):
        return [serialize_dates(item) for item in data]
    elif isinstance(data, dict):
        return {k: (v.isoformat() if isinstance(v, (datetime, date)) else v) for k, v in data.items()}
    return data

def format_log_details(table_name, records):
    if not records: return "Καμία εγγραφή"
    if isinstance(records, dict): records = [records]
    if isinstance(records, str): return records
    lines = []
    for r in records:
        if not isinstance(r, dict): continue
        if table_name == 'employees':
            lines.append(f"{r.get('name', 'Άγνωστος')}")
        elif table_name == 'projects':
            lines.append(f"'{r.get('name', 'Άγνωστο Έργο')}'")
        elif table_name == 'assignments':
            emp_id = r.get('employeeld')
            emp_name = "Χωρίς Προσωπικό"
            if emp_id and 'employees' in st.session_state:
                e_info = next((e for e in st.session_state.employees if e['id'] == emp_id), None)
                if e_info: emp_name = e_info['name']
            proj_id = r.get('projectId')
            proj_name = "Άγνωστο Έργο"
            if proj_id and 'projects' in st.session_state:
                p_info = next((p for p in st.session_state.projects if p['id'] == proj_id), None)
                if p_info: proj_name = p_info['name']
            d = r.get('date', "")
            if isinstance(d, date): d = d.strftime('%d/%m/%Y')
            elif isinstance(d, str) and "T" in d: d = d.split("T")[0]
            lines.append(f"Βάρδια: {emp_name} στο '{proj_name}' ({d})")
        elif table_name == 'leaves':
            emp_id = r.get('employeeld')
            emp_name = next((e['name'] for e in st.session_state.get('employees', []) if e['id'] == emp_id), "Άγνωστος")
            sd = r.get('startDate', "")
            ed = r.get('endDate', "")
            if isinstance(sd, date): sd = sd.strftime('%d/%m/%Y')
            if isinstance(ed, date): ed = ed.strftime('%d/%m/%Y')
            sub_id = r.get('substituteld')
            sub_str = f" [Αντικατ: {next((e['name'] for e in st.session_state.employees if e['id'] == sub_id), 'Άγνωστος')}]" if sub_id else ""
            lines.append(f"Άδεια: {emp_name} ({sd} - {ed}){sub_str}")
        elif table_name == 'evaluations':
            emp_id = r.get('employeeld')
            emp_name = next((e['name'] for e in st.session_state.get('employees', []) if e['id'] == emp_id), "Άγνωστος")
            lines.append(f"Αξιολόγηση: {emp_name} ({r.get('month')}/{r.get('year')})")
        elif table_name == 'recurring_patterns':
            lines.append(f"Επαναλαμβανόμενη σειρά: {r.get('type')}")
        else:
            lines.append("Εγγραφή")
    if not lines: return "Λεπτομέρειες μη διαθέσιμες"
    if len(lines) > 5:
        return " | ".join(lines[:5]) + f" ...και άλλες {len(lines)-5} εγγραφές"
    return " | ".join(lines)

def parse_old_log_details(table_name, details_str):
    if not isinstance(details_str, str): return details_str
    if not (details_str.startswith("[{") or details_str.startswith("{")): return details_str
    try:
        clean_str = re.sub(r"datetime\.date\((\d+),\s*(\d+),\s*(\d+)\)", r" \3/\2/\1", details_str)
        parsed_data = ast.literal_eval(clean_str)
        return format_log_details(table_name, parsed_data)
    except:
        return details_str

def log_activity(action_type, table_name, details_raw):
    if not supabase or table_name == 'activity_logs': return
    user = st.session_state.get("current_user", "Άγνωστος")
    try:
        from zoneinfo import ZoneInfo
        now_gr = datetime.now(ZoneInfo("Europe/Athens")).isoformat()
    except:
        now_gr = (datetime.utcnow() + timedelta(hours=3)).isoformat()
    
    log_entry = {
        "id": str(uuid.uuid4()),
        "timestamp": now_gr,
        "username": user,
        "action_type": action_type,
        "table_name": table_name,
        "details": str(details_raw)[:2000]
    }
    try:
        res = supabase.table("activity_logs").insert(log_entry).execute()
        if res.data:
            st.session_state.global_db_ts = res.data[0]['timestamp']
    except Exception as e:
        print(f"Log Error: {e}")

def db_insert(table, data, track=True):
    mark_data_changed()
    if track:
        records = data if isinstance(data, list) else [data]
        add_transaction([{'type': 'insert', 'table': table, 'records': records}])
    if supabase:
        try:
            supabase.table(table).insert(serialize_dates(data)).execute()
            log_activity("ΠΡΟΣΘΗΚΗ", table, format_log_details(table, data))
        except Exception as e:
            st.error(f"Σφάλμα αποθήκευσης στη βάση: {e}")

def db_delete(table, column, value, deleted_records=None, track=True):
    mark_data_changed()
    if not deleted_records:
        table_data = st.session_state.get(table, [])
        deleted_records = [r for r in table_data if r.get(column) == value]
    if track and deleted_records:
        add_transaction([{'type': 'delete', 'table': table, 'records': deleted_records}])
    if supabase:
        try:
            supabase.table(table).delete().eq(column, value).execute()
            log_activity("ΔΙΑΓΡΑΦΗ", table, format_log_details(table, deleted_records) if deleted_records else f"{column} = {value}")
        except Exception as e:
            st.error(f"Σφάλμα διαγραφής στη βάση: {e}")

def db_delete_in(table, column, values, deleted_records=None, track=True):
    mark_data_changed()
    if values:
        if not deleted_records:
            table_data = st.session_state.get(table, [])
            deleted_records = [r for r in table_data if r.get(column) in values]
        if track and deleted_records:
            add_transaction([{'type': 'delete', 'table': table, 'records': deleted_records}])
        if supabase:
            try:
                supabase.table(table).delete().in_(column, values).execute()
                log_activity("ΜΑΖΙΚΗ ΔΙΑΓΡΑΦΗ", table, format_log_details(table, deleted_records) if deleted_records else f"{len(values)} εγγραφές")
            except Exception as e:
                st.error(f"Σφάλμα μαζικής διαγραφής: {e}")

def db_update(table, id_val, new_data, old_data=None, track=True):
    mark_data_changed()
    if track and not old_data:
        table_data = st.session_state.get(table, [])
        old_data = next((r for r in table_data if r.get('id') == id_val), None)
    if track and old_data:
        add_transaction([{'type': 'update', 'table': table, 'old_records': [old_data], 'new_records': [new_data]}])
    if supabase:
        try:
            supabase.table(table).update(serialize_dates(new_data)).eq('id', id_val).execute()
            log_activity("ΕΝΗΜΕΡΩΣΗ", table, format_log_details(table, new_data))
        except Exception as e:
            st.error(f"Σφάλμα ενημέρωσης στη βάση: {e}")

def perform_undo():
    if not st.session_state.undo_stack: return
    transaction = st.session_state.undo_stack.pop()
    st.session_state.redo_stack.append(transaction)
    for act in reversed(transaction):
        if act['type'] == 'insert':
            ids = [r['id'] for r in act['records']]
            db_delete_in(act['table'], 'id', ids, track=False)
        elif act['type'] == 'delete':
            db_insert(act['table'], act['records'], track=False)
        elif act['type'] == 'update':
            for old_r in act['old_records']:
                db_update(act['table'], old_r['id'], old_r, track=False)
    mark_data_changed()

def perform_redo():
    if not st.session_state.redo_stack: return
    transaction = st.session_state.redo_stack.pop()
    st.session_state.undo_stack.append(transaction)
    for act in transaction:
        if act['type'] == 'insert':
            db_insert(act['table'], act['records'], track=False)
        elif act['type'] == 'delete':
            ids = [r['id'] for r in act['records']]
            db_delete_in(act['table'], 'id', ids, track=False)
        elif act['type'] == 'update':
            for new_r in act['new_records']:
                db_update(act['table'], new_r['id'], new_r, track=False)
    mark_data_changed()

# --- HELPERS ΓΙΑ ΔΕΔΟΜΕΝΑ ---
def get_employee_name(emp_id):
    if not emp_id: return "Χωρίς Προσωπικό"
    emp = st.session_state.emp_map.get(emp_id)
    return emp['name'] if emp else "Άγνωστος"

def get_project_name(proj_id):
    proj = st.session_state.proj_map.get(proj_id)
    return proj['name'] if proj else "Άγνωστο Έργο"

def get_project_info(proj_id):
    return st.session_state.proj_map.get(proj_id)

def is_on_leave(emp_id, check_date):
    if not emp_id: return False
    emp_leaves = st.session_state.leaves_by_emp.get(emp_id, [])
    for l in emp_leaves:
        if l['startDate'] <= check_date <= l['endDate']: return True
    return False

def check_and_resolve_conflict(emp_id, check_date, t_start, t_end, exclude_ids=None):
    if not emp_id: return t_start, t_end, False, ""
    if exclude_ids is None: exclude_ids = []
    new_s = str(t_start)[:5]
    new_e = str(t_end)[:5]
    day_assigns = st.session_state.assignments_by_date.get(check_date, [])
    emp_assigns = [a for a in day_assigns if a['employeeld'] == emp_id and a['id'] not in exclude_ids]
    
    allowed_overlap = False
    for ea in emp_assigns:
        ea_s = str(ea['startTime'])[:5]
        ea_e = str(ea['endTime'])[:5]
        if new_s < ea_e and new_e > ea_s:
            if new_e > ea_e:
                allowed_overlap = True
            else:
                return t_start, t_end, True, "Πλήρης επικάλυψη με υπάρχουσα βάρδια (δεν τελειώνει αργότερα)"
    return t_start, t_end, False, "Allowed Overlap" if allowed_overlap else ""

# --- ΑΥΤΟΜΑΤΗ ΕΠΕΚΤΑΣΗ ---
def auto_extend_recurring_patterns():
    if not st.session_state.get('recurring_patterns'): return
    max_dates = {}
    for a in st.session_state.assignments:
        rid = a.get('recurring_id')
        if rid:
            if rid not in max_dates or a['date'] > max_dates[rid]:
                max_dates[rid] = a['date']
    
    new_assignments_batch = []
    today = date.today()
    for pat in st.session_state.recurring_patterns:
        rid = pat['id']
        latest_date = max_dates.get(rid)
        if latest_date and (latest_date - today).days <= 30:
            start_ext_date = latest_date + timedelta(days=1)
            end_ext_date = start_ext_date + timedelta(days=365)
            r_type = pat.get('type')
            r_emps = pat.get('employeelds', [])
            r_proj = pat.get('projectId')
            r_color = pat.get('colorName')
            c_hex = BASIC_COLORS.get(r_color, "#999999")
            r_notes = pat.get('notes', "")
            str_arrival = pat.get('arrivalTime', "")
            str_start = str(pat.get('startTime'))[:5]
            str_end = str(pat.get('endTime'))[:5]
            selected_weekdays = pat.get('weekdays', [])
            dates_to_assign = []
            curr_date = start_ext_date
            day_map_inv = {0: "Δευτέρα", 1: "Τρίτη", 2: "Τετάρτη", 3: "Πέμπτη", 4: "Παρασκευή", 5: "Σάββατο", 6: "Κυριακή"}
            day_map = {v: k for k, v in day_map_inv.items()}
            selected_weekday_ints = [day_map[d] for d in selected_weekdays] if selected_weekdays else []
            
            while curr_date <= end_ext_date:
                if r_type == "Εβδομαδιαία":
                    dates_to_assign.append(curr_date)
                    curr_date += timedelta(days=7)
                elif r_type == "Μηνιαία":
                    dates_to_assign.append(curr_date)
                    month = curr_date.month
                    year = curr_date.year
                    if month == 12:
                        month = 1; year += 1
                    else:
                        month += 1
                    try:
                        curr_date = curr_date.replace(year=year, month=month)
                    except ValueError:
                        last_day = calendar.monthrange(year, month)[1]
                        curr_date = curr_date.replace(year=year, month=month, day=last_day)
                elif r_type == "Επιλεγμένες Μέρες Εβδομάδας":
                    if curr_date.weekday() in selected_weekday_ints:
                        dates_to_assign.append(curr_date)
                    curr_date += timedelta(days=1)
            
            for d in dates_to_assign:
                if r_type == "Επιλεγμένες Μέρες Εβδομάδας":
                    d_name = day_map_inv[d.weekday()]
                    emps_to_process = r_emps.get(d_name, []) if isinstance(r_emps, dict) else r_emps
                else:
                    emps_to_process = r_emps
                
                emps_to_process = emps_to_process if emps_to_process else [""]
                for eid in emps_to_process:
                    if eid:
                        if is_on_leave(eid, d): continue
                        adj_start, adj_end, is_conflict, msg = check_and_resolve_conflict(eid, d, str_start, str_end)
                        if is_conflict: continue
                    else:
                        adj_start, adj_end = str_start, str_end
                    
                    new_assign = {
                        'id': str(uuid.uuid4()), 'recurring_id': rid, 'employeeld': eid, 'projectId': r_proj,
                        'date': d, 'arrivalTime': str_arrival, 'startTime': adj_start, 'endTime': adj_end,
                        'colorName': r_color, 'colorHex': c_hex, 'notes': r_notes, 'is_cancelled': False, 'cancel_reason': ""
                    }
                    new_assignments_batch.append(new_assign)
                    if d not in st.session_state.assignments_by_date:
                        st.session_state.assignments_by_date[d] = []
                    st.session_state.assignments_by_date[d].append(new_assign)
                    
    if new_assignments_batch:
        st.session_state.assignments.extend(new_assignments_batch)
        st.session_state.data_dirty = True
        st.session_state.local_gantt_version = st.session_state.get('local_gantt_version', 0) + 1
        if supabase:
            def insert_batch(batch):
                chunk_size = 500
                for i in range(0, len(batch), chunk_size):
                    try:
                        supabase.table('assignments').insert(serialize_dates(batch[i:i+chunk_size])).execute()
                    except Exception as e:
                        print(f"Auto-extend insert error: {e}")
            threading.Thread(target=insert_batch, args=(new_assignments_batch,), daemon=True).start()

# --- ΣΥΓΧΡΟΝΙΣΜΟΣ ΔΕΔΟΜΕΝΩΝ (ΚΑΛΕΙΤΑΙ ΑΠΟ ΤΙΣ ΣΕΛΙΔΕΣ) ---
def init_data_and_sync():
    init_undo_stack()
    if supabase:
        st.session_state.is_cloud = True
        latest_ts = None
        try:
            res = supabase.table('activity_logs').select('timestamp').order('timestamp', desc=True).limit(1).execute()
            if res.data:
                latest_ts = res.data[0]['timestamp']
        except:
            pass
        
        if "global_db_ts" not in st.session_state or st.session_state.global_db_ts != latest_ts:
            with st.spinner("Λήψη νέων δεδομένων από Supabase..."):
                st.session_state.employees = fetch_paginated("employees")
                st.session_state.projects = fetch_paginated("projects")
                
                assigns = fetch_paginated("assignments")
                for a in assigns:
                    if isinstance(a.get('date'), str):
                        a['date'] = datetime.strptime(a['date'].split("T")[0], "%Y-%m-%d").date()
                st.session_state.assignments = assigns
                
                leaves = fetch_paginated("leaves")
                for l in leaves:
                    if isinstance(l.get('startDate'), str):
                        l['startDate'] = datetime.strptime(l['startDate'].split("T")[0], "%Y-%m-%d").date()
                    if isinstance(l.get('endDate'), str):
                        l['endDate'] = datetime.strptime(l['endDate'].split("T")[0], "%Y-%m-%d").date()
                st.session_state.leaves = leaves
                
                patterns = fetch_paginated("recurring_patterns")
                for p in patterns:
                    if isinstance(p.get('startDate'), str):
                        p['startDate'] = datetime.strptime(p['startDate'].split("T")[0], "%Y-%m-%d").date()
                st.session_state.recurring_patterns = patterns
                
                try:
                    st.session_state.evaluations = fetch_paginated("evaluations")
                except:
                    st.session_state.evaluations = []
                    
                try:
                    st.session_state.activity_logs = supabase.table("activity_logs").select("*").order("timestamp", desc=True).limit(500).execute().data
                except:
                    st.session_state.activity_logs = []
                    
                st.session_state.global_db_ts = latest_ts
                mark_data_changed()
    else:
        if 'local_data_loaded' not in st.session_state:
            st.session_state.local_data_loaded = True
            st.session_state.is_cloud = False
            st.session_state.employees = [
                {'id': '1', 'name': 'Γιάννης Παπαδόπουλος', 'position': 'ΕΡΓΑΤΗΣ', 'id_number': 'ΑΙ123456', 'phone': '6912345678', 'status': 'Ενεργός'},
                {'id': '2', 'name': 'Μαρία Παππά', 'position': 'ΕΠΟΠΤΗΣ', 'id_number': 'ΑΚ654321', 'phone': '6987654321', 'status': 'Ενεργός'}
            ]
            st.session_state.projects = [
                {'id': 'p1', 'name': 'Ανακαίνιση Γραφείων', 'color': '#4a86e8'},
                {'id': 'p2', 'name': 'Συντήρηση Δικτύου', 'color': '#e69138'}
            ]
            st.session_state.assignments = []
            st.session_state.recurring_patterns = []
            st.session_state.leaves = []
            st.session_state.evaluations = []
            st.session_state.activity_logs = []
            mark_data_changed()

    if 'view_week_date' not in st.session_state:
        st.session_state.view_week_date = date.today()

    # FAST INDEXING
    if st.session_state.get('data_dirty', True):
        st.session_state.emp_map = {e['id']: e for e in st.session_state.employees}
        st.session_state.proj_map = {p['id']: p for p in st.session_state.projects}
        
        assign_date_map = {}
        for a in st.session_state.assignments:
            d = a['date']
            if d not in assign_date_map: assign_date_map[d] = []
            assign_date_map[d].append(a)
        st.session_state.assignments_by_date = assign_date_map
        
        leaves_by_emp = {}
        for l in st.session_state.leaves:
            eid = l['employeeld']
            if eid not in leaves_by_emp: leaves_by_emp[eid] = []
            leaves_by_emp[eid].append(l)
        st.session_state.leaves_by_emp = leaves_by_emp
        st.session_state.data_dirty = False

    # Έλεγχος αυτόματης επέκτασης (ανά 1 ώρα)
    if "last_auto_extend_check" not in st.session_state or time.time() - st.session_state.last_auto_extend_check > 3600:
        auto_extend_recurring_patterns()
        st.session_state.last_auto_extend_check = time.time()

# --- ΚΟΙΝΟ UI & SIDEBAR (ΚΑΛΕΙΤΑΙ ΑΠΟ ΟΛΕΣ ΤΙΣ ΣΕΛΙΔΕΣ) ---
def setup_shared_ui():
    # CSS
    st.markdown("""
    <style>
    [data-testid="stSidebar"] {
        box-shadow: 5px 0px 20px rgba(0, 0, 0, 0.15) !important;
        border-right: 1px solid #e2e8f0 !important;
    }
    .stPlotlyChart { border: 1px solid #cbd5e1; border-radius: 8px; }
    .leave-conflict-box {
        padding: 12px; border-radius: 8px; background-color: #fee2e2;
        border: 1px solid #ef4444; margin-bottom: 8px; color: #b91c1c; font-weight: 500;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # ΨΗΦΙΑΚΟ ΡΟΛΟΙ
    components.html("""
    <script>
    const doc = window.parent.document;
    let clockDiv = doc.getElementById("staff_pro_clock");
    if (!clockDiv) {
        clockDiv = doc.createElement("div");
        clockDiv.id = "staff_pro_clock";
        doc.body.appendChild(clockDiv);
        clockDiv.style.cssText = "position: fixed; top: 12px; right: 300px; font-size: 18px; font-weight: bold; color: #1e293b; z-index: 999999; background: #ffffff; padding: 6px 14px; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06); border: 1px solid #cbd5e1; font-family: 'Courier New', Courier, monospace; letter-spacing: 2px;";
    }
    function updateClock() {
        const now = new Date();
        const dateOptions = { day: 'numeric', month: 'long', year: 'numeric' };
        clockDiv.innerHTML = now.toLocaleDateString('el-GR', dateOptions) + " | " + now.toLocaleTimeString('el-GR', {hour12: false});
    }
    updateClock();
    setInterval(updateClock, 1000);
    </script>
    """, height=0, width=0)

    # SIDEBAR CONTROLS
    st.sidebar.title("STAFF.PRO")
    st.sidebar.write("---")
    
    col_u, col_r = st.sidebar.columns(2)
    with col_u:
        if st.button("⏪ Undo", disabled=len(st.session_state.get('undo_stack', [])) == 0, use_container_width=True):
            perform_undo()
            st.rerun()
    with col_r:
        if st.button("⏩ Redo", disabled=len(st.session_state.get('redo_stack', [])) == 0, use_container_width=True):
            perform_redo()
            st.rerun()
            
    st.sidebar.write("---")
    st.sidebar.subheader("Κατάσταση Συστήματος")
    if st.session_state.get('is_cloud'):
        st.sidebar.success("☁️ Cloud Sync (Real-time)")
        if st.sidebar.button("🔄 Άμεση Ανανέωση", use_container_width=True):
            st.session_state.global_db_ts = "force_refresh"
            st.rerun()
    else:
        st.sidebar.error("🔌 Εκτός Σύνδεσης (Τοπικά)")
        
    if not SUPABASE_INSTALLED:
        st.sidebar.caption("⚠️ **Πρόβλημα:** Λείπει η βιβλιοθήκη 'supabase'. Κάνε Reboot την εφαρμογή.")
    elif not HAS_SECRETS:
        st.sidebar.caption("⚠️ **Πρόβλημα:** Δεν βρέθηκαν τα Secrets (SUPABASE_URL ή SUPABASE_KEY).")

    st.sidebar.write("---")
    st.sidebar.markdown(f"👤 Συνδεδεμένος ως: **{st.session_state.get('current_user', 'Άγνωστος')}**")
    if st.sidebar.button("🚪 Αποσύνδεση", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.current_user = None
        st.switch_page("streamlit_app.py")

    # ALERTS ΟΡΦΑΝΩΝ ΒΑΡΔΙΩΝ (Στο Main Window)
    today_date = date.today()
    orphan_count = 0
    orphan_details = []
    for i in range(8):
        check_d = today_date + timedelta(days=i)
        day_assigns = st.session_state.get('assignments_by_date', {}).get(check_d, [])
        for a in day_assigns:
            if not a.get('employeeld') and not a.get('is_cancelled', False):
                orphan_count += 1
                proj = get_project_info(a['projectId'])
                proj_name = proj['name'] if proj else "Άγνωστο Έργο"
                orphan_details.append(f"🔴 **{check_d.strftime('%d/%m/%Y')}** | Ώρες: {a['startTime'][:5]}-{a['endTime'][:5]} | Έργο: **{proj_name}**")
    
    if orphan_count > 0:
        st.error(f"⚠️ **Προσοχή: {orphan_count} βάρδια/ες τις επόμενες 7 ημέρες έμειναν ορφανές (χωρίς προσωπικό)!**")
        with st.expander("🔍 Δείτε αναλυτικά τις ορφανές βάρδιες"):
            for detail in orphan_details: st.markdown(detail)
        st.write("---")
