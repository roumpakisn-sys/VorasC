import streamlit as st
import pandas as pd
import database as db

# ==========================================
# 1. ΕΛΕΓΧΟΣ ΠΡΟΣΒΑΣΗΣ
# ==========================================
if not st.session_state.get('current_user'):
    st.warning("⚠️ Παρακαλώ συνδεθείτε από την αρχική σελίδα για να δείτε αυτή την ενότητα.")
    st.stop()

st.title("🗂️ Διαχείριση Προσωπικού & Έργων")
st.write("Εδώ μπορείτε να διαχειριστείτε τους εργαζομένους και τα ενεργά έργα/τοποθεσίες σας.")
st.write("---")

# Δημιουργούμε δύο καρτέλες (Tabs) για να είναι τακτοποιημένη η οθόνη
tab_employees, tab_projects = st.tabs(["👥 Προσωπικό", "🏗️ Έργα"])

# ==========================================
# 2. ΚΑΡΤΕΛΑ: ΠΡΟΣΩΠΙΚΟ (ΣΕ FRAGMENT ΓΙΑ ΤΑΧΥΤΗΤΑ)
# ==========================================
@st.fragment
def render_employees_tab():
    st.subheader("Λίστα Εργαζομένων")
    
    # Φόρτωση εργαζομένων από τη βάση
    employees = db.fetch_paginated('employees')
    
    # Φόρμα Προσθήκης
    with st.expander("➕ Προσθήκη Νέου Εργαζομένου"):
        with st.form("new_employee_form"):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Ονοματεπώνυμο *")
            with col2:
                specialty = st.text_input("Ειδικότητα / Πόστο")
            
            submit_emp = st.form_submit_button("Αποθήκευση Εργαζομένου")
            
            if submit_emp:
                if not name:
                    st.error("Το όνομα είναι υποχρεωτικό!")
                else:
                    try:
                        supabase = db.init_supabase()
                        new_emp = {'name': name, 'specialty': specialty}
                        res = supabase.table('employees').insert(new_emp).execute()
                        
                        if res.data:
                            inserted_id = res.data[0]['id']
                            db.log_activity("INSERT", "employees", f"Νέος εργαζόμενος: {name}", st.session_state.current_user)
                            db.add_to_undo_stack("INSERT", "employees", inserted_id, new_emp)
                            
                            st.success("Προστέθηκε επιτυχώς!")
                            db.fetch_paginated.clear() # Καθαρισμός cache
                            st.rerun()
                    except Exception as e:
                        st.error(f"Σφάλμα: {e}")

    # Προβολή του πίνακα
    if employees:
        df_emps = pd.DataFrame(employees)
        # Κρύβουμε τεχνικά πεδία αν υπάρχουν και κάνουμε μετονομασία για την οθόνη
        display_df = df_emps.rename(columns={
            'name': 'Ονοματεπώνυμο', 
            'specialty': 'Ειδικότητα',
            'created_at': 'Ημ. Προσθήκης'
        })
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("Δεν βρέθηκαν εργαζόμενοι στη βάση.")

# ==========================================
# 3. ΚΑΡΤΕΛΑ: ΕΡΓΑ (ΣΕ FRAGMENT ΓΙΑ ΤΑΧΥΤΗΤΑ)
# ==========================================
@st.fragment
def render_projects_tab():
    st.subheader("Λίστα Έργων")
    
    # Φόρτωση έργων από τη βάση
    projects = db.fetch_paginated('projects')
    
    # Φόρμα Προσθήκης
    with st.expander("➕ Προσθήκη Νέου Έργου"):
        with st.form("new_project_form"):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Όνομα Έργου *")
            with col2:
                location = st.text_input("Τοποθεσία / Περιοχή")
            
            submit_proj = st.form_submit_button("Αποθήκευση Έργου")
            
            if submit_proj:
                if not name:
                    st.error("Το όνομα του έργου είναι υποχρεωτικό!")
                else:
                    try:
                        supabase = db.init_supabase()
                        new_proj = {'name': name, 'location': location}
                        res = supabase.table('projects').insert(new_proj).execute()
                        
                        if res.data:
                            inserted_id = res.data[0]['id']
                            db.log_activity("INSERT", "projects", f"Νέο έργο: {name}", st.session_state.current_user)
                            db.add_to_undo_stack("INSERT", "projects", inserted_id, new_proj)
                            
                            st.success("Προστέθηκε επιτυχώς!")
                            db.fetch_paginated.clear() # Καθαρισμός cache
                            st.rerun()
                    except Exception as e:
                        st.error(f"Σφάλμα: {e}")

    # Προβολή του πίνακα
    if projects:
        df_projs = pd.DataFrame(projects)
        display_df = df_projs.rename(columns={
            'name': 'Όνομα Έργου', 
            'location': 'Τοποθεσία',
            'created_at': 'Ημ. Προσθήκης'
        })
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("Δεν βρέθηκαν ενεργά έργα στη βάση.")


# --- ΕΚΤΕΛΕΣΗ ΤΩΝ ΣΤΟΙΧΕΙΩΝ ΣΤΑ TABS ---
with tab_employees:
    render_employees_tab()

with tab_projects:
    render_projects_tab()
