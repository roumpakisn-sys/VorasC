import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.express as px
from datetime import datetime, date, timedelta
import uuid
import calendar
import io
import time
import textwrap
import gc  # Γρήγορη απελευθέρωση μνήμης (Garbage Collection)
import ast
import re

try:
    from supabase import create_client
    SUPABASE_INSTALLED = True
except ImportError:
    SUPABASE_INSTALLED = False

# --- Ρύθμιση σελίδας ---
st.set_page_config(page_title="Staff Manager Pro", layout="wide")

# --- GLOBAL STYLING & ΨΗΦΙΑΚΟ ΡΟΛΟΙ ---
st.markdown("""
    <style>
    [data-testid="stSidebar"] {
        box-shadow: 5px 0px 20px rgba(0, 0, 0, 0.15) !important;
        border-right: 1px solid #e2e8f0 !important;
    }
    .stPlotlyChart {
        border: 1px solid #cbd5e1;
        border-radius: 8px;
    }
    .leave-conflict-box {
        padding: 12px;
        border-radius: 8px;
        background-color: #fee2e2;
        border: 1px solid #ef4444;
        margin-bottom: 8px;
        color: #b91c1c;
        font-weight: 500;
    }
    </style>
""", unsafe_allow_html=True)

components.html("""
    <script>
        const doc = window.parent.document;
        let clockDiv = doc.getElementById("staff_pro_clock");
        if (!clockDiv) {
            clockDiv = doc.createElement("div");
            clockDiv.id = "staff_pro_clock";
            doc.body.appendChild(clockDiv);
        }
        clockDiv.style.cssText = "position: fixed; top: 12px; right: 300px; font-size: 18px; font-weight: bold; color: #1e293b; z-index: 999999; background: #ffffff; padding: 6px 14px; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06); border: 1px solid #cbd5e1; font-family: 'Courier New', Courier, monospace; letter-spacing: 2px;";
        function updateClock() {
            const now = new Date();
            const el = doc.getElementById("staff_pro_clock");
            if (el) {
                const dateOptions = { day: 'numeric', month: 'long', year: 'numeric' };
                const dateStr = now.toLocaleDateString('el-GR', dateOptions);
                const timeStr = now.toLocaleTimeString('el-GR', {hour12: false});
                el.innerHTML = dateStr + " | " + timeStr;
            }
        }
        updateClock();
        setInterval(updateClock, 1000);
    </script>
""", height=0, width=0)

# --- ΟΘΟΝΗ ΣΥΝΔΕΣΗΣ (AUTHENTICATION) ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "current_user" not in st.session_state:
    st.session_state.current_user = None

if not st.session_state.authenticated:
    st.markdown("<h1 style='text-align: center; margin-top: 10vh;'>🔒 Staff Manager Pro</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray;'>Παρακαλώ επιλέξτε χρήστη και εισάγετε τον κωδικό πρόσβασης.</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("login_form"):
            username = st.selectbox("Χρήστης", ["Admin", "EXOUZ", "MEMEK", "NAK", "TAN"])
            password = st.text_input("Κωδικός Πρόσβασης", type="password")
            submit = st.form_submit_button("Είσοδος", use_container_width=True)
            
            if submit:
                valid_passwords = {
                    "Admin": st.secrets.get("APP_PASSWORD", "admin123"),
                    "EXOUZ": st.secrets.get("USER1_PASSWORD", "pass1"),
                    "MEMEK": st.secrets.get("USER2_PASSWORD", "pass2"),
                    "NAK": st.secrets.get("USER3_PASSWORD", "pass3"),
                    "TAN": st.secrets.get("USER4_PASSWORD", "pass4")
                }
                if password == valid_passwords.get(username):
                    st.session_state.authenticated = True
                    st.session_state.current_user = username
                    st.rerun()
                else:
                    st.error("Λάθος κωδικός πρόσβασης. Δοκιμάστε ξανά.")
    st.stop()

# --- SUPABASE CONNECTION ---
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

# --- ΣΥΣΤΗΜΑ UNDO / REDO ---
if "undo_stack" not in st.session_state: st.session_state.undo_stack = []
if "redo_stack" not in st.session_state: st.session_state.redo_stack = []

def add_transaction(actions):
    st.session_state.undo_stack.append(actions)
    st.session_state.redo_stack.clear()
    if len(st.session_state.undo_stack) > 5:
        st.session_state.undo_stack.pop(0)

# --- SELECTIVE FETCHING & CACHING ---
CACHE_TTL = 300 # 5 λεπτά

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
            # ΠΡΟΣΘΗΚΗ .order("id") ΕΔΩ: Εξασφαλίζει ότι το PostgREST δεν θα χάσει ή διπλοκατεβάσει γραμμές κατά το Pagination!
            data = supabase.table(table).select("*").order("id").range(offset, offset + limit - 1).execute().data
            if data:
                all_rows.extend(data)
            if not data or len(data) < limit:
                break
            offset += limit
        except Exception:
            break
    return all_rows

def clear_all_caches():
    st.session_state.db_last_fetch = 0

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
            emp_id = r.get('employeeId')
            emp_name = next((e['name'] for e in st.session_state.get('employees', []) if e['id'] == emp_id), "Χωρίς Προσωπικό") if emp_id else "Χωρίς Προσωπικό"
            proj_id = r.get('projectId')
            proj_name = next((p['name'] for p in st.session_state.get('projects', []) if p['id'] == proj_id), "Άγνωστο Έργο") if proj_id else "Άγνωστο Έργο"
            d = r.get('date', '')
            if isinstance(d, date): d = d.strftime('%d/%m/%Y')
            elif isinstance(d, str) and "T" in d: d = d.split("T")[0]
            lines.append(f"Βάρδια: {emp_name} στο '{proj_name}' ({d})")
        elif table_name == 'leaves':
            emp_id = r.get('employeeId')
            emp_name = next((e['name'] for e in st.session_state.get('employees', []) if e['id'] == emp_id), "Άγνωστος")
            sd = r.get('startDate', '')
            ed = r.get('endDate', '')
            if isinstance(sd, date): sd = sd.strftime('%d/%m/%Y')
            if isinstance(ed, date): ed = ed.strftime('%d/%m/%Y')
            sub_id = r.get('substituteId')
            sub_str = f" [Αντικατ: {next((e['name'] for e in st.session_state.employees if e['id'] == sub_id), 'Άγνωστος')}]" if sub_id else ""
            lines.append(f"Άδεια: {emp_name} ({sd} - {ed}){sub_str}")
        elif table_name == 'evaluations':
            emp_id = r.get('employeeId')
            emp_name = next((e['name'] for e in st.session_state.get('employees', []) if e['id'] == emp_id), "Άγνωστος")
            lines.append(f"Αξιολόγηση: {emp_name} ({r.get('month')}/{r.get('year')})")
        elif table_name == 'recurring_patterns':
            lines.append(f"Επαναλαμβανόμε σειρά: {r.get('type')}")
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
        clean_str = re.sub(r"datetime\.date\((\d+),\s*(\d+),\s*(\d+)\)", r"'\3/\2/\1'", details_str)
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

# Όλες οι DB συναρτήσεις είναι Σειριακές για ασφάλεια μνήμης
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
            # Chunking για να μην "σκάει" η βάση λόγω ορίου μεγέθους στο URL (PostgREST limit)
            chunk_size = 50  # Μείωση στο 50 για απόλυτη ασφάλεια
            for i in range(0, len(values), chunk_size):
                try:
                    supabase.table(table).delete().in_(column, values[i:i+chunk_size]).execute()
                except Exception as e:
                    st.error(f"Σφάλμα μαζικής διαγραφής (chunk {i}): {e}")
            log_activity("ΜΑΖΙΚΗ ΔΙΑΓΡΑΦΗ", table, format_log_details(table, deleted_records) if deleted_records else f"{len(values)} εγγραφές")

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
        table = act['table']
        if act['type'] == 'insert':
            ids = [r['id'] for r in act['records']]
            st.session_state[table] = [r for r in st.session_state.get(table, []) if r['id'] not in ids]
            db_delete_in(table, 'id', ids, track=False)
        elif act['type'] == 'delete':
            st.session_state[table].extend(act['records'])
            db_insert(table, act['records'], track=False)
        elif act['type'] == 'update':
            upd_map = {r['id']: r for r in act['old_records']}
            st.session_state[table] = [upd_map.get(r['id'], r) for r in st.session_state.get(table, [])]
            for old_r in act['old_records']:
                db_update(table, old_r['id'], old_r, track=False)
    mark_data_changed()

def perform_redo():
    if not st.session_state.redo_stack: return
    transaction = st.session_state.redo_stack.pop()
    st.session_state.undo_stack.append(transaction)
    for act in transaction:
        table = act['table']
        if act['type'] == 'insert':
            st.session_state[table].extend(act['records'])
            db_insert(table, act['records'], track=False)
        elif act['type'] == 'delete':
            ids = [r['id'] for r in act['records']]
            st.session_state[table] = [r for r in st.session_state.get(table, []) if r['id'] not in ids]
            db_delete_in(table, 'id', ids, track=False)
        elif act['type'] == 'update':
            upd_map = {r['id']: r for r in act['new_records']}
            st.session_state[table] = [upd_map.get(r['id'], r) for r in st.session_state.get(table, [])]
            for new_r in act['new_records']:
                db_update(table, new_r['id'], new_r, track=False)
    mark_data_changed()

BASIC_COLORS = {
    "Μπλε": "#4a86e8", "Κόκκινο": "#e00000", "Πράσινο": "#6aa84f", "Κίτρινο": "#f1c232",
    "Μωβ": "#8e7cc3", "Πορτοκαλί": "#e69138", "Γαλάζιο": "#00ffff", "Ροζ": "#c90076",
    "Σκούρο Πράσινο": "#38761d", "Γκρι": "#999999"
}

# --- SELECTIVE FETCHING & REAL-TIME POLLING ---
if supabase:
    st.session_state.is_cloud = True
    
    latest_ts = None
    try:
        # Ταχύτατος έλεγχος για το πότε έγινε η τελευταία κίνηση στη βάση
        res = supabase.table('activity_logs').select('timestamp').order('timestamp', desc=True).limit(1).execute()
        if res.data:
            latest_ts = res.data[0]['timestamp']
    except:
        pass

    force_refresh = st.session_state.get("global_db_ts") == "force_refresh"
    # Εάν ο τελευταίος χρόνος άλλαξε από τη βάση (κάποιος άλλος χρήστης έκανε κίνηση), ενεργοποιούμε το reload!
    ts_changed = latest_ts and st.session_state.get("global_db_ts") not in [None, "force_refresh", latest_ts]
    
    if force_refresh or ts_changed or "db_last_fetch" not in st.session_state or time.time() - st.session_state.get("db_last_fetch", 0) > CACHE_TTL:
        with st.spinner("Λήψη δεδομένων από τη βάση..."):
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
                
            st.session_state.db_last_fetch = time.time()
            st.session_state.global_db_ts = latest_ts
            mark_data_changed()
else:
    if 'local_data_loaded' not in st.session_state:
        st.session_state.local_data_loaded = True
        st.session_state.is_cloud = False
        st.session_state.employees = []
        st.session_state.projects = []
        st.session_state.assignments = []
        st.session_state.recurring_patterns = []
        st.session_state.leaves = []
        st.session_state.evaluations = []
        st.session_state.activity_logs = []
        mark_data_changed()

if 'view_week_date' not in st.session_state:
    st.session_state.view_week_date = date.today()

# --- FAST INDEXING ---
if st.session_state.get('data_dirty', True):
    st.session_state.emp_map = {e['id']: e for e in st.session_state.employees}
    st.session_state.proj_map = {p['id']: p for p in st.session_state.projects}

    assign_date_map = {}
    for a in st.session_state.assignments:
        d = a['date']
        if d not in assign_date_map:
            assign_date_map[d] = []
        assign_date_map[d].append(a)
    st.session_state.assignments_by_date = assign_date_map

    leaves_by_emp = {}
    for l in st.session_state.leaves:
        eid = l['employeeId']
        if eid not in leaves_by_emp:
            leaves_by_emp[eid] = []
        leaves_by_emp[eid].append(l)
    st.session_state.leaves_by_emp = leaves_by_emp
    
    st.session_state.data_dirty = False

# --- Helpers ---
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
    emp_assigns = [a for a in day_assigns if a['employeeId'] == emp_id and a['id'] not in exclude_ids]
    
    allowed_overlap = False
    for ea in emp_assigns:
        ea_s = str(ea['startTime'])[:5]
        ea_e = str(ea['endTime'])[:5]
        if new_s < ea_e and new_e > ea_s:
            if new_e > ea_e:
                allowed_overlap = True
            else:
                return t_start, t_end, True, "Πλήρης επικάλυψη με υπάρχουσα βάρδια (δεν τελειώνει αργότερα)"
    return t_start, t_end, False, "AllowedOverlap" if allowed_overlap else ""

# --- ΑΥΤΟΜΑΤΗ ΕΠΕΚΤΑΣΗ ΕΠΑΝΑΛΑΜΒΑΝΟΜΕΝΩΝ (ΑΝΑ 365 ΗΜΕΡΕΣ / 1 ΕΤΟΣ) ---
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
        
        # Αν δεν βρεθεί παλιά βάρδια (π.χ. σβήστηκαν χειροκίνητα όλες), παίρνουμε την αρχική ημερομηνία έναρξης
        if not latest_date:
            latest_date = pat.get('startDate', today)
            
        # Επέκταση αν λήγει σε λιγότερο από 30 ημέρες (Προσθέτει +365 μέρες)
        if (latest_date - today).days <= 30:
            start_ext_date = latest_date + timedelta(days=1)
            end_ext_date = start_ext_date + timedelta(days=365)
            
            r_type = pat.get('type')
            r_emps = pat.get('employeeIds', [])
            r_proj = pat.get('projectId')
            r_color = pat.get('colorName')
            c_hex = BASIC_COLORS.get(r_color, "#999999")
            r_notes = pat.get('notes', '')
            str_arrival = pat.get('arrivalTime', '')
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
                    if month == 12: month = 1; year += 1
                    else: month += 1
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
                created_for_day = 0
                
                for eid in emps_to_process:
                    if eid:
                        if is_on_leave(eid, d): continue
                        adj_start, adj_end, is_conflict, msg = check_and_resolve_conflict(eid, d, str_start, str_end)
                        if is_conflict: continue
                        
                        new_assign = {
                            'id': str(uuid.uuid4()), 'recurring_id': rid, 'employeeId': eid,
                            'projectId': r_proj, 'date': d, 'arrivalTime': str_arrival,
                            'startTime': adj_start, 'endTime': adj_end, 'colorName': r_color,
                            'colorHex': c_hex, 'notes': r_notes, 'is_cancelled': False, 'cancel_reason': ""
                        }
                        new_assignments_batch.append(new_assign)
                        created_for_day += 1
                    else:
                        new_assign = {
                            'id': str(uuid.uuid4()), 'recurring_id': rid, 'employeeId': "",
                            'projectId': r_proj, 'date': d, 'arrivalTime': str_arrival,
                            'startTime': str_start, 'endTime': str_end, 'colorName': r_color,
                            'colorHex': c_hex, 'notes': r_notes, 'is_cancelled': False, 'cancel_reason': ""
                        }
                        new_assignments_batch.append(new_assign)
                        created_for_day += 1
                
                # Αν όλοι οι επιλεγμένοι υπάλληλοι είχαν άδεια/διπλοκράτηση, δημιουργούμε μια ΚΕΝΗ βάρδια για να μην χαθεί το έργο!
                if created_for_day == 0 and emps_to_process != [""]:
                    new_assign = {
                        'id': str(uuid.uuid4()), 'recurring_id': rid, 'employeeId': "",
                        'projectId': r_proj, 'date': d, 'arrivalTime': str_arrival,
                        'startTime': str_start, 'endTime': str_end, 'colorName': r_color,
                        'colorHex': c_hex, 'notes': r_notes, 'is_cancelled': False, 'cancel_reason': ""
                    }
                    new_assignments_batch.append(new_assign)
                    
    if new_assignments_batch:
        st.session_state.assignments.extend(new_assignments_batch)
        mark_data_changed()
        if supabase:
            with st.status("Αυτόματη Επέκταση Βαρδιών...", expanded=True) as status:
                chunk_size = 50 # Μείωση για απόλυτη ασφάλεια στη μνήμη του server
                has_error = False
                for i in range(0, len(new_assignments_batch), chunk_size):
                    st.write(f"Αποθήκευση βαρδιών {i+1} έως {min(i+chunk_size, len(new_assignments_batch))}...")
                    try:
                        supabase.table('assignments').insert(serialize_dates(new_assignments_batch[i:i+chunk_size])).execute()
                    except Exception as e:
                        st.error(f"Σφάλμα επέκτασης: {e}")
                        has_error = True
                if has_error:
                    status.update(label="Ολοκληρώθηκε με σφάλματα!", state="error", expanded=True)
                else:
                    status.update(label="Η επέκταση ολοκληρώθηκε επιτυχώς!", state="complete", expanded=False)

if "last_auto_extend_check" not in st.session_state or time.time() - st.session_state.last_auto_extend_check > 3600:
    auto_extend_recurring_patterns()
    st.session_state.last_auto_extend_check = time.time()

def go_prev_week():
    st.session_state.view_week_date -= timedelta(days=7)

def go_next_week():
    st.session_state.view_week_date += timedelta(days=7)

def go_to_today():
    st.session_state.view_week_date = date.today()

is_full_admin = st.session_state.get('current_user') != "TAN"
active_employee_ids = [e['id'] for e in st.session_state.employees if e.get('status', 'Ενεργός') == 'Ενεργός']

# --- Sidebar Navigation & Actions ---
st.sidebar.title("STAFF.PRO")
menu_options = ["Ταμπλό Gantt", "Διαχείριση Έργων", "Ομάδα Προσωπικού", "Άδειες", "Σύνολο Αδειών", "Επαναλαμβανόμενες Εργασίες", "Ώρες Εργασιών", "Αξιολόγηση Προσωπικού"]
if st.session_state.get('current_user') == "Admin": menu_options.append("Καταγραφή Κινήσεων")
menu = st.sidebar.radio("Μενού", menu_options)

# Καθαρισμός μνήμης γραφήματος όταν αλλάζουμε σελίδα (Memory Optimization)
if menu != "Ταμπλό Gantt":
    st.session_state.pop('cached_fig', None)
    st.session_state.pop('cached_wk_groups', None)
    st.session_state.pop('cached_export_data', None)
    st.session_state.pop('last_gantt_params', None)

st.sidebar.write("---")
st.sidebar.subheader("Ενέργειες")
col_u, col_r = st.sidebar.columns(2)
with col_u:
    if st.button("↩️ Undo", disabled=len(st.session_state.undo_stack) == 0, use_container_width=True):
        perform_undo()
        st.rerun()
with col_r:
    if st.button("↪️ Redo", disabled=len(st.session_state.redo_stack) == 0, use_container_width=True):
        perform_redo()
        st.rerun()

st.sidebar.write("---")
st.sidebar.subheader("Κατάσταση Συστήματος")

# ΠΑΝΕΞΥΠΝΟΣ ΣΥΓΧΡΟΝΙΣΜΟΣ ΠΡΑΓΜΑΤΙΚΟΥ ΧΡΟΝΟΥ (REAL-TIME FRAGMENT)
@st.fragment(run_every=timedelta(seconds=10))
def render_system_status():
    if st.session_state.get('is_cloud'):
        st.success(f"✅ Cloud Sync (Real-time)")
        if st.button("🔄 Άμεση Ανανέωση", use_container_width=True):
            st.session_state.global_db_ts = "force_refresh"
            st.rerun()
            
        # Εδώ το σύστημα ελέγχει αθόρυβα αν κάποιος άλλος έκανε αλλαγή!
        if supabase:
            try:
                res = supabase.table('activity_logs').select('timestamp').order('timestamp', desc=True).limit(1).execute()
                if res.data:
                    current_latest_ts = res.data[0]['timestamp']
                    my_local_ts = st.session_state.get("global_db_ts")
                    if my_local_ts and my_local_ts not in ["force_refresh", current_latest_ts]:
                        st.session_state.global_db_ts = "force_refresh"
                        st.rerun() # Μόνο τότε ανανεώνει τα πάντα, φέρνοντας τις νέες αλλαγές σε όλους!
            except Exception:
                pass
    else:
        st.error("❌ Εκτός Σύνδεσης (Τοπικά)")
        if not SUPABASE_INSTALLED:
            st.caption("⚠️ **Πρόβλημα:** Λείπει η βιβλιοθήκη 'supabase'. Το Streamlit δεν διάβασε το requirements.txt. Κάνε Reboot την εφαρμογή.")
        elif not HAS_SECRETS:
            st.caption("⚠️ **Πρόβλημα:** Δεν βρέθηκαν τα Secrets (SUPABASE_URL ή SUPABASE_KEY) στις ρυθμίσεις του Streamlit.")
        else:
            st.caption("⚠️ **Πρόβλημα:** Υπήρξε σφάλμα κατά τη σύνδεση ή τη φόρτωση από τη βάση. Ελέγξτε αν έχετε απενεργοποιήσει το RLS σε όλους τους πίνακες.")

# Κλήση της ασύγχρονης συνάρτησης στην Sidebar
render_system_status()


st.sidebar.write("---")
st.sidebar.markdown(f"👤 Συνδεδεμένος ως: **{st.session_state.get('current_user', 'Άγνωστος')}**")
if st.sidebar.button("🚪 Αποσύνδεση", use_container_width=True):
    st.session_state.authenticated = False
    st.session_state.current_user = None
    st.rerun()

# --- ΣΥΣΤΗΜΑ ΕΙΔΟΠΟΙΗΣΕΩΝ (ALERTS) ---
today_date = date.today()
orphan_count = 0
orphan_details = []
for i in range(8):
    check_d = today_date + timedelta(days=i)
    day_assigns = st.session_state.assignments_by_date.get(check_d, [])
    for a in day_assigns:
        if not a.get('employeeId') and not a.get('is_cancelled', False):
            orphan_count += 1
            proj = get_project_info(a['projectId'])
            proj_name = proj['name'] if proj else "Άγνωστο Έργο"
            orphan_details.append(f"• **{check_d.strftime('%d/%m/%Y')}** | Ώρες: {a['startTime'][:5]}-{a['endTime'][:5]} | Έργο: **{proj_name}**")

if orphan_count > 0:
    st.error(f"🚨 **Προσοχή: {orphan_count} βάρδια/ες τις επόμενες 7 ημέρες έμειναν ορφανές (χωρίς προσωπικό)!**")
    with st.expander("👁️ Δείτε αναλυτικά τις ορφανές βάρδιες"):
        for detail in orphan_details: st.markdown(detail)
    st.write("---")

# --- GANTT CACHING FUNCTION ---
@st.cache_data(show_spinner=False, max_entries=5)
def generate_gantt_chart(start_of_week, zoom_factor, presentation_mode, data_version, _assignments_by_date, _leaves, _emp_map, _proj_map):
    """
    Η δημιουργία του Plotly Graph μεταφέρθηκε εδώ.
    Ανασύρει ακαριαία το έτοιμο γράφημα από τη μνήμη, ΕΚΤΟΣ αν αλλάξει το data_version.
    """
    def local_get_emp(eid):
        return _emp_map.get(eid, {}).get('name', 'Άγνωστος') if eid else "Χωρίς Προσωπικό"
    def local_get_proj(pid):
        return _proj_map.get(pid, {})

    data = []
    export_data = [] 
    color_map = {}
    y_category_order = []
    tickvals_map = {}
    empty_shift_annotations = []
    wk_groups = {} 
    day_names_gr = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]

    for i in range(7):
        curr_date = start_of_week + timedelta(days=i)
        day_str = f"{day_names_gr[i]} {curr_date.strftime('%d/%m')}"
        
        leaves_today = []
        for l in _leaves:
            if l['startDate'] <= curr_date <= l['endDate']:
                emp_full = local_get_emp(l['employeeId'])
                emp_parts = emp_full.split()
                emp_n = f"{emp_parts[-1]} {emp_parts[0][0]}." if len(emp_parts) > 1 else emp_full
                
                sub_id = l.get('substituteId')
                if sub_id:
                    sub_full = local_get_emp(sub_id)
                    sub_parts = sub_full.split()
                    sub_n = f"{sub_parts[-1]} {sub_parts[0][0]}." if len(sub_parts) > 1 else sub_full
                    leaves_today.append(f"<b>{emp_n}</b><br><span style='font-size:10px; color:#991b1b;'>↳ Αντικατ: <b>{sub_n}</b></span>")
                else:
                    leaves_today.append(f"<b>{emp_n}</b>")
                    
        leaves_str = "<br><br>".join(leaves_today) if leaves_today else "Καμία"
        if leaves_today:
            base_y_label = f"<b>{day_str}</b><br><span style='font-size:11px; color:#d32f2f;'>Άδειες:<br>{leaves_str}</span>"
        else:
            base_y_label = f"<b>{day_str}</b><br><span style='font-size:11px; color:#d32f2f;'>Άδειες: {leaves_str}</span>"
        
        day_assignments = _assignments_by_date.get(curr_date, [])
        day_row_ids = []
        
        if not day_assignments:
            row_id = f"day_{i}_row_0"
            day_row_ids.append(row_id)
        else:
            # 1. ΑΦΑΙΡΕΣΗ ΔΙΠΛΟΤΥΠΩΝ (GHOST SHIFTS) ΑΠΟ ΤΗΝ ΟΘΟΝΗ
            unique_da = {}
            for da in day_assignments:
                k = f"{da.get('employeeId')}_{da.get('projectId')}_{str(da.get('startTime'))[:5]}_{str(da.get('endTime'))[:5]}"
                unique_da[k] = da
            day_assignments = list(unique_da.values())

            emp_day_assigns = {}
            for da in day_assignments:
                eid = da.get('employeeId')
                if eid:
                    if eid not in emp_day_assigns: emp_day_assigns[eid] = []
                    emp_day_assigns[eid].append(da)
                    
            groups = {}
            for a in day_assignments:
                proj = local_get_proj(a['projectId'])
                c_hex = a.get('colorHex', proj.get('color', "#999999"))
                c_name = a.get('colorName', "Προεπιλογή")
                notes = a.get('notes', '')
                is_canc = a.get('is_cancelled', False)
                c_reason = a.get('cancel_reason', '')
                arrival_time = a.get('arrivalTime', '')
                if arrival_time: arrival_time = arrival_time[:5]
                
                key = f"{curr_date}_{a['projectId']}_{a['startTime']}_{a['endTime']}_{c_hex}_{notes}_{is_canc}_{c_reason}_{arrival_time}"
                if key not in groups:
                    legend_val = f"{proj.get('name', 'Άγνωστο')} ({c_name})"
                    groups[key] = {
                        'Key': key,
                        'ProjectId': a['projectId'],
                        'Date': curr_date,
                        'Project': proj.get('name', 'Άγνωστο'),
                        'ArrivalTime': arrival_time,
                        'StartTime': str(a['startTime'])[:5],
                        'EndTime': str(a['endTime'])[:5],
                        'Start': datetime.combine(datetime(1970, 1, 1), datetime.strptime(str(a['startTime'])[:5], "%H:%M").time()),
                        'End': datetime.combine(datetime(1970, 1, 1), datetime.strptime(str(a['endTime'])[:5], "%H:%M").time()),
                        'Employees': [],
                        'EmployeeIds': [],
                        'AssignmentIds': [],
                        'ColorHex': c_hex,
                        'ColorName': c_name,
                        'Notes': notes,
                        'is_cancelled': is_canc,
                        'cancel_reason': c_reason,
                        'LegendGroup': legend_val
                    }
                
                groups[key]['AssignmentIds'].append(a['id'])
                
                if not a.get('employeeId'):
                    formatted_name = "ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ"
                else:
                    full_name = local_get_emp(a['employeeId'])
                    name_parts = full_name.split()
                    if len(name_parts) > 1:
                        formatted_name = f"{name_parts[-1]} {name_parts[0][0]}."
                    else:
                        formatted_name = full_name
                        
                    prev_assigns = []
                    my_eid = a.get('employeeId')
                    if my_eid in emp_day_assigns:
                        t_a_start_str = str(a['startTime'])[:5]
                        for pa in emp_day_assigns[my_eid]:
                            # 2. ΤΕΛΟΣ ΣΤΟ "ΜΕΤΑ ΑΠΟ ΙΔΙΟ ΕΡΓΟ". Ελέγχει ρητά αν είναι ΑΛΛΟ έργο
                            # και αν τελείωσε νωρίτερα (ή ακριβώς την ίδια ώρα) από το επόμενο!
                            if pa.get('id') != a['id'] and pa.get('projectId') != a['projectId']:
                                t_pa_end_str = str(pa['endTime'])[:5]
                                if t_pa_end_str <= t_a_start_str:
                                    prev_assigns.append(pa)
                                
                    if prev_assigns:
                        # Αν βρέθηκαν πολλά προηγούμενα έργα, πάρε το πιο πρόσφατο!
                        prev_assigns.sort(key=lambda x: str(x['endTime'])[:5], reverse=True)
                        prev_proj = local_get_proj(prev_assigns[0]['projectId'])
                        if prev_proj:
                            formatted_name = f"[ΜΕΤΑ ΑΠΟ '{prev_proj.get('name', 'Άγνωστο')}' {formatted_name}]"
                    
                groups[key]['Employees'].append(formatted_name)
                groups[key]['EmployeeIds'].append(a['employeeId'])

            wk_groups.update(groups)
            non_blue_groups = [g for g in groups.values() if g['ColorHex'].lower() != "#4a86e8"]
            blue_groups = [g for g in groups.values() if g['ColorHex'].lower() == "#4a86e8"]
            
            non_blue_lanes = [] 
            group_row_mapping = []
            
            for g in sorted(non_blue_groups, key=lambda x: x['Start']):
                placed = False
                for lane_idx, lane_end in enumerate(non_blue_lanes):
                    if g['Start'] >= lane_end:
                        row_idx = lane_idx
                        non_blue_lanes[lane_idx] = g['End']
                        placed = True
                        break
                if not placed:
                    non_blue_lanes.append(g['End'])
                    row_idx = len(non_blue_lanes) - 1
                group_row_mapping.append((g, row_idx))

            num_non_blue_lanes = len(non_blue_lanes)
            blue_lanes = []
            for g in sorted(blue_groups, key=lambda x: x['Start']):
                placed = False
                for lane_idx, lane_end in enumerate(blue_lanes):
                    if g['Start'] >= lane_end:
                        row_idx = lane_idx
                        blue_lanes[lane_idx] = g['End']
                        placed = True
                        break
                if not placed:
                    blue_lanes.append(g['End'])
                    row_idx = len(blue_lanes) - 1
                group_row_mapping.append((g, row_idx + num_non_blue_lanes))

            for g, row_idx in group_row_mapping:
                row_id = f"day_{i}_row_{row_idx}"
                if row_id not in day_row_ids:
                    day_row_ids.append(row_id)
                
                emps_str = ", ".join(g['Employees']).upper()
                proj_name = g['Project'].upper()
                arrival_str = f"[Προσ: {g['ArrivalTime']}] " if g['ArrivalTime'] else ""
                times_str = f"{arrival_str}{g['StartTime']}-{g['EndTime']}"
                base_text = f"{times_str} {proj_name} // {emps_str}"
                if g['Notes']:
                    base_text += f" ({g['Notes'].upper()})"
                    
                duration_hours = (g['End'] - g['Start']).total_seconds() / 3600.0
                wrap_w = max(15, int(duration_hours * 16))
                wrapped_base = "<br>".join(textwrap.wrap(base_text, width=wrap_w))
                
                if "ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ" in emps_str:
                    empty_shift_annotations.append(dict(
                        x=g['End'], y=row_id, text="🔴", showarrow=False, xanchor='right', yanchor='middle',
                        xshift=-4, yshift=int(28 * zoom_factor), font=dict(size=max(10, int(14 * zoom_factor)))
                    ))
                
                if g['is_cancelled']:
                    label_text = f"<s>{wrapped_base}</s>"
                    if g['cancel_reason']:
                        wrapped_reason = "<br>".join(textwrap.wrap(f"[{g['cancel_reason'].upper()}]", width=wrap_w))
                        label_text += f"<br><span style='color:#dc2626;'><b>{wrapped_reason}</b></span>"
                else:
                    label_text = wrapped_base
                    
                data.append({
                    'Y_Axis': row_id,
                    'Έργο': g['Project'],
                    'Έναρξη': g['Start'],
                    'Λήξη': g['End'],
                    'Προσωπικό': ", ".join(g['Employees']),
                    'Προσέλευση': g['ArrivalTime'] if g['ArrivalTime'] else "-",
                    'Παρατηρήσεις': g['Notes'],
                    'Ετικέτα': label_text,
                    'LegendGroup': g['LegendGroup'],
                    'ColorHex': g['ColorHex'],
                    'GroupKey': g['Key']
                })
                
                export_data.append({
                    'Ημερομηνία': curr_date.strftime('%d/%m/%Y'),
                    'Ημέρα': day_names_gr[i],
                    'Έργο': g['Project'],
                    'Προσωπικό': ", ".join(g['Employees']),
                    'Ώρα Προσέλευσης': g['ArrivalTime'] if g['ArrivalTime'] else "-",
                    'Ώρα Έναρξης': g['StartTime'],
                    'Ώρα Λήξης': g['EndTime'],
                    'Παρατηρήσεις': g['Notes'],
                    'Ακυρωμένο': 'ΝΑΙ' if g['is_cancelled'] else 'ΟΧΙ',
                    'Λόγος Ακύρωσης': g['cancel_reason']
                })
                color_map[g['LegendGroup']] = g['ColorHex']
                
        y_category_order.extend(day_row_ids)
        mid_idx = len(day_row_ids) // 2
        for idx, rid in enumerate(day_row_ids):
            tickvals_map[rid] = base_y_label if idx == mid_idx else ""
            
    # --- ΠΡΟΣΘΗΚΗ ΑΟΡΑΤΟΥ ΦΟΝΤΟΥ ΓΙΑ ΔΟΜΗ ΚΑΙ ΑΠΟΕΠΙΛΟΓΗ ---
    bg_data = []
    for rid in y_category_order:
        bg_data.append({
            'Y_Axis': rid,
            'Έργο': 'Κενό',
            'Έναρξη': datetime(1970, 1, 1, 0, 0),
            'Λήξη': datetime(1970, 1, 1, 23, 59),
            'Προσωπικό': '',
            'Προσέλευση': '',
            'Παρατηρήσεις': '',
            'Ετικέτα': '',
            'LegendGroup': 'Κενό',
            'ColorHex': 'rgba(0,0,0,0)',
            'GroupKey': 'Empty'
        })
    color_map['Κενό'] = 'rgba(0,0,0,0)'
    data = bg_data + data

    df = pd.DataFrame(data)
    ordered_categories = y_category_order[::-1]
    
    if df.empty:
        fig = px.timeline()
    else:
        fig = px.timeline(
            df, x_start="Έναρξη", x_end="Λήξη", y="Y_Axis", color="LegendGroup",
            color_discrete_map=color_map, custom_data=["GroupKey"], text="Ετικέτα"
        )
    
    for di in range(7):
        day_idxs = [idx for idx, val in enumerate(ordered_categories) if val.startswith(f"day_{di}_")]
        if day_idxs:
            mn, mx = min(day_idxs), max(day_idxs)
            if di % 2 != 0:
                fig.add_hrect(y0=mn-0.5, y1=mx+0.5, fillcolor="rgba(0, 0, 0, 0.05)", opacity=1, layer="below", line_width=0)
            if (start_of_week + timedelta(days=di)) == date.today():
                fig.add_hrect(y0=mn-0.5, y1=mx+0.5, fillcolor="#b2d8ce", opacity=1, layer="below", line_width=0)

    for idx in range(len(ordered_categories) - 1):
        if ordered_categories[idx].split('_')[1] != ordered_categories[idx+1].split('_')[1]:
            fig.add_shape(type="line", x0=0, x1=1, xref="paper", y0=idx+0.5, y1=idx+0.5, yref="y", line=dict(color="#000000", width=4))

    row_h = 55 * zoom_factor
    visible_count = 650 / row_h
    
    if presentation_mode or len(ordered_categories) <= visible_count:
        dyn_h = max(500, int(len(ordered_categories) * row_h) + 100)
        y_range = None
    else:
        dyn_h = 750
        offset = (date.today() - start_of_week).days
        if 0 <= offset <= 6:
            idxs = [idx for idx, val in enumerate(ordered_categories) if val.startswith(f"day_{offset}_")]
            if idxs:
                mid = sum(idxs) / len(idxs)
                y_range = [max(-0.5, mid - visible_count/2), min(len(ordered_categories)-0.5, mid + visible_count/2)]
            else:
                y_range = [len(ordered_categories) - visible_count - 0.5, len(ordered_categories) - 0.5]
        else:
            y_range = [len(ordered_categories) - visible_count - 0.5, len(ordered_categories) - 0.5]

    fig.update_yaxes(
        categoryorder='array', categoryarray=ordered_categories, tickmode='array', 
        tickvals=ordered_categories, ticktext=[tickvals_map[v] for v in ordered_categories],
        showgrid=True, gridcolor='rgba(0,0,0,0.1)', gridwidth=1 
    )
    
    fig.update_traces(
        textposition='inside', insidetextanchor='middle',
        textfont=dict(color='black', size=max(8, int(9*zoom_factor)), family="Arial Black, Arial, sans-serif"),
        marker=dict(line=dict(color='black', width=1)), textangle=0, constraintext='none',
        hoverinfo='none', hovertemplate=None,
        selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=1))
    )
    
    # Εξαφάνιση hoverinfo για το αόρατο κενό φόντο
    for trace in fig.data:
        if trace.name == 'Κενό':
            trace.marker.line.width = 0
            trace.hoverinfo = 'skip'
    
    fig.update_layout(
        bargap=0.12, showlegend=False, plot_bgcolor='#dbece8', paper_bgcolor='#ffffff', height=dyn_h, 
        margin=dict(l=10, r=10, t=50, b=10), annotations=empty_shift_annotations, 
        dragmode="pan", clickmode="event+select", uirevision="constant", 
        xaxis=dict(
            side='top', tickmode='linear', tick0=datetime(1970, 1, 1, 0, 0),
            dtick=1800000, tickformat="%H:%M", showgrid=True, gridcolor='black',
            gridwidth=1, range=[datetime(1970, 1, 1, 6, 0), datetime(1970, 1, 1, 17, 0)],
            title="", tickfont=dict(size=max(8, int(11 * zoom_factor)), color="black", family="Arial"),
            fixedrange=False, rangeslider=dict(visible=False) 
        ),
        yaxis=dict(title="", tickfont=dict(size=max(8, int(12 * zoom_factor)), color="black"), fixedrange=False, range=y_range)
    )
    return fig, wk_groups, export_data


# --- FRAGMENTS ΓΙΑ ΚΑΤΑΧΩΡΗΣΕΙΣ ---
@st.fragment
def render_quick_add(selected_date, qa_rc):
    with st.form("quick_add", clear_on_submit=True):
        add_date = st.date_input("Ημερομηνία", value=selected_date, key=f"qa_date_{qa_rc}")
        
        proj_choice = st.selectbox("Επιλογή Έργου (Από Λίστα)", options=[p['id'] for p in st.session_state.projects], 
                                 format_func=get_project_name, key=f"qa_proj_{qa_rc}")
        
        custom_proj_name = st.text_input("Ή πληκτρολογήστε Νέο Έργο (Αν συμπληρωθεί, αγνοεί την παραπάνω λίστα)", key=f"qa_cproj_{qa_rc}")
        
        emp_choices = st.multiselect("Προσωπικό (Προαιρετικό - Μόνο Ενεργοί)", options=active_employee_ids,
                                   format_func=get_employee_name, key=f"qa_emps_{qa_rc}")
        
        c_color, c_notes = st.columns(2)
        with c_color:
            color_choice = st.selectbox("Χρώμα Μπάρας", options=list(BASIC_COLORS.keys()), key=f"qa_color_{qa_rc}")
        with c_notes:
            add_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", key=f"qa_notes_{qa_rc}")
        
        c_arr, c_start, c_end = st.columns(3)
        with c_arr:
            use_arr = st.checkbox("Προσέλευση;", key=f"chk_arr_{qa_rc}")
            t_arrival = st.time_input("Ώρα Προσέλευσης", value=datetime.strptime("08:00", "%H:%M").time(), key=f"qa_arrival_{qa_rc}")
        with c_start:
            t_start = st.time_input("Έναρξη", value=datetime.strptime("09:00", "%H:%M").time(), key=f"qa_start_{qa_rc}")
        with c_end:
            t_end = st.time_input("Λήξη", value=datetime.strptime("17:00", "%H:%M").time(), key=f"qa_end_{qa_rc}")
            
        if st.form_submit_button("Καταχώρηση"):
            str_arrival = t_arrival.strftime("%H:%M") if use_arr else ""
            str_start = t_start.strftime("%H:%M")
            str_end = t_end.strftime("%H:%M")
            
            if str_start >= str_end:
                st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
            elif not custom_proj_name.strip() and not proj_choice:
                st.error("Παρακαλώ επιλέξτε ή πληκτρολογήστε ένα Έργο.")
            else:
                emps_to_process = emp_choices if emp_choices else [""]
                errors = []
                valid_assignments = []
                
                for eid in emps_to_process:
                    if eid:
                        emp_name = get_employee_name(eid)
                        if is_on_leave(eid, add_date):
                            errors.append(f"Ο/Η {emp_name} βρίσκεται σε άδεια στις {add_date.strftime('%d/%m')}.")
                            st.toast(f"🛑 Αδύνατη ανάθεση: Ο/Η {emp_name} έχει άδεια!", icon="🛑")
                        else:
                            adj_start, adj_end, is_conflict, msg = check_and_resolve_conflict(eid, add_date, str_start, str_end)
                            if is_conflict:
                                errors.append(f"⚠️ ΔΙΠΛΟΚΡΑΤΗΣΗ: Ο/Η {emp_name} έχει ήδη άλλη βάρδια που συμπίπτει ({str_start} - {str_end}).")
                                st.toast(f"🚨 Προσοχή: Διπλοκράτηση για τον/την {emp_name}!", icon="🚨")
                            else:
                                valid_assignments.append({'eid': eid, 'start': adj_start, 'end': adj_end, 'msg': msg, 'emp_name': emp_name})
                    else:
                        valid_assignments.append({'eid': "", 'start': str_start, 'end': str_end, 'msg': "", 'emp_name': ""})
                
                if errors:
                    for err in errors: st.error(err)
                else:
                    if custom_proj_name.strip():
                        final_proj_id = str(uuid.uuid4())
                        new_p = {'id': final_proj_id, 'name': custom_proj_name.strip(), 'color': BASIC_COLORS[color_choice]}
                        st.session_state.projects.append(new_p)
                        db_insert('projects', new_p, track=False)
                    else:
                        final_proj_id = proj_choice
                        
                    new_assigns = []
                    for va in valid_assignments:
                        if va['msg'] == "AllowedOverlap":
                            st.toast(f"ℹ️ Επιτράπηκε επικάλυψη ωραρίου για τον/την {va['emp_name']}.", icon="ℹ️")
                            
                        new_assign = {
                            'id': str(uuid.uuid4()),
                            'employeeId': va['eid'],
                            'projectId': final_proj_id,
                            'date': add_date,
                            'arrivalTime': str_arrival,
                            'startTime': va['start'],
                            'endTime': va['end'],
                            'colorName': color_choice,
                            'colorHex': BASIC_COLORS[color_choice],
                            'notes': add_notes,
                            'is_cancelled': False,
                            'cancel_reason': "",
                            'recurring_id': None
                        }
                        new_assigns.append(new_assign)
                        st.session_state.assignments.append(new_assign)
                    
                    db_insert("assignments", new_assigns, track=False)
                    st.success("Η ανάθεση ολοκληρώθηκε!")
                    st.session_state.qa_rc += 1
                    st.rerun()

@st.fragment
def render_edit_assignment(target_group, edit_date, default_proj_idx, proj_ids):
    # ΓΡΗΓΟΡΗ ΜΕΤΑΚΙΝΗΣΗ (Εκτός φόρμας)
    st.markdown("⚡ **Γρήγορη Μετακίνηση** (Αντί για Drag & Drop)")
    qm_c1, qm_c2, qm_c3, qm_c4 = st.columns(4)
    move_m_day = qm_c1.button("⬅️ -1 Μέρα", use_container_width=True)
    move_p_day = qm_c2.button("➡️ +1 Μέρα", use_container_width=True)
    move_m_hour = qm_c3.button("⏪ -1 Ώρα", use_container_width=True)
    move_p_hour = qm_c4.button("⏩ +1 Ώρα", use_container_width=True)
    
    if any([move_m_day, move_p_day, move_m_hour, move_p_hour]):
        delta_days = -1 if move_m_day else (1 if move_p_day else 0)
        delta_hours = -1 if move_m_hour else (1 if move_p_hour else 0)
        has_error = False
        new_assigns = []
        old_assigns = []
        
        for a_id in target_group['AssignmentIds']:
            orig_a = next(a for a in st.session_state.assignments if a['id'] == a_id)
            new_a = dict(orig_a)
            if delta_days != 0: new_a['date'] = orig_a['date'] + timedelta(days=delta_days)
            if delta_hours != 0:
                dummy_date = datetime(2000, 1, 1)
                s_dt = datetime.combine(dummy_date, datetime.strptime(str(orig_a['startTime'])[:5], "%H:%M").time())
                e_dt = datetime.combine(dummy_date, datetime.strptime(str(orig_a['endTime'])[:5], "%H:%M").time())
                new_s_dt = s_dt + timedelta(hours=delta_hours)
                new_e_dt = e_dt + timedelta(hours=delta_hours)
                if new_s_dt.date() != dummy_date.date() or new_e_dt.date() != dummy_date.date():
                    st.error("Η αλλαγή ώρας ξεπερνάει τα όρια της ημέρας.")
                    has_error = True
                    break
                new_a['startTime'] = new_s_dt.strftime("%H:%M")
                new_a['endTime'] = new_e_dt.strftime("%H:%M")
                if orig_a.get('arrivalTime'):
                    arr_dt = datetime.combine(dummy_date, datetime.strptime(str(orig_a['arrivalTime'])[:5], "%H:%M").time())
                    new_a['arrivalTime'] = (arr_dt + timedelta(hours=delta_hours)).strftime("%H:%M")
                
            if new_a['employeeId']:
                emp_name = get_employee_name(new_a['employeeId'])
                if is_on_leave(new_a['employeeId'], new_a['date']):
                    st.toast(f"🛑 Αδύνατη μετακίνηση: Ο/Η {emp_name} έχει άδεια!", icon="🛑")
                    has_error = True
                    break
                adj_start, adj_end, is_conflict, msg = check_and_resolve_conflict(new_a['employeeId'], new_a['date'], new_a['startTime'], new_a['endTime'], exclude_ids=target_group['AssignmentIds'])
                if is_conflict:
                    st.toast(f"🚨 Αδύνα μετακίνηση: Διπλοκράτηση {emp_name}!", icon="🚨")
                    has_error = True
                    break
                new_a['startTime'], new_a['endTime'] = adj_start, adj_end
                if msg == "AllowedOverlap": st.toast(f"ℹ️ Επιτράπηκε επικάλυψη ωραρίου ({emp_name}).", icon="ℹ️")
            old_assigns.append(orig_a)
            new_assigns.append(new_a)
            
        if not has_error:
            for old_a, new_a in zip(old_assigns, new_assigns):
                db_update('assignments', new_a['id'], new_a, old_data=old_a, track=False)
            st.session_state.assignments = [a for a in st.session_state.assignments if a['id'] not in target_group['AssignmentIds']]
            st.session_state.assignments.extend(new_assigns)
            st.rerun()

    with st.form("quick_edit"):
        edit_date_val = st.date_input("Αλλαγή Ημερομηνίας", value=edit_date)
        edit_proj = st.selectbox("Αλλαγή Έργου (Από Λίστα)", options=proj_ids, index=default_proj_idx, format_func=get_project_name)
        edit_custom_proj_name = st.text_input("Ή πληκτρολογήστε Νέο Έργο (προαιρετικό)")
        
        valid_emp_ids = [eid for eid in target_group['EmployeeIds'] if eid]
        edit_options = list(set(active_employee_ids + valid_emp_ids))
        edit_emps = st.multiselect("Αλλαγή Προσωπικού (Προαιρετικό)", options=edit_options, default=valid_emp_ids, format_func=get_employee_name)
        
        e_color_col, e_notes_col = st.columns(2)
        with e_color_col:
            default_color_idx = list(BASIC_COLORS.keys()).index(target_group['ColorName']) if target_group['ColorName'] in BASIC_COLORS else 0
            edit_color = st.selectbox("Αλλαγή Χρώματος", options=list(BASIC_COLORS.keys()), index=default_color_idx)
        with e_notes_col:
            edit_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", value=target_group['Notes'])

        e_arr, e_start, e_end = st.columns(3)
        existing_arr = target_group.get('ArrivalTime', '')
        with e_arr:
            use_arr_edit = st.checkbox("Με Προσέλευση", value=bool(existing_arr), key="edit_use_arr")
            def_arr = datetime.strptime(existing_arr, "%H:%M").time() if existing_arr else datetime.strptime(str(target_group['StartTime'])[:5], "%H:%M").time()
            new_t_arrival = st.time_input("Ώρα Προσ.", value=def_arr, key="edit_arrival_time")
        with e_start:
            new_t_start = st.time_input("Νέα Έναρξη", value=datetime.strptime(str(target_group['StartTime'])[:5], "%H:%M").time())
        with e_end:
            new_t_end = st.time_input("Νέα Λήξη", value=datetime.strptime(str(target_group['EndTime'])[:5], "%H:%M").time())
            
        st.markdown("---")
        st.write("🛑 **Ακύρωση / Διαγραφή Βάρδιας (Διαγράμμιση)**")
        c_canc1, c_canc2 = st.columns([1, 2])
        with c_canc1:
            e_is_cancelled = st.checkbox("Επισήμανση ως Ακυρωμένη", value=target_group.get('is_cancelled', False))
        with c_canc2:
            e_cancel_reason = st.text_input("Λόγος Ακύρωσης (Συμπληρώστε αν ακυρώνετε)", value=target_group.get('cancel_reason', ''))
        st.markdown("---")
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            save_edit = st.form_submit_button("💾 Αποθήκευση")
        with col_btn2:
            del_edit = st.form_submit_button("🗑️ Οριστική Διαγραφή Μπάρας")
            
        if del_edit:
            old_assigns = [a for a in st.session_state.assignments if a['id'] in target_group['AssignmentIds']]
            st.session_state.assignments = [a for a in st.session_state.assignments if a['id'] not in target_group['AssignmentIds']]
            db_delete_in('assignments', 'id', target_group['AssignmentIds'], deleted_records=old_assigns)
            st.rerun()
            
        if save_edit:
            str_arrival = new_t_arrival.strftime("%H:%M") if use_arr_edit else ""
            str_start = new_t_start.strftime("%H:%M")
            str_end = new_t_end.strftime("%H:%M")
            if str_start >= str_end:
                st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
            elif not edit_custom_proj_name.strip() and not edit_proj:
                st.error("Παρακαλώ επιλέξτε ή πληκτρολογήστε ένα Έργο.")
            else:
                emps_to_process = edit_emps if edit_emps else [""]
                errors = []
                valid_assignments = []
                for eid in emps_to_process:
                    if eid:
                        emp_name = get_employee_name(eid)
                        if is_on_leave(eid, edit_date_val):
                            errors.append(f"Ο/Η {emp_name} βρίσκεται σε άδεια στις {edit_date_val.strftime('%d/%m')}.")
                            st.toast(f"🛑 Αδύνατη ανάθεση: Ο/Η {emp_name} έχει άδεια!", icon="🛑")
                        else:
                            adj_start, adj_end, is_conflict, msg = check_and_resolve_conflict(eid, edit_date_val, str_start, str_end, exclude_ids=target_group['AssignmentIds'])
                            if is_conflict:
                                errors.append(f"⚠️ ΔΙΠΛΟΚΡΑΤΗΣΗ: Ο/Η {emp_name} έχει ήδη άλλη βάρδια που συμπίπτει.")
                                st.toast(f"🚨 Προσοχή: Διπλοκράτηση για τον/την {emp_name}!", icon="🚨")
                            else:
                                valid_assignments.append({'eid': eid, 'start': adj_start, 'end': adj_end, 'msg': msg, 'emp_name': emp_name})
                    else:
                        valid_assignments.append({'eid': "", 'start': str_start, 'end': str_end, 'msg': "", 'emp_name': ""})
                
                if errors:
                    for err in errors: st.error(err)
                else:
                    if edit_custom_proj_name.strip():
                        final_edit_proj_id = str(uuid.uuid4())
                        new_p = {'id': final_edit_proj_id, 'name': edit_custom_proj_name.strip(), 'color': BASIC_COLORS[edit_color]}
                        st.session_state.projects.append(new_p)
                        db_insert('projects', new_p, track=False)
                    else:
                        final_edit_proj_id = edit_proj
                        
                    old_assigns = [a for a in st.session_state.assignments if a['id'] in target_group['AssignmentIds']]
                    st.session_state.assignments = [a for a in st.session_state.assignments if a['id'] not in target_group['AssignmentIds']]
                    db_delete_in('assignments', 'id', target_group['AssignmentIds'], track=False)
                    
                    new_assigns = []
                    for va in valid_assignments:
                        if va['msg'] == "AllowedOverlap": st.toast(f"ℹ️ Επιτράπηκε επικάλυψη ωραρίου: {va['emp_name']} ({va['start']})", icon="ℹ️")
                        new_a = {
                            'id': str(uuid.uuid4()), 'employeeId': va['eid'], 'projectId': final_edit_proj_id,
                            'date': edit_date_val, 'arrivalTime': str_arrival, 'startTime': va['start'], 'endTime': va['end'],
                            'colorName': edit_color, 'colorHex': BASIC_COLORS[edit_color], 'notes': edit_notes,
                            'is_cancelled': e_is_cancelled, 'cancel_reason': e_cancel_reason if e_is_cancelled else "", 'recurring_id': None 
                        }
                        new_assigns.append(new_a)
                        st.session_state.assignments.append(new_a)
                    db_insert('assignments', new_assigns, track=False)
                    st.rerun()

# --- ΚΛΗΣΗ ΓΡΑΦΗΜΑΤΟΣ (ΜΟΝΟ ΟΤΑΝ ΕΙΝΑΙ ΣΤΗ ΣΕΛΙΔΑ) ---
if menu == "Ταμπλό Gantt":
    st.title("📅 Εβδομαδιαίο Χρονοδιάγραμμα Πόρων")
    
    col_nav1, col_date, col_nav2, col_today, col_zoom, col_pres = st.columns([1, 2, 1, 1, 2, 2.5])
    with col_nav1:
        st.write("")
        st.button("⬅️ Προηγούμενη", on_click=go_prev_week, use_container_width=True)
    with col_date:
        selected_date = st.date_input("Επιλογή Εβδομάδας", key="view_week_date")
        start_of_week = selected_date - timedelta(days=selected_date.weekday())
    with col_nav2:
        st.write("")
        st.button("Επόμενη ➡️", on_click=go_next_week, use_container_width=True)
    with col_today:
        st.write("")
        st.button("🏠 Σήμερα", on_click=go_to_today, use_container_width=True)
    with col_zoom:
        zoom_level = st.slider("🔍 Ζουμ Διαγράμματος (%)", min_value=50, max_value=200, value=100, step=5)
    with col_pres:
        st.write("")
        st.write("")
        presentation_mode = st.checkbox("🖥️ Λειτουργία Πλήρους Προβολής")
        
    zoom_factor = zoom_level / 100.0
    
    current_gantt_params = {
        "week": start_of_week,
        "zoom": zoom_factor,
        "presentation": presentation_mode,
        "local_version": st.session_state.get('local_gantt_version', 0)
    }
    
    fig, wk_groups, export_data = generate_gantt_chart(
        start_of_week, zoom_factor, presentation_mode, st.session_state.get('local_gantt_version', 0),
        st.session_state.assignments_by_date, st.session_state.leaves, st.session_state.emp_map, st.session_state.proj_map
    )
    
    st.session_state.cached_fig = fig
    st.session_state.cached_wk_groups = wk_groups
    st.session_state.cached_export_data = export_data
    st.session_state.last_gantt_params = current_gantt_params
    
    clicked_key = None
    try:
        # Δυναμικό κλειδί (key) που αναγκάζει το γράφημα να "ανανεώνεται" τέλεια όταν σβήνεις/προσθέτεις κάτι.
        chart_key = f"gantt_chart_{st.session_state.get('local_gantt_version', 0)}"
        event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", selection_mode="points", config={"displayModeBar": False}, key=chart_key)
        if event and "selection" in event:
            if event["selection"].get("points"):
                cd = event["selection"]["points"][0].get("customdata", [None])[0]
                if cd != "Empty":
                    clicked_key = cd
            else:
                clicked_key = None
    except Exception:
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    
    hint_text = "💡 *Συμβουλές:* **1)** Κλικ σε μια μπάρα για επεξεργασία. **2)** Κλικ στο κενό (ή σε άλλη μέρα) για αποεπιλογή. **3)** Σύρετε πάνω-κάτω. **4)** Ζουμ από τη μπάρα."
    
    if export_data:
        col_hint, col_btn = st.columns([3, 1])
        with col_hint: st.caption(hint_text)
        with col_btn:
            df_export = pd.DataFrame(export_data)
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_export.to_excel(writer, index=False, sheet_name='Πρόγραμμα')
            st.download_button(label="📥 Εξαγωγή (Excel)", data=buffer.getvalue(), file_name=f"Gantt_{start_of_week.strftime('%d_%m_%Y')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    else:
        st.caption(hint_text)

    if not presentation_mode:
        st.divider()
        if is_full_admin:
            col_add, col_edit = st.columns(2)
            with col_add:
                st.subheader("➕ Νέα Τοποθέτηση")
                if "qa_rc" not in st.session_state: st.session_state.qa_rc = 0
                render_quick_add(selected_date, st.session_state.qa_rc)

            with col_edit:
                st.subheader("✏️ Επεξεργασία Μπάρας της Εβδομάδας")
                if not wk_groups:
                    st.info("Δεν υπάρχουν μπάρες για επεξεργασία αυτή την εβδομάδα.")
                else:
                    group_keys = list(wk_groups.keys())
                    group_keys.sort(key=lambda k: (wk_groups[k]['Date'], wk_groups[k]['StartTime']))
                    
                    default_idx = 0
                    if clicked_key and clicked_key in group_keys:
                        default_idx = group_keys.index(clicked_key) + 1
                    
                    selected_key = st.selectbox(
                        "Επιλέξτε Μπάρα (Ημέρα & Έργο)", 
                        options=[""] + group_keys,
                        index=default_idx,
                        format_func=lambda x: "Επιλέξτε..." if x == "" else f"{wk_groups[x]['Date'].strftime('%d/%m')} - {wk_groups[x]['Project']} ({wk_groups[x]['StartTime']}-{wk_groups[x]['EndTime']})"
                    )
                    
                    if selected_key != "":
                        target_group = wk_groups[selected_key]
                        proj_ids = [p['id'] for p in st.session_state.projects]
                        default_proj_idx = proj_ids.index(target_group['ProjectId']) if target_group['ProjectId'] in proj_ids else 0
                        render_edit_assignment(target_group, target_group['Date'], default_proj_idx, proj_ids)

# --- VIEW: PROJECTS ---
elif menu == "Διαχείριση Έργων":
    st.title("🏗️ Έργα")
    
    @st.fragment
    def render_new_project():
        with st.form("new_project_form", clear_on_submit=True):
            p_name = st.text_input("Όνομα Έργου")
            p_color = st.color_picker("Χρώμα (Προεπιλογή)", "#4a86e8")
            if st.form_submit_button("Δημιουργία"):
                new_p = {'id': str(uuid.uuid4()), 'name': p_name, 'color': p_color}
                st.session_state.projects.append(new_p)
                db_insert('projects', new_p)
                st.rerun()

    if is_full_admin:
        with st.expander("Νέο Έργο"):
            render_new_project()
    else:
        st.info("⚠️ Έχετε πρόσβαση μόνο για προβολή στα Έργα.")
            
    for p in st.session_state.projects:
        col1, col2 = st.columns([4, 1])
        col1.write(f"**{p['name']}**")
        if is_full_admin:
            if col2.button("Διαγραφή", key=p['id']):
                st.session_state.projects = [proj for proj in st.session_state.projects if proj['id'] != p['id']]
                db_delete('projects', 'id', p['id'], deleted_records=[p])
                st.rerun()

# --- VIEW: EMPLOYEES ---
elif menu == "Ομάδα Προσωπικού":
    st.title("👥 Προσωπικό")
    
    tab_list, tab_add, tab_edit, tab_import = st.tabs(["📋 Λίστα Υπαλλήλων", "➕ Προσθήκη Υπαλλήλου", "✏️ Επεξεργασία", "📥 Εισαγωγή από Αρχείο"])
    
    with tab_add:
        if "emp_reset_counter" not in st.session_state: st.session_state.emp_reset_counter = 0
        erc = st.session_state.emp_reset_counter

        c1, c2, c3 = st.columns(3)
        with c1:
            e_name = st.text_input("Ονοματεπώνυμο", key=f"new_emp_name_{erc}")
            e_pos = st.selectbox("Θέση", ["ΕΡΓΑΤΗΣ", "ΕΠΟΠΤΗΣ", "ΟΔΗΓΟΣ"], key=f"new_emp_pos_{erc}")
        with c2:
            e_id_num = st.text_input("Αριθμός Ταυτότητας", key=f"new_emp_id_{erc}")
            e_phone = st.text_input("Κινητό Τηλέφωνο", key=f"new_emp_phone_{erc}")
        with c3:
            e_status = st.selectbox("Κατάσταση", ["Ενεργός", "Ανενεργός"], key=f"new_emp_status_{erc}")
            
        st.write("")
        col_btn1, col_btn2 = st.columns([1, 1])
        with col_btn1:
            submit_emp = st.button("Προσθήκη Υπαλλήλου", type="primary", use_container_width=True)
        with col_btn2:
            clear_emp = st.button("🧹 Καθαρισμός", key="btn_clear_emp", use_container_width=True)
            
        if clear_emp:
            st.session_state.emp_reset_counter += 1
            st.rerun()
            
        if submit_emp:
            if not e_name.strip():
                st.error("Το πεδίο 'Ονοματεπώνυμο' είναι υποχρεωτικό.")
            else:
                is_duplicate = False
                for emp in st.session_state.employees:
                    if emp['name'].strip().lower() == e_name.strip().lower():
                        st.error(f"Ο/Η υπάλληλος '{emp['name']}' υπάρχει ήδη στη λίστα.")
                        is_duplicate = True
                        break
                    if e_id_num.strip() and emp.get('id_number', '').strip().lower() == e_id_num.strip().lower():
                        st.error(f"Ο Αριθμός Ταυτότητας '{e_id_num}' ανήκει ήδη στον/στην '{emp['name']}'.")
                        is_duplicate = True
                        break

                if not is_duplicate:
                    new_e = {
                        'id': str(uuid.uuid4()), 
                        'name': e_name.strip(), 
                        'position': e_pos.strip(),
                        'id_number': e_id_num.strip(),
                        'phone': e_phone.strip(),
                        'status': e_status
                    }
                    st.session_state.employees.append(new_e)
                    db_insert('employees', new_e)
                    st.success(f"Ο/Η '{e_name.strip()}' προστέθηκε με επιτυχία! Η σελίδα ανανεώνεται...")
                    time.sleep(1.5)
                    st.session_state.emp_reset_counter += 1
                    st.rerun()
    
    with tab_edit:
        if not st.session_state.employees:
            st.info("Δεν υπάρχουν υπάλληλοι προς επεξεργασία.")
        else:
            emp_to_edit_id = st.selectbox("Επιλέξτε Υπάλληλο για Επεξεργασία", 
                                          options=[e['id'] for e in st.session_state.employees],
                                          format_func=get_employee_name)
            
            emp_to_edit = next(e for e in st.session_state.employees if e['id'] == emp_to_edit_id)
            
            with st.form("edit_emp", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                with c1:
                    ed_name = st.text_input("Ονοματεπώνυμο", value=emp_to_edit['name'])
                    
                    pos_options = ["ΕΡΓΑΤΗΣ", "ΕΠΟΠΤΗΣ", "ΟΔΗΓΟΣ"]
                    current_pos = emp_to_edit.get('position', 'ΕΡΓΑΤΗΣ')
                    pos_index = pos_options.index(current_pos) if current_pos in pos_options else 0
                    ed_pos = st.selectbox("Θέση", pos_options, index=pos_index)
                    
                with c2:
                    ed_id_num = st.text_input("Αριθμός Ταυτότητας", value=emp_to_edit.get('id_number', ''))
                    ed_phone = st.text_input("Κινητό Τηλέφωνο", value=emp_to_edit.get('phone', ''))
                with c3:
                    current_status = emp_to_edit.get('status', 'Ενεργός')
                    ed_status = st.selectbox("Κατάσταση", ["Ενεργός", "Ανενεργός"], index=0 if current_status == 'Ενεργός' else 1)
                    
                if st.form_submit_button("💾 Αποθήκευση Αλλαγών", type="primary"):
                    if not ed_name.strip():
                        st.error("Το πεδίο 'Ονοματεπώνυμο' είναι υποχρεωτικό.")
                    else:
                        is_dup = False
                        for e in st.session_state.employees:
                            if e['id'] != emp_to_edit_id:
                                if e['name'].strip().lower() == ed_name.strip().lower():
                                    st.error("Υπάρχει ήδη άλλος υπάλληλος με αυτό το όνομα.")
                                    is_dup = True
                                    break
                                elif ed_id_num.strip() and e.get('id_number', '').strip().lower() == ed_id_num.strip().lower():
                                    st.error("Ο Αριθμός Ταυτότητας ανήκει ήδη σε άλλον υπάλληλο.")
                                    is_dup = True
                                    break
                        
                        if not is_dup:
                            old_emp_data = dict(emp_to_edit)
                            
                            emp_to_edit['name'] = ed_name.strip()
                            emp_to_edit['position'] = ed_pos.strip()
                            emp_to_edit['id_number'] = ed_id_num.strip()
                            emp_to_edit['phone'] = ed_phone.strip()
                            emp_to_edit['status'] = ed_status
                            
                            db_update('employees', emp_to_edit_id, emp_to_edit, old_data=old_emp_data)
                            st.success("Οι αλλαγές αποθηκεύτηκαν!")
                            st.rerun()

    with tab_import:
        st.write("### 📥 Μαζική Εισαγωγή Υπαλλήλων")
        st.write("Κατεβάστε το Google Sheet σας ως αρχείο Excel (.xlsx) ή CSV και ανεβάστε το εδώ.")
        st.info("Το αρχείο πρέπει να περιέχει οπωσδήποτε μια στήλη με όνομα **'Ονοματεπώνυμο'** (ή 'Name'). Οι υπόλοιπες στήλες ('Θέση', 'Αριθμός Ταυτότητας', 'Κινητό', 'Κατάσταση') θα διαβαστούν αυτόματα εφόσον υπάρχουν.")
        
        with st.form("import_form", clear_on_submit=True):
            uploaded_file = st.file_uploader("Επιλέξτε αρχείο Excel ή CSV", type=['csv', 'xlsx'])
            submit_import = st.form_submit_button("Εκτέλεση Εισαγωγής", type="primary")
            
        if submit_import and uploaded_file is not None:
            try:
                if uploaded_file.name.endswith('.csv'):
                    df_import = pd.read_csv(uploaded_file)
                else:
                    df_import = pd.read_excel(uploaded_file)
                
                success_count = 0
                error_count = 0
                
                cols = [str(c).lower().strip().replace(".", "").replace("_", " ") for c in df_import.columns]
                
                name_col = None
                for orig_col, c in zip(df_import.columns, cols):
                    if 'ονομα' in c or 'name' in c or 'υπαλλ' in c or 'υπάλλ' in c:
                        name_col = orig_col
                        break
                        
                if not name_col:
                    st.error("❌ Δεν βρέθηκε στήλη για το Ονοματεπώνυμο. Βεβαιωθείτε ότι γράφεται 'Ονοματεπώνυμο' στην πρώτη γραμμή του Excel.")
                else:
                    pos_col = next((orig for orig, c in zip(df_import.columns, cols) if 'θεσ' in c or 'θέσ' in c or 'ειδικ' in c or 'ρολο' in c or 'ρόλο' in c or 'position' in c), None)
                    id_col = next((orig for orig, c in zip(df_import.columns, cols) if 'ταυτοτ' in c or 'ταυτότ' in c or 'αδτ' in c or 'id' in c), None)
                    phone_col = next((orig for orig, c in zip(df_import.columns, cols) if 'τηλ' in c or 'κινητ' in c or 'phone' in c), None)
                    status_col = next((orig for orig, c in zip(df_import.columns, cols) if 'καταστ' in c or 'κατάστ' in c or 'status' in c or 'ενεργ' in c or 'active' in c), None)
                    
                    new_employees_batch = []
                    
                    with st.spinner("Εισαγωγή Δεδομένων..."):
                        for index, row in df_import.iterrows():
                            e_name = str(row[name_col]).strip() if pd.notna(row[name_col]) else ""
                            if not e_name or e_name.lower() == 'nan':
                                continue
                                
                            e_pos = str(row[pos_col]).strip().upper() if pos_col and pd.notna(row[pos_col]) else "ΕΡΓΑΤΗΣ"
                            if e_pos not in ["ΕΡΓΑΤΗΣ", "ΕΠΟΠΤΗΣ", "ΟΔΗΓΟΣ"]:
                                e_pos = "ΕΡΓΑΤΗΣ"
                                
                            e_id_num = str(row[id_col]).strip() if id_col and pd.notna(row[id_col]) else ""
                            if e_id_num.lower() == 'nan': e_id_num = ""
                            if e_id_num.endswith('.0'): e_id_num = e_id_num[:-2] 
                            
                            e_phone = str(row[phone_col]).strip() if phone_col and pd.notna(row[phone_col]) else ""
                            if e_phone.lower() == 'nan': e_phone = ""
                            if e_phone.endswith('.0'): e_phone = e_phone[:-2]
                            
                            e_status = "Ενεργός"
                            if status_col and pd.notna(row[status_col]):
                                val = str(row[status_col]).strip().lower()
                                if any(kw in val for kw in ["ανενεργ", "inactive", "false", "0", "οχι", "όχι", "no", "αποχωρ", "παραιτ"]):
                                    e_status = "Ανενεργός"
                            
                            is_duplicate = False
                            for emp in st.session_state.employees:
                                if emp['name'].strip().lower() == e_name.lower():
                                    is_duplicate = True
                                    break
                                if e_id_num and emp.get('id_number', '').strip().lower() == e_id_num.lower():
                                    is_duplicate = True
                                    break
                                    
                            if not is_duplicate:
                                new_e = {
                                    'id': str(uuid.uuid4()), 
                                    'name': e_name, 
                                    'position': e_pos,
                                    'id_number': e_id_num,
                                    'phone': e_phone,
                                    'status': e_status
                                }
                                new_employees_batch.append(new_e)
                                st.session_state.employees.append(new_e)
                                success_count += 1
                            else:
                                error_count += 1
                                
                        if new_employees_batch:
                            db_insert('employees', new_employees_batch)
                            
                        if error_count > 0:
                            st.warning(f"Παραλείφθηκαν {error_count} υπάλληλοι επειδή υπήρχαν ήδη στη λίστα.")
                            
                        if success_count > 0:
                            st.success(f"Εισήχθησαν επιτυχώς {success_count} υπάλληλοι! Η σελίδα ανανεώνεται...")
                            time.sleep(1.5) 
                            st.rerun() 
                            
            except Exception as e:
                st.error(f"Υπήρξε πρόβλημα με την ανάγνωση του αρχείου: {e}")

    with tab_list:
        st.write("### Συνολική Λίστα Υπαλλήλων")
        search_query = st.text_input("🔍 Αναζήτηση", placeholder="Ψάξε με Όνομα, Θέση, Ταυτότητα ή Τηλέφωνο...", key="emp_search_bar")
        
        filtered_emps = st.session_state.employees
        if search_query:
            q = search_query.strip().lower()
            filtered_emps = [e for e in st.session_state.employees if 
                             q in str(e.get('name', '')).lower() or 
                             q in str(e.get('position', '')).lower() or 
                             q in str(e.get('id_number', '')).lower() or 
                             q in str(e.get('phone', '')).lower()]
        
        with st.expander("🗑️ Μαζική Διαγραφή"):
            emps_to_delete = st.multiselect(
                "Επιλέξτε τους υπαλλήλους που θέλετε να διαγράψετε (εμφανίζονται τα αποτελέσματα αναζήτησης):",
                options=[e['id'] for e in filtered_emps],
                format_func=get_employee_name,
                key="bulk_delete_emps"
            )
            if st.button("Οριστική Διαγραφή", type="primary", key="btn_bulk_del"):
                if emps_to_delete:
                    deleted_emps = [e for e in st.session_state.employees if e['id'] in emps_to_delete]
                    st.session_state.employees = [emp for emp in st.session_state.employees if emp['id'] not in emps_to_delete]
                    db_delete_in('employees', 'id', emps_to_delete, deleted_records=deleted_emps)
                    st.rerun()
                else:
                    st.warning("Δεν έχετε επιλέξει κανέναν υπάλληλο.")
        
        st.divider()
        
        if not filtered_emps:
            st.info("Δεν βρέθηκαν υπάλληλοι που να ταιριάζουν στα κριτήρια αναζήτησης.")
        else:
            hc1, hc2, hc3, hc4, hc5, hc6 = st.columns([2, 2, 2, 2, 1.5, 1])
            hc1.write("**Ονοματεπώνυμο**")
            hc2.write("**Θέση**")
            hc3.write("**Αρ. Ταυτότητας**")
            hc4.write("**Κινητό**")
            hc5.write("**Κατάσταση**")
            hc6.write("")
            st.divider()
            
            for e in filtered_emps:
                col1, col2, col3, col4, col5, col6 = st.columns([2, 2, 2, 2, 1.5, 1])
                col1.write(e['name'])
                col2.write(f"*{e['position']}*")
                col3.write(e.get('id_number') or '-')
                col4.write(e.get('phone') or '-')
                
                status_val = e.get('status', 'Ενεργός')
                status_color = "#16a34a" if status_val == 'Ενεργός' else "#dc2626"
                col5.markdown(f"<span style='color:{status_color}; font-weight:bold;'>{status_val}</span>", unsafe_allow_html=True)
                
                if col6.button("❌", key=f"del_emp_{e['id']}"):
                    st.session_state.employees = [emp for emp in st.session_state.employees if emp['id'] != e['id']]
                    db_delete('employees', 'id', e['id'], deleted_records=[e])
                    st.rerun()

# --- VIEW: LEAVES (ΜΕ ΣΥΣΤΗΜΑ ΕΓΚΡΙΣΗΣ) ---
elif menu == "Άδειες":
    st.title("🏖️ Διαχείριση Αδειών")
    
    if "pending_leave" not in st.session_state:
        st.session_state.pending_leave = None
    if "leave_conflicts" not in st.session_state:
        st.session_state.leave_conflicts = []
        
    tab_list, tab_add, tab_edit = st.tabs(["📋 Λίστα Αδειών", "➕ Καταχώρηση", "✏️ Επεξεργασία"])
    
    with tab_add:
        if "leave_reset_counter" not in st.session_state:
            st.session_state.leave_reset_counter = 0
        lrc = st.session_state.leave_reset_counter
        
        c1, c2 = st.columns(2)
        with c1:
            l_emp = st.selectbox("Υπάλληλος (Μόνο Ενεργοί)", options=active_employee_ids, 
                                 format_func=get_employee_name, key=f"l_emp_{lrc}")
            l_start = st.date_input("Από", key=f"l_start_{lrc}")
        with c2:
            l_sub_emp = st.selectbox("Αντικαταστάτης (Προαιρετικό)", options=[""] + active_employee_ids, 
                                     format_func=lambda x: "Χωρίς Αντικαταστάτη" if x == "" else get_employee_name(x), key=f"l_sub_{lrc}")
            l_end = st.date_input("Έως", key=f"l_end_{lrc}")
            
        col_b1, col_b2 = st.columns([1, 1])
        with col_b1:
            submit_leave = st.button("Καταχώρηση Άδειας", type="primary", use_container_width=True)
        with col_b2:
            clear_leave = st.button("🧹 Καθαρισμός", key="btn_clear_leave", use_container_width=True)
            
        if clear_leave:
            st.session_state.leave_reset_counter += 1
            st.session_state.pending_leave = None
            st.session_state.leave_conflicts = []
            st.rerun()
            
        if submit_leave:
            if not l_emp:
                st.error("Παρακαλώ επιλέξτε υπάλληλο.")
            elif l_start > l_end:
                st.error("Η ημερομηνία 'Από' πρέπει να είναι πριν ή ίση με την 'Έως'.")
            elif l_emp == l_sub_emp:
                st.error("Ο αντικαταστάτης δεν μπορεί να είναι το ίδιο πρόσωπο με αυτόν που παίρνει άδεια.")
            else:
                conflicts = []
                curr_date = l_start
                while curr_date <= l_end:
                    day_assigns = st.session_state.assignments_by_date.get(curr_date, [])
                    for a in day_assigns:
                        if a['employeeId'] == l_emp:
                            conflicts.append(a)
                    curr_date += timedelta(days=1)
                
                if conflicts:
                    st.session_state.pending_leave = {
                        'id': str(uuid.uuid4()), 
                        'employeeId': l_emp, 
                        'startDate': l_start, 
                        'endDate': l_end,
                        'substituteId': l_sub_emp if l_sub_emp else None,
                        'type': 'new'
                    }
                    st.session_state.leave_conflicts = conflicts
                else:
                    new_l = {
                        'id': str(uuid.uuid4()), 
                        'employeeId': l_emp, 
                        'startDate': l_start, 
                        'endDate': l_end,
                        'substituteId': l_sub_emp if l_sub_emp else None
                    }
                    st.session_state.leaves.append(new_l)
                    db_insert('leaves', new_l)
                    st.success("Η άδεια καταχωρήθηκε με επιτυχία!")
                    time.sleep(1.5)
                    st.session_state.leave_reset_counter += 1
                    st.rerun()
                    
        # Σύστημα Έγκρισης (Pop-up Boxes)
        if st.session_state.get('pending_leave') and st.session_state.pending_leave.get('type') == 'new' and st.session_state.get('leave_conflicts'):
            st.markdown("---")
            st.warning("⚠️ **Εμπλοκή με βάρδιες!** Ο/Η υπάλληλος είναι ήδη τοποθετημένος/η σε έργα τις συγκεκριμένες ημερομηνίες. Πατήστε 'Έγκριση (Αφαίρεση)' για να τον/την αφαιρέσετε από το έργο και να περαστεί η άδεια.")
            
            resolved_any = False
            for a in st.session_state.leave_conflicts:
                st.markdown(f'<div class="leave-conflict-box">', unsafe_allow_html=True)
                col_err, col_btn = st.columns([4, 1])
                proj = get_project_info(a['projectId'])
                pname = proj['name'] if proj else "Άγνωστο Έργο"
                emp_name = get_employee_name(a['employeeId'])
                date_str = a['date'].strftime('%d/%m/%Y')
                
                col_err.write(f"Ο/Η **{emp_name}** δουλεύει στις **{date_str}** στο έργο: **{pname}** ({a['startTime']}-{a['endTime']}).")
                
                if col_btn.button("✅ Έγκριση (Αφαίρεση)", key=f"res_new_{a['id']}", use_container_width=True):
                    target_a = next((assign for assign in st.session_state.assignments if assign['id'] == a['id']), None)
                    if target_a:
                        old_a = dict(target_a)
                        target_a['employeeId'] = ""  # Αφαίρεση υπαλλήλου (Ορφανή Βάρδια)
                        db_update('assignments', target_a['id'], target_a, old_data=old_a)
                        
                        st.session_state.leave_conflicts = [c for c in st.session_state.leave_conflicts if c['id'] != a['id']]
                        resolved_any = True
                st.markdown('</div>', unsafe_allow_html=True)
            
            if resolved_any:
                if not st.session_state.leave_conflicts:
                    new_l = {k: v for k, v in st.session_state.pending_leave.items() if k != 'type'}
                    st.session_state.leaves.append(new_l)
                    db_insert('leaves', new_l)
                    st.session_state.pending_leave = None
                    st.success("Όλες οι επικαλύψεις επιλύθηκαν! Η άδεια καταχωρήθηκε.")
                    time.sleep(1.5)
                    st.session_state.leave_reset_counter += 1
                st.rerun()

    with tab_edit:
        if not st.session_state.leaves:
            st.info("Δεν υπάρχουν άδειες προς επεξεργασία.")
        else:
            leave_options = {}
            for lv in st.session_state.leaves:
                emp_name = get_employee_name(lv['employeeId'])
                leave_options[lv['id']] = f"{emp_name} ({lv['startDate'].strftime('%d/%m/%Y')} - {lv['endDate'].strftime('%d/%m/%Y')})"
            
            leave_to_edit_id = st.selectbox("Επιλέξτε Άδεια για Επεξεργασία", 
                                            options=list(leave_options.keys()),
                                            format_func=lambda x: leave_options[x])
            
            leave_to_edit = next(l for l in st.session_state.leaves if l['id'] == leave_to_edit_id)
            
            c1, c2 = st.columns(2)
            with c1:
                emp_options_safe = active_employee_ids + [leave_to_edit['employeeId']] if leave_to_edit['employeeId'] not in active_employee_ids else active_employee_ids
                ed_l_emp = st.selectbox("Αλλαγή Υπαλλήλου", options=emp_options_safe,
                                        index=emp_options_safe.index(leave_to_edit['employeeId']),
                                        format_func=get_employee_name)
                ed_l_start = st.date_input("Αλλαγή Ημερομηνίας 'Από'", value=leave_to_edit['startDate'])
            with c2:
                current_sub = leave_to_edit.get('substituteId') or ""
                sub_options = [""] + active_employee_ids
                if current_sub and current_sub not in sub_options:
                    sub_options.append(current_sub)
                    
                ed_l_sub_emp = st.selectbox("Αλλαγή Αντικαταστάτη", options=sub_options,
                                            index=sub_options.index(current_sub),
                                            format_func=lambda x: "Χωρίς Αντικαταστάτη" if x == "" else get_employee_name(x))
                ed_l_end = st.date_input("Αλλαγή Ημερομηνίας 'Έως'", value=leave_to_edit['endDate'])
                
            if st.button("💾 Αποθήκευση Αλλαγών", type="primary"):
                if ed_l_start > ed_l_end:
                    st.error("Η ημερομηνία 'Από' πρέπει να είναι πριν ή ίση με την 'Έως'.")
                elif ed_l_emp == ed_l_sub_emp:
                    st.error("Ο αντικαταστάτης δεν μπορεί να είναι το ίδιο πρόσωπο με αυτόν που παίρνει άδεια.")
                else:
                    conflicts = []
                    curr_date = ed_l_start
                    while curr_date <= ed_l_end:
                        day_assigns = st.session_state.assignments_by_date.get(curr_date, [])
                        for a in day_assigns:
                            if a['employeeId'] == ed_l_emp:
                                conflicts.append(a)
                        curr_date += timedelta(days=1)
                    
                    if conflicts:
                        st.session_state.pending_leave = {
                            'id': leave_to_edit_id, 
                            'employeeId': ed_l_emp, 
                            'startDate': ed_l_start, 
                            'endDate': ed_l_end,
                            'substituteId': ed_l_sub_emp if ed_l_sub_emp else None,
                            'type': 'edit',
                            'old_data': dict(leave_to_edit)
                        }
                        st.session_state.leave_conflicts = conflicts
                    else:
                        old_leave_data = dict(leave_to_edit)
                        leave_to_edit['employeeId'] = ed_l_emp
                        leave_to_edit['startDate'] = ed_l_start
                        leave_to_edit['endDate'] = ed_l_end
                        leave_to_edit['substituteId'] = ed_l_sub_emp if ed_l_sub_emp else None
                        
                        db_update('leaves', leave_to_edit_id, leave_to_edit, old_data=old_leave_data)
                        st.success("Οι αλλαγές στην άδεια αποθηκεύτηκαν!")
                        time.sleep(1)
                        st.rerun()

            if st.session_state.get('pending_leave') and st.session_state.pending_leave.get('type') == 'edit' and st.session_state.get('leave_conflicts'):
                st.markdown("---")
                st.warning("⚠️ **Εμπλοκή με βάρδιες!** Ο/Η υπάλληλος είναι ήδη τοποθετημένος/η σε έργα. Πατήστε 'Έγκριση (Αφαίρεση)'.")
                
                resolved_any = False
                for a in st.session_state.leave_conflicts:
                    st.markdown(f'<div class="leave-conflict-box">', unsafe_allow_html=True)
                    col_err, col_btn = st.columns([4, 1])
                    proj = get_project_info(a['projectId'])
                    pname = proj['name'] if proj else "Άγνωστο Έργο"
                    emp_name = get_employee_name(a['employeeId'])
                    date_str = a['date'].strftime('%d/%m/%Y')
                    
                    col_err.write(f"Ο/Η **{emp_name}** δουλεύει στις **{date_str}** στο έργο: **{pname}** ({a['startTime']}-{a['endTime']}).")
                    
                    if col_btn.button("✅ Έγκριση (Αφαίρεση)", key=f"res_edit_{a['id']}", use_container_width=True):
                        target_a = next((assign for assign in st.session_state.assignments if assign['id'] == a['id']), None)
                        if target_a:
                            old_a = dict(target_a)
                            target_a['employeeId'] = ""  # Ορφανή βάρδια
                            db_update('assignments', target_a['id'], target_a, old_data=old_a)
                            
                            st.session_state.leave_conflicts = [c for c in st.session_state.leave_conflicts if c['id'] != a['id']]
                            resolved_any = True
                    st.markdown('</div>', unsafe_allow_html=True)
                
                if resolved_any:
                    if not st.session_state.leave_conflicts:
                        leave_id = st.session_state.pending_leave['id']
                        leave_obj = next(l for l in st.session_state.leaves if l['id'] == leave_id)
                        
                        leave_obj['employeeId'] = st.session_state.pending_leave['employeeId']
                        leave_obj['startDate'] = st.session_state.pending_leave['startDate']
                        leave_obj['endDate'] = st.session_state.pending_leave['endDate']
                        leave_obj['substituteId'] = st.session_state.pending_leave['substituteId']
                        
                        old_data = st.session_state.pending_leave['old_data']
                        
                        db_update('leaves', leave_id, leave_obj, old_data=old_data)
                        st.session_state.pending_leave = None
                        st.success("Όλες οι επικαλύψεις επιλύθηκαν! Οι αλλαγές αποθηκεύτηκαν.")
                        time.sleep(1.5)
                    st.rerun()

    with tab_list:
        if st.session_state.leaves:
            st.write("### Λίστα Αδειών")
            
            hc1, hc2, hc3, hc4, hc5 = st.columns([2.5, 2, 2, 2.5, 1])
            hc1.write("**Υπάλληλος**")
            hc2.write("**Από**")
            hc3.write("**Έως**")
            hc4.write("**Αντικαταστάτης**")
            hc5.write("")
            st.divider()
            
            for l in st.session_state.leaves:
                col1, col2, col3, col4, col5 = st.columns([2.5, 2, 2, 2.5, 1])
                col1.write(get_employee_name(l['employeeId']))
                col2.write(l['startDate'].strftime('%d/%m/%Y'))
                col3.write(l['endDate'].strftime('%d/%m/%Y'))
                
                sub_name = get_employee_name(l.get('substituteId')) if l.get('substituteId') else "-"
                col4.write(sub_name)
                
                if col5.button("❌", key=f"del_leave_{l['id']}"):
                    st.session_state.leaves = [leave for leave in st.session_state.leaves if leave['id'] != l['id']]
                    db_delete('leaves', 'id', l['id'], deleted_records=[l])
                    st.rerun()
        else:
            st.info("Δεν υπάρχουν καταχωρημένες άδειες.")

# --- VIEW: Σύνολο Αδειών ---
elif menu == "Σύνολο Αδειών":
    st.title("🏖️ Σύνολο Αδειών ανά Έτος")
    current_year = date.today().year
    years = list(range(2020, 2036))
    col1, col2 = st.columns([1, 3])
    with col1:
        selected_year = st.selectbox("Επιλογή Έτους", years, index=years.index(current_year))
    st.divider()
    
    leave_days = {emp['id']: 0 for emp in st.session_state.employees}
    year_start = date(selected_year, 1, 1)
    year_end = date(selected_year, 12, 31)
    
    for l in st.session_state.leaves:
        start_d = l['startDate']
        end_d = l['endDate']
        actual_start = max(start_d, year_start)
        actual_end = min(end_d, year_end)
        if actual_start <= actual_end:
            days = (actual_end - actual_start).days + 1
            if l['employeeId'] in leave_days:
                leave_days[l['employeeId']] += days
                
    table_data = []
    for emp in st.session_state.employees:
        table_data.append({
            "Ονοματεπώνυμο": emp['name'],
            "Θέση": emp['position'],
            "Κατάσταση": emp.get('status', 'Ενεργός'),
            "Ημέρες Άδειας": leave_days[emp['id']]
        })
    df_leaves_summary = pd.DataFrame(table_data)
    st.write(f"### Συνολικές Ημέρες Άδειας για το έτος: {selected_year}")
    st.dataframe(df_leaves_summary, use_container_width=True, hide_index=True)

# --- VIEW: Ώρες Εργασιών ---
elif menu == "Ώρες Εργασιών":
    st.title("⏱️ Ώρες Εργασιών ανά Μήνα")
    months = ["Ιανουάριος", "Φεβρουάριος", "Μάρτιος", "Απρίλιος", "Μάιος", "Ιούνιος", 
              "Ιούλιος", "Αύγουστος", "Σεπτέμβριος", "Οκτώβριος", "Νοέμβριος", "Δεκέμβριος"]
    current_month_index = date.today().month - 1
    current_year = date.today().year
    
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        selected_month_name = st.selectbox("Επιλογή Μήνα", months, index=current_month_index)
        selected_month = months.index(selected_month_name) + 1
    with col2:
        years = list(range(2020, 2036))
        selected_year = st.selectbox("Επιλογή Έτους", years, index=years.index(current_year))
    st.divider()
    
    employee_hours = {emp['id']: 0.0 for emp in st.session_state.employees}
    for a in st.session_state.assignments:
        d = a['date']
        if d.month == selected_month and d.year == selected_year:
            start_str = str(a['startTime'])[:5]
            end_str = str(a['endTime'])[:5]
            try:
                start_h, start_m = map(int, start_str.split(':'))
                end_h, end_m = map(int, end_str.split(':'))
                delta_hours = (end_h - start_h) + (end_m - start_m) / 60.0
                if a['employeeId'] in employee_hours:
                    employee_hours[a['employeeId']] += delta_hours
            except:
                pass
                
    table_data = []
    for emp in st.session_state.employees:
        table_data.append({
            "Ονοματεπώνυμο": emp['name'],
            "Θέση": emp['position'],
            "Κατάσταση": emp.get('status', 'Ενεργός'),
            "Συνολικές Ώρες": round(employee_hours[emp['id']], 2)
        })
    df_hours = pd.DataFrame(table_data)
    st.write(f"### Σύνολο Ωρών για: {selected_month_name} {selected_year}")
    st.dataframe(df_hours.style.format({"Συνολικές Ώρες": "{:.2f}"}), use_container_width=True, hide_index=True)

# --- VIEW: ΕΠΑΝΑΛΑΜΒΑΝΟΜΕΝΕΣ ΕΡΓΑΣΙΕΣ ---
elif menu == "Επαναλαμβανόμενες Εργασίες":
    st.title("🔄 Επαναλαμβανόμενες Εργασίες")
    
    if not is_full_admin:
        st.info("⚠️ Έχετε δικαιώματα μόνο για ανάγνωση. Δεν μπορείτε να διαχειριστείτε τις επαναλαμβανόμενες εργασίες.")
    else:
        st.write("Προσθέστε ή επεξεργαστείτε εργασίες που επαναλαμβάνονται «για πάντα» (επεκτείνονται αυτόματα κάθε χρόνο).")
        tab_new, tab_edit = st.tabs(["➕ Νέα Καταχώρηση", "✏️ Διαχείριση/Επεξεργασία Υπαρχουσών"])
        
        if "rec_reset_counter" not in st.session_state:
            st.session_state.rec_reset_counter = 0
        rc = st.session_state.rec_reset_counter
        
        with tab_new:
            r_col1, r_col2 = st.columns(2)
            with r_col1:
                r_proj = st.selectbox("Επιλογή Έργου (Από Λίστα)", options=[p['id'] for p in st.session_state.projects], 
                                         format_func=get_project_name, key=f"new_r_proj_{rc}")
                r_custom_proj_name = st.text_input("Ή πληκτρολογήστε Νέο Έργο (Αν συμπληρωθεί, αγνοεί την παραπάνω λίστα)", key=f"new_r_custom_proj_{rc}")
                c_r_color, c_r_notes = st.columns(2)
                with c_r_color:
                    r_color = st.selectbox("Χρώμα Μπάρας", options=list(BASIC_COLORS.keys()), key=f"new_r_color_{rc}")
                with c_r_notes:
                    r_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", key=f"new_r_notes_{rc}")
                
                r_type = st.selectbox("Συχνότητα Επανάληψης", ["Εβδομαδιαία", "Μηνιαία", "Επιλεγμένες Μέρες Εβδομάδας"], key=f"new_r_type_{rc}")
                
                r_emps = []
                selected_weekdays = []
                selected_weekdays_data = {}
                
                if r_type in ["Εβδομαδιαία", "Μηνιαία"]:
                    r_emps = st.multiselect("Προσωπικό (Προαιρετικό - Μόνο Ενεργοί)", options=active_employee_ids, 
                                            format_func=get_employee_name, key=f"new_r_emps_{rc}")
                else:
                    st.markdown("**Επιλέξτε Μέρες και Προσωπικό (ξεχωριστά ανά μέρα):**")
                    day_names = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
                    for i, d_name in enumerate(day_names):
                        c_chk, c_emp = st.columns([1, 3])
                        if c_chk.checkbox(d_name, value=(i==0), key=f"new_chk_{i}_{rc}"):
                            selected_weekdays.append(d_name)
                            selected_weekdays_data[d_name] = c_emp.multiselect(
                                f"Προσωπικό ({d_name})", options=active_employee_ids, format_func=get_employee_name, 
                                key=f"new_r_emps_day_{i}_{rc}", label_visibility="collapsed"
                            )
            
            with r_col2:
                r_start_date = st.date_input("Από Ημερομηνία", date.today(), key=f"new_r_start_date_{rc}")
                r_arr, r_start, r_end = st.columns(3)
                with r_arr:
                    use_arr_rec = st.checkbox("Προσέλευση;", key=f"chk_arr_rec_{rc}")
                    r_arrival_time = st.time_input("Ώρα Προσέλευσης", value=datetime.strptime("08:00", "%H:%M").time(), key=f"new_r_arr_{rc}", disabled=not use_arr_rec)
                with r_start:
                    r_start_time = st.time_input("Έναρξη Ώρας", value=datetime.strptime("09:00", "%H:%M").time(), key=f"new_r_start_time_{rc}")
                with r_end:
                    r_end_time = st.time_input("Λήξη Ώρας", value=datetime.strptime("17:00", "%H:%M").time(), key=f"new_r_end_time_{rc}")
                
                st.info("💡 Η εργασία θα δημιουργήσει βάρδιες για 1 χρόνο. Στη συνέχεια θα επεκτείνεται αυτόματα.")
            
            st.write("") 
            col_btn1, col_btn2 = st.columns([1, 1])
            with col_btn1:
                submit_r = st.button("Καταχώρηση Επαναλαμβανόμενης Εργασίας", type="primary", key="btn_new_r", use_container_width=True)
            with col_btn2:
                clear_r = st.button("🧹 Καθαρισμός", key="btn_clear_r", use_container_width=True)
                
            if clear_r:
                st.session_state.rec_reset_counter += 1
                st.rerun()
                
            if submit_r:
                str_arrival = r_arrival_time.strftime("%H:%M") if use_arr_rec else ""
                str_start = r_start_time.strftime("%H:%M")
                str_end = r_end_time.strftime("%H:%M")
                
                if str_start >= str_end:
                    st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                elif r_type == "Επιλεγμένες Μέρες Εβδομάδας" and not selected_weekdays:
                    st.error("Επιλέξτε τουλάχιστον μία μέρα της εβδομάδας τικάροντας το αντίστοιχο κουτάκι.")
                elif not r_custom_proj_name.strip() and not r_proj:
                    st.error("Παρακαλώ επιλέξτε ή πληκτρολογήστε ένα Έργο.")
                else:
                    actions = []
                    if r_custom_proj_name.strip():
                        final_r_proj_id = str(uuid.uuid4())
                        new_p = {'id': final_r_proj_id, 'name': r_custom_proj_name.strip(), 'color': BASIC_COLORS[r_color]}
                        st.session_state.projects.append(new_p)
                        db_insert('projects', new_p, track=False)
                        actions.append({'type': 'insert', 'table': 'projects', 'records': [new_p]})
                    else:
                        final_r_proj_id = r_proj
                        
                    pattern_id = str(uuid.uuid4())
                    r_end_date = max(r_start_date + timedelta(days=365), date.today() + timedelta(days=365))
                    
                    dates_to_assign = []
                    curr_date = r_start_date
                    day_map = {"Δευτέρα": 0, "Τρίτη": 1, "Τετάρτη": 2, "Πέμπτη": 3, "Παρασκευή": 4, "Σάββατο": 5, "Κυριακή": 6}
                    day_map_inv = {0: "Δευτέρα", 1: "Τρίτη", 2: "Τετάρτη", 3: "Πέμπτη", 4: "Παρασκευή", 5: "Σάββατο", 6: "Κυριακή"}
                    selected_weekday_ints = [day_map[d] for d in selected_weekdays] if selected_weekdays else []
                    
                    new_assignments_batch = []
                    
                    with st.spinner('Υπολογισμός και καταχώρηση βαρδιών...'):
                        while curr_date <= r_end_date:
                            if r_type == "Εβδομαδιαία":
                                dates_to_assign.append(curr_date)
                                curr_date += timedelta(days=7)
                            elif r_type == "Μηνιαία":
                                dates_to_assign.append(curr_date)
                                month = curr_date.month
                                year = curr_date.year
                                if month == 12: month = 1; year += 1
                                else: month += 1
                                try: curr_date = curr_date.replace(year=year, month=month)
                                except ValueError:
                                    last_day = calendar.monthrange(year, month)[1]
                                    curr_date = curr_date.replace(year=year, month=month, day=last_day)
                            elif r_type == "Επιλεγμένες Μέρες Εβδομάδας":
                                if curr_date.weekday() in selected_weekday_ints:
                                    dates_to_assign.append(curr_date)
                                curr_date += timedelta(days=1)
                        
                        success_count = 0
                        conflict_count = 0
                        conflict_details = []
                        
                        for d in dates_to_assign:
                            if r_type == "Επιλεγμένες Μέρες Εβδομάδας":
                                d_name = day_map_inv[d.weekday()]
                                emps_to_process = selected_weekdays_data.get(d_name, [])
                            else:
                                emps_to_process = r_emps
                            emps_to_process = emps_to_process if emps_to_process else [""]
                            
                            created_for_day = 0
                            for eid in emps_to_process:
                                if eid:
                                    emp_name = get_employee_name(eid)
                                    if is_on_leave(eid, d):
                                        conflict_count += 1
                                        conflict_details.append(f"{d.strftime('%d/%m/%Y')} - {emp_name} (Άδεια)")
                                        st.toast(f"🛑 Επαναλαμβανόμενη: Άδεια {emp_name} ({d.strftime('%d/%m')})", icon="🛑")
                                        continue
                                    
                                    adj_start, adj_end, is_conflict, msg = check_and_resolve_conflict(eid, d, str_start, str_end)
                                    if is_conflict:
                                        conflict_count += 1
                                        conflict_details.append(f"{d.strftime('%d/%m/%Y')} - {emp_name} (Επικάλυψη)")
                                        st.toast(f"🚨 Επαναλαμβανόμενη: Διπλοκράτηση {emp_name} ({d.strftime('%d/%m')})", icon="🚨")
                                        continue
                                    
                                    if msg == "AllowedOverlap":
                                        st.toast(f"ℹ️ Επιτράπηκε επικάλυψη ωραρίου: {emp_name} ({adj_start})", icon="ℹ️")
                                    new_assign = {
                                        'id': str(uuid.uuid4()), 'recurring_id': pattern_id, 'employeeId': eid,
                                        'projectId': final_r_proj_id, 'date': d, 'arrivalTime': str_arrival,
                                        'startTime': adj_start, 'endTime': adj_end, 'colorName': r_color,
                                        'colorHex': BASIC_COLORS[r_color], 'notes': r_notes,
                                        'is_cancelled': False, 'cancel_reason': ""
                                    }
                                    new_assignments_batch.append(new_assign)
                                    created_for_day += 1
                                    success_count += 1
                                else:
                                    new_assign = {
                                        'id': str(uuid.uuid4()), 'recurring_id': pattern_id, 'employeeId': "",
                                        'projectId': final_r_proj_id, 'date': d, 'arrivalTime': str_arrival,
                                        'startTime': str_start, 'endTime': str_end, 'colorName': r_color,
                                        'colorHex': BASIC_COLORS[r_color], 'notes': r_notes, 'is_cancelled': False, 'cancel_reason': ""
                                    }
                                    new_assignments_batch.append(new_assign)
                                    created_for_day += 1
                                    success_count += 1
                            
                            if created_for_day == 0 and emps_to_process != [""]:
                                new_assign = {
                                    'id': str(uuid.uuid4()), 'recurring_id': pattern_id, 'employeeId': "",
                                    'projectId': final_r_proj_id, 'date': d, 'arrivalTime': str_arrival,
                                    'startTime': str_start, 'endTime': str_end, 'colorName': r_color,
                                    'colorHex': BASIC_COLORS[r_color], 'notes': r_notes, 'is_cancelled': False, 'cancel_reason': ""
                                }
                                new_assignments_batch.append(new_assign)
                                success_count += 1
                        
                        final_employee_ids = selected_weekdays_data if r_type == "Επιλεγμένες Μέρες Εβδομάδας" else r_emps
                        new_pattern = {
                            'id': pattern_id, 'projectId': final_r_proj_id, 'employeeIds': final_employee_ids,
                            'colorName': r_color, 'notes': r_notes, 'type': r_type, 'weekdays': selected_weekdays,
                            'arrivalTime': str_arrival, 'startDate': r_start_date, 'startTime': str_start, 'endTime': str_end
                        }
                        
                        st.session_state.recurring_patterns.append(new_pattern)
                        db_insert('recurring_patterns', new_pattern, track=False)
                        actions.append({'type': 'insert', 'table': 'recurring_patterns', 'records': [new_pattern]})
                        
                        if new_assignments_batch:
                            st.session_state.assignments.extend(new_assignments_batch)
                            if supabase:
                                with st.status("Καταχώρηση στη βάση...", expanded=True) as status:
                                    chunk_size = 50
                                    has_err = False
                                    for i in range(0, len(new_assignments_batch), chunk_size):
                                        st.write(f"Συγχρονισμός... ({i+1} έως {min(i+chunk_size, len(new_assignments_batch))})")
                                        try: 
                                            supabase.table('assignments').insert(serialize_dates(new_assignments_batch[i:i+chunk_size])).execute()
                                        except Exception as e: 
                                            st.error(f"Σφάλμα DB: {e}")
                                            has_err = True
                                    if has_err:
                                        status.update(label="Ολοκληρώθηκε με σφάλματα!", state="error", expanded=True)
                                    else:
                                        status.update(label="Ολοκληρώθηκε!", state="complete", expanded=False)
                            actions.append({'type': 'insert', 'table': 'assignments', 'records': new_assignments_batch})
                        add_transaction(actions)
                        st.session_state.rec_reset_counter += 1
                        
                    if success_count > 0:
                        st.success(f"Επιτυχής δημιουργία {success_count} βαρδιών! Η σελίδα ανανεώνεται...")
                        time.sleep(1.5)
                        st.rerun()
                    if conflict_count > 0:
                        st.warning(f"Παραλείφθηκαν {conflict_count} αναθέσεις (έγιναν Χωρίς Προσωπικό) λόγω συγκρούσεων.")
                        with st.expander("Δείτε τις συγκρούσεις"):
                            for c in conflict_details: st.write(f"⚠️ {c}")

        with tab_edit:
            if not st.session_state.recurring_patterns:
                st.info("Δεν υπάρχουν ενεργές επαναλαμβανόμενες εργασίες.")
            else:
                pattern_options = {}
                for p in st.session_state.recurring_patterns:
                    p_info = get_project_info(p['projectId'])
                    p_name = p_info['name'] if p_info else 'Άγνωστο Έργο'
                    pattern_options[p['id']] = f"{p_name} | {p['type']} | Από: {p['startDate'].strftime('%d/%m/%Y')} ({p['startTime']}-{p['endTime']})"
                
                selected_pattern_id = st.selectbox("Επιλέξτε Σειρά Εργασιών", options=list(pattern_options.keys()), format_func=lambda x: pattern_options[x])
                
                if selected_pattern_id:
                    pat = next(p for p in st.session_state.recurring_patterns if p['id'] == selected_pattern_id)
                    with st.form("edit_recurring_form", clear_on_submit=True):
                        st.warning("⚠️ Προσοχή: Η αποθήκευση αλλαγών θα επαναδημιουργήσει **ΟΛΕΣ** τις βάρδιες αυτής της σειράς. Τυχόν μεμονωμένες αλλαγές που κάνατε στο Ταμπλό θα χαθούν.")
                        e_col1, e_col2 = st.columns(2)
                        with e_col1:
                            proj_ids = [p['id'] for p in st.session_state.projects]
                            default_proj_idx = proj_ids.index(pat['projectId']) if pat['projectId'] in proj_ids else 0
                            e_proj = st.selectbox("Αλλαγή Έργου", options=proj_ids, index=default_proj_idx, format_func=get_project_name, key=f"edit_r_proj_{pat['id']}")
                            e_custom_proj_name = st.text_input("Ή πληκτρολογήστε Νέο Έργο (προαιρετικό)", key=f"edit_r_custom_proj_{pat['id']}")
                            
                            e_type_options = ["Εβδομαδιαία", "Μηνιαία", "Επιλεγμένες Μέρες Εβδομάδας"]
                            current_e_type = pat.get('type', 'Εβδομαδιαία')
                            e_type_idx = e_type_options.index(current_e_type) if current_e_type in e_type_options else 0
                            e_type = st.selectbox("Συχνότητα Επανάληψης", e_type_options, index=e_type_idx, key=f"edit_r_type_{pat['id']}")
                            
                            e_employee_ids_saved = pat.get('employeeIds', [])
                            saved_ids_flat = []
                            if isinstance(e_employee_ids_saved, dict):
                                for d_list in e_employee_ids_saved.values(): saved_ids_flat.extend([eid for eid in d_list if eid])
                            else: saved_ids_flat = [eid for eid in e_employee_ids_saved if eid]
                                
                            valid_emp_ids = list(set(active_employee_ids + saved_ids_flat))
                            edit_options_r = valid_emp_ids
                            e_emps_selection = []
                            e_selected_weekdays_data = {}
                            e_selected_weekdays = pat.get('weekdays', [])
                            
                            st.write(f"**Συχνότητα Επανάληψης:** {e_type}")
                            if e_type in ["Εβδομαδιαία", "Μηνιαία"]:
                                def_emps = []
                                if isinstance(e_employee_ids_saved, list): def_emps = [eid for eid in e_employee_ids_saved if eid]
                                elif isinstance(e_employee_ids_saved, dict): def_emps = list(set([eid for lst in e_employee_ids_saved.values() for eid in lst if eid]))
                                valid_def_emps = [eid for eid in def_emps if eid in edit_options_r]
                                e_emps_selection = st.multiselect("Αλλαγή Προσωπικού", options=edit_options_r, default=valid_def_emps, format_func=get_employee_name, key=f"edit_r_emps_{pat['id']}")
                            else:
                                st.markdown("**Αλλαγή Ημερών & Προσωπικού (ανά μέρα):**")
                                day_names = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
                                e_selected_weekdays = []
                                for i, d_name in enumerate(day_names):
                                    c_chk, c_emp = st.columns([1, 3])
                                    was_checked = d_name in pat.get('weekdays', [])
                                    if c_chk.checkbox(d_name, value=was_checked, key=f"edit_chk_{i}_{pat['id']}"):
                                        e_selected_weekdays.append(d_name)
                                        def_day_emps = []
                                        if isinstance(e_employee_ids_saved, dict): def_day_emps = [eid for eid in e_employee_ids_saved.get(d_name, []) if eid]
                                        elif isinstance(e_employee_ids_saved, list): def_day_emps = [eid for eid in e_employee_ids_saved if eid]
                                        valid_def = [eid for eid in def_day_emps if eid in edit_options_r]
                                        e_selected_weekdays_data[d_name] = c_emp.multiselect(f"Προσωπικό ({d_name})", options=edit_options_r, default=valid_def, format_func=get_employee_name, key=f"edit_emps_day_{i}_{pat['id']}", label_visibility="collapsed")
                            
                            e_color_col, e_notes_col = st.columns(2)
                            with e_color_col:
                                e_color_idx = list(BASIC_COLORS.keys()).index(pat.get('colorName')) if pat.get('colorName') in BASIC_COLORS else 0
                                e_color = st.selectbox("Αλλαγή Χρώματος", options=list(BASIC_COLORS.keys()), index=e_color_idx, key=f"edit_r_color_{pat['id']}")
                            with e_notes_col:
                                e_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", value=pat.get('notes', ''), key=f"edit_r_notes_{pat['id']}")

                        with e_col2:
                            e_start_date = st.date_input("Αλλαγή Ημερομηνίας Έναρξης", value=pat['startDate'], key=f"edit_r_start_date_{pat['id']}")
                            e_arr, e_start, e_end = st.columns(3)
                            existing_arr_rec = pat.get('arrivalTime', '')
                            with e_arr:
                                use_arr_rec_edit = st.checkbox("Με Προσέλευση", value=bool(existing_arr_rec), key=f"edit_chk_arr_{pat['id']}")
                                def_arr = datetime.strptime(existing_arr_rec, "%H:%M").time() if existing_arr_rec else datetime.strptime(pat['startTime'][:5], "%H:%M").time()
                                e_arrival_time = st.time_input("Αλλαγή Προσέλευσης", value=def_arr, key=f"edit_r_arr_time_{pat['id']}", disabled=not use_arr_rec_edit)
                            with e_start:
                                e_start_time = st.time_input("Αλλαγή Έναρξης", value=datetime.strptime(pat['startTime'][:5], "%H:%M").time(), key=f"edit_r_start_time_{pat['id']}")
                            with e_end:
                                e_end_time = st.time_input("Αλλαγή Ώρας Λήξης", value=datetime.strptime(pat['endTime'][:5], "%H:%M").time(), key=f"edit_r_end_time_{pat['id']}")
                            
                        st.write("")
                        col_b1, col_b2 = st.columns(2)
                        with col_b1:
                            save_rec = st.form_submit_button("💾 Αποθήκευση Αλλαγών", type="primary")
                        with col_b2:
                            del_rec = st.form_submit_button("🗑️ Διαγραφή ΟΛΗΣ της σειράς")
                            
                        if del_rec:
                            old_assigns = [a for a in st.session_state.assignments if a.get('recurring_id') == selected_pattern_id]
                            st.session_state.assignments = [a for a in st.session_state.assignments if a.get('recurring_id') != selected_pattern_id]
                            st.session_state.recurring_patterns = [p for p in st.session_state.recurring_patterns if p['id'] != selected_pattern_id]
                            db_delete_in('assignments', 'id', [a['id'] for a in old_assigns], track=False)
                            db_delete('recurring_patterns', 'id', selected_pattern_id, track=False)
                            add_transaction([{'type': 'delete', 'table': 'assignments', 'records': old_assigns}, {'type': 'delete', 'table': 'recurring_patterns', 'records': [dict(pat)]}])
                            st.rerun()
                            
                        if save_rec:
                            str_arrival = e_arrival_time.strftime("%H:%M") if use_arr_rec_edit else ""
                            str_start = e_start_time.strftime("%H:%M")
                            str_end = e_end_time.strftime("%H:%M")
                            if str_start >= str_end: st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                            elif e_type == "Επιλεγμένες Μέρες Εβδομάδας" and not e_selected_weekdays: st.error("Επιλέξτε τουλάχιστον μία μέρα της εβδομάδας.")
                            elif not e_custom_proj_name.strip() and not e_proj: st.error("Παρακαλώ επιλέξτε ή πληκτρολογήστε ένα Έργο.")
                            else:
                                actions = []
                                if e_custom_proj_name.strip():
                                    final_e_proj_id = str(uuid.uuid4())
                                    new_p = {'id': final_e_proj_id, 'name': e_custom_proj_name.strip(), 'color': BASIC_COLORS[e_color]}
                                    st.session_state.projects.append(new_p)
                                    db_insert('projects', new_p, track=False)
                                    actions.append({'type': 'insert', 'table': 'projects', 'records': [new_p]})
                                else:
                                    final_e_proj_id = e_proj
                                    
                                old_assigns = [a for a in st.session_state.assignments if a.get('recurring_id') == selected_pattern_id]
                                st.session_state.assignments = [a for a in st.session_state.assignments if a.get('recurring_id') != selected_pattern_id]
                                db_delete_in('assignments', 'id', [a['id'] for a in old_assigns], track=False)
                                actions.append({'type': 'delete', 'table': 'assignments', 'records': old_assigns})
                                
                                r_end_date = max(e_start_date + timedelta(days=365), date.today() + timedelta(days=365)) 
                                dates_to_assign = []
                                curr_date = e_start_date
                                day_map = {"Δευτέρα": 0, "Τρίτη": 1, "Τετάρτη": 2, "Πέμπτη": 3, "Παρασκευή": 4, "Σάββατο": 5, "Κυριακή": 6}
                                day_map_inv = {0: "Δευτέρα", 1: "Τρίτη", 2: "Τετάρτη", 3: "Πέμπτη", 4: "Παρασκευή", 5: "Σάββατο", 6: "Κυριακή"}
                                selected_weekday_ints = [day_map[d] for d in e_selected_weekdays] if e_selected_weekdays else []
                                
                                old_assign_ids = [a['id'] for a in old_assigns]
                                new_assignments_batch = []
                                
                                with st.spinner('Ενημέρωση και καταχώρηση βαρδιών...'):
                                    while curr_date <= r_end_date:
                                        if e_type == "Εβδομαδιαία":
                                            dates_to_assign.append(curr_date)
                                            curr_date += timedelta(days=7)
                                        elif e_type == "Μηνιαία":
                                            dates_to_assign.append(curr_date)
                                            month = curr_date.month
                                            year = curr_date.year
                                            if month == 12: month = 1; year += 1
                                            else: month += 1
                                            try: curr_date = curr_date.replace(year=year, month=month)
                                            except ValueError:
                                                last_day = calendar.monthrange(year, month)[1]
                                                curr_date = curr_date.replace(year=year, month=month, day=last_day)
                                        elif e_type == "Επιλεγμένες Μέρες Εβδομάδας":
                                            if curr_date.weekday() in selected_weekday_ints: dates_to_assign.append(curr_date)
                                            curr_date += timedelta(days=1)
                                
                                    for d in dates_to_assign:
                                        if e_type == "Επιλεγμένες Μέρες Εβδομάδας":
                                            d_name = day_map_inv[d.weekday()]
                                            emps_to_process = e_selected_weekdays_data.get(d_name, [])
                                        else: emps_to_process = e_emps_selection
                                        emps_to_process = emps_to_process if emps_to_process else [""]
                                        
                                        created_for_day = 0
                                        for eid in emps_to_process:
                                            if eid:
                                                emp_name = get_employee_name(eid)
                                                if is_on_leave(eid, d): 
                                                    st.toast(f"🛑 Παραλείφθηκε: {emp_name} έχει άδεια", icon="🛑")
                                                    continue
                                                
                                                adj_start, adj_end, is_conflict, msg = check_and_resolve_conflict(eid, d, str_start, str_end, exclude_ids=old_assign_ids)
                                                if is_conflict: 
                                                    st.toast(f"🚨 Παραλείφθηκε: Διπλοκράτηση {emp_name}", icon="🚨")
                                                    continue
                                                
                                                if msg == "AllowedOverlap":
                                                    st.toast(f"ℹ️ Επιτράπηκε επικάλυψη ωραρίου: {emp_name} ({adj_start})", icon="ℹ️")
                                                new_assign = {
                                                    'id': str(uuid.uuid4()), 'recurring_id': selected_pattern_id, 'employeeId': eid,
                                                    'projectId': final_e_proj_id, 'date': d, 'arrivalTime': str_arrival,
                                                    'startTime': adj_start, 'endTime': adj_end, 'colorName': e_color,
                                                    'colorHex': BASIC_COLORS[e_color], 'notes': e_notes, 'is_cancelled': False, 'cancel_reason': ""
                                                }
                                                new_assignments_batch.append(new_assign)
                                                created_for_day += 1
                                            else:
                                                new_assign = {
                                                    'id': str(uuid.uuid4()), 'recurring_id': selected_pattern_id, 'employeeId': "",
                                                    'projectId': final_e_proj_id, 'date': d, 'arrivalTime': str_arrival,
                                                    'startTime': str_start, 'endTime': str_end, 'colorName': e_color,
                                                    'colorHex': BASIC_COLORS[e_color], 'notes': e_notes, 'is_cancelled': False, 'cancel_reason': ""
                                                }
                                                new_assignments_batch.append(new_assign)
                                                created_for_day += 1
                                                
                                        if created_for_day == 0 and emps_to_process != [""]:
                                            new_assign = {
                                                'id': str(uuid.uuid4()), 'recurring_id': selected_pattern_id, 'employeeId': "",
                                                'projectId': final_e_proj_id, 'date': d, 'arrivalTime': str_arrival,
                                                'startTime': str_start, 'endTime': str_end, 'colorName': e_color,
                                                'colorHex': BASIC_COLORS[e_color], 'notes': e_notes, 'is_cancelled': False, 'cancel_reason': ""
                                            }
                                            new_assignments_batch.append(new_assign)
                                
                                    old_pat = dict(pat)
                                    final_e_employee_ids = e_selected_weekdays_data if e_type == "Επιλεγμένες Μέρες Εβδομάδας" else e_emps_selection
                                    pat['projectId'] = final_e_proj_id
                                    pat['employeeIds'] = final_e_employee_ids
                                    pat['colorName'] = e_color
                                    pat['notes'] = e_notes
                                    pat['type'] = e_type
                                    pat['weekdays'] = e_selected_weekdays
                                    pat['arrivalTime'] = str_arrival
                                    pat['startDate'] = e_start_date
                                    pat['startTime'] = str_start
                                    pat['endTime'] = str_end
                                    
                                    db_update('recurring_patterns', selected_pattern_id, pat, old_data=old_pat, track=False)
                                    actions.append({'type': 'update', 'table': 'recurring_patterns', 'old_records': [old_pat], 'new_records': [dict(pat)]})
                                    
                                    if new_assignments_batch:
                                        st.session_state.assignments.extend(new_assignments_batch)
                                        if supabase:
                                            with st.status("Καταχώρηση στη βάση...", expanded=True) as status:
                                                chunk_size = 50
                                                has_err = False
                                                for i in range(0, len(new_assignments_batch), chunk_size):
                                                    st.write(f"Συγχρονισμός... ({i+1} έως {min(i+chunk_size, len(new_assignments_batch))})")
                                                    try: 
                                                        supabase.table('assignments').insert(serialize_dates(new_assignments_batch[i:i+chunk_size])).execute()
                                                    except Exception as e: 
                                                        st.error(f"Σφάλμα DB: {e}")
                                                        has_err = True
                                                if has_err:
                                                    status.update(label="Ολοκληρώθηκε με σφάλματα!", state="error", expanded=True)
                                                else:
                                                    status.update(label="Ολοκληρώθηκε!", state="complete", expanded=False)
                                        actions.append({'type': 'insert', 'table': 'assignments', 'records': new_assignments_batch})
                                    add_transaction(actions)
                                st.success("Η σειρά εργασιών ενημερώθηκε επιτυχώς! Η σελίδα ανανεώνεται...")
                                time.sleep(1.5)
                                st.rerun()

# --- VIEW: ΑΞΙΟΛΟΓΗΣΗ ΠΡΟΣΩΠΙΚΟΥ ---
elif menu == "Αξιολόγηση Προσωπικού":
    st.markdown("""
        <style>
        div[data-testid="stFormSubmitButton"] { position: fixed !important; bottom: 40px !important; right: 40px !important; z-index: 99999 !important; }
        div[data-testid="stFormSubmitButton"] button { box-shadow: 0px 8px 24px rgba(0, 0, 0, 0.4) !important; border: 3px solid #16a34a !important; border-radius: 50px !important; font-weight: bold !important; padding: 15px 30px !important; background-color: white !important; color: #16a34a !important; transition: all 0.2s ease-in-out !important; }
        div[data-testid="stFormSubmitButton"] button:hover { background-color: #16a34a !important; color: white !important; transform: scale(1.05) !important; }
        div[data-testid="stForm"] { padding-bottom: 120px !important; }
        </style>
    """, unsafe_allow_html=True)

    st.title("⭐ Αξιολόγηση Προσωπικού")

    months = ["Ιανουάριος", "Φεβρουάριος", "Μάρτιος", "Απρίλιος", "Μάιος", "Ιούνιος", "Ιούλιος", "Αύγουστος", "Σεπτέμβριος", "Οκτώβριος", "Νοέμβριος", "Δεκέμβριος"]
    current_month_index = date.today().month - 1
    current_year = date.today().year
    years = list(range(2020, 2036))

    col1, col2 = st.columns(2)
    with col1:
        selected_month_name = st.selectbox("Επιλογή Μήνα", months, index=current_month_index, key="eval_month")
        eval_month = months.index(selected_month_name) + 1
    with col2:
        eval_year = st.selectbox("Επιλογή Έτους", years, index=years.index(current_year), key="eval_year")

    st.divider()

    month_evals = [e for e in st.session_state.evaluations if e['month'] == eval_month and e['year'] == eval_year]

    if month_evals:
        for ev in month_evals: ev['avg'] = (ev.get('cooperation', 0) + ev.get('willingness', 0) + ev.get('behavior', 0)) / 3.0
        max_avg = max([ev['avg'] for ev in month_evals])
        top_evals = [ev for ev in month_evals if ev['avg'] == max_avg]

        st.markdown("### 🏆 Υπάλληλος του Μήνα")
        if max_avg > 0:
            for ev in top_evals:
                emp_name = get_employee_name(ev['employeeId'])
                st.success(f"🌟 **{emp_name}** — Υψηλότερος Μέσος Όρος: **{max_avg:.2f} / 5** 🌟")
        else:
            st.info("Οι βαθμολογίες για αυτόν τον μήνα είναι στο 0.")
    else:
        st.info("Δεν υπάρχουν ακόμα αποθηκευμένες βαθμολογίες για τον επιλεγμένο μήνα.")

    st.divider()
    
    col_title, col_reset = st.columns([3, 1])
    with col_title: st.write("### 📝 Φόρμα Βαθμολόγησης")
    with col_reset:
        if is_full_admin:
            if st.button("🔄 Επαναφορά Βαθμολογιών", use_container_width=True):
                evals_to_delete = [e['id'] for e in month_evals]
                if evals_to_delete:
                    st.session_state.evaluations = [e for e in st.session_state.evaluations if e['id'] not in evals_to_delete]
                    db_delete_in('evaluations', 'id', evals_to_delete, deleted_records=month_evals)
                for emp in active_employee_ids:
                    k_c = f"coop_{emp}_{eval_month}_{eval_year}"; k_w = f"will_{emp}_{eval_month}_{eval_year}"; k_b = f"behav_{emp}_{eval_month}_{eval_year}"
                    if k_c in st.session_state: del st.session_state[k_c]
                    if k_w in st.session_state: del st.session_state[k_w]
                    if k_b in st.session_state: del st.session_state[k_b]
                st.rerun()

    if not is_full_admin: st.info("⚠️ Έχετε δικαιώματα μόνο για ανάγνωση. Δεν μπορείτε να αποθηκεύσετε νέες αξιολογήσεις.")

    with st.form("evaluations_form"):
        hc1, hc2, hc3, hc4, hc5 = st.columns([2, 1.5, 1.5, 1.5, 1])
        hc1.write("**Ονοματεπώνυμο**"); hc2.write("**Συνεργασία (1-5)**"); hc3.write("**Προθυμία (1-5)**"); hc4.write("**Συμπεριφορά (1-5)**"); hc5.write("**Μ.Ό.**")
        st.markdown("---")

        eval_inputs = {}
        is_readonly = not is_full_admin

        for emp in active_employee_ids:
            emp_info = next(e for e in st.session_state.employees if e['id'] == emp)
            existing_eval = next((e for e in month_evals if e['employeeId'] == emp), None)

            default_coop = existing_eval['cooperation'] if existing_eval else 3
            default_will = existing_eval['willingness'] if existing_eval else 3
            default_behav = existing_eval['behavior'] if existing_eval else 3

            c1, c2, c3, c4, c5 = st.columns([2, 1.5, 1.5, 1.5, 1])
            c1.write(f"\n**{emp_info['name']}**")

            eval_inputs[emp] = {
                'coop': c2.selectbox("Συνεργασία", [1, 2, 3, 4, 5], index=default_coop - 1, key=f"coop_{emp}_{eval_month}_{eval_year}", label_visibility="collapsed", disabled=is_readonly),
                'will': c3.selectbox("Προθυμία", [1, 2, 3, 4, 5], index=default_will - 1, key=f"will_{emp}_{eval_month}_{eval_year}", label_visibility="collapsed", disabled=is_readonly),
                'behav': c4.selectbox("Συμπεριφορά", [1, 2, 3, 4, 5], index=default_behav - 1, key=f"behav_{emp}_{eval_month}_{eval_year}", label_visibility="collapsed", disabled=is_readonly),
                'existing_id': existing_eval['id'] if existing_eval else None
            }

            current_avg = (default_coop + default_will + default_behav) / 3.0
            c5.write(f"\n**{current_avg:.2f}**")

        st.markdown("---")
        submit_eval = st.form_submit_button("💾 Αποθήκευση Αξιολογήσεων", type="primary", use_container_width=True, disabled=is_readonly)

        if submit_eval and not is_readonly:
            updates_made = False
            actions = []
            with st.spinner("Αποθήκευση αξιολογήσεων..."):
                for emp_id, data in eval_inputs.items():
                    if data['existing_id']:
                        ev_to_update = next(e for e in st.session_state.evaluations if e['id'] == data['existing_id'])
                        if ev_to_update['cooperation'] != data['coop'] or ev_to_update['willingness'] != data['will'] or ev_to_update['behavior'] != data['behav']:
                            old_ev = dict(ev_to_update)
                            ev_to_update['cooperation'], ev_to_update['willingness'], ev_to_update['behavior'] = data['coop'], data['will'], data['behav']
                            payload = {k: v for k, v in ev_to_update.items() if k != 'avg'}
                            old_payload = {k: v for k, v in old_ev.items() if k != 'avg'}
                            db_update('evaluations', data['existing_id'], payload, track=False)
                            actions.append({'type': 'update', 'table': 'evaluations', 'old_records': [old_payload], 'new_records': [payload]})
                            updates_made = True
                    else:
                        new_eval = {'id': str(uuid.uuid4()), 'employeeId': emp_id, 'month': eval_month, 'year': eval_year, 'cooperation': data['coop'], 'willingness': data['will'], 'behavior': data['behav']}
                        st.session_state.evaluations.append(new_eval)
                        db_insert('evaluations', new_eval, track=False)
                        actions.append({'type': 'insert', 'table': 'evaluations', 'records': [new_eval]})
                        updates_made = True
            if actions: add_transaction(actions)
            if updates_made:
                st.success("Οι αξιολογήσεις αποθηκεύτηκαν επιτυχώς!")
                st.rerun()
            else: st.info("Δεν υπήρξαν αλλαγές για αποθήκευση.")

# --- VIEW: ΚΑΤΑΓΡΑΦΗ ΚΙΝΗΣΕΩΝ (ΜΟΝΟ ADMIN) ---
elif menu == "Καταγραφή Κινήσεων":
    st.title("📜 Καταγραφή Κινήσεων (Audit Log)")
    st.write("Παρακολουθήστε τις ενέργειες όλων των χρηστών στο σύστημα (Δημιουργία, Ενημέρωση, Διαγραφή).")
    
    col_b1, col_b2 = st.columns([1, 4])
    with col_b1:
        if st.button("🔄 Ανανέωση Ιστορικού", use_container_width=True):
            st.session_state.global_db_ts = "force_refresh"
            st.rerun()
    with col_b2:
        if st.button("🗑️ Καθαρισμός Ιστορικού", type="primary"):
            if supabase and st.session_state.activity_logs:
                try:
                    log_ids = [l['id'] for l in st.session_state.activity_logs]
                    chunk_size = 500
                    for i in range(0, len(log_ids), chunk_size):
                        supabase.table('activity_logs').delete().in_('id', log_ids[i:i+chunk_size]).execute()
                    st.session_state.activity_logs = []
                    st.session_state.global_db_ts = "force_refresh"
                    st.success("Το ιστορικό καθαρίστηκε!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Σφάλμα καθαρισμού: {e}")

    if not st.session_state.activity_logs:
        st.info("Δεν υπάρχουν καταγεγραμμένες κινήσεις ακόμα.")
    else:
        sorted_logs = sorted(st.session_state.activity_logs, key=lambda x: x.get('timestamp', ''), reverse=True)
        TABLE_NAMES_GR = {'employees': 'Προσωπικό', 'projects': 'Έργα', 'assignments': 'Βάρδιες', 'leaves': 'Άδειες', 'recurring_patterns': 'Επαν. Εργασίες', 'evaluations': 'Αξιολογήσεις'}
        
        log_data = []
        for log in sorted_logs:
            try: dt_str = datetime.fromisoformat(log.get('timestamp', '')).strftime("%d/%m/%Y %H:%M:%S")
            except: dt_str = log.get('timestamp', '')
            table_gr = TABLE_NAMES_GR.get(log.get('table_name', ''), log.get('table_name', '-'))
            details_safe = parse_old_log_details(log.get('table_name', ''), log.get('details', '-'))
            log_data.append({"Ημερομηνία/Ώρα": dt_str, "Χρήστης": log.get('username', '-'), "Ενέργεια": log.get('action_type', '-'), "Πίνακας (Στοιχείο)": table_gr, "Λεπτομέρειες": details_safe})
        
        st.dataframe(pd.DataFrame(log_data), use_container_width=True, hide_index=True)

# Στο τέλος του κώδικα, καθαρισμός μνήμης για να μην "κλατάρει" ο server
gc.collect()
