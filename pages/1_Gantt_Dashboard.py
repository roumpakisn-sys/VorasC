import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, date, timedelta
import gc
import textwrap

# Κάνουμε import τον "κινητήρα" μας
import database as db

# ==========================================
# 1. ΕΛΕΓΧΟΣ ΠΡΟΣΒΑΣΗΣ & STYLING
# ==========================================
if not st.session_state.get('current_user'):
    st.warning("⚠️ Παρακαλώ συνδεθείτε από την αρχική σελίδα για να δείτε το ταμπλό.")
    st.stop()

st.title("📊 Ταμπλό Gantt & Βάρδιες")
st.write("Σύνδεση με την υπάρχουσα βάση δεδομένων: Ενεργή (Legacy Mode)")
st.write("---")

# Βασικά χρώματα συστήματος
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

# ==========================================
# 2. ΒΟΗΘΗΤΙΚΕΣ ΣΥΝΑΡΤΗΣΕΙΣ ΠΛΟΗΓΗΣΗΣ
# ==========================================
def go_prev_week():
    st.session_state.view_week_date -= timedelta(days=7)

def go_next_week():
    st.session_state.view_week_date += timedelta(days=7)

def go_to_today():
    st.session_state.view_week_date = date.today()

if 'view_week_date' not in st.session_state:
    st.session_state.view_week_date = date.today()

# ==========================================
# 3. ΦΟΡΜΑ ΓΡΗΓΟΡΗΣ ΚΑΤΑΧΩΡΗΣΗΣ
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
                sel_emp = st.selectbox("Εργαζόμενος", [""] + emp_names)
                start_d = st.date_input("Ημερομηνία", st.session_state.view_week_date)
            with col2:
                sel_proj = st.selectbox("Έργο", proj_names)
                t_start = st.time_input("Έναρξη", datetime.strptime("09:00", "%H:%M").time())
            with col3:
                t_end = st.time_input("Λήξη", datetime.strptime("17:00", "%H:%M").time())
                notes = st.text_input("Σημειώσεις")
            
            submit = st.form_submit_button("Καταχώρηση")
            
            if submit and sel_proj:
                try:
                    emp_id = next((e['id'] for e in emps if e['name'] == sel_emp), None)
                    proj_id = next(p['id'] for p in projs if p['name'] == sel_proj)
                    proj_info = next(p for p in projs if p['id'] == proj_id)
                    
                    new_data = {
                        'employeeId': emp_id,
                        'projectId': proj_id,
                        'startTime': t_start.strftime("%H:%M"),
                        'endTime': t_end.strftime("%H:%M"),
                        'date': start_d.isoformat(),
                        'notes': notes,
                        'colorHex': proj_info.get('color', '#4a86e8'),
                        'is_cancelled': False
                    }
                    
                    supabase = db.init_supabase()
                    res = supabase.table('assignments').insert(new_data).execute()
                    
                    if res.data:
                        db.log_activity("ΠΡΟΣΘΗΚΗ", "assignments", f"Νέα βάρδια στο έργο {sel_proj}", st.session_state.current_user)
                        st.success("Η βάρδια καταχωρήθηκε!")
                        db.fetch_paginated.clear() 
                        st.rerun()
                except Exception as e:
                    st.error(f"Σφάλμα: {e}")

# ==========================================
# 4. ΔΙΑΓΡΑΜΜΑ GANTT (EXCEL-STYLE / PDF REPLICA)
# ==========================================
@st.fragment
def render_gantt_chart():
    # Ρυθμίσεις Εβδομάδας
    selected_date = st.session_state.view_week_date
    start_of_week = selected_date - timedelta(days=selected_date.weekday())
    
    col_nav1, col_date, col_nav2, col_today = st.columns([1, 2, 1, 1])
    with col_nav1: st.button("⬅️ Προηγούμενη", on_click=go_prev_week, use_container_width=True)
    with col_date: st.date_input("Εβδομάδα από:", value=start_of_week, key="week_picker", disabled=True)
    with col_nav2: st.button("Επόμενη ➡️", on_click=go_next_week, use_container_width=True)
    with col_today: st.button("📅 Σήμερα", on_click=go_to_today, use_container_width=True)

    # Φόρτωση Δεδομένων
    assignments = db.fetch_paginated('assignments')
    employees = db.fetch_paginated('employees')
    projects = db.fetch_paginated('projects')
    leaves = db.fetch_paginated('leaves')
    
    if not assignments:
        st.info("Δεν βρέθηκαν βάρδιες για προβολή.")
        return

    # Προετοιμασία DataFrames
    df_assign = pd.DataFrame(assignments)
    df_emp = pd.DataFrame(employees)
    df_proj = pd.DataFrame(projects)
    
    emp_map = {e['id']: e['name'] for e in employees}
    proj_map = {p['id']: p for p in projects}

    # Λογική Δημιουργίας Γραφήματος (Από PDF)
    chart_data = []
    y_category_order = []
    tickvals_map = {}
    color_map = {}
    day_names_gr = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]

    for i in range(7):
        curr_date = start_of_week + timedelta(days=i)
        day_str = f"{day_names_gr[i]} {curr_date.strftime('%d/%m')}"
        curr_date_iso = curr_date.isoformat()
        
        # 1. Εύρεση Αδειών Ημέρας
        leaves_today = [l for l in leaves if l['startDate'] <= curr_date_iso <= l['endDate']]
        leaves_text = "<br>".join([emp_map.get(l['employeeId'], 'Άγνωστος') for l in leaves_today]) if leaves_today else "Καμία"
        
        # Ετικέτα Άξονα Υ (Ημέρα + Άδειες)
        base_y_label = f"<b>{day_str}</b><br><span style='font-size:10px; color:#d32f2f;'>Άδειες: {leaves_text}</span>"
        
        # 2. Φιλτράρισμα Βαρδιών Ημέρας
        day_assignments = df_assign[df_assign['date'] == curr_date_iso].to_dict('records')
        
        # Ομαδοποίηση βαρδιών που είναι ίδιες (ίδιο έργο, ίδια ώρα) για να μπουν στην ίδια μπάρα
        groups = {}
        for a in day_assignments:
            key = f"{a['projectId']}_{a['startTime']}_{a['endTime']}_{a.get('notes','')}_{a.get('is_cancelled', False)}"
            if key not in groups:
                proj_info = proj_map.get(a['projectId'], {})
                groups[key] = {
                    'Project': proj_info.get('name', 'Άγνωστο'),
                    'Start': datetime.combine(date(1970,1,1), datetime.strptime(a['startTime'][:5], "%H:%M").time()),
                    'End': datetime.combine(date(1970,1,1), datetime.strptime(a['endTime'][:5], "%H:%M").time()),
                    'Emps': [],
                    'Color': a.get('colorHex', proj_info.get('color', '#4a86e8')),
                    'Notes': a.get('notes', ''),
                    'IsCancelled': a.get('is_cancelled', False)
                }
            emp_name = emp_map.get(a['employeeId'], 'ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ')
            groups[key]['Emps'].append(emp_name)

        # 3. Διαχείριση Lanes (Σειρών) ανά ημέρα για αποφυγή επικαλύψεων
        lanes = []
        day_row_ids = []
        for g in sorted(groups.values(), key=lambda x: x['Start']):
            placed = False
            for idx, lane_end in enumerate(lanes):
                if g['Start'] >= lane_end:
                    row_idx = idx
                    lanes[idx] = g['End']
                    placed = True
                    break
            if not placed:
                lanes.append(g['End'])
                row_idx = len(lanes) - 1
            
            row_id = f"day_{i}_row_{row_idx}"
            day_row_ids.append(row_id)
            
            # Δημιουργία Ετικέτας "Excel-style"
            start_t = g['Start'].strftime('%H:%M')
            end_t = g['End'].strftime('%H:%M')
            emps_str = ", ".join(g['Emps'])
            
            label_text = f"<b>{g['Project']}</b> ({start_t}-{end_t})<br>{emps_str}"
            if g['Notes']: label_text += f"<br><i>{g['Notes']}</i>"
            if g['IsCancelled']: label_text = f"<s>{label_text}</s> (ΑΚΥΡΟ)"

            chart_data.append({
                'Y_Axis': row_id,
                'Start': g['Start'],
                'End': g['End'],
                'Label': label_text,
                'Project': g['Project'],
                'Color': g['Color']
            })
            color_map[g['Project']] = g['Color']

        # Οργάνωση άξονα Υ
        y_category_order.extend(day_row_ids)
        mid_idx = len(day_row_ids) // 2
        for idx, rid in enumerate(day_row_ids):
            tickvals_map[rid] = base_y_label if idx == mid_idx else ""
            
        # Αν η μέρα είναι κενή, προσθέτουμε μια κενή γραμμή
        if not day_row_ids:
            rid = f"day_{i}_empty"
            y_category_order.append(rid)
            tickvals_map[rid] = base_y_label

    if not chart_data:
        st.info("Δεν υπάρχουν βάρδιες για αυτή την εβδομάδα.")
        return

    df_chart = pd.DataFrame(chart_data)
    
    # Σχεδίαση με Plotly
    fig = px.timeline(
        df_chart, 
        x_start="Start", 
        x_end="End", 
        y="Y_Axis", 
        color="Project",
        color_discrete_map=color_map,
        text="Label",
        template="plotly_white"
    )

    # Styling (Replica PDF)
    fig.update_traces(
        textposition='inside',
        insidetextanchor='middle',
        textfont=dict(size=10, color='black'),
        marker=dict(line=dict(width=1, color='black'))
    )

    fig.update_yaxes(
        categoryorder='array',
        categoryarray=y_category_order[::-1],
        tickmode='array',
        tickvals=y_category_order,
        ticktext=[tickvals_map[v] for v in y_category_order],
        gridcolor='rgba(0,0,0,0.1)',
        title=""
    )

    fig.update_xaxes(
        side="top",
        dtick=3600000, # Κάθε 1 ώρα
        tickformat="%H:%M",
        range=[datetime(1970,1,1,6,0), datetime(1970,1,1,22,0)], # 06:00 - 22:00
        gridcolor='black',
        title=""
    )

    # Διαχωριστικές γραμμές ημερών
    for i in range(1, 7):
        fig.add_shape(
            type="line", xref="paper", yref="y",
            x0=0, x1=1, y0=f"day_{i}_row_0" if f"day_{i}_row_0" in y_category_order else f"day_{i}_empty",
            y1=f"day_{i}_row_0" if f"day_{i}_row_0" in y_category_order else f"day_{i}_empty",
            line=dict(color="black", width=3)
        )

    fig.update_layout(
        height=200 + (len(y_category_order) * 45),
        showlegend=False,
        margin=dict(l=10, r=10, t=50, b=10),
        bargap=0.1
    )

    st.plotly_chart(fig, use_container_width=True)

# --- ΕΚΤΕΛΕΣΗ ---
quick_add_assignment()
render_gantt_chart()
gc.collect()
