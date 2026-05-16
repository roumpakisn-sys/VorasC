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

# CSS για την αισθητική του PDF
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
# 3. ΚΥΡΙΑ ΠΡΟΒΟΛΗ GANTT (PDF SPECIFIC)
# ==========================================
def render_dashboard():
    # 3.1 Nav Bar & Controls
    col_nav1, col_date, col_nav2, col_today, col_zoom, col_pres = st.columns([1, 2, 1, 1, 2, 2.5])
    
    with col_nav1:
        st.write("")
        st.button("- Προηγούμενη", on_click=go_prev_week, use_container_width=True)
    
    with col_date:
        selected_date = st.date_input("Επιλογή Εβδομάδας", key="view_week_date")
        start_of_week = selected_date - timedelta(days=selected_date.weekday())
    
    with col_nav2:
        st.write("")
        st.button("Επόμενη ", on_click=go_next_week, use_container_width=True)
        
    with col_today:
        st.write("")
        st.button(" Σήμερα", on_click=go_to_today, use_container_width=True)

    with col_zoom:
        zoom_level = st.slider(" Ζουμ Διαγράμματος (%)", min_value=50, max_value=200, value=100, step=5)
        zoom_factor = zoom_level / 100.0

    with col_pres:
        st.write("")
        st.write("")
        presentation_mode = st.checkbox(" Λειτουργία Πλήρους Προβολής")

    # 3.2 Φόρτωση Δεδομένων
    assignments = db.fetch_paginated('assignments')
    employees = db.fetch_paginated('employees')
    projects = db.fetch_paginated('projects')
    leaves = db.fetch_paginated('leaves')
    
    if not assignments:
        st.info("Δεν βρέθηκαν βάρδιες στη βάση δεδομένων.")
        return

    # 3.3 Επεξεργασία Δεδομένων για το Γράφημα (Απόλυτη Πιστή Αντιγραφή Logic από PDF)
    data = []
    export_data = []
    color_map = {}
    y_category_order = []
    tickvals_map = {}
    wk_groups = {}
    day_names_gr = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]

    emp_lookup = {e['id']: e for e in employees}
    proj_lookup = {p['id']: p for p in projects}

    for i in range(7):
        curr_date = start_of_week + timedelta(days=i)
        curr_date_iso = curr_date.isoformat()
        day_str = f"{day_names_gr[i]} {curr_date.strftime('%d/%m')}"
        
        # --- 1. Υπολογισμός Αδειών (Μορφή Επίθετο Ο.) ---
        leaves_today_list = [l for l in leaves if l['startDate'] <= curr_date_iso <= l['endDate']]
        leaves_formatted = []
        for l in leaves_today_list:
            full_name = emp_lookup.get(l['employeeId'], {}).get('name', 'Άγνωστος')
            parts = full_name.split()
            short_name = f"{parts[-1]} {parts[0][0]}." if len(parts) > 1 else full_name
            
            sub_id = l.get('substituteld') # Χρήση lowercase L όπως στο PDF
            if sub_id:
                sub_full = emp_lookup.get(sub_id, {}).get('name', 'Άγνωστος')
                s_parts = sub_full.split()
                s_name = f"{s_parts[-1]} {s_parts[0][0]}." if len(s_parts) > 1 else sub_full
                leaves_formatted.append(f"<b>{short_name}</b><br><span style='font-size: 10px; color:#991b1b;'> , Αντικατ: <b>{s_name}</b></span>")
            else:
                leaves_formatted.append(f"<b>{short_name}</b>")
        
        leaves_str = "<br><br>".join(leaves_formatted) if leaves_formatted else "Καμία"
        
        if leaves_formatted:
            base_y_label = f"<b>{day_str}</b><br><span style='font-size:11px; color:#d32f2f;'>Άδειες:<br>{leaves_str}</span>"
        else:
            base_y_label = f"<b>{day_str}</b><br><span style='font-size:11px; color:#d32f2f;'>Άδειες: {leaves_str}</span>"
        
        # --- 2. Φιλτράρισμα & Ομαδοποίηση Βαρδιών Ημέρας ---
        day_assigns = [a for a in assignments if a['date'] == curr_date_iso]
        
        # Ευρετήριο βαρδιών ανά υπάλληλο για τον έλεγχο "ΜΕΤΑ ΑΠΟ"
        emp_day_assigns = {}
        for da in day_assigns:
            eid = da.get('employeeId')
            if eid:
                if eid not in emp_day_assigns: emp_day_assigns[eid] = []
                emp_day_assigns[eid].append(da)

        groups = {}
        for a in day_assigns:
            p_info = proj_lookup.get(a['projectId'], {})
            c_hex = a.get('colorHex', p_info.get('color', "#999999"))
            c_name = a.get('colorName', "Προεπιλογή")
            notes = a.get('notes', "")
            is_canc = a.get('is_cancelled', False)
            c_reason = a.get('cancel_reason', "")
            arr_time = a.get('arrivalTime', "")
            if arr_time: arr_time = arr_time[:5]

            # Κλειδί ομαδοποίησης σύμφωνα με το PDF
            key = f"{curr_date_iso}_{a['projectId']}_{a['startTime']}_{a['endTime']}_{c_hex}_{notes}_{is_canc}_{c_reason}_{arr_time}"
            
            if key not in groups:
                legend_val = f"{p_info.get('name', 'Άγνωστο')} ({c_name})"
                groups[key] = {
                    'Key': key,
                    'ProjectId': a['projectId'],
                    'Project': p_info.get('name', 'Άγνωστο'),
                    'ArrivalTime': arr_time,
                    'StartTime': a['startTime'][:5],
                    'EndTime': a['endTime'][:5],
                    'Start': datetime.combine(date(1970, 1, 1), datetime.strptime(a['startTime'][:5], "%H:%M").time()),
                    'End': datetime.combine(date(1970, 1, 1), datetime.strptime(a['endTime'][:5], "%H:%M").time()),
                    'Employees': [],
                    'ColorHex': c_hex,
                    'LegendGroup': legend_val,
                    'Notes': notes,
                    'is_cancelled': is_canc,
                    'cancel_reason': c_reason,
                    'AssignmentIds': []
                }
            
            # Μορφοποίηση ονόματος
            eid = a.get('employeeId')
            if not eid:
                formatted_name = "ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ"
            else:
                full_name = emp_lookup.get(eid, {}).get('name', 'Άγνωστος')
                name_parts = full_name.split()
                if len(name_parts) > 1:
                    formatted_name = f"{name_parts[-1]} {name_parts[0][0]}."
                else:
                    formatted_name = full_name

                # Λογική "ΜΕΤΑ ΑΠΟ"
                t_a_start = a['startTime'][:5]
                t_a_end = a['endTime'][:5]
                prev_assigns = []
                for pa in emp_day_assigns.get(eid, []):
                    if pa['id'] != a['id']:
                        t_pa_start = pa['startTime'][:5]
                        t_pa_end = pa['endTime'][:5]
                        # Έλεγχος επικάλυψης/διαδοχής
                        if (t_pa_start < t_a_end) and (t_a_start < t_pa_end) and (t_pa_end <= t_a_end):
                            prev_assigns.append(pa)
                
                if prev_assigns:
                    prev_assigns.sort(key=lambda x: x['endTime'][:5], reverse=True)
                    prev_p = proj_lookup.get(prev_assigns[0]['projectId'])
                    if prev_p:
                        formatted_name = f"[ΜΕΤΑ ΑΠΟ '{prev_p['name']}' {formatted_name}]"

            groups[key]['Employees'].append(formatted_name)
            groups[key]['AssignmentIds'].append(a['id'])

        # --- 3. Λογική Λωρίδων (Lanes) ανά Ημέρα ---
        non_blue_groups = [g for g in groups.values() if g['ColorHex'].lower() != "#4a86e8"]
        blue_groups = [g for g in groups.values() if g['ColorHex'].lower() == "#4a86e8"]
        
        group_row_mapping = []
        
        # Λωρίδες για μη-μπλε
        non_blue_lanes = []
        for g in sorted(non_blue_groups, key=lambda x: x['Start']):
            placed = False
            for idx, lane_end in enumerate(non_blue_lanes):
                if g['Start'] >= lane_end:
                    non_blue_lanes[idx] = g['End']
                    group_row_mapping.append((g, idx))
                    placed = True
                    break
            if not placed:
                non_blue_lanes.append(g['End'])
                group_row_mapping.append((g, len(non_blue_lanes)-1))
        
        num_nb_lanes = len(non_blue_lanes)
        
        # Λωρίδες για μπλε (ξεκινούν μετά τις μη-μπλε)
        blue_lanes = []
        for g in sorted(blue_groups, key=lambda x: x['Start']):
            placed = False
            for idx, lane_end in enumerate(blue_lanes):
                if g['Start'] >= lane_end:
                    blue_lanes[idx] = g['End']
                    group_row_mapping.append((g, idx + num_nb_lanes))
                    placed = True
                    break
            if not placed:
                blue_lanes.append(g['End'])
                group_row_mapping.append((g, len(blue_lanes)-1 + num_nb_lanes))

        day_row_ids = []
        for g, row_idx in group_row_mapping:
            row_id = f"day_{i}_row_{row_idx}"
            if row_id not in day_row_ids:
                day_row_ids.append(row_id)
            
            # Κατασκευή Ετικέτας Μπάρας (Όπως στο PDF)
            emps_str = ", ".join(g['Employees']).upper()
            proj_name = g['Project'].upper()
            arrival_str = f"[Προσ: {g['ArrivalTime']}] " if g['ArrivalTime'] else ""
            times_str = f"{arrival_str}{g['StartTime']}-{g['EndTime']}"
            base_text = f"{times_str} {proj_name} // {emps_str}"
            if g['Notes']: base_text += f" ({g['Notes'].upper()})"
            
            # Αναδίπλωση κειμένου βάσει διάρκειας (PDF Logic)
            duration_h = (g['End'] - g['Start']).total_seconds() / 3600.0
            wrap_w = max(15, int(duration_h * 16))
            wrapped_label = "<br>".join(textwrap.wrap(base_text, width=wrap_w))
            
            if g['is_cancelled']:
                wrapped_label = f"<s>{wrapped_label}</s>"
                if g['cancel_reason']:
                    wrapped_reason = "<br>".join(textwrap.wrap(f"[{g['cancel_reason'].upper()}]", width=wrap_w))
                    wrapped_label += f"<br><span style='color:#dc2626;'><b>{wrapped_reason}</b></span>"

            data.append({
                'Y_Axis': row_id,
                'Start': g['Start'],
                'End': g['End'],
                'Label': wrapped_label,
                'Project': g['Project'],
                'Color': g['ColorHex'],
                'LegendGroup': g['LegendGroup'],
                'GroupKey': g['Key']
            })
            color_map[g['LegendGroup']] = g['ColorHex']
            
            export_data.append({
                'Ημερομηνία': curr_date.strftime('%d/%m/%Y'),
                'Ημέρα': day_names_gr[i],
                'Έργο': g['Project'],
                'Προσωπικό': emps_str,
                'Ώρες': f"{g['StartTime']}-{g['EndTime']}",
                'Παρατηρήσεις': g['Notes'],
                'Ακυρωμένο': 'NAI' if g['is_cancelled'] else 'OXI'
            })

        # Οργάνωση Άξονα Υ
        y_category_order.extend(day_row_ids)
        mid_idx = len(day_row_ids) // 2
        for idx, rid in enumerate(day_row_ids):
            tickvals_map[rid] = base_y_label if idx == mid_idx else ""
            
        if not day_row_ids:
            rid = f"day_{i}_empty"
            y_category_order.append(rid)
            tickvals_map[rid] = base_y_label

        wk_groups.update(groups)

    # --- 3.4 Σχεδίαση με Plotly ---
    if not data:
        st.info("Δεν βρέθηκαν βάρδιες για προβολή αυτή την εβδομάδα.")
        return

    df_plot = pd.DataFrame(data)
    ordered_cats = y_category_order[::-1] # Αντίστροφη σειρά για σωστή προβολή από πάνω προς τα κάτω
    
    fig = px.timeline(
        df_plot, x_start="Start", x_end="End", y="Y_Axis", 
        color="LegendGroup", color_discrete_map=color_map, 
        text="Label", custom_data=["GroupKey"]
    )

    # Προσθήκη σκίασης (ΗRECT) και διαχωριστικών (SHAPES)
    for di in range(7):
        day_pattern = f"day_{di}_"
        day_idxs = [idx for idx, val in enumerate(ordered_cats) if val.startswith(day_pattern)]
        if day_idxs:
            mn, mx = min(day_idxs), max(day_idxs)
            # Εναλλαγή σκίασης ανά ημέρα
            if di % 2 != 0:
                fig.add_hrect(y0=mn-0.5, y1=mx+0.5, fillcolor="rgba(0,0,0,0.05)", opacity=1, layer="below", line_width=0)
            # Σκίαση Σήμερα
            if (start_of_week + timedelta(days=di)) == date.today():
                fig.add_hrect(y0=mn-0.5, y1=mx+0.5, fillcolor="#b2d8ce", opacity=1, layer="below", line_width=0)

    # Μαύρες έντονες διαχωριστικές γραμμές μεταξύ ημερών
    for idx in range(len(ordered_cats) - 1):
        if ordered_cats[idx].split('_')[1] != ordered_cats[idx+1].split('_')[1]:
            fig.add_shape(type="line", x0=0, x1=1, xref="paper", y0=idx+0.5, y1=idx+0.5, yref="y", line=dict(color="#000000", width=4))

    # Ρυθμίσεις Traces
    fig.update_traces(
        textposition='inside', insidetextanchor='middle',
        textfont=dict(color='black', size=max(8, int(9*zoom_factor)), family="Arial Black, Arial, sans-serif"),
        marker=dict(line=dict(color='black', width=1)),
        textangle=0, constraintext='none', hoverinfo='none'
    )

    # Υπολογισμός Ύψους (Dynamic Row Height)
    row_h = 55 * zoom_factor
    dyn_h = max(500, int(len(ordered_cats) * row_h) + 100)

    fig.update_layout(
        bargap=0.12, showlegend=False, 
        plot_bgcolor='#dbece8', paper_bgcolor='#ffffff',
        height=dyn_h, margin=dict(l=10, r=10, t=50, b=10),
        xaxis=dict(
            side='top', tickmode='linear', dtick=1800000, # 30 λεπτά
            tickformat="%H:%M", showgrid=True, gridcolor='black', gridwidth=1,
            range=[datetime(1970,1,1,6,0), datetime(1970,1,1,17,0)], # Όπως στο PDF
            tickfont=dict(size=max(8, int(11*zoom_factor)), color="black", family="Arial")
        ),
        yaxis=dict(
            tickmode='array', tickvals=ordered_cats,
            ticktext=[tickvals_map.get(v, "") for v in ordered_cats],
            categoryorder='array', categoryarray=ordered_cats,
            title="", tickfont=dict(size=max(8, int(12*zoom_factor)), color="black")
        )
    )

    # Προβολή Γραφήματος
    try:
        event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", selection_mode="points", config={"displayModeBar": False})
        
        # Διαχείριση κλικ
        clicked_key = None
        if event and "selection" in event and event["selection"]["points"]:
            clicked_key = event["selection"]["points"][0].get("customdata", [None])[0]
    except:
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        clicked_key = None

    # --- 3.5 Εργαλεία Εξαγωγής & Hint ---
    col_h, col_e = st.columns([3, 1])
    with col_h:
        st.caption("💡 **Συμβουλές:** **1)** Κλικ σε μπάρα για επεξεργασία. **2)** Σύρετε πάνω-κάτω για πλοήγηση. **3)** Ζουμ από τη μπάρα.")
    with col_e:
        if export_data:
            df_exp = pd.DataFrame(export_data)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_exp.to_excel(writer, index=False, sheet_name='Πρόγραμμα')
            st.download_button("📂 Εξαγωγή Προγράμματος (Excel)", data=output.getvalue(), 
                               file_name=f"Gantt_Export_{start_of_week.strftime('%d_%m')}.xlsx", 
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # --- 3.6 Φόρμες (Add / Edit) ---
    if not presentation_mode:
        st.divider()
        col_add, col_edit = st.columns(2)
        
        with col_add:
            st.subheader("+ Νέα Τοποθέτηση")
            with st.form("add_form", clear_on_submit=True):
                f_date = st.date_input("Ημερομηνία", value=selected_date)
                f_proj = st.selectbox("Επιλογή Έργου", [p['id'] for p in projects], format_func=lambda x: proj_lookup[x]['name'])
                f_emps = st.multiselect("Προσωπικό", [e['id'] for e in employees], format_func=lambda x: emp_lookup[x]['name'])
                f_color = st.selectbox("Χρώμα", list(BASIC_COLORS.keys()))
                f_notes = st.text_input("Παρατηρήσεις")
                c_s, c_e = st.columns(2)
                f_start = c_s.time_input("Έναρξη", datetime.strptime("09:00", "%H:%M").time())
                f_end = c_e.time_input("Λήξη", datetime.strptime("17:00", "%H:%M").time())
                
                if st.form_submit_button("Καταχώρηση"):
                    new_list = []
                    for eid in (f_emps if f_emps else [None]):
                        new_list.append({
                            'employeeId': eid, 'projectId': f_proj, 'date': f_date.isoformat(),
                            'startTime': f_start.strftime("%H:%M"), 'endTime': f_end.strftime("%H:%M"),
                            'notes': f_notes, 'colorHex': BASIC_COLORS[f_color], 'is_cancelled': False, 'colorName': f_color
                        })
                    supabase = db.init_supabase()
                    supabase.table('assignments').insert(new_list).execute()
                    db.fetch_paginated.clear()
                    st.rerun()

        with col_edit:
            st.subheader("- Επεξεργασία")
            group_keys = list(wk_groups.keys())
            def_idx = group_keys.index(clicked_key) + 1 if clicked_key in group_keys else 0
            sel_key = st.selectbox("Επιλέξτε Μπάρα", [""] + group_keys, index=def_idx, 
                                   format_func=lambda x: "Επιλέξτε..." if x=="" else f"{wk_groups[x]['Project']} ({wk_groups[x]['StartTime']})")
            
            if sel_key:
                g = wk_groups[sel_key]
                with st.form("edit_form"):
                    e_notes = st.text_input("Παρατηρήσεις", value=g['Notes'])
                    e_canc = st.checkbox("Ακυρωμένη", value=g['is_cancelled'])
                    c1, c2 = st.columns(2)
                    if c1.form_submit_button("💾 Αποθήκευση"):
                        supabase = db.init_supabase()
                        for aid in g['AssignmentIds']:
                            supabase.table('assignments').update({'notes': e_notes, 'is_cancelled': e_canc}).eq('id', aid).execute()
                        db.fetch_paginated.clear()
                        st.rerun()
                    if c2.form_submit_button("🗑️ Διαγραφή"):
                        supabase = db.init_supabase()
                        supabase.table('assignments').delete().in_('id', g['AssignmentIds']).execute()
                        db.fetch_paginated.clear()
                        st.rerun()

# --- ΕΚΤΕΛΕΣΗ ---
render_dashboard()
gc.collect()
