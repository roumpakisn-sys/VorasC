import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, date, timedelta
import uuid
import calendar
import io
import time
import copy

try:
    from supabase import create_client
    SUPABASE_INSTALLED = True
except ImportError:
    SUPABASE_INSTALLED = False

# --- Ρύθμιση σελίδας ---
st.set_page_config(page_title="Staff Manager Pro", layout="wide")

# --- ΟΘΟΝΗ ΣΥΝΔΕΣΗΣ (AUTHENTICATION) ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("<h1 style='text-align: center; margin-top: 10vh;'>🔒 Staff Manager Pro</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray;'>Παρακαλώ εισάγετε τον κωδικό πρόσβασης για να συνεχίσετε.</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("login_form"):
            password = st.text_input("Κωδικός Πρόσβασης", type="password")
            submit = st.form_submit_button("Είσοδος", use_container_width=True)
            
            if submit:
                # Έλεγχος κωδικού (Από secrets ή προεπιλογή το admin123)
                correct_password = st.secrets.get("APP_PASSWORD", "admin123")
                if password == correct_password:
                    st.session_state.authenticated = True
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

@st.cache_data(ttl=15)
def fetch_all_data_from_db():
    """
    Αντλεί όλα τα δεδομένα από το Supabase. 
    Χρησιμοποιεί Pagination (σελιδοποίηση) για να παρακάμψει τον περιορισμό των 1000 γραμμών του Supabase
    και να κατεβάσει ΟΛΕΣ τις βάρδιες, ανεξάρτητα από το πόσες είναι.
    """
    if not supabase:
        return None
        
    def fetch_paginated(table):
        all_rows = []
        offset = 0
        limit = 1000
        while True:
            try:
                # Το Supabase range() περιλαμβάνει και το start και το end (γι' αυτό offset + limit - 1)
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

    try:
        emps = fetch_paginated("employees")
        projs = fetch_paginated("projects")
        
        assigns = fetch_paginated("assignments")
        for a in assigns:
            if isinstance(a.get('date'), str):
                # Ασφαλής μετατροπή ακόμα κι αν επιστραφεί time part
                a['date'] = datetime.strptime(a['date'].split("T")[0], "%Y-%m-%d").date()
                
        leaves = fetch_paginated("leaves")
        for l in leaves:
            if isinstance(l.get('startDate'), str):
                l['startDate'] = datetime.strptime(l['startDate'].split("T")[0], "%Y-%m-%d").date()
            if isinstance(l.get('endDate'), str):
                l['endDate'] = datetime.strptime(l['endDate'].split("T")[0], "%Y-%m-%d").date()
                
        patterns = fetch_paginated("recurring_patterns")
        for p in patterns:
            if isinstance(p.get('startDate'), str):
                p['startDate'] = datetime.strptime(p['startDate'].split("T")[0], "%Y-%m-%d").date()
                
        # Safe fallback για τις Αξιολογήσεις, σε περίπτωση που δεν έχει δημιουργηθεί ακόμα ο πίνακας
        try:
            evals = fetch_paginated("evaluations")
        except Exception:
            evals = []
                
        return {
            "employees": emps,
            "projects": projs,
            "assignments": assigns,
            "leaves": leaves,
            "recurring_patterns": patterns,
            "evaluations": evals
        }
    except Exception as e:
        print(f"Σφάλμα ανάγνωσης από Supabase: {e}")
        return None

def serialize_dates(data):
    """Μετατρέπει τα ημερολογιακά objects σε string για να μπουν σωστά στη βάση (Supabase/JSON)."""
    if isinstance(data, list):
        return [serialize_dates(item) for item in data]
    elif isinstance(data, dict):
        return {k: (v.isoformat() if isinstance(v, (datetime, date)) else v) for k, v in data.items()}
    return data

def db_insert(table, data, track=True):
    """Αποθηκεύει μία εγγραφή ή λίστα εγγραφών στη βάση."""
    if supabase:
        try:
            supabase.table(table).insert(serialize_dates(data)).execute()
            fetch_all_data_from_db.clear()
            if track:
                records = data if isinstance(data, list) else [data]
                add_transaction([{'type': 'insert', 'table': table, 'records': records}])
        except Exception as e:
            st.error(f"Σφάλμα αποθήκευσης στη βάση (Table: {table}): {e}")

def db_delete(table, column, value, deleted_records=None, track=True):
    """Διαγράφει εγγραφές με βάση μια συνθήκη."""
    if supabase:
        try:
            if track and not deleted_records:
                table_data = st.session_state.get(table, [])
                deleted_records = [r for r in table_data if r.get(column) == value]
                
            supabase.table(table).delete().eq(column, value).execute()
            fetch_all_data_from_db.clear()
            
            if track and deleted_records:
                add_transaction([{'type': 'delete', 'table': table, 'records': deleted_records}])
        except Exception as e:
            st.error(f"Σφάλμα διαγραφής στη βάση: {e}")

def db_delete_in(table, column, values, deleted_records=None, track=True):
    """Διαγράφει πολλές εγγραφές με βάση λίστα τιμών (IN)."""
    if supabase and values:
        try:
            if track and not deleted_records:
                table_data = st.session_state.get(table, [])
                deleted_records = [r for r in table_data if r.get(column) in values]
                
            supabase.table(table).delete().in_(column, values).execute()
            fetch_all_data_from_db.clear()
            
            if track and deleted_records:
                add_transaction([{'type': 'delete', 'table': table, 'records': deleted_records}])
        except Exception as e:
            st.error(f"Σφάλμα μαζικής διαγραφής: {e}")

def db_update(table, id_val, new_data, old_data=None, track=True):
    """Ενημερώνει μια εγγραφή με βάση το ID της."""
    if supabase:
        try:
            if track and not old_data:
                table_data = st.session_state.get(table, [])
                old_data = next((r for r in table_data if r.get('id') == id_val), None)
                
            supabase.table(table).update(serialize_dates(new_data)).eq('id', id_val).execute()
            fetch_all_data_from_db.clear()
            
            if track and old_data:
                add_transaction([{'type': 'update', 'table': table, 'old_records': [old_data], 'new_records': [new_data]}])
        except Exception as e:
            st.error(f"Σφάλμα ενημέρωσης στη βάση: {e}")

def perform_undo():
    """Εκτελεί αναίρεση της τελευταίας καταγεγραμμένης συναλλαγής."""
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
    
    fetch_all_data_from_db.clear()

def perform_redo():
    """Εκτελεί επανάληψη της τελευταίας αναιρεμένης συναλλαγής."""
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
                
    fetch_all_data_from_db.clear()

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

# --- Συνεχής Φόρτωση Δεδομένων (Real-time Sync Logic) ---
db_data = fetch_all_data_from_db()

if db_data is not None:
    st.session_state.employees = db_data["employees"]
    st.session_state.projects = db_data["projects"]
    st.session_state.assignments = db_data["assignments"]
    st.session_state.leaves = db_data["leaves"]
    st.session_state.recurring_patterns = db_data["recurring_patterns"]
    st.session_state.evaluations = db_data.get("evaluations", [])
    st.session_state.is_cloud = True
else:
    # Αν ΔΕΝ βρέθηκε Supabase ή υπήρξε σφάλμα, φορτώνουμε τα MOCK δεδομένα (Local mode)
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

if 'view_week_date' not in st.session_state:
    st.session_state.view_week_date = date.today()

# --- Helpers ---
def get_employee_name(emp_id):
    if not emp_id:
        return "Χωρίς Προσωπικό"
    for emp in st.session_state.employees:
        if emp['id'] == emp_id:
            return emp['name']
    return "Άγνωστος"

def get_project_info(proj_id):
    for proj in st.session_state.projects:
        if proj['id'] == proj_id:
            return proj
    return None

def is_on_leave(emp_id, check_date):
    if not emp_id: return False
    for l in st.session_state.leaves:
        if l['employeeId'] == emp_id and l['startDate'] <= check_date <= l['endDate']:
            return True
    return False

def has_time_conflict(emp_id, check_date, t_start, t_end, exclude_ids=None):
    if not emp_id: return False
    if exclude_ids is None:
        exclude_ids = []
        
    new_start = datetime.strptime(t_start, "%H:%M").time()
    new_end = datetime.strptime(t_end, "%H:%M").time()
    
    for a in st.session_state.assignments:
        if a['employeeId'] == emp_id and a['date'] == check_date and a['id'] not in exclude_ids:
            a_start = datetime.strptime(a['startTime'], "%H:%M").time()
            a_end = datetime.strptime(a['endTime'], "%H:%M").time()
            
            # Έλεγχος αν οι ώρες τέμνονται (overlap)
            if new_start < a_end and new_end > a_start:
                return True
    return False

def go_prev_week():
    st.session_state.view_week_date -= timedelta(days=7)

def go_next_week():
    st.session_state.view_week_date += timedelta(days=7)

# --- Sidebar Navigation ---
st.sidebar.title("STAFF.PRO")
menu = st.sidebar.radio("Μενού", [
    "Ταμπλό Gantt", 
    "Διαχείριση Έργων", 
    "Ομάδα Προσωπικού", 
    "Άδειες",
    "Σύνολο Αδειών",
    "Επαναλαμβανόμενες Εργασίες",
    "Ώρες Εργασιών",
    "Αξιολόγηση Προσωπικού"
])

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

# Διαγνωστικός Έλεγχος & Έλεγχος Αποσύνδεσης
if st.session_state.get('is_cloud'):
    st.sidebar.success("✅ Cloud Sync (Ανανέωση 15s)")
    if st.sidebar.button("🔄 Άμεση Ανανέωση", use_container_width=True):
        fetch_all_data_from_db.clear()
        st.rerun()
else:
    st.sidebar.error("❌ Εκτός Σύνδεσης (Τοπικά)")
    if not SUPABASE_INSTALLED:
        st.sidebar.caption("⚠️ **Πρόβλημα:** Λείπει η βιβλιοθήκη 'supabase'. Το Streamlit δεν διάβασε το requirements.txt. Κάνε Reboot την εφαρμογή.")
    elif not HAS_SECRETS:
        st.sidebar.caption("⚠️ **Πρόβλημα:** Δεν βρέθηκαν τα Secrets (SUPABASE_URL ή SUPABASE_KEY) στις ρυθμίσεις του Streamlit.")
    else:
        st.sidebar.caption("⚠️ **Πρόβλημα:** Υπήρξε σφάλμα κατά τη σύνδεση ή τη φόρτωση από τη βάση. Ελέγξτε αν έχετε απενεργοποιήσει το RLS σε όλους τους πίνακες.")

st.sidebar.write("---")
if st.sidebar.button("🚪 Αποσύνδεση", use_container_width=True):
    st.session_state.authenticated = False
    st.rerun()

# --- ΛΙΣΤΑ ΜΟΝΟ ΕΝΕΡΓΩΝ ΥΠΑΛΛΗΛΩΝ (Για τις φόρμες επιλογής) ---
active_employee_ids = [e['id'] for e in st.session_state.employees if e.get('status', 'Ενεργός') == 'Ενεργός']

# --- VIEW: DASHBOARD (GANTT) ---
if menu == "Ταμπλό Gantt":
    st.title("📅 Εβδομαδιαίο Χρονοδιάγραμμα Πόρων")
    
    # Μενού πλοήγησης εβδομάδων
    col_nav1, col_date, col_nav2, col_space, col_pres = st.columns([1, 2, 1, 0.5, 3])
    with col_nav1:
        st.write("")
        st.button("⬅️ Προηγούμενη", on_click=go_prev_week, use_container_width=True)
    with col_date:
        selected_date = st.date_input("Επιλογή Εβδομάδας", key="view_week_date")
        start_of_week = selected_date - timedelta(days=selected_date.weekday())
    with col_nav2:
        st.write("")
        st.button("Επόμενη ➡️", on_click=go_next_week, use_container_width=True)
    with col_pres:
        st.write("")
        st.write("")
        presentation_mode = st.checkbox("🖥️ Λειτουργία Πλήρους Προβολής")
    
    data = []
    export_data = [] # Λίστα για τα δεδομένα που θα εξαχθούν στο Excel
    color_map = {}
    y_category_order = []
    tickvals = []
    ticktext = []
    
    day_names_gr = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
    
    # Διατρέχουμε και τις 7 μέρες της εβδομάδας
    for i in range(7):
        curr_date = start_of_week + timedelta(days=i)
        day_str = f"{day_names_gr[i]} {curr_date.strftime('%d/%m')}"
        
        # Υπολογισμός αδειών για την τρέχουσα μέρα
        leaves_today = [get_employee_name(l['employeeId']) for l in st.session_state.leaves if l['startDate'] <= curr_date <= l['endDate']]
        leaves_str = ", ".join(leaves_today) if leaves_today else "Καμία"
        
        # Η βασική ετικέτα του άξονα Y για αυτή τη μέρα
        base_y_label = f"<b>{day_str}</b><br><span style='font-size:11px; color:#d32f2f;'>Άδειες: {leaves_str}</span>"
        
        day_assignments = [a for a in st.session_state.assignments if a['date'] == curr_date]
        
        # Αν η μέρα δεν έχει καθόλου εργασίες, δημιουργούμε μια διάφανη καταχώρηση
        if not day_assignments:
            row_id = f"day_{i}_row_0"
            y_category_order.append(row_id)
            tickvals.append(row_id)
            ticktext.append(base_y_label)
            
            data.append({
                'Y_Axis': row_id,
                'Έργο': 'Κενό',
                'Έναρξη': datetime(1970, 1, 1, 8, 0),
                'Λήξη': datetime(1970, 1, 1, 8, 0),
                'Προσωπικό': '',
                'Παρατηρήσεις': '',
                'Ετικέτα': '',
                'LegendGroup': 'Κενό',
                'ColorHex': 'rgba(0,0,0,0)',
                'GroupKey': 'Empty'
            })
            color_map['Κενό'] = 'rgba(0,0,0,0)'
            continue
            
        # Ομαδοποίηση εργασιών της τρέχουσας μέρας
        groups = {}
        for a in day_assignments:
            proj = get_project_info(a['projectId'])
            c_hex = a.get('colorHex', proj['color'] if proj else "#999999")
            c_name = a.get('colorName', "Προεπιλογή")
            notes = a.get('notes', '')
            is_canc = a.get('is_cancelled', False)
            c_reason = a.get('cancel_reason', '')
            
            # Δημιουργούμε ένα κλειδί που περιλαμβάνει και την ημερομηνία
            key = f"{curr_date}_{a['projectId']}_{a['startTime']}_{a['endTime']}_{c_hex}_{notes}_{is_canc}_{c_reason}"
            if key not in groups:
                legend_val = f"{proj['name']} ({c_name})" if proj else "Άγνωστο"
                groups[key] = {
                    'Key': key,
                    'Project': proj['name'] if proj else "Άγνωστο",
                    'StartTime': a['startTime'],
                    'EndTime': a['endTime'],
                    'Start': datetime.combine(datetime(1970, 1, 1), datetime.strptime(a['startTime'], "%H:%M").time()),
                    'End': datetime.combine(datetime(1970, 1, 1), datetime.strptime(a['endTime'], "%H:%M").time()),
                    'Employees': [],
                    'ColorHex': c_hex,
                    'Notes': notes,
                    'is_cancelled': is_canc,
                    'cancel_reason': c_reason,
                    'LegendGroup': legend_val
                }
            
            # Μορφοποίηση ονόματος: Επώνυμο + Αρχικό Ονόματος (π.χ. ΠΑΠΑΔΟΠΟΥΛΟΣ Γ.)
            if not a.get('employeeId'):
                formatted_name = "ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ"
            else:
                full_name = get_employee_name(a['employeeId'])
                name_parts = full_name.split()
                if len(name_parts) > 1:
                    first_name_initial = name_parts[0][0] + "."
                    last_name = name_parts[-1]
                    formatted_name = f"{last_name} {first_name_initial}"
                else:
                    formatted_name = full_name
                
            groups[key]['Employees'].append(formatted_name)

        # Αλγόριθμος πακεταρίσματος για αποφυγή επικαλύψεων (Lanes)
        sorted_groups = sorted(groups.values(), key=lambda x: x['Start'])
        lanes = [] 
        group_row_mapping = []
        
        for g in sorted_groups:
            placed = False
            for lane_idx, lane_end in enumerate(lanes):
                if g['Start'] >= lane_end:
                    row_idx = lane_idx
                    lanes[lane_idx] = g['End']
                    placed = True
                    break
            
            if not placed:
                lanes.append(g['End'])
                row_idx = len(lanes) - 1
            
            group_row_mapping.append((g, row_idx))

        num_lanes = len(lanes)
        middle_lane = num_lanes // 2  # Υπολογισμός της μεσαίας σειράς για κεντράρισμα του κειμένου
        
        day_row_ids = []
        for row_idx in range(num_lanes):
            row_id = f"day_{i}_row_{row_idx}"
            y_category_order.append(row_id)
            tickvals.append(row_id)
            
            # Το όνομα της μέρας θα εμφανιστεί ΜΟΝΟ στη μεσαία σειρά
            if row_idx == middle_lane:
                ticktext.append(base_y_label)
            else:
                ticktext.append("")
                
            day_row_ids.append(row_id)

        # Δημιουργία τελικών δεδομένων προς σχεδίαση
        for g, row_idx in group_row_mapping:
            row_id = day_row_ids[row_idx]
            
            emps_str = ", ".join(g['Employees']).upper()
            proj_name = g['Project'].upper()
            times_str = f"{g['StartTime']}-{g['EndTime']}"
            
            # Διαμόρφωση κειμένου (με ή χωρίς διαγράμμιση)
            if g['is_cancelled']:
                label_text = f"<s>{times_str} {proj_name} // {emps_str}</s>"
                if g['cancel_reason']:
                    label_text += f" <span style='color:#dc2626;'><b>[{g['cancel_reason'].upper()}]</b></span>"
            else:
                label_text = f"{times_str} {proj_name} // {emps_str}"
                
            if g['Notes']:
                label_text += f" ({g['Notes'].upper()})"
                
            data.append({
                'Y_Axis': row_id,
                'Έργο': g['Project'],
                'Έναρξη': g['Start'],
                'Λήξη': g['End'],
                'Προσωπικό': ", ".join(g['Employees']),
                'Παρατηρήσεις': g['Notes'],
                'Ετικέτα': label_text,
                'LegendGroup': g['LegendGroup'],
                'ColorHex': g['ColorHex'],
                'GroupKey': g['Key']
            })
            
            # Προσθήκη δεδομένων για το αρχείο Excel
            export_data.append({
                'Ημερομηνία': curr_date.strftime('%d/%m/%Y'),
                'Ημέρα': day_names_gr[i],
                'Έργο': g['Project'],
                'Προσωπικό': ", ".join(g['Employees']),
                'Ώρα Έναρξης': g['StartTime'],
                'Ώρα Λήξης': g['EndTime'],
                'Παρατηρήσεις': g['Notes'],
                'Ακυρωμένο': 'ΝΑΙ' if g['is_cancelled'] else 'ΟΧΙ',
                'Λόγος Ακύρωσης': g['cancel_reason']
            })
            
            color_map[g['LegendGroup']] = g['ColorHex']
        
    df = pd.DataFrame(data)
    
    # Σταθερά όρια άξονα Χ (από 07:00 το πρωί έως 23:00 το βράδυ)
    day_start = datetime(1970, 1, 1, 7, 0)
    day_end = datetime(1970, 1, 1, 23, 0)
    
    # Σχεδιασμός Γραφήματος
    fig = px.timeline(
        df, 
        x_start="Έναρξη", 
        x_end="Λήξη", 
        y="Y_Axis", 
        color="LegendGroup",
        color_discrete_map=color_map,
        custom_data=["GroupKey"], # Μεταφέρουμε το κλειδί στο γράφημα
        hover_data=["Έργο", "Προσωπικό", "Παρατηρήσεις"],
        text="Ετικέτα"
    )
    
    # Αντιστροφή της λίστας για να φαίνεται η Δευτέρα πάνω-πάνω
    fig.update_yaxes(
        categoryorder='array', 
        categoryarray=y_category_order[::-1],
        tickmode='array',
        tickvals=tickvals,
        ticktext=ticktext,
        showgrid=False # Κρύβουμε τις εσωτερικές γραμμές για να φαίνονται ενωμένα τα κελιά
    )
    
    # --- EXCEL STYLING & BORDERS ---
    fig.update_traces(
        textposition='inside', 
        insidetextanchor='middle',
        textfont=dict(color='black', size=11 if not presentation_mode else 12, family="Arial Black, Arial, sans-serif"),
        marker=dict(line=dict(color='black', width=1))
    )
    
    dynamic_height = max(500, len(y_category_order) * 60 + 100)
    
    fig.update_layout(
        showlegend=False, 
        plot_bgcolor='#dbece8', 
        paper_bgcolor='#ffffff',
        height=dynamic_height,
        margin=dict(l=10, r=10, t=50, b=10),
        xaxis=dict(
            side='top', 
            tickmode='linear',
            tick0=day_start,
            dtick=1800000, # Κάθε 30 λεπτά
            tickformat="%H:%M",
            showgrid=True,
            gridcolor='#a8c8c0',
            gridwidth=1,
            range=[day_start, day_end],
            title="",
            tickfont=dict(size=11, color="black", family="Arial"),
            fixedrange=False,
            rangeslider=dict(visible=True, thickness=0.04, bgcolor="#e2e8f0") # Εμφάνιση μπάρας κύλισης
        ),
        yaxis=dict(
            title="",
            tickfont=dict(size=12, color="black"),
            fixedrange=False
        ),
        dragmode="pan"
    )
    
    # --- ΠΡΟΣΘΗΚΗ ΠΑΧΙΩΝ ΔΙΑΧΩΡΙΣΤΙΚΩΝ ΓΡΑΜΜΩΝ ΑΝΑΜΕΣΑ ΣΤΙΣ ΗΜΕΡΕΣ ---
    for idx in range(len(y_category_order) - 1):
        row_below = y_category_order[::-1][idx]
        row_above = y_category_order[::-1][idx+1]
        
        day_below = row_below.split('_')[1]
        day_above = row_above.split('_')[1]
        
        if day_below != day_above:
            fig.add_shape(type="line", x0=0, x1=1, xref="paper", y0=idx+0.5, y1=idx+0.5, yref="y", line=dict(color="#1f2937", width=2))
            
    fig.add_shape(type="line", x0=0, x1=1, xref="paper", y0=-0.5, y1=-0.5, yref="y", line=dict(color="#1f2937", width=2))
    fig.add_shape(type="line", x0=0, x1=1, xref="paper", y0=len(y_category_order)-0.5, y1=len(y_category_order)-0.5, yref="y", line=dict(color="#1f2937", width=2))

    # --- ΕΠΙΣΗΜΑΝΣΗ ΤΗΣ ΣΗΜΕΡΙΝΗΣ ΗΜΕΡΑΣ ---
    today_date = date.today()
    today_day_index = (today_date - start_of_week).days
    
    if 0 <= today_day_index < 7:
        today_indices = [idx for idx, val in enumerate(y_category_order[::-1]) if val.startswith(f"day_{today_day_index}_")]
        if today_indices:
            min_idx = min(today_indices)
            max_idx = max(today_indices)
            fig.add_hrect(
                y0=min_idx - 0.5, 
                y1=max_idx + 0.5, 
                fillcolor="#b2d8ce", 
                opacity=1, 
                layer="below", 
                line_width=0
            )

    st.markdown(f"### 🗓️ Εβδομάδα: {start_of_week.strftime('%d/%m/%Y')} έως {(start_of_week + timedelta(days=6)).strftime('%d/%m/%Y')}")
    
    # ΑΝΑΓΝΩΡΙΣΗ ΚΛΙΚ ΣΤΟ ΓΡΑΦΗΜΑ
    clicked_key = None
    try:
        event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", selection_mode="points")
        if event:
            pts = []
            if isinstance(event, dict) and "selection" in event:
                pts = event["selection"].get("points", [])
            elif hasattr(event, "selection"):
                if isinstance(event.selection, dict):
                    pts = event.selection.get("points", [])
                else:
                    pts = getattr(event.selection, "points", [])
            
            if pts:
                customdata = pts[0].get("customdata", [])
                for item in customdata:
                    # Ψάχνουμε να βρούμε το κλειδί που περιέχει τα δεδομένα μας
                    if isinstance(item, str) and "_" in item and ":" in item:
                        clicked_key = item
                        break
    except Exception:
        # Ασφαλής εναλλακτική αν το Streamlit δεν υποστηρίζει click events
        st.plotly_chart(fig, use_container_width=True)
    
    # --- ΕΞΑΓΩΓΗ ΣΕ EXCEL ΚΑΙ ΣΥΜΒΟΥΛΕΣ ---
    if export_data:
        col_hint, col_btn = st.columns([3, 1])
        with col_hint:
            st.caption("💡 *Συμβουλές Προβολής:* **1)** Κάντε **κλικ πάνω σε μια μπάρα** για να την επεξεργαστείτε αμέσως παρακάτω! **2)** Σύρετε το διάγραμμα με το ποντίκι ή την κάτω μπάρα κύλισης.")
        with col_btn:
            df_export = pd.DataFrame(export_data)
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_export.to_excel(writer, index=False, sheet_name='Πρόγραμμα')
            
            st.download_button(
                label="📥 Εξαγωγή Προγράμματος (Excel)",
                data=buffer.getvalue(),
                file_name=f"Gantt_Programma_{start_of_week.strftime('%d_%m_%Y')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
    else:
        st.caption("💡 *Συμβουλές Προβολής:* **1)** Κάντε **κλικ πάνω σε μια μπάρα** για να την επεξεργαστείτε αμέσως παρακάτω! **2)** Σύρετε το διάγραμμα με το ποντίκι ή την κάτω μπάρα κύλισης.")

    if not presentation_mode:
        st.divider()

        col_add, col_edit = st.columns(2)

        with col_add:
            st.subheader("➕ Νέα Τοποθέτηση")
            with st.form("quick_add", clear_on_submit=True):
                add_date = st.date_input("Ημερομηνία", value=selected_date)
                
                proj_choice = st.selectbox("Επιλογή Έργου (Από Λίστα)", options=[p['id'] for p in st.session_state.projects], 
                                         format_func=lambda x: next((p['name'] for p in st.session_state.projects if p['id'] == x), "Άγνωστο Έργο"))
                
                custom_proj_name = st.text_input("Ή πληκτρολογήστε Νέο Έργο (Αν συμπληρωθεί, αγνοεί την παραπάνω λίστα)")
                
                # Φιλτράρισμα: Μόνο ενεργοί υπάλληλοι (Μπορεί να μείνει κενό)
                emp_choices = st.multiselect("Προσωπικό (Προαιρετικό - Μόνο Ενεργοί)", options=active_employee_ids,
                                           format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), "Άγνωστος"))
                
                c_color, c_notes = st.columns(2)
                with c_color:
                    color_choice = st.selectbox("Χρώμα Μπάρας", options=list(BASIC_COLORS.keys()))
                with c_notes:
                    add_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", key="add_notes")
                
                c_start, c_end = st.columns(2)
                with c_start:
                    t_start = st.time_input("Έναρξη", value=datetime.strptime("09:00", "%H:%M").time(), key="add_s")
                with c_end:
                    t_end = st.time_input("Λήξη", value=datetime.strptime("17:00", "%H:%M").time(), key="add_e")
                    
                if st.form_submit_button("Καταχώρηση"):
                    str_start = t_start.strftime("%H:%M")
                    str_end = t_end.strftime("%H:%M")
                    
                    if str_start >= str_end:
                        st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                    elif not custom_proj_name.strip() and not proj_choice:
                        st.error("Παρακαλώ επιλέξτε ή πληκτρολογήστε ένα Έργο.")
                    else:
                        emps_to_process = emp_choices if emp_choices else [""]
                        errors = []
                        for eid in emps_to_process:
                            if eid:
                                emp_name = get_employee_name(eid)
                                if is_on_leave(eid, add_date):
                                    errors.append(f"Ο/Η {emp_name} βρίσκεται σε άδεια στις {add_date.strftime('%d/%m')}.")
                                elif has_time_conflict(eid, add_date, str_start, str_end):
                                    errors.append(f"Ο/Η {emp_name} έχει ήδη εργασία που συμπίπτει στις {add_date.strftime('%d/%m')}.")
                        
                        if errors:
                            for err in errors:
                                st.error(err)
                        else:
                            actions = []
                            # Διαχείριση νέου έργου
                            if custom_proj_name.strip():
                                final_proj_id = str(uuid.uuid4())
                                new_p = {'id': final_proj_id, 'name': custom_proj_name.strip(), 'color': BASIC_COLORS[color_choice]}
                                st.session_state.projects.append(new_p)
                                db_insert('projects', new_p, track=False)
                                actions.append({'type': 'insert', 'table': 'projects', 'records': [new_p]})
                            else:
                                final_proj_id = proj_choice
                                
                            new_assigns = []
                            for eid in emps_to_process:
                                new_assign = {
                                    'id': str(uuid.uuid4()),
                                    'employeeId': eid,
                                    'projectId': final_proj_id,
                                    'date': add_date,
                                    'startTime': str_start,
                                    'endTime': str_end,
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
                            actions.append({'type': 'insert', 'table': 'assignments', 'records': new_assigns})
                            add_transaction(actions)
                            
                            st.success("Η ανάθεση ολοκληρώθηκε!")
                            st.rerun()

        with col_edit:
            st.subheader("✏️ Επεξεργασία Μπάρας της Εβδομάδας")
            
            weekly_groups = {}
            weekly_assignments = [a for a in st.session_state.assignments if start_of_week <= a['date'] <= start_of_week + timedelta(days=6)]
            
            for a in weekly_assignments:
                proj = get_project_info(a['projectId'])
                c_hex = a.get('colorHex', proj['color'] if proj else "#999999")
                c_name = a.get('colorName', "Προεπιλογή")
                notes = a.get('notes', '')
                is_canc = a.get('is_cancelled', False)
                c_reason = a.get('cancel_reason', '')
                
                key = f"{a['date']}_{a['projectId']}_{a['startTime']}_{a['endTime']}_{c_hex}_{notes}_{is_canc}_{c_reason}"
                if key not in weekly_groups:
                    weekly_groups[key] = {
                        'Date': a['date'],
                        'ProjectId': a['projectId'],
                        'Project': proj['name'] if proj else "Άγνωστο",
                        'StartTime': a['startTime'],
                        'EndTime': a['endTime'],
                        'EmployeeIds': [],
                        'AssignmentIds': [],
                        'ColorName': c_name,
                        'Notes': notes,
                        'is_cancelled': is_canc,
                        'cancel_reason': c_reason
                    }
                weekly_groups[key]['EmployeeIds'].append(a['employeeId'])
                weekly_groups[key]['AssignmentIds'].append(a['id'])

            if not weekly_groups:
                st.info("Δεν υπάρχουν μπάρες για επεξεργασία αυτή την εβδομάδα.")
            else:
                group_keys = list(weekly_groups.keys())
                group_keys.sort(key=lambda k: (weekly_groups[k]['Date'], weekly_groups[k]['StartTime']))
                
                default_idx = 0
                if clicked_key and clicked_key in group_keys:
                    default_idx = group_keys.index(clicked_key) + 1
                
                selected_key = st.selectbox(
                    "Επιλέξτε Μπάρα (Ημέρα & Έργο)", 
                    options=[""] + group_keys,
                    index=default_idx,
                    format_func=lambda x: "Επιλέξτε..." if x == "" else f"{weekly_groups[x]['Date'].strftime('%d/%m')} - {weekly_groups[x]['Project']} ({weekly_groups[x]['StartTime']}-{weekly_groups[x]['EndTime']})"
                )
                
                if selected_key != "":
                    target_group = weekly_groups[selected_key]
                    
                    with st.form("quick_edit", clear_on_submit=True):
                        edit_date = st.date_input("Αλλαγή Ημερομηνίας", value=target_group['Date'])
                        
                        proj_ids = [p['id'] for p in st.session_state.projects]
                        default_proj_idx = proj_ids.index(target_group['ProjectId']) if target_group['ProjectId'] in proj_ids else 0
                        
                        edit_proj = st.selectbox("Αλλαγή Έργου (Από Λίστα)", options=proj_ids, 
                                                 index=default_proj_idx,
                                                 format_func=lambda x: next((p['name'] for p in st.session_state.projects if p['id'] == x), "Άγνωστο Έργο"))
                                                 
                        edit_custom_proj_name = st.text_input("Ή πληκτρολογήστε Νέο Έργο (προαιρετικό)")
                        
                        # Στην επεξεργασία: Δείχνουμε τους ενεργούς + όσους είναι ήδη στην εργασία (ακόμα κι αν πλέον είναι ανενεργοί)
                        valid_emp_ids = [eid for eid in target_group['EmployeeIds'] if eid]
                        edit_options = list(set(active_employee_ids + valid_emp_ids))
                        edit_emps = st.multiselect("Αλλαγή Προσωπικού (Προαιρετικό)", options=edit_options,
                                                   default=valid_emp_ids,
                                                   format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), 'Άγνωστος'))
                        
                        e_color_col, e_notes_col = st.columns(2)
                        with e_color_col:
                            default_color_idx = list(BASIC_COLORS.keys()).index(target_group['ColorName']) if target_group['ColorName'] in BASIC_COLORS else 0
                            edit_color = st.selectbox("Αλλαγή Χρώματος", options=list(BASIC_COLORS.keys()), index=default_color_idx)
                        with e_notes_col:
                            edit_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", value=target_group['Notes'], key="edit_notes")

                        e_start, e_end = st.columns(2)
                        with e_start:
                            new_t_start = st.time_input("Νέα Έναρξη", value=datetime.strptime(target_group['StartTime'], "%H:%M").time(), key="edit_s")
                        with e_end:
                            new_t_end = st.time_input("Νέα Λήξη", value=datetime.strptime(target_group['EndTime'], "%H:%M").time(), key="edit_e")
                            
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
                            str_start = new_t_start.strftime("%H:%M")
                            str_end = new_t_end.strftime("%H:%M")
                            
                            if str_start >= str_end:
                                st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                            elif not edit_custom_proj_name.strip() and not edit_proj:
                                st.error("Παρακαλώ επιλέξτε ή πληκτρολογήστε ένα Έργο.")
                            else:
                                emps_to_process = edit_emps if edit_emps else [""]
                                errors = []
                                for eid in emps_to_process:
                                    if eid:
                                        emp_name = get_employee_name(eid)
                                        if is_on_leave(eid, edit_date):
                                            errors.append(f"Ο/Η {emp_name} βρίσκεται σε άδεια στις {edit_date.strftime('%d/%m')}.")
                                        elif has_time_conflict(eid, edit_date, str_start, str_end, exclude_ids=target_group['AssignmentIds']):
                                            errors.append(f"Ο/Η {emp_name} έχει ήδη εργασία που συμπίπτει.")
                                        
                                if errors:
                                    for err in errors:
                                        st.error(err)
                                else:
                                    actions = []
                                    # Διαχείριση νέου έργου κατά την επεξεργασία
                                    if edit_custom_proj_name.strip():
                                        final_edit_proj_id = str(uuid.uuid4())
                                        new_p = {'id': final_edit_proj_id, 'name': edit_custom_proj_name.strip(), 'color': BASIC_COLORS[edit_color]}
                                        st.session_state.projects.append(new_p)
                                        db_insert('projects', new_p, track=False)
                                        actions.append({'type': 'insert', 'table': 'projects', 'records': [new_p]})
                                    else:
                                        final_edit_proj_id = edit_proj
                                        
                                    old_assigns = [a for a in st.session_state.assignments if a['id'] in target_group['AssignmentIds']]
                                    st.session_state.assignments = [a for a in st.session_state.assignments if a['id'] not in target_group['AssignmentIds']]
                                    db_delete_in('assignments', 'id', target_group['AssignmentIds'], track=False)
                                    actions.append({'type': 'delete', 'table': 'assignments', 'records': old_assigns})
                                    
                                    new_assigns = []
                                    for eid in emps_to_process:
                                        new_a = {
                                            'id': str(uuid.uuid4()),
                                            'employeeId': eid,
                                            'projectId': final_edit_proj_id,
                                            'date': edit_date,
                                            'startTime': str_start,
                                            'endTime': str_end,
                                            'colorName': edit_color,
                                            'colorHex': BASIC_COLORS[edit_color],
                                            'notes': edit_notes,
                                            'is_cancelled': e_is_cancelled,
                                            'cancel_reason': e_cancel_reason if e_is_cancelled else "",
                                            'recurring_id': None 
                                        }
                                        new_assigns.append(new_a)
                                        st.session_state.assignments.append(new_a)
                                    
                                    db_insert('assignments', new_assigns, track=False)
                                    actions.append({'type': 'insert', 'table': 'assignments', 'records': new_assigns})
                                    
                                    add_transaction(actions)
                                    st.rerun()

# --- VIEW: RECURRING TASKS ---
elif menu == "Επαναλαμβανόμενες Εργασίες":
    st.title("🔄 Επαναλαμβανόμενες Εργασίες")
    st.write("Προσθέστε ή επεξεργαστείτε εργασίες που επαναλαμβάνονται «για πάντα» (προγραμματίζονται αυτόματα για τα επόμενα 3 χρόνια).")
    
    tab_new, tab_edit = st.tabs(["➕ Νέα Καταχώρηση", "✏️ Διαχείριση/Επεξεργασία Υπαρχουσών"])
    
    if "rec_reset_counter" not in st.session_state:
        st.session_state.rec_reset_counter = 0
    rc = st.session_state.rec_reset_counter
    
    # --- ΚΑΡΤΕΛΑ 1: ΝΕΑ Καταχώρηση ---
    with tab_new:
        r_col1, r_col2 = st.columns(2)
        
        with r_col1:
            r_proj = st.selectbox("Επιλογή Έργου (Από Λίστα)", options=[p['id'] for p in st.session_state.projects], 
                                     format_func=lambda x: next((p['name'] for p in st.session_state.projects if p['id'] == x), "Άγνωστο Έργο"), key=f"new_r_proj_{rc}")
                                     
            r_custom_proj_name = st.text_input("Ή πληκτρολογήστε Νέο Έργο (Αν συμπληρωθεί, αγνοεί την παραπάνω λίστα)", key=f"new_r_custom_proj_{rc}")
            
            # Φιλτράρισμα: Μόνο ενεργοί υπάλληλοι (Μπορεί να μείνει κενό)
            r_emps = st.multiselect("Προσωπικό (Προαιρετικό - Μόνο Ενεργοί)", options=active_employee_ids,
                                       format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), "Άγνωστος"), key=f"new_r_emps_{rc}")
            
            c_r_color, c_r_notes = st.columns(2)
            with c_r_color:
                r_color = st.selectbox("Χρώμα Μπάρας", options=list(BASIC_COLORS.keys()), key=f"new_r_color_{rc}")
            with c_r_notes:
                r_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", key=f"new_r_notes_{rc}")
            
            r_type = st.selectbox("Συχνότητα Επανάληψης", ["Εβδομαδιαία", "Μηνιαία", "Επιλεγμένες Μέρες Εβδομάδας"], key=f"new_r_type_{rc}")
            
            selected_weekdays = []
            if r_type == "Επιλεγμένες Μέρες Εβδομάδας":
                st.caption("Επιλέξτε Μέρες (τικάρετε τα κουτάκια):")
                day_names = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
                cols = st.columns(4)
                for i, d_name in enumerate(day_names):
                    if cols[i % 4].checkbox(d_name, value=(i==0), key=f"new_chk_{i}_{rc}"):
                        selected_weekdays.append(d_name)
        
        with r_col2:
            r_start_date = st.date_input("Από Ημερομηνία", date.today(), key=f"new_r_start_date_{rc}")
            r_start_time = st.time_input("Έναρξη Ώρας", value=datetime.strptime("09:00", "%H:%M").time(), key=f"new_r_start_time_{rc}")
            r_end_time = st.time_input("Λήξη Ώρας", value=datetime.strptime("17:00", "%H:%M").time(), key=f"new_r_end_time_{rc}")
            
            st.info("💡 Η εργασία θα επαναλαμβάνεται συνεχώς.")
        
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
                
                # Διαχείριση νέου έργου
                if r_custom_proj_name.strip():
                    final_r_proj_id = str(uuid.uuid4())
                    new_p = {'id': final_r_proj_id, 'name': r_custom_proj_name.strip(), 'color': BASIC_COLORS[r_color]}
                    st.session_state.projects.append(new_p)
                    db_insert('projects', new_p, track=False)
                    actions.append({'type': 'insert', 'table': 'projects', 'records': [new_p]})
                else:
                    final_r_proj_id = r_proj
                    
                pattern_id = str(uuid.uuid4())
                r_end_date = r_start_date + timedelta(days=365 * 3)
                
                dates_to_assign = []
                curr_date = r_start_date
                day_map = {"Δευτέρα": 0, "Τρίτη": 1, "Τετάρτη": 2, "Πέμπτη": 3, "Παρασκευή": 4, "Σάββατο": 5, "Κυριακή": 6}
                selected_weekday_ints = [day_map[d] for d in selected_weekdays] if selected_weekdays else []
                
                new_assignments_batch = []
                emps_to_process = r_emps if r_emps else [""]
                
                with st.spinner('Υπολογισμός και καταχώρηση βαρδιών...'):
                    while curr_date <= r_end_date:
                        if r_type == "Εβδομαδιαία":
                            dates_to_assign.append(curr_date)
                            curr_date += timedelta(days=7)
                        elif r_type == "Μηνιαία":
                            dates_to_assign.append(curr_date)
                            month = curr_date.month
                            year = curr_date.year
                            if month == 12:
                                month = 1
                                year += 1
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
                    
                    success_count = 0
                    conflict_count = 0
                    conflict_details = []
                    
                    for d in dates_to_assign:
                        for eid in emps_to_process:
                            if eid:
                                emp_name = get_employee_name(eid)
                                if is_on_leave(eid, d):
                                    conflict_count += 1
                                    conflict_details.append(f"{d.strftime('%d/%m/%Y')} - {emp_name} (Άδεια)")
                                elif has_time_conflict(eid, d, str_start, str_end):
                                    conflict_count += 1
                                    conflict_details.append(f"{d.strftime('%d/%m/%Y')} - {emp_name} (Επικάλυψη)")
                                else:
                                    new_assign = {
                                        'id': str(uuid.uuid4()),
                                        'recurring_id': pattern_id,
                                        'employeeId': eid,
                                        'projectId': final_r_proj_id,
                                        'date': d,
                                        'startTime': str_start,
                                        'endTime': str_end,
                                        'colorName': r_color,
                                        'colorHex': BASIC_COLORS[r_color],
                                        'notes': r_notes,
                                        'is_cancelled': False,
                                        'cancel_reason': ""
                                    }
                                    new_assignments_batch.append(new_assign)
                                    success_count += 1
                            else:
                                # Καταχώρηση βάρδιας χωρίς προσωπικό (χωρίς έλεγχο επικάλυψης)
                                new_assign = {
                                    'id': str(uuid.uuid4()),
                                    'recurring_id': pattern_id,
                                    'employeeId': "",
                                    'projectId': final_r_proj_id,
                                    'date': d,
                                    'startTime': str_start,
                                    'endTime': str_end,
                                    'colorName': r_color,
                                    'colorHex': BASIC_COLORS[r_color],
                                    'notes': r_notes,
                                    'is_cancelled': False,
                                    'cancel_reason': ""
                                }
                                new_assignments_batch.append(new_assign)
                                success_count += 1
                    
                    new_pattern = {
                        'id': pattern_id,
                        'projectId': final_r_proj_id,
                        'employeeIds': r_emps,
                        'colorName': r_color,
                        'notes': r_notes,
                        'type': r_type,
                        'weekdays': selected_weekdays,
                        'startDate': r_start_date,
                        'startTime': str_start,
                        'endTime': str_end
                    }
                    
                    # Update Memory & DB
                    st.session_state.recurring_patterns.append(new_pattern)
                    db_insert('recurring_patterns', new_pattern, track=False)
                    actions.append({'type': 'insert', 'table': 'recurring_patterns', 'records': [new_pattern]})
                    
                    if new_assignments_batch:
                        st.session_state.assignments.extend(new_assignments_batch)
                        # Χρησιμοποιούμε batch insert σε κομμάτια (chunks) για ασφάλεια
                        chunk_size = 500
                        for i in range(0, len(new_assignments_batch), chunk_size):
                            db_insert('assignments', new_assignments_batch[i:i+chunk_size], track=False)
                        actions.append({'type': 'insert', 'table': 'assignments', 'records': new_assignments_batch})
                        
                    add_transaction(actions)
                    
                    # Εκκαθάριση των πεδίων μετά από επιτυχημένη καταχώρηση
                    st.session_state.rec_reset_counter += 1
                    
                if success_count > 0:
                    st.success(f"Επιτυχής δημιουργία {success_count} βαρδιών! Η σελίδα ανανεώνεται...")
                    time.sleep(1.5)
                    st.rerun()
                if conflict_count > 0:
                    st.warning(f"Παραλείφθηκαν {conflict_count} αναθέσεις λόγω συγκρούσεων.")
                    with st.expander("Δείτε τις συγκρούσεις"):
                        for c in conflict_details:
                            st.write(f"⚠️ {c}")

    # --- ΚΑΡΤΕΛΑ 2: ΔΙΑΧΕΙΡΙΣΗ / ΕΠΕΞΕΡΓΑΣΙΑ ---
    with tab_edit:
        if not st.session_state.recurring_patterns:
            st.info("Δεν υπάρχ ενεργές επαναλαμβανόμενες εργασίες.")
        else:
            pattern_options = {}
            for p in st.session_state.recurring_patterns:
                p_info = get_project_info(p['projectId'])
                p_name = p_info['name'] if p_info else 'Άγνωστο Έργο'
                pattern_options[p['id']] = f"{p_name} | {p['type']} | Από: {p['startDate'].strftime('%d/%m/%Y')} ({p['startTime']}-{p['endTime']})"
            
            selected_pattern_id = st.selectbox("Επιλέξ Σειρά Εργασιών", options=list(pattern_options.keys()), format_func=lambda x: pattern_options[x])
            
            if selected_pattern_id:
                pat = next(p for p in st.session_state.recurring_patterns if p['id'] == selected_pattern_id)
                
                with st.form("edit_recurring_form", clear_on_submit=True):
                    st.warning("⚠️ Προσοχή: Η αποθήκευση αλλαγών θα επαναδημιουργήσει **ΟΛΕΣ** τις βάρδιες αυτής της σειράς. Τυχόν μεμονωμένες αλλαγές που κάνατε στο Ταμπλό θα χαθούν.")
                    
                    e_col1, e_col2 = st.columns(2)
                    with e_col1:
                        proj_ids = [p['id'] for p in st.session_state.projects]
                        default_proj_idx = proj_ids.index(pat['projectId']) if pat['projectId'] in proj_ids else 0
                        e_proj = st.selectbox("Αλλαγή Έργου", options=proj_ids, 
                                                index=default_proj_idx,
                                                format_func=lambda x: next((p['name'] for p in st.session_state.projects if p['id'] == x), "Άγνωστο Έργο"))
                                                
                        e_custom_proj_name = st.text_input("Ή πληκτρολογήστε Νέο Έργο (προαιρετικό)", key="edit_r_custom_proj")
                        
                        valid_emp_ids = [eid for eid in pat['employeeIds'] if eid]
                        edit_options_r = list(set(active_employee_ids + valid_emp_ids))
                        e_emps = st.multiselect("Αλλαγή Προσωπικού (Προαιρετικό)", options=edit_options_r,
                                                  default=valid_emp_ids,
                                                  format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), 'Άγνωστος'))
                        
                        e_color_col, e_notes_col = st.columns(2)
                        with e_color_col:
                            e_color_idx = list(BASIC_COLORS.keys()).index(pat['colorName']) if pat['colorName'] in BASIC_COLORS else 0
                            e_color = st.selectbox("Αλλαγή Χρώματος", options=list(BASIC_COLORS.keys()), index=e_color_idx)
                        with e_notes_col:
                            e_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", value=pat.get('notes', ''), key="edit_r_notes")

                    with e_col2:
                        e_start_date = st.date_input("Αλλαγή Ημερομηνίας Έναρξης", pat['startDate'])
                        e_start_time = st.time_input("Αλλαγή Ώρας Έναρξης", value=datetime.strptime(pat['startTime'], "%H:%M").time())
                        e_end_time = st.time_input("Αλλαγή Ώρας Λήξης", value=datetime.strptime(pat['endTime'], "%H:%M").time())

                    # Αν ήταν μέρες εβδομάδας, επιτρέπουμε αλλαγή ημερών
                    e_selected_weekdays = pat['weekdays']
                    e_type = pat['type']
                    if e_type == "Επιλεγμένες Μέρες Εβδομάδας":
                        st.caption("Αλλαγή Επιλεγμένων Ημερών:")
                        day_names = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
                        cols = st.columns(4)
                        new_selected = []
                        for i, d_name in enumerate(day_names):
                            if cols[i % 4].checkbox(d_name, value=(d_name in pat['weekdays']), key=f"edit_chk_{i}"):
                                new_selected.append(d_name)
                        e_selected_weekdays = new_selected
                        
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
                        
                        db_delete('assignments', 'recurring_id', selected_pattern_id, track=False)
                        db_delete('recurring_patterns', 'id', selected_pattern_id, track=False)
                        
                        add_transaction([
                            {'type': 'delete', 'table': 'assignments', 'records': old_assigns},
                            {'type': 'delete', 'table': 'recurring_patterns', 'records': [dict(pat)]}
                        ])
                        st.rerun()
                        
                    if save_rec:
                        str_start = e_start_time.strftime("%H:%M")
                        str_end = e_end_time.strftime("%H:%M")
                        
                        if str_start >= str_end:
                            st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                        elif e_type == "Επιλεγμένες Μέρες Εβδομάδας" and not e_selected_weekdays:
                            st.error("Επιλέξτε τουλάχιστον μία μέρα της εβδομάδας.")
                        elif not e_custom_proj_name.strip() and not e_proj:
                            st.error("Παρακαλώ επιλέξτε ή πληκτρολογήστε ένα Έργο.")
                        else:
                            actions = []
                            # Διαχείριση νέου έργου κατά την επεξεργασία
                            if e_custom_proj_name.strip():
                                final_e_proj_id = str(uuid.uuid4())
                                new_p = {'id': final_e_proj_id, 'name': e_custom_proj_name.strip(), 'color': BASIC_COLORS[e_color]}
                                st.session_state.projects.append(new_p)
                                db_insert('projects', new_p, track=False)
                                actions.append({'type': 'insert', 'table': 'projects', 'records': [new_p]})
                            else:
                                final_e_proj_id = e_proj
                                
                            # 1. Αφαιρούμε τις παλιές εγγραφές της σειράς
                            old_assigns = [a for a in st.session_state.assignments if a.get('recurring_id') == selected_pattern_id]
                            st.session_state.assignments = [a for a in st.session_state.assignments if a.get('recurring_id') != selected_pattern_id]
                            db_delete('assignments', 'recurring_id', selected_pattern_id, track=False)
                            actions.append({'type': 'delete', 'table': 'assignments', 'records': old_assigns})
                            
                            # 2. Παράγουμε τις νέες
                            r_end_date = e_start_date + timedelta(days=365 * 3)
                            dates_to_assign = []
                            curr_date = e_start_date
                            day_map = {"Δευτέρα": 0, "Τρίτη": 1, "Τετάρτη": 2, "Πέμπτη": 3, "Παρασκευή": 4, "Σάββατο": 5, "Κυριακή": 6}
                            selected_weekday_ints = [day_map[d] for d in e_selected_weekdays] if e_selected_weekdays else []
                            
                            new_assignments_batch = []
                            emps_to_process = e_emps if e_emps else [""]
                            
                            with st.spinner('Ενημέρωση και καταχώρηση βαρδιών...'):
                                while curr_date <= r_end_date:
                                    if e_type == "Εβδομαδιαία":
                                        dates_to_assign.append(curr_date)
                                        curr_date += timedelta(days=7)
                                    elif e_type == "Μηνιαία":
                                        dates_to_assign.append(curr_date)
                                        month = curr_date.month
                                        year = curr_date.year
                                        if month == 12:
                                            month = 1
                                            year += 1
                                        else:
                                            month += 1
                                        try:
                                            curr_date = curr_date.replace(year=year, month=month)
                                        except ValueError:
                                            last_day = calendar.monthrange(year, month)[1]
                                            curr_date = curr_date.replace(year=year, month=month, day=last_day)
                                    elif e_type == "Επιλεγμένες Μέρες Εβδομάδας":
                                        if curr_date.weekday() in selected_weekday_ints:
                                            dates_to_assign.append(curr_date)
                                        curr_date += timedelta(days=1)
                                
                                for d in dates_to_assign:
                                    for eid in emps_to_process:
                                        if eid:
                                            if not is_on_leave(eid, d) and not has_time_conflict(eid, d, str_start, str_end):
                                                new_assign = {
                                                    'id': str(uuid.uuid4()),
                                                    'recurring_id': selected_pattern_id,
                                                    'employeeId': eid,
                                                    'projectId': final_e_proj_id,
                                                    'date': d,
                                                    'startTime': str_start,
                                                    'endTime': str_end,
                                                    'colorName': e_color,
                                                    'colorHex': BASIC_COLORS[e_color],
                                                    'notes': e_notes,
                                                    'is_cancelled': False,
                                                    'cancel_reason': ""
                                                }
                                                new_assignments_batch.append(new_assign)
                                        else:
                                            new_assign = {
                                                'id': str(uuid.uuid4()),
                                                'recurring_id': selected_pattern_id,
                                                'employeeId': "",
                                                'projectId': final_e_proj_id,
                                                'date': d,
                                                'startTime': str_start,
                                                'endTime': str_end,
                                                'colorName': e_color,
                                                'colorHex': BASIC_COLORS[e_color],
                                                'notes': e_notes,
                                                'is_cancelled': False,
                                                'cancel_reason': ""
                                            }
                                            new_assignments_batch.append(new_assign)
                                
                                # 3. Ενημερώνουμε τα δεδομένα του Pattern
                                old_pat = dict(pat)
                                pat['projectId'] = final_e_proj_id
                                pat['employeeIds'] = e_emps
                                pat['colorName'] = e_color
                                pat['notes'] = e_notes
                                pat['weekdays'] = e_selected_weekdays
                                pat['startDate'] = e_start_date
                                pat['startTime'] = str_start
                                pat['endTime'] = str_end
                                
                                db_update('recurring_patterns', selected_pattern_id, pat, old_data=old_pat, track=False)
                                actions.append({'type': 'update', 'table': 'recurring_patterns', 'old_records': [old_pat], 'new_records': [dict(pat)]})
                                
                                if new_assignments_batch:
                                    st.session_state.assignments.extend(new_assignments_batch)
                                    chunk_size = 500
                                    for i in range(0, len(new_assignments_batch), chunk_size):
                                        db_insert('assignments', new_assignments_batch[i:i+chunk_size], track=False)
                                    actions.append({'type': 'insert', 'table': 'assignments', 'records': new_assignments_batch})
                                
                                add_transaction(actions)
                                
                            st.success("Η σειρά εργασιών ενημερώθηκε επιτυχώς! Η σελίδα ανανεώνεται...")
                            time.sleep(1.5)
                            st.rerun()

# --- VIEW: PROJECTS ---
elif menu == "Διαχείριση Έργων":
    st.title("🏗️ Έργα")
    with st.expander("Νέο Έργο"):
        with st.form("new_project_form", clear_on_submit=True):
            p_name = st.text_input("Όνομα Έργου")
            p_color = st.color_picker("Χρώμα (Προεπιλογή)", "#4a86e8")
            if st.form_submit_button("Δημιουργία"):
                new_p = {'id': str(uuid.uuid4()), 'name': p_name, 'color': p_color}
                st.session_state.projects.append(new_p)
                db_insert('projects', new_p)
                st.rerun()
            
    for p in st.session_state.projects:
        col1, col2 = st.columns([4, 1])
        col1.write(f"**{p['name']}**")
        if col2.button("Διαγραφή", key=p['id']):
            st.session_state.projects = [proj for proj in st.session_state.projects if proj['id'] != p['id']]
            db_delete('projects', 'id', p['id'], deleted_records=[p])
            st.rerun()

# --- VIEW: EMPLOYEES ---
elif menu == "Ομάδα Προσωπικού":
    st.title("👥 Προσωπικό")
    
    tab_list, tab_add, tab_edit, tab_import = st.tabs(["📋 Λίστα Υπαλλήλων", "➕ Προσθήκη Υπαλλήλου", "✏️ Επεξεργασία", "📥 Εισαγωγή από Αρχείο"])
    
    with tab_add:
        if "emp_reset_counter" not in st.session_state:
            st.session_state.emp_reset_counter = 0
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
                                          format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), "Άγνωστος"))
            
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
                
                # Κανονικοποίηση ονομάτων στηλών (μικρά γράμματα, χωρίς κενά)
                cols = [str(c).lower().strip().replace(".", "").replace("_", " ") for c in df_import.columns]
                
                # Αναζήτηση στήλης Ονόματος
                name_col = None
                for orig_col, c in zip(df_import.columns, cols):
                    if 'ονομα' in c or 'name' in c or 'υπαλλ' in c or 'υπάλλ' in c:
                        name_col = orig_col
                        break
                        
                if not name_col:
                    st.error("❌ Δεν βρέθηκε στήλη για το Ονοματεπώνυμο. Βεβαιωθείτε ότι γράφεται 'Ονοματεπώνυμο' στην πρώτη γραμμή του Excel.")
                else:
                    # Αναζήτηση άλλων στηλών
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
                                e_pos = "ΕΡΓΑΤΗΣ" # Default αν δεν αναγνωριστεί η θέση
                                
                            e_id_num = str(row[id_col]).strip() if id_col and pd.notna(row[id_col]) else ""
                            if e_id_num.lower() == 'nan': e_id_num = ""
                            if e_id_num.endswith('.0'): e_id_num = e_id_num[:-2] # Διορθώνει νούμερα που διαβάζονται με δεκαδικά πχ 12345.0
                            
                            e_phone = str(row[phone_col]).strip() if phone_col and pd.notna(row[phone_col]) else ""
                            if e_phone.lower() == 'nan': e_phone = ""
                            if e_phone.endswith('.0'): e_phone = e_phone[:-2]
                            
                            e_status = "Ενεργός"
                            if status_col and pd.notna(row[status_col]):
                                val = str(row[status_col]).strip().lower()
                                if any(kw in val for kw in ["ανενεργ", "inactive", "false", "0", "οχι", "όχι", "no", "αποχωρ", "παραιτ"]):
                                    e_status = "Ανενεργός"
                            
                            # Έλεγχος αν υπάρχει ήδη ο υπάλληλος
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
                            st.warning(f"Παραλείφθηκαν {error_count} υπάλληλοι επειδή υπήρχαν ήδη στη λίστα (ίδιο όνομα ή ταυτότητα).")
                            
                        if success_count > 0:
                            st.success(f"Εισήχθησαν επιτυχώς {success_count} υπάλληλοι! Η σελίδα ανανεώνεται...")
                            time.sleep(1.5) # Αναμονή για να διαβάσει ο χρήστης το μήνυμα
                            st.rerun() # Ανανέωση ώστε να φανούν αμέσως στην καρτέλα Επεξεργασίας!
                            
            except Exception as e:
                st.error(f"Υπήρξε πρόβλημα με την ανάγνωση του αρχείου: {e}")

    with tab_list:
        st.write("### Συνολική Λίστα Υπαλλήλων")
        
        with st.expander("🗑️ Μαζική Διαγραφή"):
            emps_to_delete = st.multiselect(
                "Επιλέξτε τους υπαλλήλους που θέλετε να διαγράψετε:",
                options=[e['id'] for e in st.session_state.employees],
                format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), "Άγνωστος"),
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
        
        # Επικεφαλίδες Στηλών
        hc1, hc2, hc3, hc4, hc5, hc6 = st.columns([2, 2, 2, 2, 1.5, 1])
        hc1.write("**Ονοματεπώνυμο**")
        hc2.write("**Θέση**")
        hc3.write("**Αρ. Ταυτότητας**")
        hc4.write("**Κινητό**")
        hc5.write("**Κατάσταση**")
        hc6.write("")
        st.divider()
        
        # Δεδομένα
        for e in st.session_state.employees:
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

# --- VIEW: LEAVES ---
elif menu == "Άδειες":
    st.title("🏖️ Διαχείριση Αδειών")
    with st.form("new_leave", clear_on_submit=True):
        l_emp = st.selectbox("Υπάλληλος (Μόνο Ενεργοί)", options=active_employee_ids, 
                             format_func=lambda x: next((e['name'] for e in st.session_state.employees if e['id'] == x), "Άγνωστος"))
        l_start = st.date_input("Από")
        l_end = st.date_input("Έως")
        
        if st.form_submit_button("Καταχώρηση Άδειας"):
            if not l_emp:
                st.error("Παρακαλώ επιλέξτε υπάλληλο.")
            elif l_start > l_end:
                st.error("Η ημερομηνία 'Από' πρέπει να είναι πριν ή ίση με την 'Έως'.")
            else:
                # Έλεγχος αν ο υπάλληλος εργάζεται ήδη κάποια από τις μέρες της άδειας
                conflict_errors = []
                curr_date = l_start
                while curr_date <= l_end:
                    for a in st.session_state.assignments:
                        if a['employeeId'] == l_emp and a['date'] == curr_date:
                            proj = get_project_info(a['projectId'])
                            proj_name = proj['name'] if proj else "Άγνωστο Έργο"
                            emp_name = get_employee_name(l_emp)
                            conflict_errors.append(f"Ο/Η {emp_name} δεν μπορεί να πάρει άδεια στις {curr_date.strftime('%d/%m/%Y')} διότι εργάζεται στο έργο: {proj_name}.")
                            break # Αρκεί μία επικάλυψη για να μπλοκάρει τη μέρα
                    curr_date += timedelta(days=1)
                
                if conflict_errors:
                    for err in conflict_errors:
                        st.error(err)
                else:
                    new_l = {'id': str(uuid.uuid4()), 'employeeId': l_emp, 'startDate': l_start, 'endDate': l_end}
                    st.session_state.leaves.append(new_l)
                    db_insert('leaves', new_l)
                    st.success("Η άδεια καταχωρήθηκε με επιτυχία!")
                    st.rerun()
            
    if st.session_state.leaves:
        st.write("### Λίστα Αδειών")
        
        # Επικεφαλίδες Στηλών
        hc1, hc2, hc3, hc4 = st.columns([3, 2, 2, 1])
        hc1.write("**Υπάλληλος**")
        hc2.write("**Από**")
        hc3.write("**Έως**")
        hc4.write("")
        st.divider()
        
        # Δεδομένα
        for l in st.session_state.leaves:
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
            col1.write(get_employee_name(l['employeeId']))
            col2.write(l['startDate'].strftime('%d/%m/%Y'))
            col3.write(l['endDate'].strftime('%d/%m/%Y'))
            if col4.button("❌", key=f"del_leave_{l['id']}"):
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
    
    # Υπολογισμός ημερών άδειας
    leave_days = {emp['id']: 0 for emp in st.session_state.employees}
    
    year_start = date(selected_year, 1, 1)
    year_end = date(selected_year, 12, 31)
    
    for l in st.session_state.leaves:
        start_d = l['startDate']
        end_d = l['endDate']
        
        # Υπολογισμός των ημερών της άδειας που πέφτουν ΜΕΣΑ στο επιλεγμένο έτος
        actual_start = max(start_d, year_start)
        actual_end = min(end_d, year_end)
        
        if actual_start <= actual_end:
            days = (actual_end - actual_start).days + 1
            if l['employeeId'] in leave_days:
                leave_days[l['employeeId']] += days
                
    # Προετοιμασία δεδομένων για τον πίνακα
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
    
    # Εμφάνιση του πίνακα
    st.dataframe(
        df_leaves_summary, 
        use_container_width=True,
        hide_index=True
    )

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
        # Παραγωγή λίστας ετών (π.χ. από το 2020 έως το 2035)
        years = list(range(2020, 2036))
        selected_year = st.selectbox("Επιλογή Έτους", years, index=years.index(current_year))
        
    st.divider()
    
    # Υπολογισμός ωρών
    employee_hours = {emp['id']: 0.0 for emp in st.session_state.employees}
    
    for a in st.session_state.assignments:
        d = a['date']
        if d.month == selected_month and d.year == selected_year:
            # Υπολογισμός διαφοράς ωρών
            start = datetime.strptime(a['startTime'], "%H:%M")
            end = datetime.strptime(a['endTime'], "%H:%M")
            delta = end - start
            hours = delta.total_seconds() / 3600.0
            
            if a['employeeId'] in employee_hours:
                employee_hours[a['employeeId']] += hours
                
    # Προετοιμασία δεδομένων για τον πίνακα
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
    
    # Εμφάνιση του πίνακα
    st.dataframe(
        df_hours.style.format({"Συνολικές Ώρες": "{:.2f}"}), 
        use_container_width=True,
        hide_index=True
    )

# --- VIEW: ΑΞΙΟΛΟΓΗΣΗ ΠΡΟΣΩΠΙΚΟΥ ---
elif menu == "Αξιολόγηση Προσωπικού":
    # Προσθήκη CSS μόνο για αυτήν τη σελίδα ώστε το κουμπί να μένει κολλημένο κάτω
    st.markdown("""
        <style>
        /* Απόλυτα αιωρούμενο (floating) κουμπί σε όλη την οθόνη */
        div[data-testid="stFormSubmitButton"] {
            position: fixed !important;
            bottom: 40px !important;
            right: 40px !important;
            z-index: 99999 !important;
        }
        div[data-testid="stFormSubmitButton"] button {
            box-shadow: 0px 8px 24px rgba(0, 0, 0, 0.4) !important;
            border: 3px solid #16a34a !important;
            border-radius: 50px !important;
            font-weight: bold !important;
            padding: 15px 30px !important;
            background-color: white !important;
            color: #16a34a !important;
            transition: all 0.2s ease-in-out !important;
        }
        div[data-testid="stFormSubmitButton"] button:hover {
            background-color: #16a34a !important;
            color: white !important;
            transform: scale(1.05) !important;
        }
        div[data-testid="stForm"] {
            padding-bottom: 120px !important;
        }
        </style>
    """, unsafe_allow_html=True)

    st.title("⭐ Αξιολόγηση Προσωπικού")

    months = ["Ιανουάριος", "Φεβρουάριος", "Μάρτιος", "Απρίλιος", "Μάιος", "Ιούνιος", 
              "Ιούλιος", "Αύγουστος", "Σεπτέμβριος", "Οκτώβριος", "Νοέμβριος", "Δεκέμβριος"]
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

    # --- Υπολογισμός "Υπάλληλος του Μήνα" ---
    month_evals = [e for e in st.session_state.evaluations if e['month'] == eval_month and e['year'] == eval_year]

    if month_evals:
        # Υπολογισμός μέσου όρου για κάθε αξιολόγηση
        for ev in month_evals:
            ev['avg'] = (ev.get('cooperation', 0) + ev.get('willingness', 0) + ev.get('behavior', 0)) / 3.0

        max_avg = max([ev['avg'] for ev in month_evals])

        # Εύρεση όλων των υπαλλήλων με τη μέγιστη βαθμολογία (για ισοβαθμίες)
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
    with col_title:
        st.write("### 📝 Φόρμα Βαθμολόγησης")
    with col_reset:
        if st.button("🔄 Επαναφορά Βαθμολογιών", use_container_width=True):
            evals_to_delete = [e['id'] for e in month_evals]
            if evals_to_delete:
                st.session_state.evaluations = [e for e in st.session_state.evaluations if e['id'] not in evals_to_delete]
                db_delete_in('evaluations', 'id', evals_to_delete, deleted_records=month_evals)
            
            # Καθαρισμός του session state για να επιστρέψουν τα κουτάκια στο 3
            for emp in active_employee_ids:
                if f"coop_{emp}" in st.session_state:
                    del st.session_state[f"coop_{emp}"]
                if f"will_{emp}" in st.session_state:
                    del st.session_state[f"will_{emp}"]
                if f"behav_{emp}" in st.session_state:
                    del st.session_state[f"behav_{emp}"]
                    
            st.rerun()

    with st.form("evaluations_form", clear_on_submit=True):
        # Επικεφαλίδες
        hc1, hc2, hc3, hc4, hc5 = st.columns([2, 1.5, 1.5, 1.5, 1])
        hc1.write("**Ονοματεπώνυμο**")
        hc2.write("**Συνεργασία (1-5)**")
        hc3.write("**Προθυμία (1-5)**")
        hc4.write("**Συμπεριφορά (1-5)**")
        hc5.write("**Μ.Ό.**")
        st.markdown("---")

        eval_inputs = {}

        # Εμφάνιση μόνο των Ενεργών υπαλλήλων
        for emp in active_employee_ids:
            emp_info = next(e for e in st.session_state.employees if e['id'] == emp)
            
            # Εύρεση αν υπάρχει ήδη αξιολόγηση για αυτόν τον μήνα
            existing_eval = next((e for e in month_evals if e['employeeId'] == emp), None)

            default_coop = existing_eval['cooperation'] if existing_eval else 3
            default_will = existing_eval['willingness'] if existing_eval else 3
            default_behav = existing_eval['behavior'] if existing_eval else 3

            c1, c2, c3, c4, c5 = st.columns([2, 1.5, 1.5, 1.5, 1])
            c1.write(f"\n**{emp_info['name']}**")

            eval_inputs[emp] = {
                'coop': c2.selectbox("Συνεργασία", [1, 2, 3, 4, 5], index=default_coop - 1, key=f"coop_{emp}", label_visibility="collapsed"),
                'will': c3.selectbox("Προθυμία", [1, 2, 3, 4, 5], index=default_will - 1, key=f"will_{emp}", label_visibility="collapsed"),
                'behav': c4.selectbox("Συμπεριφορά", [1, 2, 3, 4, 5], index=default_behav - 1, key=f"behav_{emp}", label_visibility="collapsed"),
                'existing_id': existing_eval['id'] if existing_eval else None
            }

            # Υπολογισμός τρέχοντος εμφανιζόμενου Μ.Ο.
            current_avg = (default_coop + default_will + default_behav) / 3.0
            c5.write(f"\n**{current_avg:.2f}**")

        st.markdown("---")
        
        # Το κουμπί πιάνει όλο το πλάτος και αιωρείται!
        submit_eval = st.form_submit_button("💾 Αποθήκευση Αξιολογήσεων", type="primary", use_container_width=True)

        if submit_eval:
            updates_made = False
            actions = []
            
            with st.spinner("Αποθήκευση αξιολογήσεων..."):
                for emp_id, data in eval_inputs.items():
                    new_coop = data['coop']
                    new_will = data['will']
                    new_behav = data['behav']
                    existing_id = data['existing_id']

                    if existing_id:
                        # Υπάρχει ήδη, ελέγχουμε αν άλλαξε κάτι για να το κάνουμε update
                        ev_to_update = next(e for e in st.session_state.evaluations if e['id'] == existing_id)
                        if ev_to_update['cooperation'] != new_coop or ev_to_update['willingness'] != new_will or ev_to_update['behavior'] != new_behav:
                            old_ev = dict(ev_to_update)
                            
                            ev_to_update['cooperation'] = new_coop
                            ev_to_update['willingness'] = new_will
                            ev_to_update['behavior'] = new_behav
                            
                            # Στέλνουμε στη βάση μόνο τα πεδία που υπάρχουν στον πίνακα (αφαιρούμε το 'avg')
                            payload = {k: v for k, v in ev_to_update.items() if k != 'avg'}
                            old_payload = {k: v for k, v in old_ev.items() if k != 'avg'}
                            
                            db_update('evaluations', existing_id, payload, track=False)
                            actions.append({'type': 'update', 'table': 'evaluations', 'old_records': [old_payload], 'new_records': [payload]})
                            updates_made = True
                    else:
                        # Νέα εγγραφή για αυτόν τον υπάλληλο και τον μήνα
                        new_eval_id = str(uuid.uuid4())
                        new_eval = {
                            'id': new_eval_id,
                            'employeeId': emp_id,
                            'month': eval_month,
                            'year': eval_year,
                            'cooperation': new_coop,
                            'willingness': new_will,
                            'behavior': new_behav
                        }
                        st.session_state.evaluations.append(new_eval)
                        db_insert('evaluations', new_eval, track=False)
                        actions.append({'type': 'insert', 'table': 'evaluations', 'records': [new_eval]})
                        updates_made = True

            if actions:
                add_transaction(actions)

            if updates_made:
                st.success("Οι αξιολογήσεις αποθηκεύτηκαν επιτυχώς!")
                st.rerun()
            else:
                st.info("Δεν υπήρξαν αλλαγές για αποθήκευση.")
