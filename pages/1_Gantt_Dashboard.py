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
st.write("Σύνδεση με την υπάρχουσα βάση δεδομένων: Ενεργή (Schema-Aware)")
st.write("---")

# CSS για να μοιάζει περισσότερο με δομημένο πίνακα (Excel-style)
st.markdown("""
<style>
    .stPlotlyChart {
        border: 2px solid #334155;
        border-radius: 8px;
        background-color: #f8fafc;
        padding: 5px;
    }
</style>
""", unsafe_allow_html=True)


# ==========================================
# 2. ΦΟΡΜΑ ΓΡΗΓΟΡΗΣ ΚΑΤΑΧΩΡΗΣΗΣ
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
                role_val = st.selectbox("Τύπος", ["Κανονική Βάρδια", "Υπερωρία", "Ειδικό Έργο"])
                notes = st.text_input("Σημειώσεις")
            
            submit = st.form_submit_button("Οριστικοποίηση Καταχώρησης")
            
            if submit:
                if sel_emp and sel_proj:
                    try:
                        emp_id = next(e['id'] for e in emps if e['name'] == sel_emp)
                        proj_id = next(p['id'] for p in projs if p['name'] == sel_proj)
                        
                        new_data = {
                            'employeeId': emp_id,
                            'projectId': proj_id,
                            'startTime': start_d.isoformat(),
                            'endTime': end_d.isoformat(),
                            'notes': f"[{role_val}] {notes}" if notes else role_val,
                            'date': start_d.isoformat()
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
# 3. ΔΙΑΓΡΑΜΜΑ GANTT (EXCEL-STYLE ΜΕ ΠΛΗΡΟΦΟΡΙΕΣ ΕΝΤΟΣ)
# ==========================================
@st.fragment
def render_gantt_chart():
    st.subheader("Ημερολόγιο Προγράμματος")
    
    # Φόρτωση Δεδομένων
    assignments = db.fetch_paginated('assignments')
    employees = db.fetch_paginated('employees')
    projects = db.fetch_paginated('projects')
    
    if not assignments:
        st.info("Δεν βρέθηκαν δεδομένα βαρδιών.")
        return

    df_assign = pd.DataFrame(assignments)
    df_emp = pd.DataFrame(employees)
    df_proj = pd.DataFrame(projects)
    
    if df_emp.empty or df_proj.empty:
        st.warning("Λείπουν δεδομένα για την προβολή.")
        return

    # --- ΜΕΤΟΝΟΜΑΣΙΑ ΒΑΣΕΙ SCREENSHOT (CamelCase) ---
    mapping = {
        'employeeId': 'employee_id',
        'projectId': 'project_id',
        'startTime': 'start_date',
        'endTime': 'end_date'
    }
    for old_col, new_col in mapping.items():
        if old_col in df_assign.columns:
            df_assign.rename(columns={old_col: new_col}, inplace=True)

    try:
        # Merges
        df = df_assign.merge(df_emp[['id', 'name']], left_on='employee_id', right_on='id', how='left')
        df.rename(columns={'name': 'Εργαζόμενος'}, inplace=True)
        
        df = df.merge(df_proj[['id', 'name']], left_on='project_id', right_on='id', how='left')
        df.rename(columns={'name': 'Έργο'}, inplace=True)
        
        # Καθαρισμός Ημερομηνιών
        df['start_date'] = pd.to_datetime(df['start_date'], errors='coerce')
        df['end_date'] = pd.to_datetime(df['end_date'], errors='coerce')
        df = df.dropna(subset=['start_date', 'end_date', 'Εργαζόμενος'])

        # --- ΔΗΜΙΟΥΡΓΙΑ EXCEL-LIKE LABEL ΓΙΑ ΤΗ ΜΠΑΡΑ ---
        # Κατασκευάζουμε το κείμενο που θα φαίνεται ΜΕΣΑ στη μπάρα
        def make_label(row):
            start_t = row['start_date'].strftime('%H:%M')
            end_t = row['end_date'].strftime('%H:%M')
            return f"<b>{row['Έργο']}</b><br>{row['Εργαζόμενος']}<br>{start_t} - {end_t}"

        df['display_label'] = df.apply(make_label, axis=1)

        # Επιλογή Χρωμάτων
        color_map = None
        if 'colorHex' in df.columns:
            color_map = df.dropna(subset=['Έργο', 'colorHex']).set_index('Έργο')['colorHex'].to_dict()

        # Δημιουργία Γραφήματος
        fig = px.timeline(
            df, 
            x_start="start_date", 
            x_end="end_date", 
            y="Εργαζόμενος", 
            color="Έργο",
            color_discrete_map=color_map,
            text="display_label", # Εμφάνιση του label μέσα στη μπάρα
            hover_data=['Έργο', 'Εργαζόμενος', 'start_date', 'end_date'],
            template="plotly_white"
        )
        
        # Ρυθμίσεις εμφάνισης κειμένου εντός των μπαρών
        fig.update_traces(
            textposition='inside', 
            insidetextanchor='start',
            textfont=dict(size=11, color='white'),
            marker=dict(line=dict(width=1, color='white')) # Λευκό περίγραμμα για "Excel" αίσθηση
        )
        
        fig.update_yaxes(autorange="reversed", gridcolor="#e2e8f0")
        fig.update_xaxes(
            dtick="D1", 
            tickformat="%d/%m\n%a", 
            gridcolor="#e2e8f0",
            side="top" # Οι ημερομηνίες πάνω όπως στο Excel
        )
        
        fig.update_layout(
            height=300 + (len(df['Εργαζόμενος'].unique()) * 50), # Πιο παχιές μπάρες για να χωράει το κείμενο
            margin=dict(l=10, r=10, t=80, b=10),
            showlegend=False, # Κρύβουμε το legend γιατί οι πληροφορίες είναι ήδη μέσα
            font=dict(family="Arial", size=12)
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
    except Exception as e:
        st.error(f"Σφάλμα προβολής: {e}")

# --- ΕΚΤΕΛΕΣΗ ---
quick_add_assignment()
render_gantt_chart()
gc.collect()
