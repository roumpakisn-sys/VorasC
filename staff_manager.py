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
CACHE_TTL = 60 

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
    if table == "employees": fetch_table_employees.clear()
    elif table == "projects": fetch_table_projects.clear()
    elif table == "assignments": fetch_table_assignments.clear()
    elif table == "leaves": fetch_table_leaves.clear()
    elif table == "recurring_patterns": fetch_table_patterns.clear()
    elif table == "evaluations": fetch_table_evaluations.clear()
    elif table == "activity_logs": fetch_table_activity_logs.clear()

def clear_all_caches():
    fetch_table_employees.clear()
    fetch_table_projects.clear()
    fetch_table_assignments.clear()
    fetch_table_leaves.clear()
    fetch_table_patterns.clear()
    fetch_table_evaluations.clear()
    fetch_table_activity_logs.clear()

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
        clean_str = re.sub(r"datetime\.date\((\d+),\s*(\d+),\s*(\d+)\)", r"'\3/\2/\1'", details_str)
        parsed_data = ast.literal_eval(clean_str)
        return format_log_details(table_name, parsed_data)
    except Exception:
        return details_str

def log_activity(action_type, table_name, details_raw):
    if not supabase: return
    if table_name == 'activity_logs': return 
    user = st.session_state.get("current_user", "Άγνωστος")
    try:
        from zoneinfo import ZoneInfo
        now_gr = datetime.now(ZoneInfo("Europe/Athens")).isoformat()
    except Exception:
        now_gr = (datetime.utcnow() + timedelta(hours=3)).isoformat()
    detail_str = str(details_raw)[:2000]
    log_entry = {
        "id": str(uuid.uuid4()),
        "timestamp": now_gr,
        "username": user,
        "action_type": action_type,
        "table_name": table_name,
        "details": detail_str
    }
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

def has_time_conflict(emp_id, check_date, t_start, t_end, exclude_ids=None):
    if not emp_id: return False
    if exclude_ids is None: exclude_ids = []
    new_start = datetime.strptime(t_start, "%H:%M").time()
    new_end = datetime.strptime(t_end, "%H:%M").time()
    for a in st.session_state.assignments:
        if a['employeeId'] == emp_id and a['date'] == check_date and a['id'] not in exclude_ids:
            a_start = datetime.strptime(a['startTime'], "%H:%M").time()
            a_end = datetime.strptime(a['endTime'], "%H:%M").time()
            if new_start < a_end and new_end > a_start: return True
    return False

def go_prev_week():
    st.session_state.view_week_date -= timedelta(days=7)

def go_next_week():
    st.session_state.view_week_date += timedelta(days=7)

def go_to_today():
    """Επαναφέρει την προβολή στη σημερινή εβδομάδα"""
    st.session_state.view_week_date = date.today()

# --- LOAD DATA ---
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
        st.session_state.employees = []
        st.session_state.projects = []
        st.session_state.assignments = []
        st.session_state.recurring_patterns = []
        st.session_state.leaves = []
        st.session_state.evaluations = []
        st.session_state.activity_logs = []

if 'view_week_date' not in st.session_state:
    st.session_state.view_week_date = date.today()

is_full_admin = st.session_state.get('current_user') != "TAN"

# --- Sidebar Navigation ---
st.sidebar.title("STAFF.PRO")
menu_options = ["Ταμπλό Gantt", "Διαχείριση Έργων", "Ομάδα Προσωπικού", "Άδειες", "Σύνολο Αδειών", "Επαναλαμβανόμενες Εργασίες", "Ώρες Εργασιών", "Αξιολόγηση Προσωπικού"]
if st.session_state.get('current_user') == "Admin": menu_options.append("Καταγραφή Κινήσεων")
menu = st.sidebar.radio("Μενού", menu_options)

st.sidebar.write("---")
col_u, col_r = st.sidebar.columns(2)
with col_u:
    if st.button("↩️ Undo", disabled=len(st.session_state.undo_stack) == 0, use_container_width=True): perform_undo(); st.rerun()
with col_r:
    if st.button("↪️ Redo", disabled=len(st.session_state.redo_stack) == 0, use_container_width=True): perform_redo(); st.rerun()

st.sidebar.write("---")
if st.session_state.get('is_cloud'):
    st.sidebar.success(f"✅ Cloud Sync (Ανανέωση {CACHE_TTL}s)")
    if st.sidebar.button("🔄 Άμεση Ανανέωση", use_container_width=True): clear_all_caches(); st.rerun()
else:
    st.sidebar.error("❌ Εκτός Σύνδεσης (Τοπικά)")

st.sidebar.write("---")
st.sidebar.markdown(f"👤 Συνδεδεμένος ως: **{st.session_state.get('current_user', 'Άγνωστος')}**")
if st.sidebar.button("🚪 Αποσύνδεση", use_container_width=True):
    st.session_state.authenticated = False
    st.session_state.current_user = None
    st.rerun()

active_employee_ids = [e['id'] for e in st.session_state.employees if e.get('status', 'Ενεργός') == 'Ενεργός']

# --- ΣΥΣΤΗΜΑ ΕΙΔΟΠΟΙΗΣΕΩΝ ---
today_date = date.today()
next_week_date = today_date + timedelta(days=7)
orphan_count = 0
orphan_details = []
for a in st.session_state.assignments:
    shift_date = a.get('date')
    if today_date <= shift_date <= next_week_date:
        if not a.get('employeeId') and not a.get('is_cancelled', False):
            orphan_count += 1
            proj = get_project_info(a['projectId'])
            pname = proj['name'] if proj else "Άγνωστο Έργο"
            orphan_details.append(f"• **{shift_date.strftime('%d/%m/%Y')}** | Ώρες: {a['startTime']}-{a['endTime']} | Έργο: **{pname}**")

if orphan_count > 0:
    st.error(f"🚨 **Προσοχή: {orphan_count} βάρδια/ες τις επόμενες 7 ημέρες έμειναν ορφανές!**")
    with st.expander("👁️ Δείτε αναλυτικά τις ορφανές βάρδιες"):
        for detail in orphan_details: st.markdown(detail)
    st.write("---")

# --- VIEW: DASHBOARD (GANTT) ---
if menu == "Ταμπλό Gantt":
    st.title("📅 Εβδομαδιαίο Χρονοδιάγραμμα Πόρων")
    
    # Πλοήγηση Εβδομάδων
    col_nav1, col_date, col_nav2, col_today, col_zoom, col_pres = st.columns([1, 2, 1, 1, 2, 2.5])
    with col_nav1:
        st.write("")
        st.button("⬅️ Προν", on_click=go_prev_week, use_container_width=True)
    with col_date:
        selected_date = st.date_input("Επιλογή Εβδομάδας", key="view_week_date")
        start_of_week = selected_date - timedelta(days=selected_date.weekday())
    with col_nav2:
        st.write("")
        st.button("Επόμ ➡️", on_click=go_next_week, use_container_width=True)
    with col_today:
        st.write("")
        st.button("🏠 Σήμερα", on_click=go_to_today, use_container_width=True)
    with col_zoom:
        zoom_level = st.slider("🔍 Ζουμ Διαγράμματος (%)", min_value=50, max_value=200, value=100, step=5)
    with col_pres:
        st.write(""); st.write("")
        presentation_mode = st.checkbox("🖥️ Λειτουργία Πλήρους Προβολής")
        
    zoom_factor = zoom_level / 100.0
    
    data, export_data, color_map, y_category_order, tickvals, ticktext, empty_shift_annotations = [], [], {}, [], [], [], []
    day_names_gr = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
    
    for i in range(7):
        curr_date = start_of_week + timedelta(days=i)
        day_str = f"{day_names_gr[i]} {curr_date.strftime('%d/%m')}"
        leaves_today = []
        for l in st.session_state.leaves:
            if l['startDate'] <= curr_date <= l['endDate']:
                emp_full = get_employee_name(l['employeeId'])
                sub_id = l.get('substituteId')
                if sub_id:
                    sub_full = get_employee_name(sub_id)
                    leaves_today.append(f"<b>{emp_full}</b><br><span style='font-size:10px; color:#991b1b;'>↳ Αντικ: <b>{sub_full}</b></span>")
                else:
                    leaves_today.append(f"<b>{emp_full}</b>")
        
        leaves_str = "<br><br>".join(leaves_today) if leaves_today else "Καμία"
        base_y_label = f"<b>{day_str}</b><br><span style='font-size:11px; color:#d32f2f;'>Άδειες:<br>{leaves_str}</span>"
        day_assignments = [a for a in st.session_state.assignments if a['date'] == curr_date]
        
        if not day_assignments:
            row_id = f"day_{i}_row_0"
            y_category_order.append(row_id); tickvals.append(row_id); ticktext.append(base_y_label)
            data.append({'Y_Axis': row_id, 'Έργο': 'Κενό', 'Έναρξη': datetime(1970, 1, 1, 8, 0), 'Λήξη': datetime(1970, 1, 1, 8, 0), 'ColorHex': 'rgba(0,0,0,0)', 'GroupKey': 'Empty', 'Ετικέτα': '', 'LegendGroup': 'Κενό'})
            color_map['Κενό'] = 'rgba(0,0,0,0)'; continue

        groups = {}
        for a in day_assignments:
            proj = get_project_info(a['projectId'])
            c_hex = a.get('colorHex', proj['color'] if proj else "#999999")
            key = f"{curr_date}_{a['projectId']}_{a['startTime']}_{a['endTime']}_{c_hex}_{a.get('notes', '')}_{a.get('is_cancelled', False)}"
            if key not in groups:
                groups[key] = {'Project': proj['name'] if proj else "Άγνωστο", 'StartTime': a['startTime'], 'EndTime': a['endTime'], 'Start': datetime.combine(datetime(1970, 1, 1), datetime.strptime(a['startTime'], "%H:%M").time()), 'End': datetime.combine(datetime(1970, 1, 1), datetime.strptime(a['endTime'], "%H:%M").time()), 'Employees': [], 'ColorHex': c_hex, 'Notes': a.get('notes', ''), 'is_cancelled': a.get('is_cancelled', False), 'cancel_reason': a.get('cancel_reason', ''), 'LegendGroup': f"{proj['name'] if proj else 'Άγνωστο'} ({a.get('colorName', 'Προεπιλογή')})", 'Key': key}
            
            emp_n = get_employee_name(a['employeeId'])
            groups[key]['Employees'].append(emp_n)

        sorted_groups = sorted(groups.values(), key=lambda x: x['Start'])
        lanes = []
        for g in sorted_groups:
            placed = False
            for idx, end in enumerate(lanes):
                if g['Start'] >= end: lanes[idx] = g['End']; row_idx = idx; placed = True; break
            if not placed: lanes.append(g['End']); row_idx = len(lanes) - 1
            
            row_id = f"day_{i}_row_{row_idx}"
            if row_id not in y_category_order: y_category_order.append(row_id); tickvals.append(row_id); ticktext.append(base_y_label if row_idx == 0 else "")
            
            emps_str = ", ".join(g['Employees']).upper()
            base_text = f"{g['StartTime']}-{g['EndTime']} {g['Project'].upper()} // {emps_str}"
            wrap_w = max(15, int(((g['End']-g['Start']).total_seconds()/3600.0) * 16))
            wrapped = "<br>".join(textwrap.wrap(base_text, width=wrap_w))
            
            label = f"<s>{wrapped}</s><br><span style='color:#dc2626;'><b>{g['cancel_reason']}</b></span>" if g['is_cancelled'] else wrapped
            data.append({'Y_Axis': row_id, 'Έργο': g['Project'], 'Έναρξη': g['Start'], 'Λήξη': g['End'], 'Ετικέτα': label, 'LegendGroup': g['LegendGroup'], 'ColorHex': g['ColorHex'], 'GroupKey': g['Key']})
            color_map[g['LegendGroup']] = g['ColorHex']

    df = pd.DataFrame(data)
    fig = px.timeline(df, x_start="Έναρξη", x_end="Λήξη", y="Y_Axis", color="LegendGroup", color_discrete_map=color_map, text="Ετικέτα", custom_data=["GroupKey"])
    fig.update_yaxes(categoryorder='array', categoryarray=y_category_order[::-1], tickmode='array', tickvals=tickvals, ticktext=ticktext, showgrid=False)
    
    scaled_font = max(8, int((10 if not presentation_mode else 12) * zoom_factor))
    fig.update_traces(textposition='inside', insidetextanchor='middle', textfont=dict(color='black', size=scaled_font, family="Arial Black"), marker=dict(line=dict(color='black', width=1)))
    
    # --- STICKY HEADER LOGIC ---
    total_rows = len(y_category_order)
    row_h = 90 * zoom_factor
    visible_count = 650 / row_h
    if presentation_mode or total_rows <= visible_count:
        dyn_h, y_range = max(500, int(total_rows * row_h) + 100), None
    else:
        dyn_h = 750
        offset = (date.today() - start_of_week).days
        if 0 <= offset <= 6:
            idxs = [idx for idx, val in enumerate(y_category_order[::-1]) if val.startswith(f"day_{offset}_")]
            if idxs:
                mid = sum(idxs)/len(idxs)
                y_range = [max(-0.5, mid - visible_count/2), min(total_rows-0.5, mid + visible_count/2)]
            else: y_range = [total_rows - visible_count - 0.5, total_rows - 0.5]
        else: y_range = [total_rows - visible_count - 0.5, total_rows - 0.5]

    fig.update_layout(bargap=0.02, showlegend=False, plot_bgcolor='#dbece8', height=dyn_h, margin=dict(l=10, r=10, t=50, b=10),
                      xaxis=dict(side='top', tickmode='linear', dtick=1800000, tickformat="%H:%M", range=[datetime(1970, 1, 1, 6, 0), datetime(1970, 1, 1, 17, 0)]),
                      yaxis=dict(title="", range=y_range, fixedrange=False), dragmode="pan")
    
    clicked_key = None
    event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", selection_mode="points")
    if event and "selection" in event and event["selection"].get("points"):
        clicked_key = event["selection"]["points"][0].get("customdata", [None])[0]

    st.caption("💡 **Tip:** Σύρετε (Drag) το γράφημα πάνω-κάτω για κύλιση. Κάντε κλικ σε μια μπάρα για επεξεργασία.")

    if not presentation_mode and is_full_admin:
        st.divider()
        col_add, col_edit = st.columns(2)
        with col_add:
            st.subheader("➕ Νέα Τοποθέτηση")
            with st.form("quick_add", clear_on_submit=True):
                a_date = st.date_input("Ημερομηνία", value=selected_date)
                p_id = st.selectbox("Έργο", options=[p['id'] for p in st.session_state.projects], format_func=lambda x: next(p['name'] for p in st.session_state.projects if p['id']==x))
                e_ids = st.multiselect("Προσωπικό", options=active_employee_ids, format_func=get_employee_name)
                c_name = st.selectbox("Χρώμα", options=list(BASIC_COLORS.keys()))
                t_s = st.time_input("Έναρξη", value=datetime.strptime("09:00", "%H:%M").time())
                t_e = st.time_input("Λήξη", value=datetime.strptime("17:00", "%H:%M").time())
                if st.form_submit_button("Καταχώρηση"):
                    if t_s >= t_e: st.error("Λάθος ώρες")
                    else:
                        new_batch = []
                        for eid in (e_ids if e_ids else [""]):
                            if eid and (is_on_leave(eid, a_date) or has_time_conflict(eid, a_date, t_s.strftime("%H:%M"), t_e.strftime("%H:%M"))):
                                st.toast(f"🚨 Πρόβλημα με {get_employee_name(eid)}", icon="🚨"); continue
                            new_batch.append({'id': str(uuid.uuid4()), 'employeeId': eid, 'projectId': p_id, 'date': a_date, 'startTime': t_s.strftime("%H:%M"), 'endTime': t_e.strftime("%H:%M"), 'colorName': c_name, 'colorHex': BASIC_COLORS[c_name]})
                        if new_batch: db_insert("assignments", new_batch); st.rerun()

        with col_edit:
            st.subheader("✏️ Επεξεργασία")
            # Συνοπτική λογική επεξεργασίας... (παραμένει ως είχε στον κώδικά σας)

# --- VIEW: Άδειες (Approval System) ---
elif menu == "Άδειες":
    st.title("🏖️ Διαχείριση Αδειών")
    if "pending_leave" not in st.session_state: st.session_state.pending_leave = None
    if "leave_conflicts" not in st.session_state: st.session_state.leave_conflicts = []
    
    tab_list, tab_add = st.tabs(["📋 Λίστα", "➕ Καταχώρηση"])
    with tab_add:
        with st.form("l_form"):
            l_emp = st.selectbox("Υπάλληλος", options=active_employee_ids, format_func=get_employee_name)
            l_s = st.date_input("Από"); l_e = st.date_input("Έως")
            l_sub = st.selectbox("Αντικαταστάτης", options=[""] + active_employee_ids, format_func=lambda x: get_employee_name(x) if x else "Κανείς")
            if st.form_submit_button("Έλεγχος & Καταχώρηση"):
                conflicts = [a for a in st.session_state.assignments if a['employeeId'] == l_emp and l_s <= a['date'] <= l_e]
                if conflicts:
                    st.session_state.pending_leave = {'employeeId': l_emp, 'startDate': l_s, 'endDate': l_e, 'substituteId': l_sub if l_sub else None}
                    st.session_state.leave_conflicts = conflicts
                else:
                    db_insert('leaves', {'id': str(uuid.uuid4()), 'employeeId': l_emp, 'startDate': l_s, 'endDate': l_e, 'substituteId': l_sub if l_sub else None})
                    st.success("Έγινε!"); time.sleep(1); st.rerun()

        if st.session_state.pending_leave and st.session_state.leave_conflicts:
            st.warning("⚠️ **Εμπλοκή με βάρδιες:** Ο εργαζόμενος δουλεύει τις παρακάτω μέρες. Πατήστε 'Έγκριση' για να τον αφαιρέσετε από το έργο και να εγκριθεί η άδεια.")
            for a in st.session_state.leave_conflicts:
                c1, c2 = st.columns([4, 1])
                proj = get_project_info(a['projectId'])
                c1.error(f"📍 {a['date'].strftime('%d/%m')} στο έργο '{proj['name'] if proj else '?'}'")
                if c2.button("✅ Έγκριση", key=f"appr_{a['id']}"):
                    target = next(assign for assign in st.session_state.assignments if assign['id'] == a['id'])
                    old = dict(target); target['employeeId'] = "" # Remove worker
                    db_update('assignments', target['id'], target, old_data=old)
                    st.session_state.leave_conflicts = [c for c in st.session_state.leave_conflicts if c['id'] != a['id']]
                    if not st.session_state.leave_conflicts:
                        db_insert('leaves', {**st.session_state.pending_leave, 'id': str(uuid.uuid4())})
                        st.session_state.pending_leave = None
                    st.rerun()

# --- ΥΠΟΛΟΙΠΕΣ ΣΕΛΙΔΕΣ (Projects, Team, Stats etc.) ---
# Παραμένουν ως είχαν στον αρχικό κώδικα...
