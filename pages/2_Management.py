import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import uuid
import io
import time
import ast

# --- INITIALIZATION & ΑΣΠΙΔΑ ΑΣΦΑΛΕΙΑΣ ---
if "authenticated" not in st.session_state: st.session_state.authenticated = False
if "employees" not in st.session_state: st.session_state.employees = []
if "projects" not in st.session_state: st.session_state.projects = []
if "assignments" not in st.session_state: st.session_state.assignments = []
if "leaves" not in st.session_state: st.session_state.leaves = []
if "recurring_patterns" not in st.session_state: st.session_state.recurring_patterns = []
if "evaluations" not in st.session_state: st.session_state.evaluations = []

# ΣΗΜΑΝΤΙΚΟ: Σταματάει τον κώδικα εδώ και σε στέλνει στο Login αν δεν είσαι συνδεδεμένος!
if not st.session_state.get("authenticated"):
    st.switch_page("streamlit_app.py")
    st.stop()

import config
import utils
import scheduling

# Συγχρονισμός και UI
utils.init_data_and_sync()
utils.setup_shared_ui()

st.title("⚙️ Διαχείριση Συστήματος")

# --- ΑΠΕΝΕΡΓΟΠΟΙΗΣΗ AUTO-POLLING ΣΤΗ ΔΙΑΧΕΙΡΙΣΗ ---
# Η παρακάτω "κρυφή" σημαία λέει στη Javascript (του utils.py) να ΜΗΝ 
# κάνει αυτόματη ανανέωση όσο είμαστε σε αυτή τη σελίδα, 
# ώστε να μην χάνονται όσα πληκτρολογείς στις φόρμες!
st.markdown('<div id="is_editing_flag" style="display:none;"></div>', unsafe_allow_html=True)

is_full_admin = st.session_state.get('current_user') != "TAN"
active_employee_ids = [e['id'] for e in st.session_state.employees if e.get('status', 'Ενεργός') == 'Ενεργός']

# Δημιουργία Καρτελών (Tabs) για οργάνωση
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🏗️ Έργα", "👥 Προσωπικό", "🌴 Άδειες", "📊 Σύνολο Αδειών",
    "🔁 Επαναλαμβανόμενες", "⭐ Αξιολόγηση", "📝 Καταγραφή (Logs)"
])

# ==========================================
# ΚΑΡΤΕΛΑ 1: ΔΙΑΧΕΙΡΙΣΗ ΕΡΓΩΝ
# ==========================================
with tab1:
    st.header("Διαχείριση Έργων")
    if is_full_admin:
        with st.form("add_project_form", clear_on_submit=True):
            st.subheader("Προσθήκη Νέου Έργου")
            c1, c2 = st.columns(2)
            with c1: new_proj_name = st.text_input("Όνομα Έργου")
            with c2: new_proj_color = st.selectbox("Χρώμα", options=list(config.BASIC_COLORS.keys()))
            if st.form_submit_button("Προσθήκη Έργου"):
                if new_proj_name.strip():
                    new_proj = {'id': str(uuid.uuid4()), 'name': new_proj_name.strip(), 'color': config.BASIC_COLORS[new_proj_color]}
                    st.session_state.projects.append(new_proj)
                    utils.db_insert('projects', new_proj)
                    st.success("Το έργο προστέθηκε!")
                    st.rerun()
                else:
                    st.error("Το όνομα του έργου δεν μπορεί να είναι κενό.")
    
    st.subheader("Λίστα Έργων")
    if not st.session_state.projects:
        st.info("Δεν υπάρχουν καταχωρημένα έργα.")
    else:
        for p in st.session_state.projects:
            col_name, col_color, col_del = st.columns([3, 1, 1])
            col_name.write(p['name'])
            
            color_name = "Άγνωστο"
            for k, v in config.BASIC_COLORS.items():
                if v == p.get('color'):
                    color_name = k
                    break
            col_color.markdown(f"<div style='background-color:{p.get('color', '#999')}; color:white; text-align:center; border-radius:4px;'>{color_name}</div>", unsafe_allow_html=True)
            
            if is_full_admin:
                if col_del.button("❌ Διαγραφή", key=f"del_p_{p['id']}"):
                    st.session_state.projects = [proj for proj in st.session_state.projects if proj['id'] != p['id']]
                    utils.db_delete('projects', 'id', p['id'])
                    # Cascade delete assignments/patterns linked to this project
                    assigns_to_delete = [a for a in st.session_state.assignments if a['projectId'] == p['id']]
                    if assigns_to_delete:
                        st.session_state.assignments = [a for a in st.session_state.assignments if a['projectId'] != p['id']]
                        utils.db_delete_in('assignments', 'projectId', [p['id']])
                    patterns_to_delete = [pat for pat in st.session_state.recurring_patterns if pat['projectId'] == p['id']]
                    if patterns_to_delete:
                        st.session_state.recurring_patterns = [pat for pat in st.session_state.recurring_patterns if pat['projectId'] != p['id']]
                        utils.db_delete_in('recurring_patterns', 'projectId', [p['id']])
                    st.rerun()

# ==========================================
# ΚΑΡΤΕΛΑ 2: ΟΜΑΔΑ ΠΡΟΣΩΠΙΚΟΥ
# ==========================================
with tab2:
    st.header("Ομάδα Προσωπικού")
    if is_full_admin:
        
        # 1. ΠΡΟΣΘΗΚΗ ΝΕΟΥ ΥΠΑΛΛΗΛΟΥ
        with st.expander("➕ Προσθήκη Νέου Υπαλλήλου", expanded=False):
            with st.form("add_employee_form", clear_on_submit=True):
                st.subheader("Στοιχεία Νέου Υπαλλήλου")
                
                c1, c2 = st.columns(2)
                with c1: new_emp_name = st.text_input("Ονοματεπώνυμο *")
                with c2: new_emp_role = st.selectbox("Ρόλος *", ["Εργάτης", "Επόπτης", "Οδηγός"])
                
                c3, c4 = st.columns(2)
                with c3: new_emp_phone = st.text_input("Τηλέφωνο")
                with c4: new_emp_id_num = st.text_input("Αρ. Ταυτότητας")
                
                new_emp_specialty = st.text_input("Ειδικότητα (Προαιρετικό)")
                
                c5, c6 = st.columns(2)
                with c5: new_emp_status = st.selectbox("Κατάσταση", ["Ενεργός", "Ανενεργός"])
                with c6: is_external = st.checkbox("Εξωτερικό Συνεργείο;")
                
                if st.form_submit_button("Προσθήκη Υπαλλήλου"):
                    if new_emp_name.strip():
                        existing = next((e for e in st.session_state.employees if e['name'].strip().lower() == new_emp_name.strip().lower()), None)
                        if existing:
                            st.warning("⚠️ Υπάρχει ήδη υπάλληλος με αυτό το όνομα. Παρακαλώ χρησιμοποιήστε την Επεξεργασία.")
                        else:
                            new_emp = {
                                'id': str(uuid.uuid4()), 
                                'name': new_emp_name.strip(),
                                'role': new_emp_role,
                                'phone': new_emp_phone.strip(),
                                'id_number': new_emp_id_num.strip(),
                                'specialty': new_emp_specialty.strip(), 
                                'status': new_emp_status, 
                                'is_external_crew': is_external
                            }
                            st.session_state.employees.append(new_emp)
                            utils.db_insert('employees', new_emp)
                            st.success("Ο υπάλληλος προστέθηκε επιτυχώς!")
                            time.sleep(0.5)
                            st.rerun()
                    else:
                        st.error("Το πεδίο Ονοματεπώνυμο είναι υποχρεωτικό.")
        
        # 2. ΕΠΕΞΕΡΓΑΣΙΑ ΥΠΑΡΧΟΝΤΩΝ
        with st.expander("✏️ Επεξεργασία Εργαζομένων", expanded=False):
            if not st.session_state.employees:
                st.info("Δεν υπάρχουν υπάλληλοι προς επεξεργασία.")
            else:
                edit_emp_id = st.selectbox("Επιλογή Υπαλλήλου για Επεξεργασία", options=[e['id'] for e in st.session_state.employees], format_func=utils.get_employee_name)
                
                if edit_emp_id:
                    target_emp = next((e for e in st.session_state.employees if e['id'] == edit_emp_id), None)
                    if target_emp:
                        with st.form("edit_employee_form"):
                            st.subheader(f"Επεξεργασία: {target_emp.get('name')}")
                            
                            ec1, ec2 = st.columns(2)
                            with ec1: e_name = st.text_input("Ονοματεπώνυμο", value=target_emp.get('name', ''))
                            
                            roles = ["Εργάτης", "Επόπτης", "Οδηγός"]
                            current_role = target_emp.get('role', 'Εργάτης')
                            if current_role not in roles and current_role: roles.append(current_role)
                            with ec2: e_role = st.selectbox("Ρόλος", roles, index=roles.index(current_role) if current_role in roles else 0)
                            
                            ec3, ec4 = st.columns(2)
                            with ec3: e_phone = st.text_input("Τηλέφωνο", value=target_emp.get('phone', ''))
                            with ec4: e_id_num = st.text_input("Αρ. Ταυτότητας", value=target_emp.get('id_number', ''))
                            
                            e_spec = st.text_input("Ειδικότητα", value=target_emp.get('specialty', ''))
                            
                            ec5, ec6 = st.columns(2)
                            statuses = ["Ενεργός", "Ανενεργός"]
                            curr_status = target_emp.get('status', 'Ενεργός')
                            with ec5: e_status = st.selectbox("Κατάσταση", statuses, index=statuses.index(curr_status) if curr_status in statuses else 0)
                            with ec6: e_ext = st.checkbox("Εξωτερικό Συνεργείο;", value=bool(target_emp.get('is_external_crew', False)))
                            
                            if st.form_submit_button("Αποθήκευση Αλλαγών"):
                                if e_name.strip():
                                    updated_emp = dict(target_emp)
                                    updated_emp.update({
                                        'name': e_name.strip(),
                                        'role': e_role,
                                        'phone': e_phone.strip(),
                                        'id_number': e_id_num.strip(),
                                        'specialty': e_spec.strip(),
                                        'status': e_status,
                                        'is_external_crew': e_ext
                                    })
                                    utils.db_update('employees', target_emp['id'], updated_emp)
                                    st.session_state.employees = [updated_emp if e['id'] == target_emp['id'] else e for e in st.session_state.employees]
                                    st.success("Τα στοιχεία του υπαλλήλου ενημερώθηκαν!")
                                    time.sleep(0.5)
                                    st.rerun()
                                else:
                                    st.error("Το όνομα δεν μπορεί να είναι κενό.")
                        
        # 3. ΜΑΖΙΚΗ ΕΙΣΑΓΩΓΗ EXCEL
        with st.expander("📁 Μαζική Εισαγωγή από Excel", expanded=False):
            uploaded_file = st.file_uploader("Ανεβάστε αρχείο Excel", type=["xlsx"])
            if uploaded_file is not None:
                try:
                    df_emps = pd.read_excel(uploaded_file)
                    # Οι μόνες 100% υποχρεωτικές στήλες είναι το Ονοματεπώνυμο
                    if 'Ονοματεπώνυμο' in df_emps.columns:
                        new_records = []
                        for _, row in df_emps.iterrows():
                            name = str(row['Ονοματεπώνυμο']).strip()
                            if not name or name == 'nan': continue
                            existing = next((e for e in st.session_state.employees if e['name'].strip().lower() == name.lower()), None)
                            if not existing:
                                new_records.append({
                                    'id': str(uuid.uuid4()),
                                    'name': name,
                                    'role': str(row.get('Ρόλος', 'Εργάτης')).strip() if pd.notna(row.get('Ρόλος')) else "Εργάτης",
                                    'phone': str(row.get('Τηλέφωνο', '')).strip() if pd.notna(row.get('Τηλέφωνο')) else "",
                                    'id_number': str(row.get('Αρ. Ταυτότητας', '')).strip() if pd.notna(row.get('Αρ. Ταυτότητας')) else "",
                                    'specialty': str(row.get('Ειδικότητα', '')).strip() if pd.notna(row.get('Ειδικότητα')) else "",
                                    'status': str(row.get('Κατάσταση', 'Ενεργός')).strip() if pd.notna(row.get('Κατάσταση')) else "Ενεργός",
                                    'is_external_crew': bool(row.get('Εξωτερικό Συνεργείο', False)) if pd.notna(row.get('Εξωτερικό Συνεργείο')) else False
                                })
                        if new_records:
                            st.session_state.employees.extend(new_records)
                            utils.db_insert_bulk_background('employees', new_records, "ΜΑΖΙΚΗ ΕΙΣΑΓΩΓΗ ΠΡΟΣΩΠΙΚΟΥ")
                            utils.mark_data_changed()
                            st.success(f"Εισήχθησαν επιτυχώς {len(new_records)} νέοι υπάλληλοι!")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.info("Δεν βρέθηκαν νέοι υπάλληλοι προς εισαγωγή (υπάρχουν ήδη).")
                    else:
                        st.error("Το Excel πρέπει να περιέχει τουλάχιστον τη στήλη 'Ονοματεπώνυμο'.")
                except Exception as e:
                    st.error(f"Σφάλμα κατά την ανάγνωση: {e}")

    # ==================================
    # ΠΙΝΑΚΑΣ - ΛΙΣΤΑ ΠΡΟΣΩΠΙΚΟΥ
    # ==================================
    st.subheader("Λίστα Προσωπικού")
    if not st.session_state.employees:
        st.info("Δεν υπάρχει καταχωρημένο προσωπικό.")
    else:
        df_display = pd.DataFrame(st.session_state.employees)
        
        # --- ΑΣΠΙΔΑ ΓΙΑ ΤΟ KEYERROR ---
        # Δημιουργούμε δυναμικά όποια στήλη λείπει από παλιές εγγραφές της βάσης
        required_columns = ['name', 'role', 'phone', 'id_number', 'specialty', 'status', 'id']
        for col in required_columns:
            if col not in df_display.columns:
                df_display[col] = ""
                
        if 'is_external_crew' not in df_display.columns:
            df_display['is_external_crew'] = False
            
        # Μετατροπή της boolean στήλης σε Ναι/Όχι με ασφάλεια
        df_display['Εξωτερικό Συνεργείο'] = df_display['is_external_crew'].apply(lambda x: "Ναι" if str(x).lower() in ['true', '1'] or x is True else "Όχι")
        
        # Επιλογή και μετονομασία των τελικών στηλών για την εμφάνιση
        df_display = df_display[['name', 'role', 'phone', 'id_number', 'specialty', 'status', 'Εξωτερικό Συνεργείο', 'id']]
        df_display.columns = ['Ονοματεπώνυμο', 'Ρόλος', 'Τηλέφωνο', 'Αρ. Ταυτότητας', 'Ειδικότητα', 'Κατάσταση', 'Εξωτερικό Συνεργείο', 'ID']
        
        st.dataframe(df_display.drop(columns=['ID']), use_container_width=True)
        
        if is_full_admin:
            emp_to_del = st.selectbox("Επιλογή Υπαλλήλου για Διαγραφή", options=[e['id'] for e in st.session_state.employees], format_func=utils.get_employee_name)
            if st.button("❌ Οριστική Διαγραφή", type="primary"):
                st.session_state.employees = [e for e in st.session_state.employees if e['id'] != emp_to_del]
                utils.db_delete('employees', 'id', emp_to_del)
                
                # Cascade Deletes
                st.session_state.assignments = [a for a in st.session_state.assignments if a['employeeId'] != emp_to_del]
                utils.db_delete_in('assignments', 'employeeId', [emp_to_del], track=False)
                
                st.session_state.leaves = [l for l in st.session_state.leaves if l['employeeId'] != emp_to_del]
                utils.db_delete_in('leaves', 'employeeId', [emp_to_del], track=False)
                
                st.session_state.evaluations = [ev for ev in st.session_state.evaluations if ev['employeeId'] != emp_to_del]
                utils.db_delete_in('evaluations', 'employeeId', [emp_to_del], track=False)
                
                st.success("Διαγράφηκε επιτυχώς!")
                time.sleep(0.5)
                st.rerun()

# ==========================================
# ΚΑΡΤΕΛΑ 3: ΑΔΕΙΕΣ & ΑΠΟΥΣΙΕΣ
# ==========================================
with tab3:
    st.header("Άδειες / Απουσίες")
    if is_full_admin:
        with st.form("add_leave_form", clear_on_submit=True):
            st.subheader("Καταχώρηση Άδειας")
            l_emp = st.selectbox("Υπάλληλος", options=active_employee_ids, format_func=utils.get_employee_name)
            c1, c2 = st.columns(2)
            with c1: l_start = st.date_input("Από")
            with c2: l_end = st.date_input("Έως")
            l_sub = st.selectbox("Αντικαταστάτης (Προαιρετικό)", options=[""] + active_employee_ids, format_func=lambda x: "Κανένας" if x == "" else utils.get_employee_name(x))
            
            if st.form_submit_button("Καταχώρηση Άδειας"):
                if l_start > l_end:
                    st.error("Η ημερομηνία 'Έως' πρέπει να είναι μετά την ημερομηνία 'Από'.")
                else:
                    new_l = {
                        'id': str(uuid.uuid4()), 'employeeId': l_emp,
                        'startDate': l_start, 'endDate': l_end,
                        'substituteId': l_sub if l_sub else None
                    }
                    st.session_state.leaves.append(new_l)
                    utils.db_insert('leaves', new_l)
                    st.success("Η άδεια καταχωρήθηκε!")
                    st.rerun()
                    
    st.subheader("Τρέχουσες & Μελοντικές Άδειες")
    today = date.today()
    future_leaves = [l for l in st.session_state.leaves if l['endDate'] >= today]
    future_leaves.sort(key=lambda x: x['startDate'])
    
    if not future_leaves:
        st.info("Δεν υπάρχουν ενεργές ή μελλοντικές άδειες.")
    else:
        for l in future_leaves:
            c1, c2 = st.columns([4, 1])
            emp_name = utils.get_employee_name(l['employeeId'])
            sub_str = f" [Αντικαταστάτης: {utils.get_employee_name(l['substituteId'])}]" if l.get('substituteId') else ""
            c1.write(f"🌴 **{emp_name}**: {l['startDate'].strftime('%d/%m/%Y')} έως {l['endDate'].strftime('%d/%m/%Y')}{sub_str}")
            if is_full_admin:
                if c2.button("❌ Διαγραφή", key=f"del_l_{l['id']}"):
                    st.session_state.leaves = [lv for lv in st.session_state.leaves if lv['id'] != l['id']]
                    utils.db_delete('leaves', 'id', l['id'])
                    st.rerun()

# ==========================================
# ΚΑΡΤΕΛΑ 4: ΣΥΝΟΛΟ ΑΔΕΙΩΝ
# ==========================================
with tab4:
    st.header("Σύνολο Αδειών Ανά Υπάλληλο")
    selected_year = st.selectbox("Επιλογή Έτους", options=list(range(2023, 2031)), index=list(range(2023, 2031)).index(date.today().year))
    
    leave_totals = []
    for emp in st.session_state.employees:
        total_days = 0
        emp_leaves = [l for l in st.session_state.leaves if l['employeeId'] == emp['id']]
        for l in emp_leaves:
            s_date = l['startDate']
            e_date = l['endDate']
            if s_date.year <= selected_year <= e_date.year:
                calc_s = max(s_date, date(selected_year, 1, 1))
                calc_e = min(e_date, date(selected_year, 12, 31))
                total_days += (calc_e - calc_s).days + 1
        
        if total_days > 0 or emp.get('status', 'Ενεργός') == 'Ενεργός':
            leave_totals.append({"Υπάλληλος": emp['name'], "Ειδικότητα": emp.get('specialty', ''), "Σύνολο Ημερών (Έτος)": total_days})
            
    if leave_totals:
        df_leaves = pd.DataFrame(leave_totals).sort_values(by="Σύνολο Ημερών (Έτος)", ascending=False)
        st.dataframe(df_leaves, use_container_width=True)
    else:
        st.info("Δεν βρέθηκαν δεδομένα αδειών για το επιλεγμένο έτος.")

# ==========================================
# ΚΑΡΤΕΛΑ 5: ΕΠΑΝΑΛΑΜΒΑΝΟΜΕΝΕΣ ΕΡΓΑΣΙΕΣ
# ==========================================
with tab5:
    st.header("Επαναλαμβανόμενες Εργασίες (Μοτίβα)")
    if is_full_admin:
        with st.form("recurring_form", clear_on_submit=True):
            st.subheader("Νέο Μοτίβο")
            r_type = st.selectbox("Τύπος Επανάληψης", ["Εβδομαδιαία", "Μηνιαία", "Επιλεγμένες Μέρες Εβδομάδας"])
            
            weekdays = []
            if r_type == "Επιλεγμένες Μέρες Εβδομάδας":
                weekdays = st.multiselect("Μέρες", ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"])
                
            r_start_date = st.date_input("Ημερομηνία Έναρξης Επανάληψης")
            r_proj = st.selectbox("Έργο", options=[p['id'] for p in st.session_state.projects], format_func=utils.get_project_name)
            
            # Δυναμική επιλογή προσωπικού ανάλογα με τον τύπο
            if r_type == "Επιλεγμένες Μέρες Εβδομάδας" and weekdays:
                r_emps = {}
                for day in weekdays:
                    r_emps[day] = st.multiselect(f"Προσωπικό για {day}", options=active_employee_ids, format_func=utils.get_employee_name, key=f"r_emp_{day}")
            else:
                r_emps = st.multiselect("Προσωπικό", options=active_employee_ids, format_func=utils.get_employee_name)
                
            c1, c2, c3 = st.columns(3)
            with c1: r_arr = st.time_input("Ώρα Προσέλευσης (Προαιρετικό)", value=None)
            with c2: r_start = st.time_input("Ώρα Έναρξης", value=datetime.strptime("09:00", "%H:%M").time())
            with c3: r_end = st.time_input("Ώρα Λήξης", value=datetime.strptime("17:00", "%H:%M").time())
            
            c4, c5 = st.columns(2)
            with c4: r_color = st.selectbox("Χρώμα", options=list(config.BASIC_COLORS.keys()))
            with c5: r_notes = st.text_input("Παρατηρήσεις")
            
            if st.form_submit_button("Αποθήκευση Μοτίβου & Εφαρμογή"):
                if r_start >= r_end:
                    st.error("Η έναρξη πρέπει να είναι πριν τη λήξη.")
                elif r_type == "Επιλεγμένες Μέρες Εβδομάδας" and not weekdays:
                    st.error("Επιλέξτε τουλάχιστον μία ημέρα.")
                else:
                    new_pat = {
                        'id': str(uuid.uuid4()),
                        'type': r_type,
                        'weekdays': str(weekdays),
                        'startDate': r_start_date,
                        'projectId': r_proj,
                        'employeeIds': str(r_emps),
                        'arrivalTime': r_arr.strftime("%H:%M") if r_arr else "",
                        'startTime': r_start.strftime("%H:%M"),
                        'endTime': r_end.strftime("%H:%M"),
                        'colorName': r_color,
                        'notes': r_notes
                    }
                    st.session_state.recurring_patterns.append(new_pat)
                    utils.db_insert('recurring_patterns', new_pat)
                    # Trigger Auto-Extend immediately
                    utils.auto_extend_recurring_patterns()
                    st.success("Το μοτίβο αποθηκεύτηκε και επεκτάθηκε!")
                    time.sleep(1)
                    st.rerun()
                    
    st.subheader("Ενεργά Μοτίβα")
    if not st.session_state.recurring_patterns:
        st.info("Δεν υπάρχουν ενεργά μοτίβα επαναλαμβανόμενων εργασιών.")
    else:
        for pat in st.session_state.recurring_patterns:
            c1, c2 = st.columns([4, 1])
            proj_name = utils.get_project_name(pat['projectId'])
            start_str = pat['startDate'].strftime('%d/%m/%Y') if isinstance(pat['startDate'], date) else pat['startDate']
            c1.write(f"🔁 **{pat['type']}** | Έργο: {proj_name} | Από: {start_str} | Ώρες: {str(pat['startTime'])[:5]}-{str(pat['endTime'])[:5]}")
            if is_full_admin:
                if c2.button("❌ Διαγραφή", key=f"del_pat_{pat['id']}"):
                    st.session_state.recurring_patterns = [p for p in st.session_state.recurring_patterns if p['id'] != pat['id']]
                    utils.db_delete('recurring_patterns', 'id', pat['id'])
                    # Delete future generated assignments from this pattern
                    future_assigns = [a for a in st.session_state.assignments if a.get('recurring_id') == pat['id'] and a['date'] >= date.today()]
                    if future_assigns:
                        ids_to_del = [a['id'] for a in future_assigns]
                        st.session_state.assignments = [a for a in st.session_state.assignments if a['id'] not in ids_to_del]
                        utils.db_delete_in('assignments', 'id', ids_to_del)
                    st.rerun()

# ==========================================
# ΚΑΡΤΕΛΑ 6: ΑΞΙΟΛΟΓΗΣΗ ΠΡΟΣΩΠΙΚΟΥ
# ==========================================
with tab6:
    st.header("Αξιολόγηση Προσωπικού")
    if is_full_admin:
        with st.form("eval_form", clear_on_submit=True):
            st.subheader("Νέα Αξιολόγηση")
            ev_emp = st.selectbox("Υπάλληλος", options=active_employee_ids, format_func=utils.get_employee_name)
            c1, c2, c3 = st.columns(3)
            with c1: ev_month = st.selectbox("Μήνας", options=list(range(1, 13)), index=date.today().month-1)
            with c2: ev_year = st.selectbox("Έτος", options=list(range(2023, 2031)), index=list(range(2023, 2031)).index(date.today().year))
            with c3: ev_rating = st.slider("Βαθμολογία (1-5)", min_value=1, max_value=5, value=5)
            ev_comments = st.text_area("Σχόλια")
            
            if st.form_submit_button("Αποθήκευση Αξιολόγησης"):
                new_ev = {
                    'id': str(uuid.uuid4()), 'employeeId': ev_emp,
                    'month': ev_month, 'year': ev_year,
                    'rating': ev_rating, 'comments': ev_comments, 'date_added': date.today()
                }
                st.session_state.evaluations.append(new_ev)
                utils.db_insert('evaluations', new_ev)
                st.success("Η αξιολόγηση καταχωρήθηκε!")
                st.rerun()
                
    st.subheader("Ιστορικό Αξιολογήσεων")
    if not st.session_state.evaluations:
        st.info("Δεν υπάρχουν αξιολογήσεις.")
    else:
        df_evals = pd.DataFrame(st.session_state.evaluations)
        df_evals['Υπάλληλος'] = df_evals['employeeId'].apply(utils.get_employee_name)
        df_evals['Περίοδος'] = df_evals['month'].astype(str) + "/" + df_evals['year'].astype(str)
        df_evals['Βαθμολογία'] = df_evals['rating'].apply(lambda x: "⭐" * int(x))
        df_display_ev = df_evals[['Υπάλληλος', 'Περίοδος', 'Βαθμολογία', 'comments', 'id']].rename(columns={'comments': 'Σχόλια'})
        
        for _, row in df_display_ev.iterrows():
            with st.expander(f"📌 {row['Υπάλληλος']} - {row['Περίοδος']} ({row['Βαθμολογία']})"):
                st.write(f"**Σχόλια:** {row['Σχόλια']}")
                if is_full_admin:
                    if st.button("Διαγραφή Αξιολόγησης", key=f"del_ev_{row['id']}"):
                        st.session_state.evaluations = [ev for ev in st.session_state.evaluations if ev['id'] != row['id']]
                        utils.db_delete('evaluations', 'id', row['id'])
                        st.rerun()

# ==========================================
# ΚΑΡΤΕΛΑ 7: ΚΑΤΑΓΡΑΦΗ ΚΙΝΗΣΕΩΝ (LOGS)
# ==========================================
with tab7:
    st.header("Ιστορικό Κινήσεων (Logs)")
    if not is_full_admin:
        st.warning("Δεν έχετε δικαίωμα πρόσβασης σε αυτήν την ενότητα.")
    else:
        if utils.supabase:
            st.caption("Εμφανίζονται οι τελευταίες 100 ενέργειες στο σύστημα.")
            if st.button("🔄 Ανανέωση Logs"):
                st.rerun()
                
            try:
                res = utils.supabase.table("activity_logs").select("*").order("timestamp", desc=True).limit(100).execute()
                logs_data = res.data
                if not logs_data:
                    st.info("Δεν βρέθηκαν καταγραφές.")
                else:
                    for l in logs_data:
                        t_obj = datetime.fromisoformat(l['timestamp'].replace("Z", "+00:00"))
                        t_str = t_obj.strftime("%d/%m/%Y %H:%M:%S")
                        parsed_det = utils.parse_old_log_details(l.get('table_name', ''), l.get('details', ''))
                        st.markdown(f"**{t_str}** | Χρήστης: `{l['username']}` | **{l['action_type']}** στον πίνακα `{l['table_name']}`  \n*Λεπτομέρειες:* {parsed_det}")
                        st.divider()
            except Exception as e:
                st.error(f"Αδυναμία ανάκτησης logs: {e}")
        else:
            st.warning("Τα Logs λειτουργούν μόνο όταν είστε συνδεδεμένοι στο Supabase Cloud.")
