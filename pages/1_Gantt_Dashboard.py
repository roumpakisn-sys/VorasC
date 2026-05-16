import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, date, timedelta
import gc

# Κάνουμε import τον "κινητήρα" μας
import database as db

# ==========================================
# 1. ΕΛΕΓΧΟΣ ΠΡΟΣΒΑΣΗΣ & STYLING
# ==========================================
if not st.session_state.get('current_user'):
    st.warning("⚠️ Παρακαλώ συνδεθείτε από την αρχική σελίδα για να δείτε το ταμπλό.")
    st.stop()

st.title("📊 Ταμπλό Gantt & Βάρδιες")
st.write("Σύνδεση με την υπάρχουσα βάση δεδομένων: Ενεργή")
st.write("---")

st.markdown("""
<style>
    .stPlotlyChart {
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        box-shadow: 2px 2px 10px rgba(0,0,0,0.05);
    }
</style>
""", unsafe_allow_html=True)


# ==========================================
# 2. ΦΟΡΜΑ ΓΡΗΓΟΡΗΣ ΚΑΤΑΧΩΡΗΣΗΣ (ΣΕ FRAGMENT)
# ==========================================
@st.fragment
def quick_add_assignment():
    with st.expander("➕ Γρήγορη Καταχώρηση Βάρδιας", expanded=False):
        with st.form("quick_add_form"):
            col1, col2, col3 = st.columns(3)
            
            emps = db.fetch_paginated('employees')
            projs = db.fetch_paginated('projects')
            
            emp_names = [e['name'] for e in emps] if emps else []
            proj_names = [p['name'] for p in projs] if projs else []
            
            with col1:
                sel_emp = st.selectbox("Εργαζόμενος", emp_names)
                start_d = st.date_input("Από Ημερομηνία", date.today())
            with col2:
                sel_proj = st.selectbox("Έργο", proj_names)
                end_d = st.date_input("Έως Ημερομηνία", date.today() + timedelta(days=1))
            with col3:
                role = st.selectbox("Τύπος", ["Κανονική Βάρδια", "Υπερωρία", "Άδεια"])
                notes = st.text_input("Σημειώσεις")
            
            submit = st.form_submit_button("Αποθήκευση Βάρδιας")
            
            if submit:
                if sel_emp and sel_proj:
                    try:
                        emp_id = next(e['id'] for e in emps if e['name'] == sel_emp)
                        proj_id = next(p['id'] for p in projs if p['name'] == sel_proj)
                        
                        # Εδώ χρησιμοποιούμε τα ονόματα που περιμένει η βάση σου
                        new_data = {
                            'employee_id': emp_id,
                            'project_id': proj_id,
                            'start_date': start_d.isoformat(),
                            'end_date': end_d.isoformat(),
                            'role': role,
                            'notes': notes
                        }
                        
                        supabase = db.init_supabase()
                        res = supabase.table('assignments').insert(new_data).execute()
                        
                        if res.data:
                            db.log_activity("ΠΡΟΣΘΗΚΗ", "assignments", f"Νέα βάρδια: {sel_emp} -> {sel_proj}", st.session_state.current_user)
                            st.success("Η βάρδια καταχωρήθηκε!")
                            db.fetch_paginated.clear() 
                            st.rerun()
                    except Exception as e:
                        st.error(f"Σφάλμα: {e}")


# ==========================================
# 3. ΔΙΑΓΡΑΜΜΑ GANTT (ΜΕ ΔΙΟΡΘΩΣΗ ΓΙΑ ΠΑΛΙΑ ΒΑΣΗ)
# ==========================================
@st.fragment
def render_gantt_chart():
    st.subheader("Ημερολόγιο Έργων")
    
    # Φόρτωση Δεδομένων
    assignments = db.fetch_paginated('assignments')
    employees = db.fetch_paginated('employees')
    projects = db.fetch_paginated('projects')
    
    if not assignments:
        st.info("Δεν βρέθηκαν καταχωρημένες βάρδιες.")
        return

    df_assign = pd.DataFrame(assignments)
    df_emp = pd.DataFrame(employees)
    df_proj = pd.DataFrame(projects)
    
    if df_emp.empty or df_proj.empty:
        st.warning("Λείπουν δεδομένα Προσωπικού ή Έργων.")
        return

    # --- ΕΞΥΠΝΗ ΔΙΟΡΘΩΣΗ ΣΤΗΛΩΝ ---
    # Αν η βάση σου χρησιμοποιεί άλλα ονόματα αντί για employee_id / project_id
    # προσπαθούμε να τα βρούμε και να τα μετονομάσουμε για το merge
    mapping = {
        'worker_id': 'employee_id',
        'emp_id': 'employee_id',
        'proj_id': 'project_id'
    }
    for old_col, new_col in mapping.items():
        if old_col in df_assign.columns and new_col not in df_assign.columns:
            df_assign.rename(columns={old_col: new_col}, inplace=True)

    # Έλεγχος αν μετά τη διόρθωση υπάρχουν οι στήλες
    if 'employee_id' not in df_assign.columns or 'project_id' not in df_assign.columns:
        st.error("⚠️ Σφάλμα Δομής: Η εφαρμογή δεν βρίσκει τις στήλες σύνδεσης (IDs) στον πίνακα assignments.")
        st.info(f"Διαθέσιμες στήλες στη βάση σου: {', '.join(df_assign.columns)}")
        return
        
    try:
        # Συνένωση πινάκων
        df = df_assign.merge(df_emp[['id', 'name']], left_on='employee_id', right_on='id')
        df.rename(columns={'name': 'Όνομα Εργαζομένου'}, inplace=True)
        
        df = df.merge(df_proj[['id', 'name']], left_on='project_id', right_on='id')
        df.rename(columns={'name': 'Όνομα Έργου'}, inplace=True)
        
        # Μετατροπή ημερομηνιών
        df['start_date'] = pd.to_datetime(df['start_date'])
        df['end_date'] = pd.to_datetime(df['end_date'])
        
        # Δημιουργία Γραφήματος
        fig = px.timeline(
            df, 
            x_start="start_date", 
            x_end="end_date", 
            y="Όνομα Εργαζομένου", 
            color="Όνομα Έργου",
            hover_name="role",
            title="Πρόγραμμα Εργαζομένων",
            template="plotly_white"
        )
        
        fig.update_yaxes(autorange="reversed")
        fig.update_layout(height=600, margin=dict(l=10, r=10, t=40, b=10))
        
        st.plotly_chart(fig, use_container_width=True)
        
    except Exception as e:
        st.error(f"Σφάλμα κατά τη δημιουργία του γραφήματος: {e}")
        st.write("Δοκιμάστε να πατήσετε 'Ανανέωση Δεδομένων' στη σελίδα Management.")


# --- ΕΚΤΕΛΕΣΗ ---
quick_add_assignment()
render_gantt_chart()
gc.collect()
