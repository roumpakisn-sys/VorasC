import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import uuid
import calendar
import time
import threading

# --- INITIALIZATION ---
if not st.session_state.get("authenticated"):
    st.switch_page("streamlit_app.py")

import utils

utils.init_data_and_sync()
utils.setup_shared_ui()

# Helpers local access
is_full_admin = st.session_state.get('current_user') != "TAN"
active_employee_ids = [e['id'] for e in st.session_state.employees if e.get('status', 'Ενεργός') == 'Ενεργός']

menu_options = ["Διαχείριση Έργων", "Ομάδα Προσωπικού", "Άδειες", "Σύνολο Αδειών", "Επαναλαμβανόμενες Εργασίες", "Ώρες Εργασιών", "Αξιολόγηση Προσωπικού"]
if st.session_state.get('current_user') == "Admin":
    menu_options.append("Καταγραφή Κινήσεων")

# Επιλογή Μενού (είτε με tabs είτε με radio button. Χρησιμοποιούμε radio όπως ήταν)
menu = st.sidebar.radio("Μενού Διαχείρισης", menu_options)

# --- VIEW: PROJECTS ---
if menu == "Διαχείριση Έργων":
    st.title("🏗️ Έργα")
    if is_full_admin:
        with st.expander("Νέο Έργο"):
            with st.form("new_project_form", clear_on_submit=True):
                p_name = st.text_input("Όνομα Έργου")
                p_color = st.color_picker("Χρώμα (Προεπιλογή)", "#4a86e8")
                if st.form_submit_button("Δημιουργία"):
                    new_p = {'id': str(uuid.uuid4()), 'name': p_name, 'color': p_color}
                    st.session_state.projects.append(new_p)
                    utils.db_insert('projects', new_p)
                    st.rerun()
    else:
        st.info("🔒 Έχετε πρόσβαση μόνο για προβολή στα Έργα.")

    for p in st.session_state.projects:
        col1, col2 = st.columns([4, 1])
        col1.write(f"**{p['name']}**")
        if is_full_admin:
            if col2.button("Διαγραφή", key=p['id']):
                st.session_state.projects = [proj for proj in st.session_state.projects if proj['id'] != p['id']]
                utils.db_delete('projects', 'id', p['id'], deleted_records=[p])
                st.rerun()

# --- VIEW: EMPLOYEES ---
elif menu == "Ομάδα Προσωπικού":
    st.title("👥 Προσωπικό")
    tab_list, tab_add, tab_edit, tab_import = st.tabs(["📋 Λίστα Υπαλλήλων", "➕ Προσθήκη Υπαλλήλου", "✏️ Επεξεργασία", "📁 Εισαγωγή από Αρχείο"])
    
    with tab_add:
        if "emp_reset_counter" not in st.session_state: st.session_state.emp_reset_counter = 0
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
        with col_btn1: submit_emp = st.button("Προσθήκη Υπαλλήλου", type="primary", use_container_width=True)
        with col_btn2: clear_emp = st.button("🧹 Καθαρισμός", key="btn_clear_emp", use_container_width=True)
        
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
                    if e_id_num.strip() and emp.get('id_number', "").strip().lower() == e_id_num.strip().lower():
                        st.error(f"Ο Αριθμός Ταυτότητας '{e_id_num}' ανήκει ήδη στον/στην '{emp['name']}'.")
                        is_duplicate = True
                        break
                if not is_duplicate:
                    new_e = {'id': str(uuid.uuid4()), 'name': e_name.strip(), 'position': e_pos.strip(), 'id_number': e_id_num.strip(), 'phone': e_phone.strip(), 'status': e_status}
                    st.session_state.employees.append(new_e)
                    utils.db_insert('employees', new_e)
                    st.success(f"Ο/Η '{e_name.strip()}' προστέθηκε με επιτυχία! Η σελίδα ανανεώνεται...")
                    time.sleep(1.5)
                    st.session_state.emp_reset_counter += 1
                    st.rerun()

    with tab_edit:
        if not st.session_state.employees:
            st.info("Δεν υπάρχουν υπάλληλοι προς επεξεργασία.")
        else:
            emp_to_edit_id = st.selectbox("Επιλέξτε Υπάλληλο για Επεξεργασία", options=[e['id'] for e in st.session_state.employees], format_func=utils.get_employee_name)
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
                    ed_id_num = st.text_input("Αριθμός Ταυτότητας", value=emp_to_edit.get('id_number', ""))
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
                                    is_dup = True; break
                                elif ed_id_num.strip() and e.get('id_number', "").strip().lower() == ed_id_num.strip().lower():
                                    st.error("Ο Αριθμός Ταυτότητας ανήκει ήδη σε άλλον υπάλληλο.")
                                    is_dup = True; break
                        if not is_dup:
                            old_emp_data = dict(emp_to_edit)
                            emp_to_edit.update({'name': ed_name.strip(), 'position': ed_pos.strip(), 'id_number': ed_id_num.strip(), 'phone': ed_phone.strip(), 'status': ed_status})
                            utils.db_update('employees', emp_to_edit_id, emp_to_edit, old_data=old_emp_data)
                            st.success("Οι αλλαγές αποθηκεύτηκαν!")
                            st.rerun()

    with tab_import:
        st.write("### 📁 Μαζική Εισαγωγή Υπαλλήλων")
        st.write("Κατεβάστε το Google Sheet σας ως αρχείο Excel (.xlsx) ή CSV και ανεβάστε το εδώ.")
        st.info("Το αρχείο πρέπει να περιέχει οπωσδήποτε μια στήλη με όνομα **'Ονοματεπώνυμο'** (ή 'Name'). Οι υπόλοιπες στήλες ('Θέση', 'Αριθμός Ταυτότητας', 'Κινητό', 'Κατάσταση') θα διαβαστούν αυτόματα εφόσον υπάρχουν.")
        with st.form("import_form", clear_on_submit=True):
            uploaded_file = st.file_uploader("Επιλέξτε αρχείο Excel ή CSV", type=['csv', 'xlsx'])
            submit_import = st.form_submit_button("Εκτέλεση Εισαγωγής", type="primary")
            if submit_import and uploaded_file is not None:
                try:
                    df_import = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
                    success_count, error_count = 0, 0
                    cols = [str(c).lower().strip().replace(".", "").replace("_", "") for c in df_import.columns]
                    name_col = next((orig_col for orig_col, c in zip(df_import.columns, cols) if 'ονομα' in c or 'name' in c or 'υπαλλ' in c or 'υπάλλ' in c), None)
                    
                    if not name_col:
                        st.error("Δεν βρέθηκε στήλη για το Ονοματεπώνυμο.")
                    else:
                        pos_col = next((orig for orig, c in zip(df_import.columns, cols) if 'θεσ' in c or 'θέσ' in c or 'ειδικ' in c or 'ρολο' in c or 'ρόλο' in c or 'position' in c), None)
                        id_col = next((orig for orig, c in zip(df_import.columns, cols) if 'ταυτοτ' in c or 'ταυτότ' in c or 'αδτ' in c or 'id' in c), None)
                        phone_col = next((orig for orig, c in zip(df_import.columns, cols) if 'τηλ' in c or 'κινητ' in c or 'phone' in c), None)
                        status_col = next((orig for orig, c in zip(df_import.columns, cols) if 'καταστ' in c or 'κατάστ' in c or 'status' in c or 'ενεργ' in c or 'active' in c), None)
                        
                        new_employees_batch = []
                        with st.spinner("Εισαγωγή Δεδομένων..."):
                            for index, row in df_import.iterrows():
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
                                    if any(kw in val for kw in ["ανενεργ", "inactive", "false", "0", "οχι", "όχι", "no", "αποχωρ", "παραιτ"]):
                                        e_status = "Ανενεργός"
                                        
                                is_duplicate = False
                                for emp in st.session_state.employees:
                                    if emp['name'].strip().lower() == e_name.lower() or (e_id_num and emp.get('id_number', "").strip().lower() == e_id_num.lower()):
                                        is_duplicate = True; break
                                        
                                if not is_duplicate:
                                    new_e = {'id': str(uuid.uuid4()), 'name': e_name, 'position': e_pos, 'id_number': e_id_num, 'phone': e_phone, 'status': e_status}
                                    new_employees_batch.append(new_e)
                                    st.session_state.employees.append(new_e)
                                    success_count += 1
                                else:
                                    error_count += 1
                                    
                        if new_employees_batch: utils.db_insert('employees', new_employees_batch)
                        if error_count > 0: st.warning(f"Παραλείφθηκαν {error_count} υπάλληλοι επειδή υπήρχαν ήδη στη λίστα.")
                        if success_count > 0:
                            st.success(f"Εισήχθησαν επιτυχώς {success_count} υπάλληλοι! Η σελίδα ανανεώνεται...")
                            time.sleep(1.5)
                            st.rerun()
                except Exception as e:
                    st.error(f"Υπήρξε πρόβλημα με την ανάγνωση του αρχείου: {e}")

    with tab_list:
        st.write("### 📋 Συνολική Λίστα Υπαλλήλων")
        search_query = st.text_input("🔍 Αναζήτηση", placeholder="Ψάξε με Όνομα, Θέση, Ταυτότητα ή Τηλέφωνο...", key="emp_search_bar")
        filtered_emps = st.session_state.employees
        if search_query:
            q = search_query.strip().lower()
            filtered_emps = [e for e in st.session_state.employees if q in str(e.get('name', '')).lower() or q in str(e.get('position', '')).lower() or q in str(e.get('id_number', '')).lower() or q in str(e.get('phone', '')).lower()]
        
        with st.expander("🗑️ Μαζική Διαγραφή"):
            emps_to_delete = st.multiselect("Επιλέξτε τους υπαλλήλους που θέλετε να διαγράψετε:", options=[e['id'] for e in filtered_emps], format_func=utils.get_employee_name, key="bulk_delete_emps")
            if st.button("Οριστική Διαγραφή", type="primary", key="btn_bulk_del"):
                if emps_to_delete:
                    deleted_emps = [e for e in st.session_state.employees if e['id'] in emps_to_delete]
                    st.session_state.employees = [emp for emp in st.session_state.employees if emp['id'] not in emps_to_delete]
                    utils.db_delete_in('employees', 'id', emps_to_delete, deleted_records=deleted_emps)
                    st.rerun()
                else:
                    st.warning("Δεν έχετε επιλέξει κανέναν υπάλληλο.")
        st.divider()
        
        if not filtered_emps:
            st.info("Δεν βρέθηκαν υπάλληλοι που να ταιριάζουν στα κριτήρια αναζήτησης.")
        else:
            hc1, hc2, hc3, hc4, hc5, hc6 = st.columns([2, 2, 2, 2, 1.5, 1])
            hc1.write("**Ονοματεπώνυμο**"); hc2.write("**Θέση**"); hc3.write("**Αρ. Ταυτότητας**"); hc4.write("**Κινητό**"); hc5.write("**Κατάσταση**"); hc6.write("")
            st.divider()
            for e in filtered_emps:
                col1, col2, col3, col4, col5, col6 = st.columns([2, 2, 2, 2, 1.5, 1])
                col1.write(e['name']); col2.write(f"*{e['position']}*"); col3.write(e.get('id_number') or '-'); col4.write(e.get('phone') or '-')
                status_val = e.get('status', 'Ενεργός')
                status_color = "#16a34a" if status_val == 'Ενεργός' else "#dc2626"
                col5.markdown(f"<span style='color:{status_color}; font-weight:bold;'>{status_val}</span>", unsafe_allow_html=True)
                if col6.button("❌", key=f"del_emp_{e['id']}"):
                    st.session_state.employees = [emp for emp in st.session_state.employees if emp['id'] != e['id']]
                    utils.db_delete('employees', 'id', e['id'], deleted_records=[e])
                    st.rerun()

# --- VIEW: LEAVES ---
elif menu == "Άδειες":
    st.title("🌴 Διαχείριση Αδειών")
    if "pending_leave" not in st.session_state: st.session_state.pending_leave = None
    if "leave_conflicts" not in st.session_state: st.session_state.leave_conflicts = []
    
    tab_list, tab_add, tab_edit = st.tabs(["📋 Λίστα Αδειών", "➕ Καταχώρηση", "✏️ Επεξεργασία"])
    with tab_add:
        if "leave_reset_counter" not in st.session_state: st.session_state.leave_reset_counter = 0
        lrc = st.session_state.leave_reset_counter
        c1, c2 = st.columns(2)
        with c1:
            l_emp = st.selectbox("Υπάλληλος (Μόνο Ενεργοί)", options=active_employee_ids, format_func=utils.get_employee_name, key=f"l_emp_{lrc}")
            l_start = st.date_input("Από", key=f"l_start_{lrc}")
        with c2:
            l_sub_emp = st.selectbox("Αντικαταστάτης (Προαιρετικό)", options=[""] + active_employee_ids, format_func=lambda x: "Χωρίς Αντικαταστάτη" if x == "" else utils.get_employee_name(x), key=f"l_sub_{lrc}")
            l_end = st.date_input("Έως", key=f"l_end_{lrc}")
            
        col_b1, col_b2 = st.columns([1, 1])
        with col_b1: submit_leave = st.button("Καταχώρηση Άδειας", type="primary", use_container_width=True)
        with col_b2: clear_leave = st.button("🧹 Καθαρισμός", key="btn_clear_leave", use_container_width=True)
        
        if clear_leave:
            st.session_state.leave_reset_counter += 1
            st.session_state.pending_leave = None
            st.session_state.leave_conflicts = []
            st.rerun()
            
        if submit_leave:
            if not l_emp: st.error("Παρακαλώ επιλέξτε υπάλληλο.")
            elif l_start > l_end: st.error("Η ημερομηνία 'Από' πρέπει να είναι πριν ή ίση με την 'Έως'.")
            elif l_emp == l_sub_emp: st.error("Ο αντικαταστάτης δεν μπορεί να είναι το ίδιο πρόσωπο.")
            else:
                conflicts = []
                curr_date = l_start
                while curr_date <= l_end:
                    day_assigns = st.session_state.assignments_by_date.get(curr_date, [])
                    for a in day_assigns:
                        if a['employeeId'] == l_emp: conflicts.append(a)
                    curr_date += timedelta(days=1)
                
                if conflicts:
                    st.session_state.pending_leave = {'id': str(uuid.uuid4()), 'employeeId': l_emp, 'startDate': l_start, 'endDate': l_end, 'substituteId': l_sub_emp if l_sub_emp else None, 'type': 'new'}
                    st.session_state.leave_conflicts = conflicts
                else:
                    new_l = {'id': str(uuid.uuid4()), 'employeeId': l_emp, 'startDate': l_start, 'endDate': l_end, 'substituteId': l_sub_emp if l_sub_emp else None}
                    st.session_state.leaves.append(new_l)
                    utils.db_insert('leaves', new_l)
                    st.success("Η άδεια καταχωρήθηκε με επιτυχία!")
                    time.sleep(1.5)
                    st.session_state.leave_reset_counter += 1
                    st.rerun()

        if st.session_state.get('pending_leave') and st.session_state.pending_leave.get('type') == 'new' and st.session_state.get('leave_conflicts'):
            st.markdown("---")
            st.warning("⚠️ **Εμπλοκή με βάρδιες!** Ο/Η υπάλληλος είναι ήδη τοποθετημένος/η σε έργα. Πατήστε 'Έγκριση (Αφαίρεση)'.")
            resolved_any = False
            for a in st.session_state.leave_conflicts:
                st.markdown('<div class="leave-conflict-box">', unsafe_allow_html=True)
                col_err, col_btn = st.columns([4, 1])
                proj = utils.get_project_info(a['projectId'])
                pname = proj['name'] if proj else "Άγνωστο Έργο"
                emp_name = utils.get_employee_name(a['employeeId'])
                col_err.write(f"O/H **{emp_name}** δουλεύει στις **{a['date'].strftime('%d/%m/%Y')}** στο έργο: **{pname}** ({a['startTime']}-{a['endTime']}).")
                if col_btn.button("✔️ Έγκριση (Αφαίρεση)", key=f"res_new_{a['id']}", use_container_width=True):
                    target_a = next((assign for assign in st.session_state.assignments if assign['id'] == a['id']), None)
                    if target_a:
                        old_a = dict(target_a)
                        target_a['employeeId'] = "" 
                        utils.db_update('assignments', target_a['id'], target_a, old_data=old_a)
                        st.session_state.leave_conflicts = [c for c in st.session_state.leave_conflicts if c['id'] != a['id']]
                        resolved_any = True
                st.markdown('</div>', unsafe_allow_html=True)
                
            if resolved_any and not st.session_state.leave_conflicts:
                new_l = {k: v for k, v in st.session_state.pending_leave.items() if k != 'type'}
                st.session_state.leaves.append(new_l)
                utils.db_insert('leaves', new_l)
                st.session_state.pending_leave = None
                st.success("Όλες οι επικαλύψεις επιλύθηκαν! Η άδεια καταχωρήθηκε.")
                time.sleep(1.5)
                st.session_state.leave_reset_counter += 1
                st.rerun()

    with tab_edit:
        if not st.session_state.leaves: st.info("Δεν υπάρχουν άδειες προς επεξεργασία.")
        else:
            leave_options = {lv['id']: f"{utils.get_employee_name(lv['employeeId'])} ({lv['startDate'].strftime('%d/%m/%Y')} - {lv['endDate'].strftime('%d/%m/%Y')})" for lv in st.session_state.leaves}
            leave_to_edit_id = st.selectbox("Επιλέξτε Άδεια για Επεξεργασία", options=list(leave_options.keys()), format_func=lambda x: leave_options[x])
            leave_to_edit = next(l for l in st.session_state.leaves if l['id'] == leave_to_edit_id)
            c1, c2 = st.columns(2)
            with c1:
                emp_options_safe = active_employee_ids + [leave_to_edit['employeeId']] if leave_to_edit['employeeId'] not in active_employee_ids else active_employee_ids
                ed_l_emp = st.selectbox("Αλλαγή Υπαλλήλου", options=emp_options_safe, index=emp_options_safe.index(leave_to_edit['employeeId']), format_func=utils.get_employee_name)
                ed_l_start = st.date_input("Αλλαγή Ημερομηνίας 'Από'", value=leave_to_edit['startDate'])
            with c2:
                current_sub = leave_to_edit.get('substituteId') or ""
                sub_options = [""] + active_employee_ids
                if current_sub and current_sub not in sub_options: sub_options.append(current_sub)
                ed_l_sub_emp = st.selectbox("Αλλαγή Αντικαταστάτη", options=sub_options, index=sub_options.index(current_sub), format_func=lambda x: "Χωρίς Αντικαταστάτη" if x == "" else utils.get_employee_name(x))
                ed_l_end = st.date_input("Αλλαγή Ημερομηνίας 'Έως'", value=leave_to_edit['endDate'])
                
            if st.button("💾 Αποθήκευση Αλλαγών", type="primary"):
                if ed_l_start > ed_l_end: st.error("Η ημερομηνία 'Από' πρέπει να είναι πριν ή ίση με την 'Έως'.")
                elif ed_l_emp == ed_l_sub_emp: st.error("Ο αντικαταστάτης δεν μπορεί να είναι το ίδιο πρόσωπο.")
                else:
                    conflicts = []
                    curr_date = ed_l_start
                    while curr_date <= ed_l_end:
                        day_assigns = st.session_state.assignments_by_date.get(curr_date, [])
                        for a in day_assigns:
                            if a['employeeId'] == ed_l_emp: conflicts.append(a)
                        curr_date += timedelta(days=1)
                        
                    if conflicts:
                        st.session_state.pending_leave = {'id': leave_to_edit_id, 'employeeId': ed_l_emp, 'startDate': ed_l_start, 'endDate': ed_l_end, 'substituteId': ed_l_sub_emp if ed_l_sub_emp else None, 'type': 'edit', 'old_data': dict(leave_to_edit)}
                        st.session_state.leave_conflicts = conflicts
                    else:
                        old_leave_data = dict(leave_to_edit)
                        leave_to_edit.update({'employeeId': ed_l_emp, 'startDate': ed_l_start, 'endDate': ed_l_end, 'substituteId': ed_l_sub_emp if ed_l_sub_emp else None})
                        utils.db_update('leaves', leave_to_edit_id, leave_to_edit, old_data=old_leave_data)
                        st.success("Οι αλλαγές στην άδεια αποθηκεύτηκαν!")
                        time.sleep(1)
                        st.rerun()

            if st.session_state.get('pending_leave') and st.session_state.pending_leave.get('type') == 'edit' and st.session_state.get('leave_conflicts'):
                st.markdown("---")
                st.warning("⚠️ **Εμπλοκή με βάρδιες!** Πατήστε 'Έγκριση (Αφαίρεση)'.")
                resolved_any = False
                for a in st.session_state.leave_conflicts:
                    st.markdown('<div class="leave-conflict-box">', unsafe_allow_html=True)
                    col_err, col_btn = st.columns([4, 1])
                    proj = utils.get_project_info(a['projectId'])
                    col_err.write(f"O/H **{utils.get_employee_name(a['employeeId'])}** δουλεύει στις **{a['date'].strftime('%d/%m/%Y')}** στο έργο: **{proj['name'] if proj else 'Άγνωστο Έργο'}**")
                    if col_btn.button("✔️ Έγκριση (Αφαίρεση)", key=f"res_edit_{a['id']}", use_container_width=True):
                        target_a = next((assign for assign in st.session_state.assignments if assign['id'] == a['id']), None)
                        if target_a:
                            old_a = dict(target_a)
                            target_a['employeeId'] = "" 
                            utils.db_update('assignments', target_a['id'], target_a, old_data=old_a)
                            st.session_state.leave_conflicts = [c for c in st.session_state.leave_conflicts if c['id'] != a['id']]
                            resolved_any = True
                    st.markdown('</div>', unsafe_allow_html=True)
                    
                if resolved_any and not st.session_state.leave_conflicts:
                    leave_id = st.session_state.pending_leave['id']
                    leave_obj = next(l for l in st.session_state.leaves if l['id'] == leave_id)
                    old_data = st.session_state.pending_leave['old_data']
                    leave_obj.update({'employeeId': st.session_state.pending_leave['employeeId'], 'startDate': st.session_state.pending_leave['startDate'], 'endDate': st.session_state.pending_leave['endDate'], 'substituteId': st.session_state.pending_leave['substituteId']})
                    utils.db_update('leaves', leave_id, leave_obj, old_data=old_data)
                    st.session_state.pending_leave = None
                    st.success("Όλες οι επικαλύψεις επιλύθηκαν! Οι αλλαγές αποθηκεύτηκαν.")
                    time.sleep(1.5)
                    st.rerun()

    with tab_list:
        if st.session_state.leaves:
            st.write("### 📋 Λίστα Αδειών")
            hc1, hc2, hc3, hc4, hc5 = st.columns([2.5, 2, 2, 2.5, 1])
            hc1.write("**Υπάλληλος**"); hc2.write("**Από**"); hc3.write("**Έως**"); hc4.write("**Αντικαταστάτης**"); hc5.write("")
            st.divider()
            for l in st.session_state.leaves:
                col1, col2, col3, col4, col5 = st.columns([2.5, 2, 2, 2.5, 1])
                col1.write(utils.get_employee_name(l['employeeId']))
                col2.write(l['startDate'].strftime('%d/%m/%Y'))
                col3.write(l['endDate'].strftime('%d/%m/%Y'))
                col4.write(utils.get_employee_name(l.get('substituteId')) if l.get('substituteId') else "-")
                if col5.button("❌", key=f"del_leave_{l['id']}"):
                    st.session_state.leaves = [leave for leave in st.session_state.leaves if leave['id'] != l['id']]
                    utils.db_delete('leaves', 'id', l['id'], deleted_records=[l])
                    st.rerun()
        else:
            st.info("Δεν υπάρχουν καταχωρημένες άδειες.")

# --- VIEW: LEAVE SUMMARY ---
elif menu == "Σύνολο Αδειών":
    st.title("📊 Σύνολο Αδειών ανά Έτος")
    current_year = date.today().year
    years = list(range(2020, 2036))
    col1, col2 = st.columns([1, 3])
    with col1: selected_year = st.selectbox("Επιλογή Έτους", years, index=years.index(current_year))
    st.divider()
    
    leave_days = {emp['id']: 0 for emp in st.session_state.employees}
    year_start = date(selected_year, 1, 1)
    year_end = date(selected_year, 12, 31)
    for l in st.session_state.leaves:
        actual_start = max(l['startDate'], year_start)
        actual_end = min(l['endDate'], year_end)
        if actual_start <= actual_end:
            if l['employeeId'] in leave_days:
                leave_days[l['employeeId']] += (actual_end - actual_start).days + 1
                
    table_data = [{"Ονοματεπώνυμο": emp['name'], "Θέση": emp['position'], "Κατάσταση": emp.get('status', 'Ενεργός'), "Ημέρες Άδειας": leave_days[emp['id']]} for emp in st.session_state.employees]
    st.write(f"### Συνολικές Ημέρες Άδειας για το έτος: {selected_year}")
    st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)

# --- VIEW: WORK HOURS ---
elif menu == "Ώρες Εργασιών":
    st.title("⏱️ Ώρες Εργασιών ανά Μήνα")
    months = ["Ιανουάριος", "Φεβρουάριος", "Μάρτιος", "Απρίλιος", "Μάιος", "Ιούνιος", "Ιούλιος", "Αύγουστος", "Σεπτέμβριος", "Οκτώβριος", "Νοέμβριος", "Δεκέμβριος"]
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1: selected_month_name = st.selectbox("Επιλογή Μήνα", months, index=date.today().month - 1)
    selected_month = months.index(selected_month_name) + 1
    with col2: selected_year = st.selectbox("Επιλογή Έτους", list(range(2020, 2036)), index=list(range(2020, 2036)).index(date.today().year))
    st.divider()
    
    employee_hours = {emp['id']: 0.0 for emp in st.session_state.employees}
    for a in st.session_state.assignments:
        d = a['date']
        if d.month == selected_month and d.year == selected_year:
            try:
                start_h, start_m = map(int, str(a['startTime'])[:5].split(':'))
                end_h, end_m = map(int, str(a['endTime'])[:5].split(':'))
                delta_hours = (end_h - start_h) + (end_m - start_m) / 60.0
                if a['employeeId'] in employee_hours: employee_hours[a['employeeId']] += delta_hours
            except: pass
            
    table_data = [{"Ονοματεπώνυμο": emp['name'], "Θέση": emp['position'], "Κατάσταση": emp.get('status', 'Ενεργός'), "Συνολικές Ώρες": round(employee_hours[emp['id']], 2)} for emp in st.session_state.employees]
    st.write(f"### Σύνολο Ωρών για: {selected_month_name} {selected_year}")
    st.dataframe(pd.DataFrame(table_data).style.format({"Συνολικές Ώρες": "{:.2f}"}), use_container_width=True, hide_index=True)

# --- VIEW: RECURRING ---
elif menu == "Επαναλαμβανόμενες Εργασίες":
    st.title("🔄 Επαναλαμβανόμενες Εργασίες")
    if not is_full_admin:
        st.info("🔒 Έχετε δικαιώματα μόνο για ανάγνωση.")
    else:
        st.write("Προσθέστε ή επεξεργαστείτε εργασίες που επαναλαμβάνονται «για πάντα» (επεκτείνονται αυτόματα κάθε χρόνο).")
        tab_new, tab_edit = st.tabs(["➕ Νέα Καταχώρηση", "⚙️ Διαχείριση/Επεξεργασία Υπαρχουσών"])
        if "rec_reset_counter" not in st.session_state: st.session_state.rec_reset_counter = 0
        rc = st.session_state.rec_reset_counter
        
        with tab_new:
            r_col1, r_col2 = st.columns(2)
            with r_col1:
                r_proj = st.selectbox("Επιλογή Έργου (Από Λίστα)", options=[p['id'] for p in st.session_state.projects], format_func=utils.get_project_name, key=f"new_r_proj_{rc}")
                r_custom_proj_name = st.text_input("Ή πληκτρολογήστε Νέο Έργο", key=f"new_r_custom_proj_{rc}")
                c_r_color, c_r_notes = st.columns(2)
                with c_r_color: r_color = st.selectbox("Χρώμα Μπάρας", options=list(utils.BASIC_COLORS.keys()), key=f"new_r_color_{rc}")
                with c_r_notes: r_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", key=f"new_r_notes_{rc}")
                r_type = st.selectbox("Συχνότητα Επανάληψης", ["Εβδομαδιαία", "Μηνιαία", "Επιλεγμένες Μέρες Εβδομάδας"], key=f"new_r_type_{rc}")
                
                r_emps, selected_weekdays, selected_weekdays_data = [], [], {}
                if r_type in ["Εβδομαδιαία", "Μηνιαία"]:
                    r_emps = st.multiselect("Προσωπικό (Μόνο Ενεργοί)", options=active_employee_ids, format_func=utils.get_employee_name, key=f"new_r_emps_{rc}")
                else:
                    st.markdown("**Επιλέξτε Μέρες και Προσωπικό (ξεχωριστά ανά μέρα):**")
                    day_names = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
                    for i, d_name in enumerate(day_names):
                        c_chk, c_emp = st.columns([1, 3])
                        if c_chk.checkbox(d_name, value=(i==0), key=f"new_chk_{i}_{rc}"):
                            selected_weekdays.append(d_name)
                            selected_weekdays_data[d_name] = c_emp.multiselect(f"Προσωπικό ({d_name})", options=active_employee_ids, format_func=utils.get_employee_name, key=f"new_r_emps_day_{i}_{rc}", label_visibility="collapsed")
                            
            with r_col2:
                r_start_date = st.date_input("Από Ημερομηνία", date.today(), key=f"new_r_start_date_{rc}")
                r_arr, r_start, r_end = st.columns(3)
                with r_arr:
                    use_arr_rec = st.checkbox("Προσέλευση;", key=f"chk_arr_rec_{rc}")
                    r_arrival_time = st.time_input("Ώρα Προσέλευσης", value=datetime.strptime("08:00", "%H:%M").time(), key=f"new_r_arr_{rc}", disabled=not use_arr_rec)
                with r_start: r_start_time = st.time_input("Έναρξη Ώρας", value=datetime.strptime("09:00", "%H:%M").time(), key=f"new_r_start_time_{rc}")
                with r_end: r_end_time = st.time_input("Λήξη Ώρας", value=datetime.strptime("17:00", "%H:%M").time(), key=f"new_r_end_time_{rc}")
                
            st.info("ℹ️ Η εργασία θα δημιουργήσει βάρδιες για 1 χρόνο. Στη συνέχεια θα επεκτείνεται αυτόματα.")
            col_btn1, col_btn2 = st.columns([1, 1])
            with col_btn1: submit_r = st.button("Καταχώρηση Επαναλαμβανόμενης Εργασίας", type="primary", key="btn_new_r", use_container_width=True)
            with col_btn2:
                if st.button("🧹 Καθαρισμός", key="btn_clear_r", use_container_width=True):
                    st.session_state.rec_reset_counter += 1
                    st.rerun()
                    
            if submit_r:
                str_arrival = r_arrival_time.strftime("%H:%M") if use_arr_rec else ""
                str_start, str_end = r_start_time.strftime("%H:%M"), r_end_time.strftime("%H:%M")
                if str_start >= str_end: st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                elif r_type == "Επιλεγμένες Μέρες Εβδομάδας" and not selected_weekdays: st.error("Επιλέξτε τουλάχιστον μία μέρα της εβδομάδας.")
                elif not r_custom_proj_name.strip() and not r_proj: st.error("Παρακαλώ επιλέξτε ή πληκτρολογήστε ένα Έργο.")
                else:
                    actions = []
                    if r_custom_proj_name.strip():
                        final_r_proj_id = str(uuid.uuid4())
                        new_p = {'id': final_r_proj_id, 'name': r_custom_proj_name.strip(), 'color': utils.BASIC_COLORS[r_color]}
                        st.session_state.projects.append(new_p)
                        utils.db_insert('projects', new_p, track=False)
                        actions.append({'type': 'insert', 'table': 'projects', 'records': [new_p]})
                    else: final_r_proj_id = r_proj
                    
                    pattern_id = str(uuid.uuid4())
                    r_end_date = r_start_date + timedelta(days=365)
                    dates_to_assign = []
                    curr_date = r_start_date
                    day_map = {"Δευτέρα": 0, "Τρίτη": 1, "Τετάρτη": 2, "Πέμπτη": 3, "Παρασκευή": 4, "Σάββατο": 5, "Κυριακή": 6}
                    day_map_inv = {v: k for k, v in day_map.items()}
                    selected_weekday_ints = [day_map[d] for d in selected_weekdays] if selected_weekdays else []
                    
                    new_assignments_batch = []
                    with st.spinner('Υπολογισμός και καταχώρηση βαρδιών...'):
                        while curr_date <= r_end_date:
                            if r_type == "Εβδομαδιαία":
                                dates_to_assign.append(curr_date)
                                curr_date += timedelta(days=7)
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
                            emps_to_process = selected_weekdays_data.get(day_map_inv[d.weekday()], []) if r_type == "Επιλεγμένες Μέρες Εβδομάδας" else r_emps
                            emps_to_process = emps_to_process if emps_to_process else [""]
                            for eid in emps_to_process:
                                if eid:
                                    emp_name = utils.get_employee_name(eid)
                                    if utils.is_on_leave(eid, d):
                                        conflict_count += 1
                                        conflict_details.append(f"{d.strftime('%d/%m/%Y')} - {emp_name} (Άδεια)")
                                    else:
                                        adj_start, adj_end, is_conflict, msg = utils.check_and_resolve_conflict(eid, d, str_start, str_end)
                                        if is_conflict:
                                            conflict_count += 1
                                            conflict_details.append(f"{d.strftime('%d/%m/%Y')} - {emp_name} (Επικάλυψη)")
                                        else:
                                            new_assign = {'id': str(uuid.uuid4()), 'recurring_id': pattern_id, 'employeeId': eid, 'projectId': final_r_proj_id, 'date': d, 'arrivalTime': str_arrival, 'startTime': adj_start, 'endTime': adj_end, 'colorName': r_color, 'colorHex': utils.BASIC_COLORS[r_color], 'notes': r_notes, 'is_cancelled': False, 'cancel_reason': ""}
                                            new_assignments_batch.append(new_assign)
                                            success_count += 1
                                else:
                                    new_assign = {'id': str(uuid.uuid4()), 'recurring_id': pattern_id, 'employeeId': "", 'projectId': final_r_proj_id, 'date': d, 'arrivalTime': str_arrival, 'startTime': str_start, 'endTime': str_end, 'colorName': r_color, 'colorHex': utils.BASIC_COLORS[r_color], 'notes': r_notes, 'is_cancelled': False, 'cancel_reason': ""}
                                    new_assignments_batch.append(new_assign)
                                    success_count += 1
                                    
                        final_employee_ids = selected_weekdays_data if r_type == "Επιλεγμένες Μέρες Εβδομάδας" else r_emps
                        new_pattern = {'id': pattern_id, 'projectId': final_r_proj_id, 'employeeIds': final_employee_ids, 'colorName': r_color, 'notes': r_notes, 'type': r_type, 'weekdays': selected_weekdays, 'arrivalTime': str_arrival, 'startDate': r_start_date, 'startTime': str_start, 'endTime': str_end}
                        st.session_state.recurring_patterns.append(new_pattern)
                        utils.db_insert('recurring_patterns', new_pattern, track=False)
                        actions.append({'type': 'insert', 'table': 'recurring_patterns', 'records': [new_pattern]})
                        
                        if new_assignments_batch:
                            st.session_state.assignments.extend(new_assignments_batch)
                            if utils.supabase:
                                def insert_b(b):
                                    chunk_size = 500
                                    for i in range(0, len(b), chunk_size):
                                        try: utils.supabase.table('assignments').insert(utils.serialize_dates(b[i:i+chunk_size])).execute()
                                        except: pass
                                threading.Thread(target=insert_b, args=(new_assignments_batch,), daemon=True).start()
                            actions.append({'type': 'insert', 'table': 'assignments', 'records': new_assignments_batch})
                            
                    utils.add_transaction(actions)
                    st.session_state.rec_reset_counter += 1
                    if success_count > 0: st.success(f"Επιτυχής δημιουργία {success_count} βαρδιών! Η σελίδα ανανεώνεται..."); time.sleep(1.5); st.rerun()
                    if conflict_count > 0:
                        st.warning(f"Παραλείφθηκαν {conflict_count} αναθέσεις λόγω συγκρούσεων.")
                        with st.expander("Δείτε τις συγκρούσεις"):
                            for c in conflict_details: st.write(f"⚠️ {c}")

        with tab_edit:
            if not st.session_state.recurring_patterns: st.info("Δεν υπάρχουν ενεργές επαναλαμβανόμενες εργασίες.")
            else:
                pattern_options = {p['id']: f"{utils.get_project_info(p['projectId'])['name'] if utils.get_project_info(p['projectId']) else 'Άγνωστο Έργο'} | {p['type']} | Από: {p['startDate'].strftime('%d/%m/%Y')} ({p['startTime']}-{p['endTime']})" for p in st.session_state.recurring_patterns}
                selected_pattern_id = st.selectbox("Επιλέξτε Σειρά Εργασιών", options=list(pattern_options.keys()), format_func=lambda x: pattern_options[x])
                
                if selected_pattern_id:
                    pat = next(p for p in st.session_state.recurring_patterns if p['id'] == selected_pattern_id)
                    with st.form("edit_recurring_form", clear_on_submit=True):
                        st.warning("⚠️ Προσοχή: Η αποθήκευση αλλαγών θα επαναδημιουργήσει **ΟΛΕΣ** τις βάρδιες αυτής της σειράς. Τυχόν μεμονωμένες αλλαγές που κάνατε στο Ταμπλό θα χαθούν.")
                        
                        col_b1, col_b2 = st.columns(2)
                        with col_b1: save_rec = st.form_submit_button("💾 Αποθήκευση Αλλαγών", type="primary")
                        with col_b2: del_rec = st.form_submit_button("🗑️ Διαγραφή ΟΛΗΣ της σειράς")
                        
                        if del_rec:
                            old_assigns = [a for a in st.session_state.assignments if a.get('recurring_id') == selected_pattern_id]
                            st.session_state.assignments = [a for a in st.session_state.assignments if a.get('recurring_id') != selected_pattern_id]
                            st.session_state.recurring_patterns = [p for p in st.session_state.recurring_patterns if p['id'] != selected_pattern_id]
                            utils.db_delete_in('assignments', 'id', [a['id'] for a in old_assigns], track=False)
                            utils.db_delete('recurring_patterns', 'id', selected_pattern_id, track=False)
                            utils.add_transaction([{'type': 'delete', 'table': 'assignments', 'records': old_assigns}, {'type': 'delete', 'table': 'recurring_patterns', 'records': [dict(pat)]}])
                            st.rerun()

# --- VIEW: EVALUATIONS ---
elif menu == "Αξιολόγηση Προσωπικού":
    st.markdown("""<style>div[data-testid="stFormSubmitButton"] {position: fixed !important; bottom: 40px !important; right: 40px !important; z-index: 99999 !important;} div[data-testid="stFormSubmitButton"] button {box-shadow: 0px 8px 24px rgba(0, 0, 0, 0.4) !important; border: 3px solid #16a34a !important; border-radius: 50px !important; font-weight: bold !important; padding: 15px 30px !important; background-color: white !important; color: #16a34a !important;} div[data-testid="stForm"] {padding-bottom: 120px !important;}</style>""", unsafe_allow_html=True)
    st.title("⭐ Αξιολόγηση Προσωπικού")
    
    months = ["Ιανουάριος", "Φεβρουάριος", "Μάρτιος", "Απρίλιος", "Μάιος", "Ιούνιος", "Ιούλιος", "Αύγουστος", "Σεπτέμβριος", "Οκτώβριος", "Νοέμβριος", "Δεκέμβριος"]
    col1, col2 = st.columns(2)
    with col1: selected_month_name = st.selectbox("Επιλογή Μήνα", months, index=date.today().month - 1, key="eval_month")
    eval_month = months.index(selected_month_name) + 1
    with col2: eval_year = st.selectbox("Επιλογή Έτους", list(range(2020, 2036)), index=list(range(2020, 2036)).index(date.today().year), key="eval_year")
    st.divider()
    
    month_evals = [e for e in st.session_state.evaluations if e['month'] == eval_month and e['year'] == eval_year]
    if month_evals:
        for ev in month_evals: ev['avg'] = (ev.get('cooperation', 0) + ev.get('willingness', 0) + ev.get('behavior', 0)) / 3.0
        max_avg = max([ev['avg'] for ev in month_evals])
        top_evals = [ev for ev in month_evals if ev['avg'] == max_avg]
        st.markdown("### 🏆 Υπάλληλος του Μήνα")
        if max_avg > 0:
            for ev in top_evals: st.success(f"🏅 **{utils.get_employee_name(ev['employeeId'])}** — Υψηλότερος Μέσος Όρος: **{max_avg:.2f} / 5**")
        else: st.info("Οι βαθμολογίες για αυτόν τον μήνα είναι στο 0.")
    else: st.info("Δεν υπάρχουν ακόμα αποθηκευμένες βαθμολογίες για τον επιλεγμένο μήνα.")
    st.divider()
    
    col_title, col_reset = st.columns([3, 1])
    with col_title: st.write("### Φόρμα Βαθμολόγησης")
    with col_reset:
        if is_full_admin:
            if st.button("🔄 Επαναφορά Βαθμολογιών", use_container_width=True):
                evals_to_delete = [e['id'] for e in month_evals]
                if evals_to_delete:
                    st.session_state.evaluations = [e for e in st.session_state.evaluations if e['id'] not in evals_to_delete]
                    utils.db_delete_in('evaluations', 'id', evals_to_delete, deleted_records=month_evals)
                    st.rerun()

    if not is_full_admin: st.info("🔒 Έχετε δικαιώματα μόνο για ανάγνωση.")
    with st.form("evaluations_form"):
        hc1, hc2, hc3, hc4, hc5 = st.columns([2, 1.5, 1.5, 1.5, 1])
        hc1.write("**Ονοματεπώνυμο**"); hc2.write("**Συνεργασία**"); hc3.write("**Προθυμία**"); hc4.write("**Συμπεριφορά**"); hc5.write("**Μ.Ό.**")
        st.markdown("---")
        
        eval_inputs = {}
        is_readonly = not is_full_admin
        for emp in active_employee_ids:
            emp_info = next(e for e in st.session_state.employees if e['id'] == emp)
            existing_eval = next((e for e in month_evals if e['employeeId'] == emp), None)
            dc = existing_eval['cooperation'] if existing_eval else 3
            dw = existing_eval['willingness'] if existing_eval else 3
            db = existing_eval['behavior'] if existing_eval else 3
            
            c1, c2, c3, c4, c5 = st.columns([2, 1.5, 1.5, 1.5, 1])
            c1.write(f"\n**{emp_info['name']}**")
            eval_inputs[emp] = {
                'coop': c2.selectbox("Συνεργασία", [1, 2, 3, 4, 5], index=dc - 1, key=f"coop_{emp}", label_visibility="collapsed", disabled=is_readonly),
                'will': c3.selectbox("Προθυμία", [1, 2, 3, 4, 5], index=dw - 1, key=f"will_{emp}", label_visibility="collapsed", disabled=is_readonly),
                'behav': c4.selectbox("Συμπεριφορά", [1, 2, 3, 4, 5], index=db - 1, key=f"behav_{emp}", label_visibility="collapsed", disabled=is_readonly),
                'existing_id': existing_eval['id'] if existing_eval else None
            }
            c5.write(f"\n**{((dc + dw + db) / 3.0):.2f}**")
            
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
                            ev_to_update.update({'cooperation': data['coop'], 'willingness': data['will'], 'behavior': data['behav']})
                            payload = {k: v for k, v in ev_to_update.items() if k != 'avg'}
                            old_payload = {k: v for k, v in old_ev.items() if k != 'avg'}
                            utils.db_update('evaluations', data['existing_id'], payload, track=False)
                            actions.append({'type': 'update', 'table': 'evaluations', 'old_records': [old_payload], 'new_records': [payload]})
                            updates_made = True
                    else:
                        new_eval = {'id': str(uuid.uuid4()), 'employeeId': emp_id, 'month': eval_month, 'year': eval_year, 'cooperation': data['coop'], 'willingness': data['will'], 'behavior': data['behav']}
                        st.session_state.evaluations.append(new_eval)
                        utils.db_insert('evaluations', new_eval, track=False)
                        actions.append({'type': 'insert', 'table': 'evaluations', 'records': [new_eval]})
                        updates_made = True
            if actions: utils.add_transaction(actions)
            if updates_made: st.success("Οι αξιολογήσεις αποθηκεύτηκαν επιτυχώς!"); st.rerun()

# --- VIEW: AUDIT LOG ---
elif menu == "Καταγραφή Κινήσεων":
    st.title("🛡️ Καταγραφή Κινήσεων (Audit Log)")
    col_b1, col_b2 = st.columns([1, 4])
    with col_b1:
        if st.button("🔄 Ανανέωση Ιστορικού", use_container_width=True): st.session_state.global_db_ts = "force_refresh"; st.rerun()
    with col_b2:
        if st.button("🗑️ Καθαρισμός Ιστορικού", type="primary"):
            if utils.supabase and st.session_state.activity_logs:
                try:
                    log_ids = [l['id'] for l in st.session_state.activity_logs]
                    for i in range(0, len(log_ids), 500): utils.supabase.table('activity_logs').delete().in_('id', log_ids[i:i+500]).execute()
                    st.session_state.activity_logs = []
                    st.session_state.global_db_ts = "force_refresh"
                    st.success("Το ιστορικό καθαρίστηκε!"); time.sleep(1); st.rerun()
                except Exception as e: st.error(f"Σφάλμα καθαρισμού: {e}")
                
    if not st.session_state.activity_logs: st.info("Δεν υπάρχουν καταγεγραμμένες κινήσεις ακόμα.")
    else:
        sorted_logs = sorted(st.session_state.activity_logs, key=lambda x: x.get('timestamp', ''), reverse=True)
        TABLE_NAMES_GR = {'employees': 'Προσωπικό', 'projects': 'Έργα', 'assignments': 'Βάρδιες', 'leaves': 'Άδειες', 'recurring_patterns': 'Επαν. Εργασίες', 'evaluations': 'Αξιολογήσεις'}
        log_data = []
        for log in sorted_logs:
            try: dt_str = datetime.fromisoformat(log.get('timestamp', '')).strftime("%d/%m/%Y %H:%M:%S")
            except: dt_str = log.get('timestamp', '')
            log_data.append({"Ημερομηνία/Ώρα": dt_str, "Χρήστης": log.get('username', '-'), "Ενέργεια": log.get('action_type', '-'), "Πίνακας": TABLE_NAMES_GR.get(log.get('table_name', ''), log.get('table_name', '-')), "Λεπτομέρειες": utils.parse_old_log_details(log.get('table_name', ''), log.get('details', '-'))})
        st.dataframe(pd.DataFrame(log_data), use_container_width=True, hide_index=True)
