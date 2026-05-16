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

st.title("🗂️ Διαχείριση Προσωπικού & Έργων")
st.write("Σύνδεση με την υπάρχουσα βάση δεδομένων ενεργή.")
st.write("---")

# Δημιουργούμε τρεις καρτέλες (Tabs) για να συμπεριλάβουμε και το Ιστορικό της βάσης σου
tab_employees, tab_projects, tab_history = st.tabs(["👥 Προσωπικό", "🏗️ Έργα", "📜 Ιστορικό Βάσης"])

# ==========================================
# 2. ΚΑΡΤΕΛΑ: ΠΡΟΣΩΠΙΚΟ (Συγχρονισμένο με στήλη 'position')
# ==========================================
@st.fragment
def render_employees_tab():
    st.subheader("Λίστα Εργαζομένων")
    
    # Φόρτωση εργαζομένων από την υπάρχουσα βάση
    employees = db.fetch_paginated('employees')
    
    # Φόρμα Προσθήκης
    with st.expander("➕ Προσθήκη Νέου Εργαζομένου", expanded=False):
        with st.form("new_employee_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Ονοματεπώνυμο *")
            with col2:
                # Αντιστοίχιση με τη στήλη 'position' της βάσης σου
                pos_input = st.text_input("Ειδικότητα / Πόστο")
            
            submit_emp = st.form_submit_button("Αποθήκευση Εργαζομένου")
            
            if submit_emp:
                if not name:
                    st.error("Το όνομα είναι υποχρεωτικό!")
                else:
                    try:
                        supabase = db.init_supabase()
                        # Χρήση 'position' για να "κουμπώσει" στην παλιά βάση
                        new_emp = {'name': name, 'position': pos_input}
                        res = supabase.table('employees').insert(new_emp).execute()
                        
                        if res.data:
                            inserted_id = res.data[0]['id']
                            # Καταγραφή στο υπάρχον activity_logs (username, action_type)
                            db.log_activity("ΠΡΟΣΘΗΚΗ", "employees", f"Νέος εργαζόμενος: {name}", st.session_state.current_user)
                            db.add_to_undo_stack("INSERT", "employees", inserted_id, new_emp)
                            
                            st.success(f"Ο/Η {name} προστέθηκε επιτυχώς!")
                            db.fetch_paginated.clear() 
                            st.rerun()
                    except Exception as e:
                        st.error(f"Σφάλμα κατά την αποθήκευση: {e}")

    # Προβολή του πίνακα
    if employees:
        df_emps = pd.DataFrame(employees)
        # Επιλογή στηλών που υπάρχουν ήδη στη βάση σου
        cols_to_show = [c for c in ['name', 'position', 'created_at'] if c in df_emps.columns]
            
        display_df = df_emps[cols_to_show].rename(columns={
            'name': 'Ονοματεπώνυμο', 
            'position': 'Ειδικότητα',
            'created_at': 'Ημ. Προσθήκης'
        })
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("Δεν βρέθηκαν εργαζόμενοι στην υπάρχουσα βάση.")

# ==========================================
# 3. ΚΑΡΤΕΛΑ: ΕΡΓΑ
# ==========================================
@st.fragment
def render_projects_tab():
    st.subheader("Λίστα Έργων / Τοποθεσιών")
    
    projects = db.fetch_paginated('projects')
    
    with st.expander("➕ Προσθήκη Νέου Έργου", expanded=False):
        with st.form("new_project_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                p_name = st.text_input("Όνομα Έργου *")
            with col2:
                location = st.text_input("Τοποθεσία / Περιοχή")
            
            submit_proj = st.form_submit_button("Αποθήκευση Έργου")
            
            if submit_proj:
                if not p_name:
                    st.error("Το όνομα του έργου είναι υποχρεωτικό!")
                else:
                    try:
                        supabase = db.init_supabase()
                        new_proj = {'name': p_name, 'location': location}
                        res = supabase.table('projects').insert(new_proj).execute()
                        
                        if res.data:
                            inserted_id = res.data[0]['id']
                            db.log_activity("ΠΡΟΣΘΗΚΗ", "projects", f"Νέο έργο: {p_name}", st.session_state.current_user)
                            db.add_to_undo_stack("INSERT", "projects", inserted_id, new_proj)
                            
                            st.success(f"Το έργο '{p_name}' προστέθηκε επιτυχώς!")
                            db.fetch_paginated.clear() 
                            st.rerun()
                    except Exception as e:
                        st.error(f"Σφάλμα κατά την αποθήκευση: {e}")

    if projects:
        df_projs = pd.DataFrame(projects)
        cols_to_show = [c for c in ['name', 'location', 'created_at'] if c in df_projs.columns]

        display_df = df_projs[cols_to_show].rename(columns={
            'name': 'Όνομα Έργου', 
            'location': 'Τοποθεσία',
            'created_at': 'Ημ. Προσθήκης'
        })
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("Δεν βρέθηκαν ενεργά έργα στην υπάρχουσα βάση.")

# ==========================================
# 4. ΚΑΡΤΕΛΑ: ΙΣΤΟΡΙΚΟ (Ανάγνωση από activity_logs)
# ==========================================
@st.fragment
def render_history_tab():
    st.subheader("Ιστορικό Ενεργειών Συστήματος")
    st.write("Προβολή των τελευταίων 100 κινήσεων στη βάση δεδομένων.")
    
    # Φόρτωση logs από τον πίνακα που μου έδειξες στην εικόνα
    logs = db.fetch_paginated('activity_logs')
    
    if logs:
        df_logs = pd.DataFrame(logs)
        # Μετατροπή ημερομηνίας για καλύτερη ανάγνωση
        if 'timestamp' in df_logs.columns:
            df_logs['timestamp'] = pd.to_datetime(df_logs['timestamp']).dt.strftime('%d/%m/%Y %H:%M')
        
        # Αντιστοίχιση στηλών με τα ονόματα της βάσης σου (username, action_type)
        cols_to_show = [c for c in ['timestamp', 'username', 'action_type', 'table_name', 'details'] if c in df_logs.columns]
        
        display_df = df_logs[cols_to_show].rename(columns={
            'timestamp': 'Ημερομηνία/Ώρα',
            'username': 'Χρήστης',
            'action_type': 'Ενέργεια',
            'table_name': 'Πίνακας',
            'details': 'Λεπτομέρειες'
        })
        
        # Εμφάνιση με τα πιο πρόσφατα πάνω-πάνω
        st.dataframe(display_df.iloc[::-1], use_container_width=True, hide_index=True)
    else:
        st.info("Το ιστορικό είναι κενό.")

# --- ΕΚΤΕΛΕΣΗ ΤΩΝ ΣΤΟΙΧΕΙΩΝ ΣΤΑ TABS ---
with tab_employees:
    render_employees_tab()

with tab_projects:
    render_projects_tab()

with tab_history:
    render_history_tab()
