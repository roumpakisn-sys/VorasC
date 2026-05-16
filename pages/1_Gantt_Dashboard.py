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

# CSS για βελτίωση της εμφάνισης του διαγράμματος
st.markdown("""
<style>
    .stPlotlyChart {
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
        background-color: white;
        padding: 10px;
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
            
            # Φόρτωση δεδομένων για τα selectboxes
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
                        
                        # Χρήση των ονομάτων στηλών της παλιάς σου βάσης (camelCase)
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
                            st.success("Η βάρδια καταχωρήθηκε επιτυχώς!")
                            db.fetch_paginated.clear() 
                            st.rerun()
                    except Exception as e:
                        st.error(f"Σφάλμα κατά την αποθήκευση: {e}")


# ==========================================
# 3. ΔΙΑΓΡΑΜΜΑ GANTT (ΕΠΑΝΑΦΟΡΑ ΠΑΛΙΑΣ ΕΜΦΑΝΙΣΗΣ)
# ==========================================
@st.fragment
def render_gantt_chart():
    st.subheader("Ημερολόγιο Προγράμματος")
    
    # Φόρτωση Δεδομένων από τη Supabase
    assignments = db.fetch_paginated('assignments')
    employees = db.fetch_paginated('employees')
    projects = db.fetch_paginated('projects')
    
    if not assignments:
        st.info("Δεν βρέθηκαν δεδομένα βαρδιών στη βάση.")
        return

    df_assign = pd.DataFrame(assignments)
    df_emp = pd.DataFrame(employees)
    df_proj = pd.DataFrame(projects)
    
    if df_emp.empty or df_proj.empty:
        st.warning("Απαραίτητη η ύπαρξη εργαζομένων και έργων για την προβολή.")
        return

    # --- ΕΝΑΡΜΟΝΙΣΗ ΣΤΗΛΩΝ (Mapping από παλιά βάση) ---
    # Μετατρέπουμε τα camelCase ονόματα στα ονόματα που περιμένει η λογική μας
    mapping = {
        'employeeId': 'employee_id',
        'projectId': 'project_id',
        'startTime': 'start_date',
        'endTime': 'end_date'
    }
    for old_col, new_col in mapping.items():
        if old_col in df_assign.columns:
            df_assign.rename(columns={old_col: new_col}, inplace=True)

    # Έλεγχος κρίσιμων στηλών
    required = ['employee_id', 'project_id', 'start_date', 'end_date']
    if not all(c in df_assign.columns for c in required):
        st.error("⚠️ Σφάλμα δομής δεδομένων στον πίνακα 'assignments'.")
        return
        
    try:
        # Merge με Εργαζόμενους (για ονόματα στον Υ-άξονα)
        df = df_assign.merge(df_emp[['id', 'name']], left_on='employee_id', right_on='id', how='left')
        df.rename(columns={'name': 'Εργαζόμενος'}, inplace=True)
        
        # Merge με Έργα (για ονόματα στο Legend)
        df = df.merge(df_proj[['id', 'name']], left_on='project_id', right_on='id', how='left')
        df.rename(columns={'name': 'Έργο'}, inplace=True)
        
        # Καθαρισμός ημερομηνιών
        df['start_date'] = pd.to_datetime(df['start_date'], errors='coerce')
        df['end_date'] = pd.to_datetime(df['end_date'], errors='coerce')
        df = df.dropna(subset=['start_date', 'end_date', 'Εργαζόμενος'])

        # --- ΕΠΙΛΟΓΗ ΧΡΩΜΑΤΙΣΜΟΥ (Όπως στον παλιό κώδικα) ---
        # Αν υπάρχει στήλη colorHex στη βάση σου, τη χρησιμοποιούμε
        color_col = 'Έργο'
        discrete_map = None
        
        if 'colorHex' in df.columns:
            # Δημιουργούμε ένα λεξικό χρωμάτων αν υπάρχουν hex codes
            temp_map = df.dropna(subset=['Έργο', 'colorHex']).set_index('Έργο')['colorHex'].to_dict()
            if temp_map:
                discrete_map = temp_map

        # Δυναμικό Hover Data
        hover_list = ['Έργο']
        if 'notes' in df.columns: hover_list.append('notes')
        if 'role' in df.columns: hover_list.append('role')

        # Δημιουργία του Gantt Chart με Plotly
        fig = px.timeline(
            df, 
            x_start="start_date", 
            x_end="end_date", 
            y="Εργαζόμενος", 
            color=color_col,
            color_discrete_map=discrete_map,
            hover_data=hover_list,
            template="plotly_white",
            labels={"Εργαζόμενος": ""} # Κρύβουμε το label του άξονα Υ για καθαρότητα
        )
        
        # Βελτίωση Layout (Αντιγραφή από την "παλιά" επιτυχημένη έκδοση)
        fig.update_yaxes(autorange="reversed", tickfont=dict(size=12))
        fig.update_xaxes(
            dtick="D1", # Εμφάνιση ανά ημέρα
            tickformat="%d %b",
            gridcolor="#f1f5f9"
        )
        
        fig.update_layout(
            height=400 + (len(df['Εργαζόμενος'].unique()) * 25), # Δυναμικό ύψος βάσει υπαλλήλων
            margin=dict(l=10, r=10, t=50, b=10),
            legend=dict(
                orientation="h", 
                yanchor="bottom", 
                y=1.02, 
                xanchor="right", 
                x=1,
                title=None
            ),
            hoverlabel=dict(bgcolor="white", font_size=13)
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
    except Exception as e:
        st.error(f"Σφάλμα κατά τη σχεδίαση: {e}")
        st.info("💡 Δοκιμάστε να ανανεώσετε τα δεδομένα από τη σελίδα Διαχείρισης.")

# --- ΕΚΤΕΛΕΣΗ ΣΕΛΙΔΑΣ ---
quick_add_assignment()
render_gantt_chart()
gc.collect()
