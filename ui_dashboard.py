import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta
import config
import utils
import uuid
import re

def render_top_nav(go_prev_week, go_next_week, go_to_today):
    col_nav1, col_date, col_nav2, col_today, col_zoom, col_pres = st.columns([1, 2, 1, 1, 2, 2.5])
    with col_nav1:
        st.write("")
        st.button("⬅️ Προηγούμενη", on_click=go_prev_week, use_container_width=True)
    with col_date:
        # --- Η ΑΠΟΛΥΤΗ ΛΥΣΗ ΓΙΑ ΤΟ RESET ΤΗΣ ΕΒΔΟΜΑΔΑΣ ---
        # Τροφοδοτούμε ρητά το ημερολόγιο με την αποθηκευμένη ημερομηνία (value)
        # Έτσι η φόρμα δεν μπορεί ποτέ να του κάνει "reset" εν αγνοία μας.
        selected_date = st.date_input(
            "Επιλογή Εβδομάδας", 
            value=st.session_state.view_week_date
        )
        
        # Αν ο χρήστης αλλάξει την ημερομηνία χειροκίνητα στο ημερολόγιο:
        if selected_date != st.session_state.view_week_date:
            st.session_state.view_week_date = selected_date
            st.rerun()
            
        start_of_week = st.session_state.view_week_date - timedelta(days=st.session_state.view_week_date.weekday())
    with col_nav2:
        st.write("")
        st.button("Επόμενη ➡️", on_click=go_next_week, use_container_width=True)
    with col_today:
        st.write("")
        st.button("📅 Σήμερα", on_click=go_to_today, use_container_width=True)
    with col_zoom:
        zoom_level = st.slider("🔍 Ζουμ Διαγράμματος (%)", min_value=50, max_value=200, value=100, step=5)
    with col_pres:
        st.write("")
        st.write("")
        presentation_mode = st.checkbox("📺 Λειτουργία Πλήρους Προβολής")
    return selected_date, start_of_week, zoom_level, presentation_mode

def render_export_section(export_data, start_of_week):
    hint_text = "💡 *Συμβουλές:* **1)** Κλικ σε μπάρα για επεξεργασία. **2)** Σύρετε το διάγραμμα (Pan) δεξιά-αριστερά για τον χρόνο. **3)** Σύρετε την μπάρα κύλισης πάνω-κάτω για να δείτε όλες τις μέρες."
    if export_data:
        col_hint, col_btn = st.columns([3, 1])
        with col_hint: st.caption(hint_text)
        with col_btn:
            df_export = pd.DataFrame(export_data)
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_export.to_excel(writer, index=False, sheet_name='Πρόγραμμα')
            st.download_button(
                label="📥 Εξαγωγή (Excel)", data=buffer.getvalue(),
                file_name=f"Gantt_Programma_{start_of_week.strftime('%d_%m_%Y')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
    else:
        st.caption(hint_text)

def render_quick_add_form(selected_date, active_employee_ids):
    st.subheader("➕ Νέα Τοποθέτηση")
    if "qa_rc" not in st.session_state: st.session_state.qa_rc = 0
    qa_rc = st.session_state.qa_rc
    
    with st.form("quick_add", clear_on_submit=True):
        c_date, c_dur = st.columns(2)
        with c_date:
            add_date = st.date_input("Ημερομηνία", value=selected_date, key=f"qa_date_{qa_rc}")
        with c_dur:
            duration_days = st.number_input("Διάρκεια (Συνεχόμενες Ημέρες)", min_value=1, max_value=365, value=1, step=1, key=f"qa_dur_{qa_rc}")
            
        proj_choice = st.selectbox("Επιλογή Έργου (Από Λίστα)", options=[p['id'] for p in st.session_state.projects], format_func=utils.get_project_name, key=f"qa_proj_{qa_rc}")
        custom_proj_name = st.text_input("Ή πληκτρολογήστε Νέο Έργο (Αν συμπληρωθεί, αγνοεί την παραπάνω λίστα)", key=f"qa_cproj_{qa_rc}")
        emp_choices = st.multiselect("Προσωπικό (Προαιρετικό - Μόνο Ενεργοί)", options=active_employee_ids, format_func=utils.get_employee_name, key=f"qa_emps_{qa_rc}")
        
        c_color, c_notes = st.columns(2)
        with c_color: 
            color_choice = st.selectbox("Χρώμα Μπάρας", options=list(config.BASIC_COLORS.keys()), key=f"qa_color_{qa_rc}")
        with c_notes: 
            add_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", key=f"qa_notes_{qa_rc}")
            
        c_arr, c_start, c_end = st.columns(3)
        with c_arr:
            use_arr = st.checkbox("Προσέλευση;", key=f"chk_arr_{qa_rc}")
            t_arrival = st.time_input("Ώρα Προσέλευσης", value=datetime.strptime("08:00", "%H:%M").time(), key=f"qa_arrival_{qa_rc}")
        with c_start:
            t_start = st.time_input("Έναρξη", value=datetime.strptime("09:00", "%H:%M").time(), key=f"qa_start_{qa_rc}")
        with c_end:
            t_end = st.time_input("Λήξη", value=datetime.strptime("17:00", "%H:%M").time(), key=f"qa_end_{qa_rc}")
        
        if st.form_submit_button("Καταχώρηση"):
            return {
                "add_date": add_date, "duration_days": duration_days, "proj_choice": proj_choice, "custom_proj_name": custom_proj_name,
                "emp_choices": emp_choices, "color_choice": color_choice, "add_notes": add_notes,
                "use_arr": use_arr, "t_arrival": t_arrival, "t_start": t_start, "t_end": t_end
            }
    return None

def render_edit_form(wk_groups, clicked_key, active_employee_ids):
    st.subheader("✏️ Επεξεργασία Μπάρας της Εβδομάδας")
    if not wk_groups:
        st.info("Δεν υπάρχουν μπάρες για επεξεργασία αυτή την εβδομάδα.")
        return None
        
    group_keys = list(wk_groups.keys())
    group_keys.sort(key=lambda k: (wk_groups[k]['Date'], wk_groups[k]['StartTime']))
    default_idx = 0
    if clicked_key and clicked_key in group_keys:
        default_idx = group_keys.index(clicked_key) + 1
        
    selected_key = st.selectbox(
        "Επιλέξτε Μπάρα (Ημέρα & Έργο)", options=[""] + group_keys, index=default_idx,
        format_func=lambda x: "Επιλέξτε..." if x == "" else f"{wk_groups[x]['Date'].strftime('%d/%m')} - {wk_groups[x]['Project']} ({wk_groups[x]['StartTime']}-{wk_groups[x]['EndTime']})"
    )
    
    if selected_key != "":
        target_group = wk_groups[selected_key]
        st.markdown("⚡ **Γρήγορη Μετακίνηση** (Αντί για Drag & Drop)")
        qm_c1, qm_c2, qm_c3, qm_c4 = st.columns(4)
        move_m_day = qm_c1.button("⬅️ -1 Μέρα", use_container_width=True)
        move_p_day = qm_c2.button("➡️ +1 Μέρα", use_container_width=True)
        move_m_hour = qm_c3.button("🔼 -1 Ώρα", use_container_width=True)
        move_p_hour = qm_c4.button("🔽 +1 Ώρα", use_container_width=True)
        
        if any([move_m_day, move_p_day, move_m_hour, move_p_hour]):
            delta_days = -1 if move_m_day else (1 if move_p_day else 0)
            delta_hours = -1 if move_m_hour else (1 if move_p_hour else 0)
            return {"action": "move", "target_group": target_group, "delta_days": delta_days, "delta_hours": delta_hours}

        with st.form("quick_edit"):
            edit_date = st.date_input("Αλλαγή Ημερομηνίας", value=target_group['Date'])
            proj_ids = [p['id'] for p in st.session_state.projects]
            default_proj_idx = proj_ids.index(target_group['ProjectId']) if target_group['ProjectId'] in proj_ids else 0
            edit_proj = st.selectbox("Αλλαγή Έργου (Από Λίστα)", options=proj_ids, index=default_proj_idx, format_func=utils.get_project_name)
            edit_custom_proj_name = st.text_input("Ή πληκτρολογήστε Νέο Έργο (προαιρετικό)")
            
            valid_emp_ids = [eid for eid in target_group['EmployeeIds'] if eid]
            
            for note in target_group.get('Notes_List', []):
                matches = re.findall(r'\[(?:Άδεια|Εμπλοκή):\s*(.*?)\]', note)
                for match in matches:
                    name_to_find = match.strip()
                    for emp in st.session_state.employees:
                        if emp['name'].strip() == name_to_find:
                            if emp['id'] not in valid_emp_ids:
                                valid_emp_ids.append(emp['id'])
                            break

            edit_options = list(set(active_employee_ids + valid_emp_ids))
            edit_emps = st.multiselect("Αλλαγή Προσωπικού (Προαιρετικό)", options=edit_options, default=valid_emp_ids, format_func=utils.get_employee_name)
            
            e_color_col, e_notes_col = st.columns(2)
            with e_color_col:
                default_color_idx = list(config.BASIC_COLORS.keys()).index(target_group['ColorName']) if target_group['ColorName'] in config.BASIC_COLORS else 0
                edit_color = st.selectbox("Αλλαγή Χρώματος", options=list(config.BASIC_COLORS.keys()), index=default_color_idx)
            with e_notes_col:
                clean_note = re.sub(r'\[(?:Άδεια|Εμπλοκή):.*?\]', '', target_group.get('Notes', ''))
                clean_note = re.sub(r'\s*\|\s*', ' ', clean_note).strip()
                edit_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", value=clean_note)
                
            e_arr, e_start, e_end = st.columns(3)
            existing_arr = target_group.get('ArrivalTime', '')
            with e_arr:
                use_arr_edit = st.checkbox("Με Προσέλευση", value=bool(existing_arr), key="edit_use_arr")
                def_arr = datetime.strptime(existing_arr, "%H:%M").time() if existing_arr else datetime.strptime(str(target_group['StartTime'])[:5], "%H:%M").time()
                new_t_arrival = st.time_input("Ώρα Προσ.", value=def_arr, key="edit_arrival_time")
            with e_start:
                new_t_start = st.time_input("Νέα Έναρξη", value=datetime.strptime(str(target_group['StartTime'])[:5], "%H:%M").time())
            with e_end:
                new_t_end = st.time_input("Νέα Λήξη", value=datetime.strptime(str(target_group['EndTime'])[:5], "%H:%M").time())
                
            st.markdown("---")
            st.write("🛑 **Ακύρωση / Διαγραφή Βάρδιας (Διαγράμμιση)**")
            c_canc1, c_canc2 = st.columns([1, 2])
            with c_canc1:
                e_is_cancelled = st.checkbox("Επισήμανση ως Ακυρωμένη", value=target_group.get('is_cancelled', False))
            with c_canc2:
                e_cancel_reason = st.text_input("Λόγος Ακύρωσης (Συμπληρώστε αν ακυρώνετε)", value=target_group.get('cancel_reason', ""))
                
            st.markdown("---")
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                save_edit = st.form_submit_button("💾 Αποθήκευση")
            with col_btn2:
                del_edit = st.form_submit_button("🗑️ Οριστική Διαγραφή Μπάρας")
                
            if del_edit:
                return {"action": "delete", "target_group": target_group}
                
            if save_edit:
                return {
                    "action": "edit", "target_group": target_group, "edit_date": edit_date, "edit_proj": edit_proj,
                    "edit_custom_proj_name": edit_custom_proj_name, "edit_emps": edit_emps, "edit_color": edit_color,
                    "edit_notes": edit_notes, "use_arr_edit": use_arr_edit, "new_t_arrival": new_t_arrival,
                    "new_t_start": new_t_start, "new_t_end": new_t_end, "e_is_cancelled": e_is_cancelled,
                    "e_cancel_reason": e_cancel_reason
                }
    return None
