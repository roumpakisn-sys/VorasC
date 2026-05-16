import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, date, timedelta
import gc
import textwrap
import io
import uuid
import calendar
import time

# Κάνουμε import τον "κινητήρα" μας
import database as db

# ==========================================
# 1. ΕΛΕΓΧΟΣ ΠΡΟΣΒΑΣΗΣ & STYLING
# ==========================================
if not st.session_state.get('current_user'):
    st.warning("⚠️ Παρακαλώ συνδεθείτε από την αρχική σελίδα για να δείτε το ταμπλό.")
    st.stop()

st.title("🏢 Staff Manager Pro - Χρονοδιάγραμμα")

# CSS για την αισθητική του παλιού project
st.markdown("""
<style>
    .stPlotlyChart {
        border: 1px solid #cbd5e1;
        border-radius: 8px;
    }
    .leave-conflict-box {
        padding: 12px;
        border-radius: 8px;
        background-color: #fee2e2;
        border: 1px solid #ef4444;
        margin-bottom: 8px;
        color: #b91c1c;
        font-weight: 500;
    }
</style>
""", unsafe_allow_html=True)

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

def get_employee_name(emp_id, employees_list):
    if not emp_id: return "Χωρίς Προσωπικό"
    emp = next((e for e in employees_list if e['id'] == emp_id), None)
    return emp['name'] if emp else "Άγνωστος"

def get_project_info(proj_id, projects_list):
    return next((p for p in projects_list if p['id'] == proj_id), None)

# ==========================================
# 3. ΚΥΡΙΑ ΠΡΟΒΟΛΗ GANTT
# ==========================================
def render_dashboard():
    # 3.1 Nav Bar
    col_nav1, col_date, col_nav2, col_today, col_zoom, col_pres = st.columns([1, 2, 1, 1, 2, 2.5])
    
    with col_nav1:
        st.write("")
        st.button("⬅️ Προηγούμενη", on_click=go_prev_week, use_container_width=True)
    
    with col_date:
        selected_date = st.date_input("Επιλογή Εβδομάδας", key="view_week_date")
        start_of_week = selected_date - timedelta(days=selected_date.weekday())
    
    with col_nav2:
        st.write("")
        st.button("Επόμενη ➡️", on_click=go_next_week, use_container_width=True)
        
    with col_today:
        st.write("")
        st.button("📅 Σήμερα", on_click=go_to_today, use_container_width=True)

    with col_zoom:
        zoom_level = st.slider("🔍 Ζουμ (%)", min_value=50, max_value=200, value=100, step=5)
        zoom_factor = zoom_level / 100.0

    with col_pres:
        st.write("")
        st.write("")
        presentation_mode = st.checkbox("📽️ Λειτουργία Παρουσίασης")

    # 3.2 Φόρτωση Δεδομένων
    assignments = db.fetch_paginated('assignments')
    employees = db.fetch_paginated('employees')
    projects = db.fetch_paginated('projects')
    leaves = db.fetch_paginated('leaves')
    
    if not assignments:
        st.info("Δεν βρέθηκαν βάρδιες στη βάση δεδομένων.")
        return

    df_assign = pd.DataFrame(assignments)
    
    # 3.3 Λογική Επεξεργασίας Δεδομένων (Πλήρης PDF Replica)
    data = []
    export_data = []
    color_map = {}
    y_category_order = []
    tickvals_map = {}
    wk_groups = {}
    day_names_gr = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]

    for i in range(7):
        curr_date = start_of_week + timedelta(days=i)
        curr_date_iso = curr_date.isoformat()
        day_str = f"{day_names_gr[i]} {curr_date.strftime('%d/%m')}"
        
        # Εύρεση Αδειών
        leaves_today = [l for l in leaves if l['startDate'] <= curr_date_iso <= l['endDate']]
        leaves_list = []
        for l in leaves_today:
            emp_name = get_employee_name(l['employeeId'], employees)
            leaves_list.append(f"<b>{emp_name}</b>")
        
        leaves_str = "<br>".join(leaves_list) if leaves_list else "Καμία"
        base_y_label = f"<b>{day_str}</b><br><span style='font-size:11px; color:#d32f2f;'>Άδειες:<br>{leaves_str}</span>"
        
        # Φιλτράρισμα Βαρδιών
        day_assigns = df_assign[df_assign['date'] == curr_date_iso].to_dict('records')
        
        # Ομαδοποίηση
        groups = {}
        for a in day_assigns:
            # Χρήση camelCase όπως στην παλιά βάση
            key = f"{curr_date_iso}_{a['projectId']}_{a['startTime']}_{a['endTime']}_{a.get('colorHex','')}_{a.get('notes','')}_{a.get('is_cancelled', False)}"
            if key not in groups:
                proj = get_project_info(a['projectId'], projects)
                c_hex = a.get('colorHex', proj['color'] if proj else "#999999")
                groups[key] = {
                    'Key': key,
                    'ProjectId': a['projectId'],
                    'Project': proj['name'] if proj else "Άγνωστο",
                    'StartTime': a['startTime'][:5],
                    'EndTime': a['endTime'][:5],
                    'Start': datetime.combine(date(1970,1,1), datetime.strptime(a['startTime'][:5], "%H:%M").time()),
                    'End': datetime.combine(date(1970,1,1), datetime.strptime(a['endTime'][:5], "%H:%M").time()),
                    'Employees': [],
                    'ColorHex': c_hex,
                    'Notes': a.get('notes', ''),
                    'is_cancelled': a.get('is_cancelled', False),
                    'AssignmentIds': []
                }
            
            emp_name = get_employee_name(a.get('employeeId'), employees)
            groups[key]['Employees'].append(emp_name)
            groups[key]['AssignmentIds'].append(a['id'])

        # Collision & Lane Logic
        lanes = []
        day_row_ids = []
        for g in sorted(groups.values(), key=lambda x: x['Start']):
            placed = False
            for lane_idx, lane_end in enumerate(lanes):
                if g['Start'] >= lane_end:
                    row_idx = lane_idx
                    lanes[lane_idx] = g['End']
                    placed = True
                    break
            if not placed:
                lanes.append(g['End'])
                row_idx = len(lanes) - 1
            
            row_id = f"day_{i}_row_{row_idx}"
            day_row_ids.append(row_id)
            
            # Label Generation
            emps_str = ", ".join(g['Employees']).upper()
            proj_name = g['Project'].upper()
            times_str = f"{g['StartTime']}-{g['EndTime']}"
            base_text = f"{times_str} {proj_name} // {emps_str}"
            if g['Notes']: base_text += f" ({g['Notes'].upper()})"
            
            wrap_w = max(15, int(((g['End'] - g['Start']).total_seconds() / 3600.0) * 16))
            wrapped_base = "<br>".join(textwrap.wrap(base_text, width=wrap_w))
            
            if g['is_cancelled']:
                label_text = f"<s>{wrapped_base}</s> (ΑΚΥΡΟ)"
            else:
                label_text = wrapped_base

            data.append({
                'Y_Axis': row_id,
                'Project': g['Project'],
                'Έναρξη': g['Start'],
                'Λήξη': g['End'],
                'Ετικέτα': label_text,
                'ColorHex': g['ColorHex'],
                'GroupKey': g['Key']
            })
            export_data.append({
                'Ημερομηνία': curr_date.strftime('%d/%m/%Y'),
                'Έργο': g['Project'],
                'Προσωπικό': emps_str,
                'Ώρες': times_str,
                'Σημειώσεις': g['Notes']
            })
            color_map[g['Project']] = g['ColorHex']

        # Y-Axis Mapping
        y_category_order.extend(day_row_ids)
        mid_idx = len(day_row_ids) // 2
        for idx, rid in enumerate(day_row_ids):
            tickvals_map[rid] = base_y_label if idx == mid_idx else ""
        
        if not day_row_ids:
            rid = f"day_{i}_empty"
            y_category_order.append(rid)
            tickvals_map[rid] = base_y_label

        wk_groups.update(groups)

    # 3.4 Σχεδίαση με Plotly (Legacy Specs)
    df = pd.DataFrame(data)
    ordered_cats = y_category_order[::-1]
    
    fig = px.timeline(
        df, x_start="Έναρξη", x_end="Λήξη", y="Y_Axis", 
        color="Project", color_discrete_map=color_map, 
        text="Ετικέτα", custom_data=["GroupKey"]
    )

    # Background και Διαχωριστικά
    for di in range(7):
        day_idxs = [idx for idx, val in enumerate(ordered_cats) if val.startswith(f"day_{di}_")]
        if day_idxs:
            mn, mx = min(day_idxs), max(day_idxs)
            if di % 2 != 0:
                fig.add_hrect(y0=mn-0.5, y1=mx+0.5, fillcolor="rgba(0,0,0,0.05)", layer="below", line_width=0)
            if (start_of_week + timedelta(days=di)) == date.today():
                fig.add_hrect(y0=mn-0.5, y1=mx+0.5, fillcolor="#b2d8ce", layer="below", line_width=0)
        
    fig.update_traces(
        textposition='inside', insidetextanchor='middle',
        textfont=dict(color='black', size=max(8, int(9*zoom_factor)), family="Arial Black"),
        marker=dict(line=dict(color='black', width=1))
    )

    row_h = 55 * zoom_factor
    dyn_h = max(500, int(len(ordered_cats) * row_h) + 100)

    fig.update_layout(
        bargap=0.12, showlegend=False, 
        plot_bgcolor='#dbece8', paper_bgcolor='#ffffff',
        height=dyn_h, margin=dict(l=10, r=10, t=50, b=10),
        xaxis=dict(
            side='top', tickformat="%H:%M", dtick=1800000, # 30 min ticks
            gridcolor='black', gridwidth=1,
            range=[datetime(1970,1,1,7,0), datetime(1970,1,1,20,0)]
        ),
        yaxis=dict(
            tickmode='array', tickvals=ordered_cats,
            ticktext=[tickvals_map[v] for v in ordered_cats],
            categoryorder='array', categoryarray=ordered_cats
        )
    )

    # Rendering
    event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", selection_mode="points")
    
    # 3.5 Export και Hint
    col_h, col_e = st.columns([3, 1])
    with col_h:
        st.caption("💡 **Συμβουλή:** Κάντε κλικ σε μια μπάρα για επεξεργασία. Σύρετε για πλοήγηση στον χρόνο.")
    with col_e:
        if export_data:
            df_exp = pd.DataFrame(export_data)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_exp.to_excel(writer, index=False)
            st.download_button("📥 Εξαγωγή Excel", data=output.getvalue(), file_name="Gantt_Export.xlsx")

    # 3.6 Φόρμες (Add / Edit)
    st.divider()
    
    # Διαχείριση επιλογής από το γράφημα
    clicked_key = None
    if event and "selection" in event and event["selection"]["points"]:
        clicked_key = event["selection"]["points"][0].get("customdata", [None])[0]

    col_add, col_edit = st.columns(2)
    
    with col_add:
        st.subheader("➕ Νέα Τοποθέτηση")
        with st.form("add_assignment_form", clear_on_submit=True):
            f_date = st.date_input("Ημερομηνία", value=selected_date)
            f_proj = st.selectbox("Έργο", [p['id'] for p in projects], format_func=lambda x: next(p['name'] for p in projects if p['id']==x))
            f_emps = st.multiselect("Προσωπικό", [e['id'] for e in employees], format_func=lambda x: next(e['name'] for e in employees if e['id']==x))
            f_color = st.selectbox("Χρώμα Μπάρας", list(BASIC_COLORS.keys()))
            f_notes = st.text_input("Παρατηρήσεις")
            c_s, c_e = st.columns(2)
            f_start = c_s.time_input("Έναρξη", datetime.strptime("09:00", "%H:%M").time())
            f_end = c_e.time_input("Λήξη", datetime.strptime("17:00", "%H:%M").time())
            
            if st.form_submit_button("✅ Καταχώρηση"):
                new_assigns = []
                for eid in (f_emps if f_emps else [None]):
                    new_assigns.append({
                        'employeeId': eid,
                        'projectId': f_proj,
                        'date': f_date.isoformat(),
                        'startTime': f_start.strftime("%H:%M"),
                        'endTime': f_end.strftime("%H:%M"),
                        'notes': f_notes,
                        'colorHex': BASIC_COLORS[f_color],
                        'is_cancelled': False
                    })
                supabase = db.init_supabase()
                supabase.table('assignments').insert(new_assigns).execute()
                db.log_activity("ΠΡΟΣΘΗΚΗ", "assignments", f"Νέα ανάθεση στο {f_date}", st.session_state.current_user)
                db.fetch_paginated.clear()
                st.rerun()

    with col_edit:
        st.subheader("📝 Επεξεργασία")
        group_keys = list(wk_groups.keys())
        default_idx = group_keys.index(clicked_key) + 1 if clicked_key in group_keys else 0
        
        sel_group_key = st.selectbox("Επιλέξτε Μπάρα", [""] + group_keys, index=default_idx, 
                                     format_func=lambda x: "Επιλέξτε..." if x=="" else f"{wk_groups[x]['Project']} ({wk_groups[x]['StartTime']})")
        
        if sel_group_key:
            g = wk_groups[sel_group_key]
            with st.form("edit_assignment_form"):
                e_date = st.date_input("Αλλαγή Ημερομηνίας", value=datetime.fromisoformat(g['Key'].split("_")[0]).date())
                e_notes = st.text_input("Παρατηρήσεις", value=g['Notes'])
                e_cancel = st.checkbox("Ακύρωση Βάρδιας", value=g['is_cancelled'])
                
                c1, c2 = st.columns(2)
                if c1.form_submit_button("💾 Αποθήκευση"):
                    supabase = db.init_supabase()
                    for aid in g['AssignmentIds']:
                        supabase.table('assignments').update({
                            'date': e_date.isoformat(),
                            'notes': e_notes,
                            'is_cancelled': e_cancel
                        }).eq('id', aid).execute()
                    db.log_activity("ΕΝΗΜΕΡΩΣΗ", "assignments", f"Αλλαγή στη μπάρα {sel_group_key}", st.session_state.current_user)
                    db.fetch_paginated.clear()
                    st.rerun()
                
                if c2.form_submit_button("🗑️ Διαγραφή"):
                    supabase = db.init_supabase()
                    supabase.table('assignments').delete().in_('id', g['AssignmentIds']).execute()
                    db.log_activity("ΔΙΑΓΡΑΦΗ", "assignments", f"Διαγραφή μπάρας {sel_group_key}", st.session_state.current_user)
                    db.fetch_paginated.clear()
                    st.rerun()

# --- ΕΚΤΕΛΕΣΗ ---
render_dashboard()
gc.collect()
