import streamlit as st
import pandas as pd
import database as db

# ==========================================
# 1. ΕΛΕΓΧΟΣ ΠΡΟΣΒΑΣΗΣ & ΡΥΘΜΙΣΗ ΣΕΛΙΔΑΣ
# ==========================================
st.set_page_config(page_title="Διαχείριση - Staff Manager", page_icon="🗂️", layout="wide")

# Αν ο χρήστης δεν είναι συνδεδεμένος, σταματάμε την εκτέλεση
if not st.session_state.get('current_user'):
    st.warning("⚠️ Παρακαλώ συνδεθείτε από την αρχική σελίδα για να δείτε αυτή την ενότητα.")
    st.stop()

st.title("🗂️ Διαχείριση Συστήματος (Πλήρης Έλεγχος)")
st.write("Σύνδεση με την υπάρχουσα βάση δεδομένων: Ενεργή")
st.write("---")

# Δημιουργούμε τις καρτέλες για όλα τα δεδομένα της βάσης σου
tab_employees, tab_projects, tab_leaves, tab_patterns, tab_history = st.tabs([
    "👥 Προσωπικό", 
    "🏗️ Έργα", 
    "📅 Άδειες", 
    "🔄 Πρότυπα", 
    "📜 Ιστορικό"
])

# ==========================================
# 2. ΚΑΡΤΕΛΑ: ΠΡΟΣΩΠΙΚΟ (Στήλη 'position')
# ==========================================
@st.fragment
def render_employees_tab():
    st.subheader("👥 Διαχείριση Εργαζομένων")
    employees = db.fetch_paginated('employees')
    
    with st.expander("➕ Προσθήκη Νέου Εργαζομένου"):
        with st.form("new_employee_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Ονοματεπώνυμο *")
            with col2:
                pos_input = st.text_input("Ειδικότητα / Πόστο")
            submit_emp = st.form_submit_button("Αποθήκευση")
            
            if submit_emp and name:
                try:
                    supabase = db.init_supabase()
                    new_emp = {'name': name, 'position': pos_input}
                    res = supabase.table('employees').insert(new_emp).execute()
                    if res.data:
                        db.log_activity("ΠΡΟΣΘΗΚΗ", "employees", f"Νέος εργαζόμενος: {name}", st.session_state.current_user)
                        st.success("Ο εργαζόμενος προστέθηκε!")
                        db.fetch_paginated.clear() 
                        st.rerun()
                except Exception as e: st.error(f"Σφάλμα: {e}")

    if employees:
        df = pd.DataFrame(employees)
        cols = [c for c in ['name', 'position', 'created_at'] if c in df.columns]
        st.dataframe(df[cols].rename(columns={'name': 'Όνομα', 'position': 'Ειδικότητα'}), use_container_width=True, hide_index=True)

# ==========================================
# 3. ΚΑΡΤΕΛΑ: ΕΡΓΑ
# ==========================================
@st.fragment
def render_projects_tab():
    st.subheader("🏗️ Διαχείριση Έργων & Τοποθεσιών")
    projects = db.fetch_paginated('projects')
    
    with st.expander("➕ Προσθήκη Νέου Έργου"):
        with st.form("new_project_form", clear_on_submit=True):
            p_name = st.text_input("Όνομα Έργου *")
            location = st.text_input("Τοποθεσία")
            submit_proj = st.form_submit_button("Αποθήκευση")
            
            if submit_proj and p_name:
                try:
                    supabase = db.init_supabase()
                    res = supabase.table('projects').insert({'name': p_name, 'location': location}).execute()
                    if res.data:
                        db.log_activity("ΠΡΟΣΘΗΚΗ", "projects", f"Νέο έργο: {p_name}", st.session_state.current_user)
                        st.success("Το έργο αποθηκεύτηκε!")
                        db.fetch_paginated.clear()
                        st.rerun()
                except Exception as e: st.error(f"Σφάλμα: {e}")

    if projects:
        df = pd.DataFrame(projects)
        cols = [c for c in ['name', 'location'] if c in df.columns]
        st.dataframe(df[cols].rename(columns={'name': 'Έργο', 'location': 'Τοποθεσία'}), use_container_width=True, hide_index=True)

# ==========================================
# 4. ΚΑΡΤΕΛΑ: ΑΔΕΙΕΣ (Leaves)
# ==========================================
@st.fragment
def render_leaves_tab():
    st.subheader("📅 Προβολή Αδειών")
    leaves = db.fetch_paginated('leaves')
    employees = db.fetch_paginated('employees')
    
    if leaves and employees:
        df_l = pd.DataFrame(leaves)
        df_e = pd.DataFrame(employees)
        
        # Ένωση για να βλέπουμε ονόματα
        df = df_l.merge(df_e[['id', 'name']], left_on='employee_id', right_on='id', how='left')
        
        cols = [c for c in ['name', 'leave_type', 'start_date', 'end_date'] if c in df.columns]
        st.dataframe(df[cols].rename(columns={'name': 'Εργαζόμενος', 'leave_type': 'Τύπος'}), use_container_width=True, hide_index=True)
    else:
        st.info("Δεν βρέθηκαν καταχωρημένες άδειες.")

# ==========================================
# 5. ΚΑΡΤΕΛΑ: ΠΡΟΤΥΠΑ (Recurring Patterns)
# ==========================================
@st.fragment
def render_patterns_tab():
    st.subheader("🔄 Επαναλαμβανόμενες Εργασίες & Πρότυπα")
    patterns = db.fetch_paginated('recurring_patterns')
    
    if patterns:
        df = pd.DataFrame(patterns)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Δεν υπάρχουν αποθηκευμένα πρότυπα εργασιών.")

# ==========================================
# 6. ΚΑΡΤΕΛΑ: ΙΣΤΟΡΙΚΟ (Activity Logs)
# ==========================================
@st.fragment
def render_history_tab():
    st.subheader("📜 Ιστορικό Ενεργειών Βάσης")
    logs = db.fetch_paginated('activity_logs')
    
    if logs:
        df = pd.DataFrame(logs)
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp']).dt.strftime('%d/%m/%Y %H:%M')
        
        cols = [c for c in ['timestamp', 'username', 'action_type', 'table_name', 'details'] if c in df.columns]
        st.dataframe(df[cols].iloc[::-1], use_container_width=True, hide_index=True)

# --- ΕΚΤΕΛΕΣΗ ΤΩΝ ΣΤΟΙΧΕΙΩΝ ---
with tab_employees: render_employees_tab()
with tab_projects: render_projects_tab()
with tab_leaves: render_leaves_tab()
with tab_patterns: render_patterns_tab()
with tab_history: render_history_tab()
