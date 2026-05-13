import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.express as px
from datetime import datetime, date, timedelta
import uuid
import calendar
import io
import time
import copy
import ast
import re
import textwrap

try:
    from supabase import create_client
    SUPABASE_INSTALLED = True
except ImportError:
    SUPABASE_INSTALLED = False

# --- Ρύθμιση σελίδας ---
st.set_page_config(page_title="Staff Manager Pro", layout="wide")

# --- GLOBAL STYLING & ΨΗΦΙΑΚΟ ΡΟΛΟΙ ---
# Προσθήκη CSS για ελαφριά εξωτερική σκίαση στο πλευρικό μενού (Sidebar)
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

# Προσθήκη αιωρούμενου Ψηφιακού Ρολογιού πιο αριστερά με Javascript (χωρίς να μπλοκάρει το Streamlit)
components.html("""
    <script>
        const doc = window.parent.document;
        let clockDiv = doc.getElementById("staff_pro_clock");
        
        // Δημιουργία του στοιχείου αν δεν υπάρχει
        if (!clockDiv) {
            clockDiv = doc.createElement("div");
            clockDiv.id = "staff_pro_clock";
            doc.body.appendChild(clockDiv);
        }
        
        // Επιβολή του CSS σε κάθε εκτέλεση (έτσι μετακινείται σίγουρα ακόμα κι αν υπήρχε ήδη)
        // Ρυθμίστηκε στο right: 300px για να είναι εντελώς μακριά από τα εικονίδια του Streamlit
        clockDiv.style.cssText = "position: fixed; top: 12px; right: 300px; font-size: 18px; font-weight: bold; color: #1e293b; z-index: 999999; background: #ffffff; padding: 6px 14px; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06); border: 1px solid #cbd5e1; font-family: 'Courier New', Courier, monospace; letter-spacing: 2px;";
        
        // Η ρουτίνα ανανέωσης ΠΡΕΠΕΙ να είναι έξω από το if(!clockDiv) 
        // ώστε το νέο iframe που φορτώνει το Streamlit να συνεχίζει να του δίνει "ζωή".
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
                # Έλεγχος κωδικών για κάθε χρήστη (Από secrets ή προεπιλεγμένοι)
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
    
    # Σταματάει την εκτέλεση του υπόλοιπου κώδικα αν δεν γίνει σύνδεση
    st.stop()


# Check if secrets exist safely
try:
    HAS_SECRETS = "SUPABASE_URL" in st.secrets and "SUPABASE_KEY" in st.secrets
except Exception:
    HAS_SECRETS = False

# --- ΣΥΣΤΗΜΑ UNDO / REDO ---
if "undo_stack" not in st.session_state:
    st.session_state.undo_stack = []
if "redo_stack" not in st.session_state:
    st.session_state.redo_stack = []

def add_transaction(actions):
    """Καταγράφει μια λίστα ενεργειών για το Undo"""
    st.session_state.undo_stack.append(actions)
    st.session_state.redo_stack.clear()
    if len(st.session_state.undo_stack) > 30: # Κρατάει ιστορικό 30 κινήσεων
        st.session_state.undo_stack.pop(0)

# --- SUPABASE CONNECTION & HELPERS ---
@st.cache_resource
def init_supabase():
    if not SUPABASE_INSTALLED:
        return None
    if HAS_SECRETS:
        try:
            return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
        except Exception:
            pass
    return None

supabase = init_supabase()

# --- ΒΕΛΤΙΣΤΟΠΟΙΗΜΕΝΟ ΣΥΣΤΗΜΑ CACHING (Micro-Caching) ---
CACHE_TTL = 60 # 60 δευτερόλεπτα προσωρινή μνήμη

def fetch_paginated(table):
    if not supabase:
        return []
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
        except Exception as e:
            print(f"Σφάλμα ανάγνωσης από τον πίνακα {table}: {e}")
            break
    return all_rows

@st.cache_data(ttl=CACHE_TTL)
def fetch_table_employees():
    return fetch_paginated("employees")

@st.cache_data(ttl=CACHE_TTL)
def fetch_table_projects():
    return fetch_paginated("projects")

@st.cache_data(ttl=CACHE_TTL)
def fetch_table_assignments():
    assigns = fetch_paginated("assignments")
    for a in assigns:
        if isinstance(a.get('date'), str):
            a['date'] = datetime.strptime(a['date'].split("T")[0], "%Y-%m-%d").date()
    return assigns

@st.cache_data(ttl=CACHE_TTL)
def fetch_table_leaves():
    leaves = fetch_paginated("leaves")
    for l in leaves:
        if isinstance(l.get('startDate'), str):
            l['startDate'] = datetime.strptime(l['startDate'].split("T")[0], "%Y-%m-%d").date()
        if isinstance(l.get('endDate'), str):
            l['endDate'] = datetime.strptime(l['endDate'].split("T")[0], "%Y-%m-%d").date()
    return leaves

@st.cache_data(ttl=CACHE_TTL)
def fetch_table_patterns():
    patterns = fetch_paginated("recurring_patterns")
    for p in patterns:
        if isinstance(p.get('startDate'), str):
            p['startDate'] = datetime.strptime(p['startDate'].split("T")[0], "%Y-%m-%d").date()
    return patterns

@st.cache_data(ttl=CACHE_TTL)
def fetch_table_evaluations():
    try:
        return fetch_paginated("evaluations")
    except Exception:
        return []

@st.cache_data(ttl=CACHE_TTL)
def fetch_table_activity_logs():
    try:
        return fetch_paginated("activity_logs")
    except Exception:
        return []

def clear_cache_for_table(table):
    """Καθαρίζει τη μνήμη ΜΟΝΟ για τον πίνακα που μόλις τροποποιήθηκε"""
    if table == "employees": fetch_table_employees.clear()
    elif table == "projects": fetch_table_projects.clear()
    elif table == "assignments": fetch_table_assignments.clear()
    elif table == "leaves": fetch_table_leaves.clear()
    elif table == "recurring_patterns": fetch_table_patterns.clear()
    elif table == "evaluations": fetch_table_evaluations.clear()
    elif table == "activity_logs": fetch_table_activity_logs.clear()

def clear_all_caches():
    """Εξαναγκάζει καθαρισμό σε όλους τους πίνακες (για το κουμπί Ανανέωσης)"""
    fetch_table_employees.clear()
    fetch_table_projects.clear()
    fetch_table_assignments.clear()
    fetch_table_leaves.clear()
    fetch_table_patterns.clear()
    fetch_table_evaluations.clear()
    fetch_table_activity_logs.clear()

def serialize_dates(data):
    """Μετατρέπει τα ημερολογιακά objects σε string για να μπουν σωστά στη βάση (Supabase/JSON)."""
    if isinstance(data, list):
        return [serialize_dates(item) for item in data]
    elif isinstance(data, dict):
        return {k: (v.isoformat() if isinstance(v, (datetime, date)) else v) for k, v in data.items()}
    return data

def format_log_details(table_name, records):
    """Μετατρέπει τα δεδομένα σε μορφή JSON (dict) σε φιλικό και ευανάγνωστο κείμενο."""
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
            emp_name = "Χωρίς Προσωπικό"
            if emp_id and 'employees' in st.session_state:
                e_info = next((e for e in st.session_state.employees if e['id'] == emp_id), None)
                if e_info: emp_name = e_info['name']
            
            proj_id = r.get('projectId')
            proj_name = "Άγνωστο Έργο"
            if proj_id and 'projects' in st.session_state:
                p_info = next((p for p in st.session_state.projects if p['id'] == proj_id), None)
                if p_info: proj_name = p_info['name']
                
            d = r.get('date', '')
            if isinstance(d, date): d = d.strftime('%d/%m/%Y')
            elif isinstance(d, str) and "T" in d: d = d.split("T")[0]
            
            lines.append(f"Βάρδια: {emp_name} στο '{proj_name}' ({d})")
            
        elif table_name == 'leaves':
            emp_id = r.get('employeeId')
            emp_name = "Άγνωστος"
            if emp_id and 'employees' in st.session_state:
                e_info = next((e for e in st.session_state.employees if e['id'] == emp_id), None)
                if e_info: emp_name = e_info['name']
            sd = r.get('startDate', '')
            ed = r.get('endDate', '')
            if isinstance(sd, date): sd = sd.strftime('%d/%m/%Y')
            if isinstance(ed, date): ed = ed.strftime('%d/%m/%Y')
            
            sub_str = ""
            sub_id = r.get('substituteId')
            if sub_id:
                sub_name = next((e['name'] for e in st.session_state.employees if e['id'] == sub_id), "Άγνωστος")
                sub_str = f" [Αντικατ: {sub_name}]"
                
            lines.append(f"Άδεια: {emp_name} ({sd} - {ed}){sub_str}")
            
        elif table_name == 'evaluations':
            emp_id = r.get('employeeId')
            emp_name = "Άγνωστος"
            if emp_id and 'employees' in st.session_state:
                e_info = next((e for e in st.session_state.employees if e['id'] == emp_id), None)
                if e_info: emp_name = e_info['name']
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
    """Παίρνει παλιές ακατέργαστες εγγραφές (raw dict/list strings) από τη βάση και τις μετατρέπει σε φιλικό κείμενο δυναμικά."""
    if not isinstance(details_str, str): return details_str
    if not (details_str.startswith("[{") or details_str.startswith("{")): return details_str
    
    try:
        # Αντικαθιστούμε τα datetime.date(Y, M, D) με απλά strings μορφής 'D/M/Y' για να περάσουν από την eval
        clean_str = re.sub(r"datetime\.date\((\d+),\s*(\d+),\s*(\d+)\)", r"'\3/\2/\1'", details_str)
        parsed_data = ast.literal_eval(clean_str)
        return format_log_details(table_name, parsed_data)
    except Exception:
        return details_str

def log_activity(action_type, table_name, details_raw):
    """Καταγράφει την ενέργεια του χρήστη στον πίνακα activity_logs"""
    if not supabase: return
    if table_name == 'activity_logs': return 
    
    user = st.session_state.get("current_user", "Άγνωστος")
    try:
        from zoneinfo import ZoneInfo
        now_gr = datetime.now(ZoneInfo("Europe/Athens")).isoformat()
    except Exception:
        now_gr = (datetime.utcnow() + timedelta(hours=3)).isoformat()
        
    detail_str = str(details_raw)[:2000]
    log_entry = {"id": str(uuid.uuid4()), "timestamp": now_gr, "username": user, "action_type": action_type, "table_name": table_name, "details": detail_str}
    try:
        supabase.table("activity_logs").insert(log_entry).execute()
        clear_cache_for_table("activity_logs")
    except Exception as e:
        print(f"Σφάλμα αποθήκευσης στο Ιστορικό (activity_logs): {e}")

def db_insert(table, data, track=True):
    if supabase:
        try:
            supabase.table(table).insert(serialize_dates(data)).execute()
            clear_cache_for_table(table)
            if track:
                records = data if isinstance(data, list) else [data]
                add_transaction([{'type': 'insert', 'table': table, 'records': records}])
            details_str = format_log_details(table, data)
            log_activity("ΠΡΟΣΘΗΚΗ", table, details_str)
        except Exception as e:
            st.error(f"Σφάλμα αποθήκευσης στη βάση (Table: {table}): {e}")

def db_delete(table, column, value, deleted_records=None, track=True):
    if supabase:
        try:
            if not deleted_records:
                table_data = st.session_state.get(table, [])
                deleted_records = [r for r in table_data if r.get(column) == value]
            supabase.table(table).delete().eq(column, value).execute()
            clear_cache_for_table(table)
            if track and deleted_records:
                add_transaction([{'type': 'delete', 'table': table, 'records': deleted_records}])
            details_str = format_log_details(table, deleted_records) if deleted_records else f"{column} = {value}"
            log_activity("ΔΙΑΓΡΑΦΗ", table, details_str)
        except Exception as e:
            st.error(f"Σφάλμα διαγραφής στη βάση: {e}")

def db_delete_in(table, column, values, deleted_records=None, track=True):
    if supabase and values:
        try:
            if not deleted_records:
                table_data = st.session_state.get(table, [])
                deleted_records = [r for r in table_data if r.get(column) in values]
            supabase.table(table).delete().in_(column, values).execute()
            clear_cache_for_table(table)
            if track and deleted_records:
                add_transaction([{'type': 'delete', 'table': table, 'records': deleted_records}])
            details_str = format_log_details(table, deleted_records) if deleted_records else f"{len(values)} εγγραφές"
            log_activity("ΜΑΖΙΚΗ ΔΙΑΓΡΑΦΗ", table, details_str)
        except Exception as e:
            st.error(f"Σφάλμα μαζικής διαγραφής: {e}")

def db_update(table, id_val, new_data, old_data=None, track=True):
    if supabase:
        try:
            if track and not old_data:
                table_data = st.session_state.get(table, [])
                old_data = next((r for r in table_data if r.get('id') == id_val), None)
            supabase.table(table).update(serialize_dates(new_data)).eq('id', id_val).execute()
            clear_cache_for_table(table)
            if track and old_data:
                add_transaction([{'type': 'update', 'table': table, 'old_records': [old_data], 'new_records': [new_data]}])
            details_str = format_log_details(table, new_data)
            log_activity("ΕΝΗΜΕΡΩΣΗ", table, details_str)
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
    clear_all_caches()

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
    clear_all_caches()

# --- 10 Βασικά Χρώματα ---
BASIC_COLORS = {
    "Μπλε": "#4a86e8", "Κόκκινο": "#e00000", "Πράσινο": "#6aa84f", "Κίτρινο": "#f1c232",
    "Μωβ": "#8e7cc3", "Πορτοκαλί": "#e69138", "Γαλάζιο": "#00ffff", "Ροζ": "#c90076",
    "Σκούρο Πράσινο": "#38761d", "Γκρι": "#999999"
}

# --- Συνεχής Φόρτωση Δεδομένων (Real-time Sync Logic) ---
if supabase:
    st.session_state.employees = fetch_table_employees()
    st.session_state.projects = fetch_table_projects()
    st.session_state.assignments = fetch_table_assignments()
    st.session_state.leaves = fetch_table_leaves()
    st.session_state.recurring_patterns = fetch_table_patterns()
    st.session_state.evaluations = fetch_table_evaluations()
    st.session_state.activity_logs = fetch_table_activity_logs()
    st.session_state.is_cloud = True
else:
    if 'local_data_loaded' not in st.session_state:
        st.session_state.local_data_loaded = True
        st.session_state.is_cloud = False
        st.session_state.employees = [
            {'id': '1', 'name': 'Γιάννης Παπαδόπουλος', 'position': 'ΕΡΓΑΤΗΣ', 'id_number': 'ΑΙ123456', 'phone': '6912345678', 'status': 'Ενεργός'},
            {'id': '2', 'name': 'Μαρία Παππά', 'position': 'ΕΠΟΠΤΗΣ', 'id_number': 'ΑΚ654321', 'phone': '6987654321', 'status': 'Ενεργός'},
            {'id': '3', 'name': 'Νίκος Νικολάου', 'position': 'ΟΔΗΓΟΣ', 'id_number': 'ΑΜ987654', 'phone': '6900000000', 'status': 'Ενεργός'},
        ]
        st.session_state.projects = [
            {'id': 'p1', 'name': 'Ανακαίνιση Γραφείων', 'color': '#4a86e8'},
            {'id': 'p2', 'name': 'Συντήρηση Δικτύου', 'color': '#e69138'},
        ]
        st.session_state.assignments = []
        st.session_state.recurring_patterns = []
        st.session_state.leaves = []
        st.session_state.evaluations = []
        st.session_state.activity_logs = []

if 'view_week_date' not in st.session_state:
    st.session_state.view_week_date = date.today()

# --- Helpers ---
def get_employee_name(emp_id):
    if not emp_id: return "Χωρίς Προσωπικό"
    for emp in st.session_state.employees:
        if emp['id'] == emp_id: return emp['name']
    return "Άγνωστος"

def get_project_info(proj_id):
    for proj in st.session_state.projects:
        if proj['id'] == proj_id: return proj
    return None

def is_on_leave(emp_id, check_date):
    if not emp_id: return False
    for l in st.session_state.leaves:
        if l['employeeId'] == emp_id and l['startDate'] <= check_date <= l['endDate']:
            return True
    return False

def check_and_resolve_conflict(emp_id, check_date, t_start, t_end, exclude_ids=None):
    """
    Ελέγχει αν υπάρχει επικάλυψη ωραρίου.
    Εάν ο υπάλληλος εργάζεται σε άλλο έργο που τελειώνει πριν από το νέο έργο,
    προσαρμόζει ΑΥΤΟΜΑΤΑ την ώρα έναρξής του για να μη χτυπάει σφάλμα (διπλοκράτηση).
    """
    if not emp_id: return t_start, t_end, False, ""
    if exclude_ids is None: exclude_ids = []
    
    new_s = datetime.strptime(t_start, "%H:%M").time()
    new_e = datetime.strptime(t_end, "%H:%M").time()
    
    emp_assigns = [a for a in st.session_state.assignments if a['employeeId'] == emp_id and a['date'] == check_date and a['id'] not in exclude_ids]
    emp_assigns.sort(key=lambda x: datetime.strptime(x['startTime'], "%H:%M").time())
    
    adjusted = False
    for ea in emp_assigns:
        ea_s = datetime.strptime(ea['startTime'], "%H:%M").time()
        ea_e = datetime.strptime(ea['endTime'], "%H:%M").time()
        
        # Έλεγχος επικάλυψης
        if new_s < ea_e and new_e > ea_s:
            # Αν η υπάρχουσα βάρδια τελειώνει πριν τη λήξη της νέας ΚΑΙ ξεκινάει πριν ή ταυτόχρονα με τη νέα
            if ea_e < new_e and ea_s <= new_s:
                new_s = max(new_s, ea_e)
                adjusted = True
            else:
                return t_start, t_end, True, "Μη επιλύσιμη επικάλυψη"
                
    if new_s >= new_e:
        return t_start, t_end, True, "Μη επιλύσιμη επικάλυψη"
        
    return new_s.strftime("%H:%M"), new_e.strftime("%H:%M"), False, "Adjusted" if adjusted else ""

def go_prev_week(): st.session_state.view_week_date -= timedelta(days=7)
def go_next_week(): st.session_state.view_week_date += timedelta(days=7)
def go_to_today(): st.session_state.view_week_date = date.today()

is_full_admin = st.session_state.get('current_user') != "TAN"

# --- Sidebar Navigation ---
st.sidebar.title("STAFF.PRO")
menu_options = ["Ταμπλό Gantt", "Διαχείριση Έργων", "Ομάδα Προσωπικού", "Άδειες", "Σύνολο Αδειών", "Επαναλαμβανόμενες Εργασίες", "Ώρες Εργασιών", "Αξιολόγηση Προσωπικού"]
if st.session_state.get('current_user') == "Admin": menu_options.append("Καταγραφή Κινήσεων")
menu = st.sidebar.radio("Μενού", menu_options)

st.sidebar.write("---")
st.sidebar.subheader("Ενέργειες")
col_u, col_r = st.sidebar.columns(2)
with col_u:
    if st.button("↩️ Undo", disabled=len(st.session_state.undo_stack) == 0, use_container_width=True):
        perform_undo(); st.rerun()
with col_r:
    if st.button("↪️ Redo", disabled=len(st.session_state.redo_stack) == 0, use_container_width=True):
        perform_redo(); st.rerun()

st.sidebar.write("---")
st.sidebar.subheader("Κατάσταση Συστήματος")
if st.session_state.get('is_cloud'):
    st.sidebar.success(f"✅ Cloud Sync (Ανανέωση {CACHE_TTL}s)")
    if st.sidebar.button("🔄 Άμεση Ανανέωση", use_container_width=True):
        clear_all_caches(); st.rerun()
else:
    st.sidebar.error("❌ Εκτός Σύνδεσης (Τοπικά)")

st.sidebar.write("---")
st.sidebar.markdown(f"👤 Συνδεδεμένος ως: **{st.session_state.get('current_user', 'Άγνωστος')}**")
if st.sidebar.button("🚪 Αποσύνδεση", use_container_width=True):
    st.session_state.authenticated, st.session_state.current_user = False, None
    st.rerun()

active_employee_ids = [e['id'] for e in st.session_state.employees if e.get('status', 'Ενεργός') == 'Ενεργός']

# --- ΣΥΣΤΗΜΑ ΕΙΔΟΠΟΙΗΣΕΩΝ (ALERTS) ---
today_date = date.today()
next_week_date = today_date + timedelta(days=7)
orphan_count, orphan_details = 0, []
for a in st.session_state.assignments:
    shift_date = a.get('date')
    if today_date <= shift_date <= next_week_date:
        if not a.get('employeeId') and not a.get('is_cancelled', False):
            orphan_count += 1
            proj = get_project_info(a['projectId'])
            proj_name = proj['name'] if proj else "Άγνωστο Έργο"
            orphan_details.append(f"• **{shift_date.strftime('%d/%m/%Y')}** | Ώρες: {a['startTime']}-{a['endTime']} | Έργο: **{proj_name}**")

if orphan_count > 0:
    st.error(f"🚨 **Προσοχή: {orphan_count} βάρδια/ες τις επόμενες 7 ημέρες έμειναν ορφανές (χωρίς προσωπικό)!**")
    with st.expander("👁️ Δείτε αναλυτικά τις ορφανές βάρδιες"):
        for detail in orphan_details: st.markdown(detail)
    st.write("---")

# --- VIEW: DASHBOARD (GANTT) ---
if menu == "Ταμπλό Gantt":
    st.title("📅 Εβδομαδιαίο Χρονοδιάγραμμα Πόρων")
    
    col_nav1, col_date, col_nav2, col_today, col_zoom, col_pres = st.columns([1, 2, 1, 1, 2, 2.5])
    with col_nav1:
        st.write(""); st.button("⬅️ Προηγούμενη", on_click=go_prev_week, use_container_width=True)
    with col_date:
        selected_date = st.date_input("Επιλογή Εβδομάδας", key="view_week_date")
        start_of_week = selected_date - timedelta(days=selected_date.weekday())
    with col_nav2:
        st.write(""); st.button("Επόμενη ➡️", on_click=go_next_week, use_container_width=True)
    with col_today:
        st.write(""); st.button("🏠 Σήμερα", on_click=go_to_today, use_container_width=True)
    with col_zoom:
        zoom_level = st.slider("🔍 Ζουμ Διαγράμματος (%)", min_value=50, max_value=200, value=100, step=5)
    with col_pres:
        st.write(""); st.write("")
        presentation_mode = st.checkbox("🖥️ Λειτουργία Πλήρους Προβολής")
        
    zoom_factor = zoom_level / 100.0
    
    data, export_data, color_map, y_category_order, tickvals_map, empty_shift_annotations = [], [], {}, [], {}, []
    day_names_gr = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
    wk_groups = {} 

    for i in range(7):
        curr_date = start_of_week + timedelta(days=i)
        day_str = f"{day_names_gr[i]} {curr_date.strftime('%d/%m')}"
        
        leaves_today = []
        for l in st.session_state.leaves:
            if l['startDate'] <= curr_date <= l['endDate']:
                emp_full = get_employee_name(l['employeeId'])
                emp_parts = emp_full.split()
                emp_n = f"{emp_parts[-1]} {emp_parts[0][0]}." if len(emp_parts) > 1 else emp_full
                
                sub_id = l.get('substituteId')
                if sub_id:
                    sub_full = get_employee_name(sub_id)
                    sub_parts = sub_full.split()
                    sub_n = f"{sub_parts[-1]} {sub_parts[0][0]}." if len(sub_parts) > 1 else sub_full
                    leaves_today.append(f"<b>{emp_n}</b><br><span style='font-size:10px; color:#991b1b;'>↳ Αντικατ: <b>{sub_n}</b></span>")
                else:
                    leaves_today.append(f"<b>{emp_n}</b>")
                    
        leaves_str = "<br><br>".join(leaves_today) if leaves_today else "Καμία"
        if leaves_today: base_y_label = f"<b>{day_str}</b><br><span style='font-size:11px; color:#d32f2f;'>Άδειες:<br>{leaves_str}</span>"
        else: base_y_label = f"<b>{day_str}</b><br><span style='font-size:11px; color:#d32f2f;'>Άδειες: {leaves_str}</span>"
        
        day_assignments = [a for a in st.session_state.assignments if a['date'] == curr_date]
        day_row_ids = []
        
        if not day_assignments:
            row_id = f"day_{i}_row_0"
            day_row_ids.append(row_id)
            data.append({'Y_Axis': row_id, 'Έργο': 'Κενό', 'Έναρξη': datetime(1970, 1, 1, 8, 0), 'Λήξη': datetime(1970, 1, 1, 8, 0), 'Προσωπικό': '', 'Παρατηρήσεις': '', 'Ετικέτα': '', 'LegendGroup': 'Κενό', 'ColorHex': 'rgba(0,0,0,0)', 'GroupKey': 'Empty'})
            color_map['Κενό'] = 'rgba(0,0,0,0)'
        else:
            groups = {}
            for a in day_assignments:
                proj = get_project_info(a['projectId'])
                c_hex = a.get('colorHex', proj['color'] if proj else "#999999")
                c_name = a.get('colorName', "Προεπιλογή")
                notes = a.get('notes', '')
                is_canc = a.get('is_cancelled', False)
                c_reason = a.get('cancel_reason', '')
                
                key = f"{curr_date}_{a['projectId']}_{a['startTime']}_{a['endTime']}_{c_hex}_{notes}_{is_canc}_{c_reason}"
                if key not in groups:
                    groups[key] = {
                        'Key': key, 'ProjectId': a['projectId'], 'Date': curr_date, 'Project': proj['name'] if proj else "Άγνωστο",
                        'StartTime': a['startTime'], 'EndTime': a['endTime'],
                        'Start': datetime.combine(datetime(1970, 1, 1), datetime.strptime(a['startTime'], "%H:%M").time()),
                        'End': datetime.combine(datetime(1970, 1, 1), datetime.strptime(a['endTime'], "%H:%M").time()),
                        'Employees': [], 'EmployeeIds': [], 'AssignmentIds': [], 'ColorHex': c_hex, 'ColorName': c_name, 'Notes': notes, 'is_cancelled': is_canc, 'cancel_reason': c_reason, 'LegendGroup': f"{proj['name'] if proj else 'Άγνωστο'} ({c_name})"
                    }
                
                if not a.get('employeeId'):
                    formatted_name = "ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ"
                else:
                    full_name = get_employee_name(a['employeeId'])
                    name_parts = full_name.split()
                    formatted_name = f"{name_parts[-1]} {name_parts[0][0]}." if len(name_parts) > 1 else full_name
                        
                    # Εντοπισμός προηγούμενου έργου την ίδια μέρα για τον συγκεκριμένο υπάλληλο ("μετά από το...")
                    prev_assigns = [pa for pa in day_assignments if pa.get('employeeId') == a['employeeId'] and pa.get('id') != a['id'] and datetime.strptime(pa['endTime'][:5], "%H:%M").time() <= datetime.strptime(a['startTime'][:5], "%H:%M").time()]
                    if prev_assigns:
                        prev_assigns.sort(key=lambda x: datetime.strptime(x['endTime'][:5], "%H:%M").time(), reverse=True)
                        prev_proj = get_project_info(prev_assigns[0]['projectId'])
                        if prev_proj:
                            formatted_name = f"μετά από το '{prev_proj['name']}' {formatted_name}"
                    
                groups[key]['Employees'].append(formatted_name)
                groups[key]['EmployeeIds'].append(a['employeeId'])
                groups[key]['AssignmentIds'].append(a['id'])

            wk_groups.update(groups)

            non_blue_groups = [g for g in groups.values() if g['ColorHex'].lower() != "#4a86e8"]
            blue_groups = [g for g in groups.values() if g['ColorHex'].lower() == "#4a86e8"]
            
            non_blue_lanes, group_row_mapping = [], []
            for g in sorted(non_blue_groups, key=lambda x: x['Start']):
                placed = False
                for lane_idx, lane_end in enumerate(non_blue_lanes):
                    if g['Start'] >= lane_end:
                        row_idx = lane_idx
                        non_blue_lanes[lane_idx] = g['End']
                        placed = True; break
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
                        placed = True; break
                if not placed:
                    blue_lanes.append(g['End'])
                    row_idx = len(blue_lanes) - 1
                group_row_mapping.append((g, row_idx + num_non_blue_lanes))

            for g, row_idx in group_row_mapping:
                row_id = f"day_{i}_row_{row_idx}"
                if row_id not in day_row_ids: day_row_ids.append(row_id)
                
                emps_str = ", ".join(g['Employees']).upper()
                base_text = f"{g['StartTime']}-{g['EndTime']} {g['Project'].upper()} // {emps_str}"
                if g['Notes']: base_text += f" ({g['Notes'].upper()})"
                    
                duration_hours = (g['End'] - g['Start']).total_seconds() / 3600.0
                wrap_w = max(15, int(duration_hours * 16))
                wrapped_base = "<br>".join(textwrap.wrap(base_text, width=wrap_w))
                
                if "ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ" in emps_str:
                    empty_shift_annotations.append(dict(x=g['End'], y=row_id, text="🔴", showarrow=False, xanchor='right', yanchor='middle', xshift=-4, yshift=int(28 * zoom_factor), font=dict(size=max(10, int(14 * zoom_factor)))))
                
                if g['is_cancelled']:
                    label_text = f"<s>{wrapped_base}</s>"
                    if g['cancel_reason']: label_text += f"<br><span style='color:#dc2626;'><b>{'<br>'.join(textwrap.wrap(f'[{g['cancel_reason'].upper()}]', width=wrap_w))}</b></span>"
                else: label_text = wrapped_base
                    
                data.append({'Y_Axis': row_id, 'Έργο': g['Project'], 'Έναρξη': g['Start'], 'Λήξη': g['End'], 'Προσωπικό': ", ".join(g['Employees']), 'Παρατηρήσεις': g['Notes'], 'Ετικέτα': label_text, 'LegendGroup': g['LegendGroup'], 'ColorHex': g['ColorHex'], 'GroupKey': g['Key']})
                export_data.append({'Ημερομηνία': curr_date.strftime('%d/%m/%Y'), 'Ημέρα': day_names_gr[i], 'Έργο': g['Project'], 'Προσωπικό': ", ".join(g['Employees']), 'Ώρα Έναρξης': g['StartTime'], 'Ώρα Λήξης': g['EndTime'], 'Παρατηρήσεις': g['Notes'], 'Ακυρωμένο': 'ΝΑΙ' if g['is_cancelled'] else 'ΟΧΙ', 'Λόγος Ακύρωσης': g['cancel_reason']})
                color_map[g['LegendGroup']] = g['ColorHex']
                
        y_category_order.extend(day_row_ids)
        mid_idx = len(day_row_ids) // 2
        for idx, rid in enumerate(day_row_ids): tickvals_map[rid] = base_y_label if idx == mid_idx else ""
            
    df = pd.DataFrame(data)
    ordered_categories = y_category_order[::-1]
    
    fig = px.timeline(df, x_start="Έναρξη", x_end="Λήξη", y="Y_Axis", color="LegendGroup", color_discrete_map=color_map, custom_data=["GroupKey"], hover_data=["Έργο", "Προσωπικό", "Παρατηρήσεις"], text="Ετικέτα")
    
    for di in range(7):
        day_idxs = [idx for idx, val in enumerate(ordered_categories) if val.startswith(f"day_{di}_")]
        if day_idxs:
            mn, mx = min(day_idxs), max(day_idxs)
            if di % 2 != 0: fig.add_hrect(y0=mn-0.5, y1=mx+0.5, fillcolor="rgba(0, 0, 0, 0.05)", opacity=1, layer="below", line_width=0)
            if (start_of_week + timedelta(days=di)) == date.today(): fig.add_hrect(y0=mn-0.5, y1=mx+0.5, fillcolor="#b2d8ce", opacity=1, layer="below", line_width=0)

    for idx in range(len(ordered_categories) - 1):
        if ordered_categories[idx].split('_')[1] != ordered_categories[idx+1].split('_')[1]:
            fig.add_shape(type="line", x0=0, x1=1, xref="paper", y0=idx+0.5, y1=idx+0.5, yref="y", line=dict(color="#000000", width=4))

    row_h = 75 * zoom_factor
    visible_count = 650 / row_h
    
    if presentation_mode or len(ordered_categories) <= visible_count: dyn_h, y_range = max(500, int(len(ordered_categories) * row_h) + 100), None
    else:
        dyn_h = 750
        offset = (date.today() - start_of_week).days
        if 0 <= offset <= 6:
            idxs = [idx for idx, val in enumerate(ordered_categories) if val.startswith(f"day_{offset}_")]
            if idxs:
                mid = sum(idxs) / len(idxs)
                y_range = [max(-0.5, mid - visible_count/2), min(len(ordered_categories)-0.5, mid + visible_count/2)]
            else: y_range = [len(ordered_categories) - visible_count - 0.5, len(ordered_categories) - 0.5]
        else: y_range = [len(ordered_categories) - visible_count - 0.5, len(ordered_categories) - 0.5]

    fig.update_yaxes(categoryorder='array', categoryarray=ordered_categories, tickmode='array', tickvals=ordered_categories, ticktext=[tickvals_map[v] for v in ordered_categories], showgrid=True, gridcolor='rgba(0,0,0,0.1)', gridwidth=1)
    fig.update_traces(textposition='inside', insidetextanchor='middle', textfont=dict(color='black', size=max(8, int(10*zoom_factor)), family="Arial Black, Arial, sans-serif"), marker=dict(line=dict(color='black', width=1)), textangle=0)
    
    fig.update_layout(
        bargap=0.15, showlegend=False, plot_bgcolor='#dbece8', paper_bgcolor='#ffffff', height=dyn_h, margin=dict(l=10, r=10, t=50, b=10), annotations=empty_shift_annotations, dragmode="pan", uirevision="constant",
        xaxis=dict(side='top', tickmode='linear', tick0=datetime(1970, 1, 1, 0, 0), dtick=1800000, tickformat="%H:%M", showgrid=True, gridcolor='black', gridwidth=1, range=[datetime(1970, 1, 1, 6, 0), datetime(1970, 1, 1, 17, 0)], title="", tickfont=dict(size=max(8, int(11 * zoom_factor)), color="black", family="Arial"), fixedrange=False, rangeslider=dict(visible=False)),
        yaxis=dict(title="", tickfont=dict(size=max(8, int(12 * zoom_factor)), color="black"), fixedrange=False, range=y_range)
    )
    
    clicked_key = None
    try:
        event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", selection_mode="points", config={"displayModeBar": False})
        if event and "selection" in event and event["selection"].get("points"): clicked_key = event["selection"]["points"][0].get("customdata", [None])[0]
    except Exception: st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    
    if export_data:
        col_hint, col_btn = st.columns([3, 1])
        with col_hint: st.caption("💡 *Συμβουλές:* **1)** Κλικ σε μια μπάρα για επεξεργασία. **2)** Σύρετε το γράφημα πάνω-κάτω.")
        with col_btn:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer: pd.DataFrame(export_data).to_excel(writer, index=False, sheet_name='Πρόγραμμα')
            st.download_button(label="📥 Εξαγωγή", data=buffer.getvalue(), file_name=f"Gantt_{start_of_week.strftime('%d_%m_%Y')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    else: st.caption("💡 *Συμβουλές:* **1)** Κλικ σε μια μπάρα για επεξεργασία. **2)** Σύρετε το γράφημα πάνω-κάτω.")

    if not presentation_mode:
        st.divider()

        if is_full_admin:
            col_add, col_edit = st.columns(2)

            with col_add:
                st.subheader("➕ Νέα Τοποθέτηση")
                
                if "qa_rc" not in st.session_state: st.session_state.qa_rc = 0
                qa_rc = st.session_state.qa_rc
                
                with st.form("quick_add", clear_on_submit=True):
                    add_date = st.date_input("Ημερομηνία", value=selected_date, key=f"qa_date_{qa_rc}")
                    proj_choice = st.selectbox("Επιλογή Έργου", options=[p['id'] for p in st.session_state.projects], format_func=lambda x: next((p['name'] for p in st.session_state.projects if p['id'] == x), "Άγνωστο"), key=f"qa_proj_{qa_rc}")
                    custom_proj_name = st.text_input("Ή Νέο Έργο (Αν συμπληρωθεί, αγνοεί τη λίστα)", key=f"qa_cproj_{qa_rc}")
                    emp_choices = st.multiselect("Προσωπικό", options=active_employee_ids, format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), "Άγνωστος"), key=f"qa_emps_{qa_rc}")
                    
                    c_color, c_notes = st.columns(2)
                    with c_color: color_choice = st.selectbox("Χρώμα Μπάρας", options=list(BASIC_COLORS.keys()), key=f"qa_color_{qa_rc}")
                    with c_notes: add_notes = st.text_input("Παρατηρήσεις", key=f"qa_notes_{qa_rc}")
                    
                    c_start, c_end = st.columns(2)
                    with c_start: t_start = st.time_input("Έναρξη", value=datetime.strptime("09:00", "%H:%M").time(), key=f"qa_start_{qa_rc}")
                    with c_end: t_end = st.time_input("Λήξη", value=datetime.strptime("17:00", "%H:%M").time(), key=f"qa_end_{qa_rc}")
                        
                    if st.form_submit_button("Καταχώρηση"):
                        str_start, str_end = t_start.strftime("%H:%M"), t_end.strftime("%H:%M")
                        if str_start >= str_end: st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                        elif not custom_proj_name.strip() and not proj_choice: st.error("Παρακαλώ επιλέξτε Έργο.")
                        else:
                            emps_to_process = emp_choices if emp_choices else [""]
                            errors, new_b = [], []
                            
                            final_proj_id = str(uuid.uuid4()) if custom_proj_name.strip() else proj_choice
                            
                            for eid in emps_to_process:
                                if eid:
                                    emp_name = get_employee_name(eid)
                                    if is_on_leave(eid, add_date):
                                        errors.append(f"Ο/Η {emp_name} έχει άδεια.")
                                        st.toast(f"🛑 {emp_name} έχει άδεια!", icon="🛑")
                                    else:
                                        adj_start, adj_end, is_conflict, msg = check_and_resolve_conflict(eid, add_date, str_start, str_end)
                                        if is_conflict:
                                            errors.append(f"⚠️ ΔΙΠΛΟΚΡΑΤΗΣΗ για τον/την {emp_name}.")
                                            st.toast(f"🚨 Διπλοκράτηση {emp_name}!", icon="🚨")
                                        else:
                                            if msg == "Adjusted": st.toast(f"🔄 Ο/Η {emp_name} ξεκινά {adj_start} λόγω προηγούμενης βάρδιας.", icon="🔄")
                                            new_b.append({'id': str(uuid.uuid4()), 'employeeId': eid, 'projectId': final_proj_id, 'date': add_date, 'startTime': adj_start, 'endTime': adj_end, 'colorName': color_choice, 'colorHex': BASIC_COLORS[color_choice], 'notes': add_notes, 'is_cancelled': False, 'cancel_reason': "", 'recurring_id': None})
                                else:
                                    new_b.append({'id': str(uuid.uuid4()), 'employeeId': eid, 'projectId': final_proj_id, 'date': add_date, 'startTime': str_start, 'endTime': str_end, 'colorName': color_choice, 'colorHex': BASIC_COLORS[color_choice], 'notes': add_notes, 'is_cancelled': False, 'cancel_reason': "", 'recurring_id': None})
                            
                            if errors:
                                for err in errors: st.error(err)
                            else:
                                actions = []
                                if custom_proj_name.strip():
                                    new_p = {'id': final_proj_id, 'name': custom_proj_name.strip(), 'color': BASIC_COLORS[color_choice]}
                                    st.session_state.projects.append(new_p)
                                    db_insert('projects', new_p, track=False)
                                    actions.append({'type': 'insert', 'table': 'projects', 'records': [new_p]})
                                
                                st.session_state.assignments.extend(new_b)
                                db_insert("assignments", new_b, track=False)
                                actions.append({'type': 'insert', 'table': 'assignments', 'records': new_b})
                                add_transaction(actions)
                                
                                st.success("Ολοκληρώθηκε!")
                                time.sleep(1); st.session_state.qa_rc += 1; st.rerun()

            with col_edit:
                st.subheader("✏️ Επεξεργασία Μπάρας της Εβδομάδας")
                if not wk_groups: st.info("Δεν υπάρχουν μπάρες.")
                else:
                    group_keys = list(wk_groups.keys())
                    group_keys.sort(key=lambda k: (wk_groups[k]['Date'], wk_groups[k]['StartTime']))
                    default_idx = group_keys.index(clicked_key) + 1 if clicked_key in group_keys else 0
                    
                    selected_key = st.selectbox("Επιλέξτε Μπάρα", options=[""] + group_keys, index=default_idx, format_func=lambda x: "Επιλέξτε..." if x == "" else f"{wk_groups[x]['Date'].strftime('%d/%m')} - {wk_groups[x]['Project']} ({wk_groups[x]['StartTime']}-{wk_groups[x]['EndTime']})")
                    
                    if selected_key != "":
                        target_group = wk_groups[selected_key]
                        
                        st.markdown("⚡ **Γρήγορη Μετακίνηση** (Αντί για Drag & Drop)")
                        qm_c1, qm_c2, qm_c3, qm_c4 = st.columns(4)
                        move_m_day, move_p_day, move_m_hour, move_p_hour = qm_c1.button("⬅️ -1 Μέρα", use_container_width=True), qm_c2.button("➡️ +1 Μέρα", use_container_width=True), qm_c3.button("⏪ -1 Ώρα", use_container_width=True), qm_c4.button("⏩ +1 Ώρα", use_container_width=True)
                        
                        if any([move_m_day, move_p_day, move_m_hour, move_p_hour]):
                            d_d, d_h = -1 if move_m_day else (1 if move_p_day else 0), -1 if move_m_hour else (1 if move_p_hour else 0)
                            has_error, new_assigns, old_assigns = False, [], []
                            
                            for a_id in target_group['AssignmentIds']:
                                orig_a = next(a for a in st.session_state.assignments if a['id'] == a_id)
                                new_a = dict(orig_a)
                                if d_d != 0: new_a['date'] = orig_a['date'] + timedelta(days=d_d)
                                if d_h != 0:
                                    dummy = datetime(2000, 1, 1)
                                    new_s_dt = datetime.combine(dummy, datetime.strptime(orig_a['startTime'], "%H:%M").time()) + timedelta(hours=d_h)
                                    new_e_dt = datetime.combine(dummy, datetime.strptime(orig_a['endTime'], "%H:%M").time()) + timedelta(hours=d_h)
                                    if new_s_dt.date() != dummy.date() or new_e_dt.date() != dummy.date():
                                        st.error("Η αλλαγή ώρας ξεπερνάει τα όρια της ημέρας."); has_error = True; break
                                    new_a['startTime'], new_a['endTime'] = new_s_dt.strftime("%H:%M"), new_e_dt.strftime("%H:%M")
                                    
                                if new_a['employeeId']:
                                    emp_name = get_employee_name(new_a['employeeId'])
                                    if is_on_leave(new_a['employeeId'], new_a['date']):
                                        st.toast(f"🛑 Αδύνατη μετακίνηση: {emp_name} έχει άδεια!", icon="🛑"); has_error = True; break
                                    
                                    adj_start, adj_end, is_conflict, msg = check_and_resolve_conflict(new_a['employeeId'], new_a['date'], new_a['startTime'], new_a['endTime'], exclude_ids=target_group['AssignmentIds'])
                                    if is_conflict:
                                        st.toast(f"🚨 Αδύνατη μετακίνηση: Διπλοκράτηση {emp_name}!", icon="🚨"); has_error = True; break
                                    
                                    new_a['startTime'], new_a['endTime'] = adj_start, adj_end
                                    if msg == "Adjusted": st.toast(f"🔄 Αυτόματη προσαρμογή έναρξης {adj_start} ({emp_name}).", icon="🔄")
                                
                                old_assigns.append(orig_a); new_assigns.append(new_a)
                                
                            if not has_error:
                                for old_a, new_a in zip(old_assigns, new_assigns): db_update('assignments', new_a['id'], new_a, old_data=old_a, track=False)
                                add_transaction([{'type': 'update', 'table': 'assignments', 'old_records': old_assigns, 'new_records': new_assigns}])
                                st.session_state.assignments = [a for a in st.session_state.assignments if a['id'] not in target_group['AssignmentIds']]
                                st.session_state.assignments.extend(new_assigns)
                                st.rerun()

                        with st.form("quick_edit"):
                            edit_date = st.date_input("Αλλαγή Ημερομηνίας", value=target_group['Date'])
                            proj_ids = [p['id'] for p in st.session_state.projects]
                            edit_proj = st.selectbox("Αλλαγή Έργου", options=proj_ids, index=proj_ids.index(target_group['ProjectId']) if target_group['ProjectId'] in proj_ids else 0, format_func=lambda x: next((p['name'] for p in st.session_state.projects if p['id'] == x), "Άγνωστο"))
                            edit_custom_proj_name = st.text_input("Ή Νέο Έργο")
                            
                            valid_emp_ids = [eid for eid in target_group['EmployeeIds'] if eid]
                            edit_emps = st.multiselect("Αλλαγή Προσωπικού", options=list(set(active_employee_ids + valid_emp_ids)), default=valid_emp_ids, format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), 'Άγνωστος'))
                            
                            e_color_col, e_notes_col = st.columns(2)
                            with e_color_col: edit_color = st.selectbox("Χρώμα", options=list(BASIC_COLORS.keys()), index=list(BASIC_COLORS.keys()).index(target_group['ColorName']) if target_group['ColorName'] in BASIC_COLORS else 0)
                            with e_notes_col: edit_notes = st.text_input("Παρατηρήσεις", value=target_group['Notes'])

                            e_start, e_end = st.columns(2)
                            with e_start: new_t_start = st.time_input("Νέα Έναρξη", value=datetime.strptime(target_group['StartTime'], "%H:%M").time())
                            with e_end: new_t_end = st.time_input("Νέα Λήξη", value=datetime.strptime(target_group['EndTime'], "%H:%M").time())
                                
                            st.markdown("---"); st.write("🛑 **Ακύρωση / Διαγραφή Βάρδιας**")
                            c_canc1, c_canc2 = st.columns([1, 2])
                            with c_canc1: e_is_cancelled = st.checkbox("Επισήμανση ως Ακυρωμένη", value=target_group.get('is_cancelled', False))
                            with c_canc2: e_cancel_reason = st.text_input("Λόγος", value=target_group.get('cancel_reason', ''))
                            st.markdown("---")
                            
                            col_btn1, col_btn2 = st.columns(2)
                            with col_btn1: save_edit = st.form_submit_button("💾 Αποθήκευση")
                            with col_btn2: del_edit = st.form_submit_button("🗑️ Οριστική Διαγραφή")
                                
                            if del_edit:
                                old_assigns = [a for a in st.session_state.assignments if a['id'] in target_group['AssignmentIds']]
                                st.session_state.assignments = [a for a in st.session_state.assignments if a['id'] not in target_group['AssignmentIds']]
                                db_delete_in('assignments', 'id', target_group['AssignmentIds'], deleted_records=old_assigns)
                                st.rerun()
                                
                            if save_edit:
                                str_start, str_end = new_t_start.strftime("%H:%M"), new_t_end.strftime("%H:%M")
                                if str_start >= str_end: st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                                elif not edit_custom_proj_name.strip() and not edit_proj: st.error("Επιλέξτε Έργο.")
                                else:
                                    emps_to_process = edit_emps if edit_emps else [""]
                                    errors, new_assigns = [], []
                                    final_edit_proj_id = str(uuid.uuid4()) if edit_custom_proj_name.strip() else edit_proj
                                    
                                    for eid in emps_to_process:
                                        if eid:
                                            emp_name = get_employee_name(eid)
                                            if is_on_leave(eid, edit_date):
                                                errors.append(f"Ο/Η {emp_name} έχει άδεια.")
                                                st.toast(f"🛑 Αδύνατη ανάθεση: {emp_name} έχει άδεια!", icon="🛑")
                                            else:
                                                adj_start, adj_end, is_conflict, msg = check_and_resolve_conflict(eid, edit_date, str_start, str_end, exclude_ids=target_group['AssignmentIds'])
                                                if is_conflict:
                                                    errors.append(f"⚠️ ΔΙΠΛΟΚΡΑΤΗΣΗ: {emp_name}")
                                                    st.toast(f"🚨 Διπλοκράτηση {emp_name}!", icon="🚨")
                                                else:
                                                    if msg == "Adjusted": st.toast(f"🔄 Αυτόματη προσαρμογή: {emp_name} ({adj_start})", icon="🔄")
                                                    new_assigns.append({'id': str(uuid.uuid4()), 'employeeId': eid, 'projectId': final_edit_proj_id, 'date': edit_date, 'startTime': adj_start, 'endTime': adj_end, 'colorName': edit_color, 'colorHex': BASIC_COLORS[edit_color], 'notes': edit_notes, 'is_cancelled': e_is_cancelled, 'cancel_reason': e_cancel_reason if e_is_cancelled else "", 'recurring_id': None})
                                        else:
                                            new_assigns.append({'id': str(uuid.uuid4()), 'employeeId': "", 'projectId': final_edit_proj_id, 'date': edit_date, 'startTime': str_start, 'endTime': str_end, 'colorName': edit_color, 'colorHex': BASIC_COLORS[edit_color], 'notes': edit_notes, 'is_cancelled': e_is_cancelled, 'cancel_reason': e_cancel_reason if e_is_cancelled else "", 'recurring_id': None})
                                            
                                    if errors:
                                        for err in errors: st.error(err)
                                    else:
                                        actions = []
                                        if edit_custom_proj_name.strip():
                                            new_p = {'id': final_edit_proj_id, 'name': edit_custom_proj_name.strip(), 'color': BASIC_COLORS[edit_color]}
                                            st.session_state.projects.append(new_p)
                                            db_insert('projects', new_p, track=False)
                                            actions.append({'type': 'insert', 'table': 'projects', 'records': [new_p]})
                                            
                                        old_assigns = [a for a in st.session_state.assignments if a['id'] in target_group['AssignmentIds']]
                                        st.session_state.assignments = [a for a in st.session_state.assignments if a['id'] not in target_group['AssignmentIds']]
                                        db_delete_in('assignments', 'id', target_group['AssignmentIds'], track=False)
                                        actions.append({'type': 'delete', 'table': 'assignments', 'records': old_assigns})
                                        
                                        st.session_state.assignments.extend(new_assigns)
                                        db_insert('assignments', new_assigns, track=False)
                                        actions.append({'type': 'insert', 'table': 'assignments', 'records': new_assigns})
                                        
                                        add_transaction(actions); st.rerun()

# --- VIEW: PROJECTS ---
elif menu == "Διαχείριση Έργων":
    st.title("🏗️ Έργα")
    if is_full_admin:
        with st.expander("Νέο Έργο"):
            with st.form("new_project_form", clear_on_submit=True):
                p_name, p_color = st.text_input("Όνομα Έργου"), st.color_picker("Χρώμα", "#4a86e8")
                if st.form_submit_button("Δημιουργία"):
                    new_p = {'id': str(uuid.uuid4()), 'name': p_name, 'color': p_color}
                    st.session_state.projects.append(new_p)
                    db_insert('projects', new_p); st.rerun()
    else: st.info("⚠️ Έχετε πρόσβαση μόνο για προβολή στα Έργα.")
            
    for p in st.session_state.projects:
        col1, col2 = st.columns([4, 1])
        col1.write(f"**{p['name']}**")
        if is_full_admin and col2.button("Διαγραφή", key=p['id']):
            st.session_state.projects = [proj for proj in st.session_state.projects if proj['id'] != p['id']]
            db_delete('projects', 'id', p['id'], deleted_records=[p]); st.rerun()

# --- VIEW: EMPLOYEES ---
elif menu == "Ομάδα Προσωπικού":
    st.title("👥 Προσωπικό")
    tab_list, tab_add, tab_edit, tab_import = st.tabs(["📋 Λίστα Υπαλλήλων", "➕ Προσθήκη", "✏️ Επεξεργασία", "📥 Εισαγωγή"])
    
    with tab_add:
        if "emp_reset_counter" not in st.session_state: st.session_state.emp_reset_counter = 0
        erc = st.session_state.emp_reset_counter
        c1, c2, c3 = st.columns(3)
        with c1: e_name, e_pos = st.text_input("Ονοματεπώνυμο", key=f"new_emp_name_{erc}"), st.selectbox("Θέση", ["ΕΡΓΑΤΗΣ", "ΕΠΟΠΤΗΣ", "ΟΔΗΓΟΣ"], key=f"new_emp_pos_{erc}")
        with c2: e_id_num, e_phone = st.text_input("Αριθμός Ταυτότητας", key=f"new_emp_id_{erc}"), st.text_input("Κινητό", key=f"new_emp_phone_{erc}")
        with c3: e_status = st.selectbox("Κατάσταση", ["Ενεργός", "Ανενεργός"], key=f"new_emp_status_{erc}")
            
        st.write("")
        col_btn1, col_btn2 = st.columns([1, 1])
        if col_btn2.button("🧹 Καθαρισμός", key="btn_clear_emp", use_container_width=True): st.session_state.emp_reset_counter += 1; st.rerun()
        if col_btn1.button("Προσθήκη", type="primary", use_container_width=True):
            if not e_name.strip(): st.error("Το πεδίο 'Ονοματεπώνυμο' είναι υποχρεωτικό.")
            else:
                is_duplicate = False
                for emp in st.session_state.employees:
                    if emp['name'].strip().lower() == e_name.strip().lower(): st.error("Υπάρχει ήδη."); is_duplicate = True; break
                    if e_id_num.strip() and emp.get('id_number', '').strip().lower() == e_id_num.strip().lower(): st.error("Αριθμός Ταυτότητας υπάρχει ήδη."); is_duplicate = True; break
                if not is_duplicate:
                    new_e = {'id': str(uuid.uuid4()), 'name': e_name.strip(), 'position': e_pos.strip(), 'id_number': e_id_num.strip(), 'phone': e_phone.strip(), 'status': e_status}
                    st.session_state.employees.append(new_e)
                    db_insert('employees', new_e)
                    st.success("Επιτυχία!"); time.sleep(1); st.session_state.emp_reset_counter += 1; st.rerun()
    
    with tab_edit:
        if not st.session_state.employees: st.info("Δεν υπάρχουν υπάλληλοι.")
        else:
            emp_to_edit_id = st.selectbox("Επιλέξτε Υπάλληλο", options=[e['id'] for e in st.session_state.employees], format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), "Άγνωστος"))
            emp_to_edit = next(e for e in st.session_state.employees if e['id'] == emp_to_edit_id)
            with st.form("edit_emp", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                with c1: ed_name, ed_pos = st.text_input("Ονοματεπώνυμο", value=emp_to_edit['name']), st.selectbox("Θέση", ["ΕΡΓΑΤΗΣ", "ΕΠΟΠΤΗΣ", "ΟΔΗΓΟΣ"], index=["ΕΡΓΑΤΗΣ", "ΕΠΟΠΤΗΣ", "ΟΔΗΓΟΣ"].index(emp_to_edit.get('position', 'ΕΡΓΑΤΗΣ')))
                with c2: ed_id_num, ed_phone = st.text_input("Αριθμός Ταυτότητας", value=emp_to_edit.get('id_number', '')), st.text_input("Κινητό", value=emp_to_edit.get('phone', ''))
                with c3: ed_status = st.selectbox("Κατάσταση", ["Ενεργός", "Ανενεργός"], index=0 if emp_to_edit.get('status', 'Ενεργός') == 'Ενεργός' else 1)
                if st.form_submit_button("💾 Αποθήκευση"):
                    if not ed_name.strip(): st.error("Υποχρεωτικό Όνομα.")
                    else:
                        is_dup = False
                        for e in st.session_state.employees:
                            if e['id'] != emp_to_edit_id:
                                if e['name'].strip().lower() == ed_name.strip().lower(): st.error("Υπάρχει ήδη."); is_dup = True; break
                                elif ed_id_num.strip() and e.get('id_number', '').strip().lower() == ed_id_num.strip().lower(): st.error("Αριθμός Ταυτότητας υπάρχει."); is_dup = True; break
                        if not is_dup:
                            old_emp_data = dict(emp_to_edit)
                            emp_to_edit.update({'name': ed_name.strip(), 'position': ed_pos.strip(), 'id_number': ed_id_num.strip(), 'phone': ed_phone.strip(), 'status': ed_status})
                            db_update('employees', emp_to_edit_id, emp_to_edit, old_data=old_emp_data)
                            st.success("Αποθηκεύτηκαν!"); st.rerun()

    with tab_import:
        st.write("### 📥 Μαζική Εισαγωγή")
        with st.form("import_form", clear_on_submit=True):
            uploaded_file = st.file_uploader("Αρχείο Excel ή CSV", type=['csv', 'xlsx'])
            if st.form_submit_button("Εκτέλεση Εισαγωγής") and uploaded_file is not None:
                try:
                    df_import = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
                    success_count, error_count = 0, 0
                    cols = [str(c).lower().strip().replace(".", "").replace("_", " ") for c in df_import.columns]
                    name_col = next((orig for orig, c in zip(df_import.columns, cols) if 'ονομα' in c or 'name' in c or 'υπαλλ' in c or 'υπάλλ' in c), None)
                    if not name_col: st.error("❌ Δεν βρέθηκε στήλη για το Ονοματεπώνυμο.")
                    else:
                        pos_col = next((orig for orig, c in zip(df_import.columns, cols) if 'θεσ' in c or 'θέσ' in c or 'ειδικ' in c or 'ρολο' in c or 'ρόλο' in c or 'position' in c), None)
                        id_col = next((orig for orig, c in zip(df_import.columns, cols) if 'ταυτοτ' in c or 'ταυτότ' in c or 'αδτ' in c or 'id' in c), None)
                        phone_col = next((orig for orig, c in zip(df_import.columns, cols) if 'τηλ' in c or 'κινητ' in c or 'phone' in c), None)
                        status_col = next((orig for orig, c in zip(df_import.columns, cols) if 'καταστ' in c or 'κατάστ' in c or 'status' in c or 'ενεργ' in c or 'active' in c), None)
                        
                        new_employees_batch = []
                        with st.spinner("Εισαγωγή Δεδομένων..."):
                            for _, row in df_import.iterrows():
                                e_name = str(row[name_col]).strip() if pd.notna(row[name_col]) else ""
                                if not e_name or e_name.lower() == 'nan': continue
                                e_pos = str(row[pos_col]).strip().upper() if pos_col and pd.notna(row[pos_col]) else "ΕΡΓΑΤΗΣ"
                                if e_pos not in ["ΕΡΓΑΤΗΣ", "ΕΠΟΠΤΗΣ", "ΟΔΗΓΟΣ"]: e_pos = "ΕΡΓΑΤΗΣ"
                                e_id_num = str(row[id_col]).strip() if id_col and pd.notna(row[id_col]) else ""
                                if e_id_num.lower() == 'nan': e_id_num = ""
                                if e_id_num.endswith('.0'): e_id_num = e_id_num[:-2] 
                                e_phone = str(row[phone_col]).strip() if phone_col and pd.notna(row[phone_col]) else ""
                                if e_phone.lower() == 'nan': e_phone = ""
                                if e_phone.endswith('.0'): e_phone = e_phone[:-2]
                                e_status = "Ενεργός"
                                if status_col and pd.notna(row[status_col]):
                                    val = str(row[status_col]).strip().lower()
                                    if any(kw in val for kw in ["ανενεργ", "inactive", "false", "0", "οχι", "όχι", "no", "αποχωρ", "παραιτ"]): e_status = "Ανενεργός"
                                
                                is_duplicate = False
                                for emp in st.session_state.employees:
                                    if emp['name'].strip().lower() == e_name.lower() or (e_id_num and emp.get('id_number', '').strip().lower() == e_id_num.lower()): is_duplicate = True; break
                                if not is_duplicate:
                                    new_e = {'id': str(uuid.uuid4()), 'name': e_name, 'position': e_pos, 'id_number': e_id_num, 'phone': e_phone, 'status': e_status}
                                    new_employees_batch.append(new_e); st.session_state.employees.append(new_e); success_count += 1
                                else: error_count += 1
                                    
                            if new_employees_batch: db_insert('employees', new_employees_batch)
                            if error_count > 0: st.warning(f"Παραλείφθηκαν {error_count} υπάλληλοι (διπλότυποι).")
                            if success_count > 0: st.success(f"Εισήχθησαν {success_count} υπάλληλοι!"); time.sleep(1.5); st.rerun() 
                except Exception as e: st.error(f"Σφάλμα: {e}")

    with tab_list:
        st.write("### Συνολική Λίστα Υπαλλήλων")
        search_query = st.text_input("🔍 Αναζήτηση", placeholder="Ψάξε με Όνομα, Θέση, Ταυτότητα ή Τηλέφωνο...", key="emp_search_bar")
        filtered_emps = st.session_state.employees
        if search_query:
            q = search_query.strip().lower()
            filtered_emps = [e for e in st.session_state.employees if q in str(e.get('name', '')).lower() or q in str(e.get('position', '')).lower() or q in str(e.get('id_number', '')).lower() or q in str(e.get('phone', '')).lower()]
        
        with st.expander("🗑️ Μαζική Διαγραφή"):
            emps_to_delete = st.multiselect("Επιλέξτε τους υπαλλήλους:", options=[e['id'] for e in filtered_emps], format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), "Άγνωστος"))
            if st.button("Οριστική Διαγραφή", type="primary"):
                if emps_to_delete:
                    deleted_emps = [e for e in st.session_state.employees if e['id'] in emps_to_delete]
                    st.session_state.employees = [emp for emp in st.session_state.employees if emp['id'] not in emps_to_delete]
                    db_delete_in('employees', 'id', emps_to_delete, deleted_records=deleted_emps); st.rerun()
                else: st.warning("Δεν επιλέξατε υπάλληλο.")
        
        st.divider()
        if not filtered_emps: st.info("Δεν βρέθηκαν υπάλληλοι.")
        else:
            hc1, hc2, hc3, hc4, hc5, hc6 = st.columns([2, 2, 2, 2, 1.5, 1])
            hc1.write("**Ονοματεπώνυμο**"); hc2.write("**Θέση**"); hc3.write("**Αρ. Ταυτότητας**"); hc4.write("**Κινητό**"); hc5.write("**Κατάσταση**")
            st.divider()
            for e in filtered_emps:
                col1, col2, col3, col4, col5, col6 = st.columns([2, 2, 2, 2, 1.5, 1])
                col1.write(e['name']); col2.write(f"*{e['position']}*"); col3.write(e.get('id_number') or '-'); col4.write(e.get('phone') or '-')
                status_val = e.get('status', 'Ενεργός')
                col5.markdown(f"<span style='color:{'#16a34a' if status_val == 'Ενεργός' else '#dc2626'}; font-weight:bold;'>{status_val}</span>", unsafe_allow_html=True)
                if col6.button("❌", key=f"del_emp_{e['id']}"):
                    st.session_state.employees = [emp for emp in st.session_state.employees if emp['id'] != e['id']]
                    db_delete('employees', 'id', e['id'], deleted_records=[e]); st.rerun()

# --- VIEW: LEAVES ---
elif menu == "Άδειες":
    st.title("🏖️ Διαχείριση Αδειών")
    
    if "pending_leave" not in st.session_state: st.session_state.pending_leave = None
    if "leave_conflicts" not in st.session_state: st.session_state.leave_conflicts = []
        
    tab_list, tab_add, tab_edit = st.tabs(["📋 Λίστα Αδειών", "➕ Καταχώρηση", "✏️ Επεξεργασία"])
    
    with tab_add:
        if "leave_reset_counter" not in st.session_state: st.session_state.leave_reset_counter = 0
        lrc = st.session_state.leave_reset_counter
        
        c1, c2 = st.columns(2)
        with c1:
            l_emp = st.selectbox("Υπάλληλος (Μόνο Ενεργοί)", options=active_employee_ids, format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), "Άγνωστος"), key=f"l_emp_{lrc}")
            l_start = st.date_input("Από", key=f"l_start_{lrc}")
        with c2:
            l_sub_emp = st.selectbox("Αντικαταστάτης (Προαιρετικό)", options=[""] + active_employee_ids, format_func=lambda x: "Χωρίς Αντικαταστάτη" if x == "" else next((e['name'] for e in st.session_state.employees if e['id'] == x), "Άγνωστος"), key=f"l_sub_{lrc}")
            l_end = st.date_input("Έως", key=f"l_end_{lrc}")
            
        col_b1, col_b2 = st.columns([1, 1])
        with col_b1: submit_leave = st.button("Καταχώρηση Άδειας", type="primary", use_container_width=True)
        with col_b2:
            if st.button("🧹 Καθαρισμός", key="btn_clear_leave", use_container_width=True):
                st.session_state.leave_reset_counter += 1; st.session_state.pending_leave = None; st.session_state.leave_conflicts = []; st.rerun()
            
        if submit_leave:
            if not l_emp: st.error("Παρακαλώ επιλέξτε υπάλληλο.")
            elif l_start > l_end: st.error("Η ημερομηνία 'Από' πρέπει να είναι πριν ή ίση με την 'Έως'.")
            elif l_emp == l_sub_emp: st.error("Ο αντικαταστάτης δεν μπορεί να είναι το ίδιο πρόσωπο με αυτόν που παίρνει άδεια.")
            else:
                conflicts = []
                curr_date = l_start
                while curr_date <= l_end:
                    for a in st.session_state.assignments:
                        if a['employeeId'] == l_emp and a['date'] == curr_date: conflicts.append(a)
                    curr_date += timedelta(days=1)
                
                if conflicts:
                    st.session_state.pending_leave = {'id': str(uuid.uuid4()), 'employeeId': l_emp, 'startDate': l_start, 'endDate': l_end, 'substituteId': l_sub_emp if l_sub_emp else None, 'type': 'new'}
                    st.session_state.leave_conflicts = conflicts
                else:
                    new_l = {'id': str(uuid.uuid4()), 'employeeId': l_emp, 'startDate': l_start, 'endDate': l_end, 'substituteId': l_sub_emp if l_sub_emp else None}
                    st.session_state.leaves.append(new_l); db_insert('leaves', new_l)
                    st.success("Η άδεια καταχωρήθηκε με επιτυχία!"); time.sleep(1.5); st.session_state.leave_reset_counter += 1; st.rerun()
                    
        # Σύστημα Έγκρισης (Pop-up Boxes)
        if st.session_state.get('pending_leave') and st.session_state.pending_leave.get('type') == 'new' and st.session_state.get('leave_conflicts'):
            st.markdown("---")
            st.warning("⚠️ **Εμπλοκή με βάρδιες!** Ο/Η υπάλληλος είναι ήδη τοποθετημένος/η σε έργα τις συγκεκριμένες ημερομηνίες. Πατήστε 'Έγκριση (Αφαίρεση)' για να τον/την αφαιρέσετε από το έργο και να περαστεί η άδεια.")
            
            resolved_any = False
            for a in st.session_state.leave_conflicts:
                st.markdown(f'<div class="leave-conflict-box">', unsafe_allow_html=True)
                col_err, col_btn = st.columns([4, 1])
                proj = get_project_info(a['projectId'])
                col_err.write(f"Ο/Η **{get_employee_name(a['employeeId'])}** δουλεύει στις **{a['date'].strftime('%d/%m/%Y')}** στο έργο: **{proj['name'] if proj else '?'}** ({a['startTime']}-{a['endTime']}).")
                
                if col_btn.button("✅ Έγκριση (Αφαίρεση)", key=f"res_new_{a['id']}", use_container_width=True):
                    target_a = next((assign for assign in st.session_state.assignments if assign['id'] == a['id']), None)
                    if target_a:
                        old_a = dict(target_a); target_a['employeeId'] = ""  
                        db_update('assignments', target_a['id'], target_a, old_data=old_a)
                        st.session_state.leave_conflicts = [c for c in st.session_state.leave_conflicts if c['id'] != a['id']]
                        resolved_any = True
                st.markdown('</div>', unsafe_allow_html=True)
            
            if resolved_any:
                if not st.session_state.leave_conflicts:
                    new_l = {k: v for k, v in st.session_state.pending_leave.items() if k != 'type'}
                    st.session_state.leaves.append(new_l); db_insert('leaves', new_l)
                    st.session_state.pending_leave = None
                    st.success("Όλες οι επικαλύψεις επιλύθηκαν! Η άδεια καταχωρήθηκε."); time.sleep(1.5); st.session_state.leave_reset_counter += 1
                st.rerun()

    with tab_edit:
        if not st.session_state.leaves: st.info("Δεν υπάρχουν άδειες προς επεξεργασία.")
        else:
            leave_options = {lv['id']: f"{get_employee_name(lv['employeeId'])} ({lv['startDate'].strftime('%d/%m/%Y')} - {lv['endDate'].strftime('%d/%m/%Y')})" for lv in st.session_state.leaves}
            leave_to_edit_id = st.selectbox("Επιλέξτε Άδεια για Επεξεργασία", options=list(leave_options.keys()), format_func=lambda x: leave_options[x])
            leave_to_edit = next(l for l in st.session_state.leaves if l['id'] == leave_to_edit_id)
            
            c1, c2 = st.columns(2)
            with c1:
                emp_options_safe = active_employee_ids + [leave_to_edit['employeeId']] if leave_to_edit['employeeId'] not in active_employee_ids else active_employee_ids
                ed_l_emp = st.selectbox("Αλλαγή Υπαλλήλου", options=emp_options_safe, index=emp_options_safe.index(leave_to_edit['employeeId']), format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), "Άγνωστος"))
                ed_l_start = st.date_input("Αλλαγή Ημερομηνίας 'Από'", value=leave_to_edit['startDate'])
            with c2:
                current_sub = leave_to_edit.get('substituteId') or ""
                sub_options = [""] + active_employee_ids
                if current_sub and current_sub not in sub_options: sub_options.append(current_sub)
                ed_l_sub_emp = st.selectbox("Αλλαγή Αντικαταστάτη", options=sub_options, index=sub_options.index(current_sub), format_func=lambda x: "Χωρίς Αντικαταστάτη" if x == "" else next((e['name'] for e in st.session_state.employees if e['id'] == x), "Άγνωστος"))
                ed_l_end = st.date_input("Αλλαγή Ημερομηνίας 'Έως'", value=leave_to_edit['endDate'])
                
            if st.button("💾 Αποθήκευση Αλλαγών", type="primary"):
                if ed_l_start > ed_l_end: st.error("Η ημερομηνία 'Από' πρέπει να είναι πριν ή ίση με την 'Έως'.")
                elif ed_l_emp == ed_l_sub_emp: st.error("Ο αντικαταστάτης δεν μπορεί να είναι το ίδιο πρόσωπο με αυτόν που παίρνει άδεια.")
                else:
                    conflicts = []
                    curr_date = ed_l_start
                    while curr_date <= ed_l_end:
                        for a in st.session_state.assignments:
                            if a['employeeId'] == ed_l_emp and a['date'] == curr_date: conflicts.append(a)
                        curr_date += timedelta(days=1)
                    
                    if conflicts:
                        st.session_state.pending_leave = {'id': leave_to_edit_id, 'employeeId': ed_l_emp, 'startDate': ed_l_start, 'endDate': ed_l_end, 'substituteId': ed_l_sub_emp if ed_l_sub_emp else None, 'type': 'edit', 'old_data': dict(leave_to_edit)}
                        st.session_state.leave_conflicts = conflicts
                    else:
                        old_leave_data = dict(leave_to_edit)
                        leave_to_edit.update({'employeeId': ed_l_emp, 'startDate': ed_l_start, 'endDate': ed_l_end, 'substituteId': ed_l_sub_emp if ed_l_sub_emp else None})
                        db_update('leaves', leave_to_edit_id, leave_to_edit, old_data=old_leave_data)
                        st.success("Οι αλλαγές στην άδεια αποθηκεύτηκαν!"); time.sleep(1); st.rerun()

            if st.session_state.get('pending_leave') and st.session_state.pending_leave.get('type') == 'edit' and st.session_state.get('leave_conflicts'):
                st.markdown("---")
                st.warning("⚠️ **Εμπλοκή με βάρδιες!** Ο/Η υπάλληλος είναι ήδη τοποθετημένος/η σε έργα. Πατήστε 'Έγκριση (Αφαίρεση)'.")
                
                resolved_any = False
                for a in st.session_state.leave_conflicts:
                    st.markdown(f'<div class="leave-conflict-box">', unsafe_allow_html=True)
                    col_err, col_btn = st.columns([4, 1])
                    proj = get_project_info(a['projectId'])
                    col_err.write(f"Ο/Η **{get_employee_name(a['employeeId'])}** δουλεύει στις **{a['date'].strftime('%d/%m/%Y')}** στο έργο: **{proj['name'] if proj else '?'}** ({a['startTime']}-{a['endTime']}).")
                    
                    if col_btn.button("✅ Έγκριση (Αφαίρεση)", key=f"res_edit_{a['id']}", use_container_width=True):
                        target_a = next((assign for assign in st.session_state.assignments if assign['id'] == a['id']), None)
                        if target_a:
                            old_a = dict(target_a); target_a['employeeId'] = ""  
                            db_update('assignments', target_a['id'], target_a, old_data=old_a)
                            st.session_state.leave_conflicts = [c for c in st.session_state.leave_conflicts if c['id'] != a['id']]
                            resolved_any = True
                    st.markdown('</div>', unsafe_allow_html=True)
                
                if resolved_any:
                    if not st.session_state.leave_conflicts:
                        leave_id = st.session_state.pending_leave['id']
                        leave_obj = next(l for l in st.session_state.leaves if l['id'] == leave_id)
                        leave_obj.update({'employeeId': st.session_state.pending_leave['employeeId'], 'startDate': st.session_state.pending_leave['startDate'], 'endDate': st.session_state.pending_leave['endDate'], 'substituteId': st.session_state.pending_leave['substituteId']})
                        db_update('leaves', leave_id, leave_obj, old_data=st.session_state.pending_leave['old_data'])
                        st.session_state.pending_leave = None
                        st.success("Όλες οι επικαλύψεις επιλύθηκαν! Οι αλλαγές αποθηκεύτηκαν."); time.sleep(1.5)
                    st.rerun()

    with tab_list:
        if st.session_state.leaves:
            st.write("### Λίστα Αδειών")
            hc1, hc2, hc3, hc4, hc5 = st.columns([2.5, 2, 2, 2.5, 1])
            hc1.write("**Υπάλληλος**"); hc2.write("**Από**"); hc3.write("**Έως**"); hc4.write("**Αντικαταστάτης**"); hc5.write("")
            st.divider()
            
            for l in st.session_state.leaves:
                col1, col2, col3, col4, col5 = st.columns([2.5, 2, 2, 2.5, 1])
                col1.write(get_employee_name(l['employeeId']))
                col2.write(l['startDate'].strftime('%d/%m/%Y'))
                col3.write(l['endDate'].strftime('%d/%m/%Y'))
                col4.write(get_employee_name(l.get('substituteId')) if l.get('substituteId') else "-")
                
                if col5.button("❌", key=f"del_leave_{l['id']}"):
                    st.session_state.leaves = [leave for leave in st.session_state.leaves if leave['id'] != l['id']]
                    db_delete('leaves', 'id', l['id'], deleted_records=[l]); st.rerun()
        else: st.info("Δεν υπάρχουν καταχωρημένες άδειες.")

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
    year_start, year_end = date(selected_year, 1, 1), date(selected_year, 12, 31)
    
    for l in st.session_state.leaves:
        actual_start = max(l['startDate'], year_start)
        actual_end = min(l['endDate'], year_end)
        if actual_start <= actual_end and l['employeeId'] in leave_days:
            leave_days[l['employeeId']] += (actual_end - actual_start).days + 1
                
    table_data = [{"Ονοματεπώνυμο": emp['name'], "Θέση": emp['position'], "Κατάσταση": emp.get('status', 'Ενεργός'), "Ημέρες Άδειας": leave_days[emp['id']]} for emp in st.session_state.employees]
    st.write(f"### Συνολικές Ημέρες Άδειας για το έτος: {selected_year}")
    st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)

# --- VIEW: Ώρες Εργασιών ---
elif menu == "Ώρες Εργασιών":
    st.title("⏱️ Ώρες Εργασιών ανά Μήνα")
    months = ["Ιανουάριος", "Φεβρουάριος", "Μάρτιος", "Απρίλιος", "Μάιος", "Ιούνιος", "Ιούλιος", "Αύγουστος", "Σεπτέμβριος", "Οκτώβριος", "Νοέμβριος", "Δεκέμβριος"]
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
            hours = (datetime.strptime(a['endTime'], "%H:%M") - datetime.strptime(a['startTime'], "%H:%M")).total_seconds() / 3600.0
            if a['employeeId'] in employee_hours: employee_hours[a['employeeId']] += hours
                
    table_data = [{"Ονοματεπώνυμο": emp['name'], "Θέση": emp['position'], "Κατάσταση": emp.get('status', 'Ενεργός'), "Συνολικές Ώρες": round(employee_hours[emp['id']], 2)} for emp in st.session_state.employees]
    st.write(f"### Σύνολο Ωρών για: {selected_month_name} {selected_year}")
    st.dataframe(pd.DataFrame(table_data).style.format({"Συνολικές Ώρες": "{:.2f}"}), use_container_width=True, hide_index=True)

# --- VIEW: ΕΠΑΝΑΛΑΜΒΑΝΟΜΕΝΕΣ ΕΡΓΑΣΙΕΣ ---
elif menu == "Επαναλαμβανόμενες Εργασίες":
    st.title("🔄 Επαναλαμβανόμενες Εργασίες")
    if not is_full_admin: st.info("⚠️ Έχετε δικαιώματα μόνο για ανάγνωση. Δεν μπορείτε να διαχειριστείτε τις επαναλαμβανόμενες εργασίες.")
    else:
        st.write("Προσθέστε ή επεξεργαστείτε εργασίες που επαναλαμβάνονται «για πάντα» (προγραμματίζονται αυτόματα για τα επόμενα 3 χρόνια).")
        tab_new, tab_edit = st.tabs(["➕ Νέα Καταχώρηση", "✏️ Διαχείριση/Επεξεργασία Υπαρχουσών"])
        if "rec_reset_counter" not in st.session_state: st.session_state.rec_reset_counter = 0
        rc = st.session_state.rec_reset_counter
        
        with tab_new:
            r_col1, r_col2 = st.columns(2)
            with r_col1:
                r_proj = st.selectbox("Επιλογή Έργου (Από Λίστα)", options=[p['id'] for p in st.session_state.projects], format_func=lambda x: next((p['name'] for p in st.session_state.projects if p['id'] == x), "Άγνωστο Έργο"), key=f"new_r_proj_{rc}")
                r_custom_proj_name = st.text_input("Ή πληκτρολογήστε Νέο Έργο (Αν συμπληρωθεί, αγνοεί την παραπάνω λίστα)", key=f"new_r_custom_proj_{rc}")
                c_r_color, c_r_notes = st.columns(2)
                with c_r_color: r_color = st.selectbox("Χρώμα Μπάρας", options=list(BASIC_COLORS.keys()), key=f"new_r_color_{rc}")
                with c_r_notes: r_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", key=f"new_r_notes_{rc}")
                r_type = st.selectbox("Συχνότητα Επανάληψης", ["Εβδομαδιαία", "Μηνιαία", "Επιλεγμένες Μέρες Εβδομάδας"], key=f"new_r_type_{rc}")
                r_emps, selected_weekdays, selected_weekdays_data = [], [], {}
                
                if r_type in ["Εβδομαδιαία", "Μηνιαία"]:
                    r_emps = st.multiselect("Προσωπικό (Προαιρετικό - Μόνο Ενεργοί)", options=active_employee_ids, format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), "Άγνωστος"), key=f"new_r_emps_{rc}")
                else:
                    st.markdown("**Επιλέξτε Μέρες και Προσωπικό (ξεχωριστά ανά μέρα):**")
                    day_names = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
                    for i, d_name in enumerate(day_names):
                        c_chk, c_emp = st.columns([1, 3])
                        if c_chk.checkbox(d_name, value=(i==0), key=f"new_chk_{i}_{rc}"):
                            selected_weekdays.append(d_name)
                            selected_weekdays_data[d_name] = c_emp.multiselect(
                                f"Προσωπικό ({d_name})", options=active_employee_ids, format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), "Άγνωστος"), key=f"new_r_emps_day_{i}_{rc}", label_visibility="collapsed"
                            )
            with r_col2:
                r_start_date = st.date_input("Από Ημερομηνία", date.today(), key=f"new_r_start_date_{rc}")
                r_start_time = st.time_input("Έναρξη Ώρας", value=datetime.strptime("09:00", "%H:%M").time(), key=f"new_r_start_time_{rc}")
                r_end_time = st.time_input("Λήξη Ώρας", value=datetime.strptime("17:00", "%H:%M").time(), key=f"new_r_end_time_{rc}")
                st.info("💡 Η εργασία θα επαναλαμβάνεται συνεχώς.")
            
            st.write("") 
            col_btn1, col_btn2 = st.columns([1, 1])
            with col_btn1: submit_r = st.button("Καταχώρηση Επαναλαμβανόμενης Εργασίας", type="primary", key="btn_new_r", use_container_width=True)
            with col_btn2:
                if st.button("🧹 Καθαρισμός", key="btn_clear_r", use_container_width=True): st.session_state.rec_reset_counter += 1; st.rerun()
                
            if submit_r:
                str_start, str_end = r_start_time.strftime("%H:%M"), r_end_time.strftime("%H:%M")
                if str_start >= str_end: st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                elif r_type == "Επιλεγμένες Μέρες Εβδομάδας" and not selected_weekdays: st.error("Επιλέξτε τουλάχιστον μία μέρα της εβδομάδας τικάροντας το αντίστοιχο κουτάκι.")
                elif not r_custom_proj_name.strip() and not r_proj: st.error("Παρακαλώ επιλέξτε ή πληκτρολογήστε ένα Έργο.")
                else:
                    actions = []
                    if r_custom_proj_name.strip():
                        final_r_proj_id = str(uuid.uuid4())
                        new_p = {'id': final_r_proj_id, 'name': r_custom_proj_name.strip(), 'color': BASIC_COLORS[r_color]}
                        st.session_state.projects.append(new_p)
                        db_insert('projects', new_p, track=False)
                        actions.append({'type': 'insert', 'table': 'projects', 'records': [new_p]})
                    else: final_r_proj_id = r_proj
                        
                    pattern_id = str(uuid.uuid4())
                    r_end_date = r_start_date + timedelta(days=365 * 3)
                    dates_to_assign = []
                    curr_date = r_start_date
                    day_map = {"Δευτέρα": 0, "Τρίτη": 1, "Τετάρτη": 2, "Πέμπτη": 3, "Παρασκευή": 4, "Σάββατο": 5, "Κυριακή": 6}
                    day_map_inv = {0: "Δευτέρα", 1: "Τρίτη", 2: "Τετάρτη", 3: "Πέμπτη", 4: "Παρασκευή", 5: "Σάββατο", 6: "Κυριακή"}
                    selected_weekday_ints = [day_map[d] for d in selected_weekdays] if selected_weekdays else []
                    new_assignments_batch = []
                    
                    with st.spinner('Υπολογισμός και καταχώρηση βαρδιών...'):
                        while curr_date <= r_end_date:
                            if r_type == "Εβδομαδιαία": dates_to_assign.append(curr_date); curr_date += timedelta(days=7)
                            elif r_type == "Μηνιαία":
                                dates_to_assign.append(curr_date)
                                month, year = curr_date.month, curr_date.year
                                if month == 12: month = 1; year += 1
                                else: month += 1
                                try: curr_date = curr_date.replace(year=year, month=month)
                                except ValueError: curr_date = curr_date.replace(year=year, month=month, day=calendar.monthrange(year, month)[1])
                            elif r_type == "Επιλεγμένες Μέρες Εβδομάδας":
                                if curr_date.weekday() in selected_weekday_ints: dates_to_assign.append(curr_date)
                                curr_date += timedelta(days=1)
                        
                        success_count, conflict_count, conflict_details = 0, 0, []
                        
                        for d in dates_to_assign:
                            if r_type == "Επιλεγμένες Μέρες Εβδομάδας":
                                d_name = day_map_inv[d.weekday()]
                                emps_to_process = selected_weekdays_data.get(d_name, [])
                            else: emps_to_process = r_emps
                            emps_to_process = emps_to_process if emps_to_process else [""]
                            
                            for eid in emps_to_process:
                                if eid:
                                    emp_name = get_employee_name(eid)
                                    if is_on_leave(eid, d):
                                        conflict_count += 1; conflict_details.append(f"{d.strftime('%d/%m/%Y')} - {emp_name} (Άδεια)")
                                        st.toast(f"🛑 Επαναλαμβανόμενη: Άδεια {emp_name} ({d.strftime('%d/%m')})", icon="🛑")
                                    else:
                                        adj_start, adj_end, is_conflict, msg = check_and_resolve_conflict(eid, d, str_start, str_end)
                                        if is_conflict:
                                            conflict_count += 1; conflict_details.append(f"{d.strftime('%d/%m/%Y')} - {emp_name} (Επικάλυψη)")
                                            st.toast(f"🚨 Επαναλαμβανόμενη: Διπλοκράτηση {emp_name} ({d.strftime('%d/%m')})", icon="🚨")
                                        else:
                                            new_assignments_batch.append({'id': str(uuid.uuid4()), 'recurring_id': pattern_id, 'employeeId': eid, 'projectId': final_r_proj_id, 'date': d, 'startTime': adj_start, 'endTime': adj_end, 'colorName': r_color, 'colorHex': BASIC_COLORS[r_color], 'notes': r_notes, 'is_cancelled': False, 'cancel_reason': ""})
                                            success_count += 1
                                else:
                                    new_assignments_batch.append({'id': str(uuid.uuid4()), 'recurring_id': pattern_id, 'employeeId': "", 'projectId': final_r_proj_id, 'date': d, 'startTime': str_start, 'endTime': str_end, 'colorName': r_color, 'colorHex': BASIC_COLORS[r_color], 'notes': r_notes, 'is_cancelled': False, 'cancel_reason': ""})
                                    success_count += 1
                        
                        final_employee_ids = selected_weekdays_data if r_type == "Επιλεγμένες Μέρες Εβδομάδας" else r_emps
                        new_pattern = {'id': pattern_id, 'projectId': final_r_proj_id, 'employeeIds': final_employee_ids, 'colorName': r_color, 'notes': r_notes, 'type': r_type, 'weekdays': selected_weekdays, 'startDate': r_start_date, 'startTime': str_start, 'endTime': str_end}
                        
                        st.session_state.recurring_patterns.append(new_pattern)
                        db_insert('recurring_patterns', new_pattern, track=False)
                        actions.append({'type': 'insert', 'table': 'recurring_patterns', 'records': [new_pattern]})
                        
                        if new_assignments_batch:
                            st.session_state.assignments.extend(new_assignments_batch)
                            for i in range(0, len(new_assignments_batch), 500): db_insert('assignments', new_assignments_batch[i:i+500], track=False)
                            actions.append({'type': 'insert', 'table': 'assignments', 'records': new_assignments_batch})
                        add_transaction(actions)
                        st.session_state.rec_reset_counter += 1
                        
                    if success_count > 0:
                        st.success(f"Επιτυχής δημιουργία {success_count} βαρδιών! Η σελίδα ανανεώνεται...")
                        time.sleep(1.5); st.rerun()
                    if conflict_count > 0:
                        st.warning(f"Παραλείφθηκαν {conflict_count} αναθέσεις λόγω συγκρούσεων.")
                        with st.expander("Δείτε τις συγκρούσεις"):
                            for c in conflict_details: st.write(f"⚠️ {c}")

        with tab_edit:
            if not st.session_state.recurring_patterns: st.info("Δεν υπάρχουν ενεργές επαναλαμβανόμενες εργασίες.")
            else:
                pattern_options = {}
                for p in st.session_state.recurring_patterns:
                    p_info = get_project_info(p['projectId'])
                    pattern_options[p['id']] = f"{p_info['name'] if p_info else 'Άγνωστο'} | {p['type']} | Από: {p['startDate'].strftime('%d/%m/%Y')} ({p['startTime']}-{p['endTime']})"
                
                selected_pattern_id = st.selectbox("Επιλέξτε Σειρά Εργασιών", options=list(pattern_options.keys()), format_func=lambda x: pattern_options[x])
                if selected_pattern_id:
                    pat = next(p for p in st.session_state.recurring_patterns if p['id'] == selected_pattern_id)
                    with st.form("edit_recurring_form", clear_on_submit=True):
                        st.warning("⚠️ Προσοχή: Η αποθήκευση αλλαγών θα επαναδημιουργήσει **ΟΛΕΣ** τις βάρδιες αυτής της σειράς. Τυχόν μεμονωμένες αλλαγές που κάνατε στο Ταμπλό θα χαθούν.")
                        e_col1, e_col2 = st.columns(2)
                        with e_col1:
                            proj_ids = [p['id'] for p in st.session_state.projects]
                            e_proj = st.selectbox("Αλλαγή Έργου", options=proj_ids, index=proj_ids.index(pat['projectId']) if pat['projectId'] in proj_ids else 0, format_func=lambda x: next((p['name'] for p in st.session_state.projects if p['id'] == x), "Άγνωστο Έργο"))
                            e_custom_proj_name = st.text_input("Ή πληκτρολογήστε Νέο Έργο (προαιρετικό)", key="edit_r_custom_proj")
                            e_type_options = ["Εβδομαδιαία", "Μηνιαία", "Επιλεγμένες Μέρες Εβδομάδας"]
                            e_type = st.selectbox("Συχνότητα Επανάληψης", e_type_options, index=e_type_options.index(pat.get('type', 'Εβδομαδιαία')))
                            
                            e_employee_ids_saved = pat.get('employeeIds', [])
                            saved_ids_flat = [eid for d_list in e_employee_ids_saved.values() for eid in d_list if eid] if isinstance(e_employee_ids_saved, dict) else [eid for eid in e_employee_ids_saved if eid]
                            edit_options_r = list(set(active_employee_ids + saved_ids_flat))
                            
                            e_emps_selection, e_selected_weekdays_data, e_selected_weekdays = [], {}, pat.get('weekdays', [])
                            if e_type in ["Εβδομαδιαία", "Μηνιαία"]:
                                def_emps = list(set([eid for lst in e_employee_ids_saved.values() for eid in lst if eid])) if isinstance(e_employee_ids_saved, dict) else [eid for eid in e_employee_ids_saved if eid]
                                valid_def_emps = [eid for eid in def_emps if eid in edit_options_r]
                                e_emps_selection = st.multiselect("Αλλαγή Προσωπικού", options=edit_options_r, default=valid_def_emps, format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), 'Άγνωστος'))
                            else:
                                st.markdown("**Αλλαγή Ημερών & Προσωπικού (ανά μέρα):**")
                                day_names = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
                                e_selected_weekdays = []
                                for i, d_name in enumerate(day_names):
                                    c_chk, c_emp = st.columns([1, 3])
                                    if c_chk.checkbox(d_name, value=(d_name in pat.get('weekdays', [])), key=f"edit_chk_{i}_{pat['id']}"):
                                        e_selected_weekdays.append(d_name)
                                        def_day_emps = [eid for eid in e_employee_ids_saved.get(d_name, []) if eid] if isinstance(e_employee_ids_saved, dict) else [eid for eid in e_employee_ids_saved if eid]
                                        e_selected_weekdays_data[d_name] = c_emp.multiselect(f"Προσωπικό ({d_name})", options=edit_options_r, default=[eid for eid in def_day_emps if eid in edit_options_r], format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), 'Άγνωστος'), label_visibility="collapsed")
                            
                            e_color_col, e_notes_col = st.columns(2)
                            with e_color_col: e_color = st.selectbox("Αλλαγή Χρώματος", options=list(BASIC_COLORS.keys()), index=list(BASIC_COLORS.keys()).index(pat.get('colorName')) if pat.get('colorName') in BASIC_COLORS else 0)
                            with e_notes_col: e_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", value=pat.get('notes', ''))

                        with e_col2:
                            e_start_date = st.date_input("Αλλαγή Ημερομηνίας Έναρξης", value=pat['startDate'])
                            e_start_time = st.time_input("Αλλαγή Ώρας Έναρξης", value=datetime.strptime(pat['startTime'], "%H:%M").time())
                            e_end_time = st.time_input("Αλλαγή Ώρας Λήξης", value=datetime.strptime(pat['endTime'], "%H:%M").time())
                            
                        st.write("")
                        col_b1, col_b2 = st.columns(2)
                        with col_b1: save_rec = st.form_submit_button("💾 Αποθήκευση Αλλαγών", type="primary")
                        with col_b2: del_rec = st.form_submit_button("🗑️ Διαγραφή ΟΛΗΣ της σειράς")
                            
                        if del_rec:
                            old_assigns = [a for a in st.session_state.assignments if a.get('recurring_id') == selected_pattern_id]
                            st.session_state.assignments = [a for a in st.session_state.assignments if a.get('recurring_id') != selected_pattern_id]
                            st.session_state.recurring_patterns = [p for p in st.session_state.recurring_patterns if p['id'] != selected_pattern_id]
                            db_delete('assignments', 'recurring_id', selected_pattern_id, track=False)
                            db_delete('recurring_patterns', 'id', selected_pattern_id, track=False)
                            add_transaction([{'type': 'delete', 'table': 'assignments', 'records': old_assigns}, {'type': 'delete', 'table': 'recurring_patterns', 'records': [dict(pat)]}])
                            st.rerun()
                            
                        if save_rec:
                            str_start, str_end = e_start_time.strftime("%H:%M"), e_end_time.strftime("%H:%M")
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
                                else: final_e_proj_id = e_proj
                                    
                                old_assigns = [a for a in st.session_state.assignments if a.get('recurring_id') == selected_pattern_id]
                                st.session_state.assignments = [a for a in st.session_state.assignments if a.get('recurring_id') != selected_pattern_id]
                                db_delete('assignments', 'recurring_id', selected_pattern_id, track=False)
                                actions.append({'type': 'delete', 'table': 'assignments', 'records': old_assigns})
                                
                                r_end_date = e_start_date + timedelta(days=365 * 3)
                                dates_to_assign = []
                                curr_date = e_start_date
                                day_map_inv = {0: "Δευτέρα", 1: "Τρίτη", 2: "Τετάρτη", 3: "Πέμπτη", 4: "Παρασκευή", 5: "Σάββατο", 6: "Κυριακή"}
                                selected_weekday_ints = [{"Δευτέρα": 0, "Τρίτη": 1, "Τετάρτη": 2, "Πέμπτη": 3, "Παρασκευή": 4, "Σάββατο": 5, "Κυριακή": 6}[d] for d in e_selected_weekdays] if e_selected_weekdays else []
                                
                                new_assignments_batch = []
                                with st.spinner('Ενημέρωση και καταχώρηση βαρδιών...'):
                                    while curr_date <= r_end_date:
                                        if e_type == "Εβδομαδιαία": dates_to_assign.append(curr_date); curr_date += timedelta(days=7)
                                        elif e_type == "Μηνιαία":
                                            dates_to_assign.append(curr_date)
                                            month, year = curr_date.month, curr_date.year
                                            if month == 12: month = 1; year += 1
                                            else: month += 1
                                            try: curr_date = curr_date.replace(year=year, month=month)
                                            except ValueError: curr_date = curr_date.replace(year=year, month=month, day=calendar.monthrange(year, month)[1])
                                        elif e_type == "Επιλεγμένες Μέρες Εβδομάδας":
                                            if curr_date.weekday() in selected_weekday_ints: dates_to_assign.append(curr_date)
                                            curr_date += timedelta(days=1)
                                
                                    for d in dates_to_assign:
                                        emps_to_process = e_selected_weekdays_data.get(day_map_inv[d.weekday()], []) if e_type == "Επιλεγμένες Μέρες Εβδομάδας" else e_emps_selection
                                        emps_to_process = emps_to_process if emps_to_process else [""]
                                        
                                        for eid in emps_to_process:
                                            if eid:
                                                if is_on_leave(eid, d): st.toast(f"🛑 Παραλείφθηκε: {get_employee_name(eid)} (Άδεια)", icon="🛑")
                                                else:
                                                    adj_s, adj_e, is_conf, msg = check_and_resolve_conflict(eid, d, str_start, str_end)
                                                    if is_conf: st.toast(f"🚨 Παραλείφθηκε: {get_employee_name(eid)} (Επικάλυψη)", icon="🚨")
                                                    else: new_assignments_batch.append({'id': str(uuid.uuid4()), 'recurring_id': selected_pattern_id, 'employeeId': eid, 'projectId': final_e_proj_id, 'date': d, 'startTime': adj_s, 'endTime': adj_e, 'colorName': e_color, 'colorHex': BASIC_COLORS[e_color], 'notes': e_notes, 'is_cancelled': False, 'cancel_reason': ""})
                                            else:
                                                new_assignments_batch.append({'id': str(uuid.uuid4()), 'recurring_id': selected_pattern_id, 'employeeId': "", 'projectId': final_e_proj_id, 'date': d, 'startTime': str_start, 'endTime': str_end, 'colorName': e_color, 'colorHex': BASIC_COLORS[e_color], 'notes': e_notes, 'is_cancelled': False, 'cancel_reason': ""})
                                
                                    old_pat = dict(pat)
                                    pat.update({'projectId': final_e_proj_id, 'employeeIds': e_selected_weekdays_data if e_type == "Επιλεγμένες Μέρες Εβδομάδας" else e_emps_selection, 'colorName': e_color, 'notes': e_notes, 'type': e_type, 'weekdays': e_selected_weekdays, 'startDate': e_start_date, 'startTime': str_start, 'endTime': str_end})
                                    db_update('recurring_patterns', selected_pattern_id, pat, old_data=old_pat, track=False)
                                    actions.append({'type': 'update', 'table': 'recurring_patterns', 'old_records': [old_pat], 'new_records': [dict(pat)]})
                                    
                                    if new_assignments_batch:
                                        st.session_state.assignments.extend(new_assignments_batch)
                                        for i in range(0, len(new_assignments_batch), 500): db_insert('assignments', new_assignments_batch[i:i+500], track=False)
                                        actions.append({'type': 'insert', 'table': 'assignments', 'records': new_assignments_batch})
                                
                                    add_transaction(actions)
                                st.success("Η σειρά εργασιών ενημερώθηκε επιτυχώς! Η σελίδα ανανεώνεται...")
                                time.sleep(1.5); st.rerun()

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
                st.success(f"🌟 **{get_employee_name(ev['employeeId'])}** — Υψηλότερος Μέσος Όρος: **{max_avg:.2f} / 5** 🌟")
        else: st.info("Οι βαθμολογίες για αυτόν τον μήνα είναι στο 0.")
    else: st.info("Δεν υπάρχουν ακόμα αποθηκευμένες βαθμολογίες για τον επιλεγμένο μήνα.")

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
                    if f"coop_{emp}_{eval_month}_{eval_year}" in st.session_state: del st.session_state[f"coop_{emp}_{eval_month}_{eval_year}"]
                    if f"will_{emp}_{eval_month}_{eval_year}" in st.session_state: del st.session_state[f"will_{emp}_{eval_month}_{eval_year}"]
                    if f"behav_{emp}_{eval_month}_{eval_year}" in st.session_state: del st.session_state[f"behav_{emp}_{eval_month}_{eval_year}"]
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
            c5.write(f"\n**{((default_coop + default_will + default_behav) / 3.0):.2f}**")

        st.markdown("---")
        submit_eval = st.form_submit_button("💾 Αποθήκευση Αξιολογήσεων", type="primary", use_container_width=True, disabled=is_readonly)

        if submit_eval and not is_readonly:
            updates_made, actions = False, []
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
            if updates_made: st.success("Οι αξιολογήσεις αποθηκεύτηκαν επιτυχώς!"); st.rerun()
            else: st.info("Δεν υπήρξαν αλλαγές για αποθήκευση.")

# --- VIEW: ΚΑΤΑΓΡΑΦΗ ΚΙΝΗΣΕΩΝ (ΜΟΝΟ ADMIN) ---
elif menu == "Καταγραφή Κινήσεων":
    st.title("📜 Καταγραφή Κινήσεων (Audit Log)")
    st.write("Παρακολουθήστε τις ενέργειες όλων των χρηστών στο σύστημα (Δημιουργία, Ενημέρωση, Διαγραφή).")
    
    col_b1, col_b2 = st.columns([1, 4])
    with col_b1:
        if st.button("🔄 Ανανέωση Ιστορικού", use_container_width=True): clear_cache_for_table("activity_logs"); st.rerun()
    with col_b2:
        if st.button("🗑️ Καθαρισμός Ιστορικού", type="primary"):
            if supabase and st.session_state.activity_logs:
                try:
                    log_ids = [l['id'] for l in st.session_state.activity_logs]
                    for i in range(0, len(log_ids), 500): supabase.table('activity_logs').delete().in_('id', log_ids[i:i+500]).execute()
                    clear_cache_for_table("activity_logs")
                    st.success("Το ιστορικό καθαρίστηκε!"); time.sleep(1); st.rerun()
                except Exception as e: st.error(f"Σφάλμα καθαρισμού: {e}")

    if not st.session_state.activity_logs:
        st.info("Δεν υπάρχουν καταγεγραμμένες κινήσεις ακόμα.")
    else:
        sorted_logs = sorted(st.session_state.activity_logs, key=lambda x: x.get('timestamp', ''), reverse=True)
        TABLE_NAMES_GR = {'employees': 'Προσωπικό', 'projects': 'Έργα', 'assignments': 'Βάρδιες', 'leaves': 'Άδειες', 'recurring_patterns': 'Επαν. Εργασίες', 'evaluations': 'Αξιολογήσεις'}
        log_data = []
        for log in sorted_logs:
            try:
                dt_obj = datetime.fromisoformat(log.get('timestamp', ''))
                dt_str = dt_obj.strftime("%d/%m/%Y %H:%M:%S")
            except: dt_str = log.get('timestamp', '')
            table_gr = TABLE_NAMES_GR.get(log.get('table_name', ''), log.get('table_name', '-'))
            
            # Custom try/except evaluation to safely display old DB string layouts
            details_str = log.get('details', '-')
            if isinstance(details_str, str) and (details_str.startswith("[{") or details_str.startswith("{")):
                try:
                    clean_str = re.sub(r"datetime\.date\((\d+),\s*(\d+),\s*(\d+)\)", r"'\3/\2/\1'", details_str)
                    details_safe = format_log_details(log.get('table_name', ''), ast.literal_eval(clean_str))
                except: details_safe = details_str
            else: details_safe = details_str
                
            log_data.append({"Ημερομηνία/Ώρα": dt_str, "Χρήστης": log.get('username', '-'), "Ενέργεια": log.get('action_type', '-'), "Πίνακας (Στοιχείο)": table_gr, "Λεπτομέρειες": details_safe})
        st.dataframe(pd.DataFrame(log_data), use_container_width=True, hide_index=True)
