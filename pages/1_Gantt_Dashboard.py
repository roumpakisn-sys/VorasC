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

#--- GLOBAL STYLING (Replica from PDF) ---
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
# 2. ΣΥΝΑΡΤΗΣΕΙΣ ΠΛΟΗΓΗΣΗΣ
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
# 3. ΚΥΡΙΑ ΛΟΓΙΚΗ ΠΡΟΒΟΛΗΣ (DASHBOARD)
# ==========================================
def render_dashboard():
    st.title("📊 Εβδομαδιαίο Χρονοδιάγραμμα Πόρων")

    # 3.1 Nav Controls
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
        zoom_level = st.slider(" Ζουμ Διαγράμματος (%)", min_value=50, max_value=150, value=100, step=5)
        zoom_factor = zoom_level / 100.0
    with col_pres:
        st.write("")
        st.write("")
        presentation_mode = st.checkbox(" Λειτουργία Πλήρους Προβολής")

    # 3.2 Fetch Data
    assignments = db.fetch_paginated('assignments')
    employees = db.fetch_paginated('employees')
    projects = db.fetch_paginated('projects')
    leaves = db.fetch_paginated('leaves')
    
    if not assignments:
        st.info("Δεν βρέθηκαν βάρδιες στη βάση.")
        return

    # 3.3 Data Processing (Πιστή αντιγραφή από PDF)
    data = []
    color_map = {}
    y_category_order = []
    tickvals_map = {}
    wk_groups = {}
    day_names_gr = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]

    emp_lookup = {e['id']: e for e in employees}
    proj_lookup = {p['id']: p for p in projects}

    for i in range(7):
        curr_date = start_of_week + timedelta(days=i)
        curr_iso = curr_date.isoformat()
        day_str = f"{day_names_gr[i]} {curr_date.strftime('%d/%m')}"
        
        # --- ΑΔΕΙΕΣ ΗΜΕΡΑΣ (Μορφή PDF: Επίθετο Ο.) ---
        leaves_today = [l for l in leaves if l['startDate'] <= curr_iso <= l['endDate']]
        leaves_formatted = []
        for l in leaves_today:
            ename = emp_lookup.get(l['employeeId'], {}).get('name', 'Άγνωστος')
            parts = ename.split()
            short = f"{parts[-1]} {parts[0][0]}." if len(parts) > 1 else ename
            
            sub_id = l.get('substituteld')
            if sub_id:
                sname = emp_lookup.get(sub_id, {}).get('name', 'Άγνωστος')
                sparts = sname.split()
                sshort = f"{sparts[-1]} {sparts[0][0]}." if len(sparts) > 1 else sname
                leaves_formatted.append(f"<b>{short}</b><br><span style='font-size: 10px; color:#991b1b;'> , Αντικατ: <b>{sshort}</b></span>")
            else:
                leaves_formatted.append(f"<b>{short}</b>")
        
        leaves_str = "<br><br>".join(leaves_formatted) if leaves_formatted else "Καμία"
        
        if leaves_formatted:
            base_y_label = f"<b>{day_str}</b><br><span style='font-size:11px; color:#d32f2f;'>Άδειες:<br>{leaves_str}</span>"
        else:
            base_y_label = f"<b>{day_str}</b><br><span style='font-size:11px; color:#d32f2f;'>Άδειες: {leaves_str}</span>"
        
        # --- ΒΑΡΔΙΕΣ ΗΜΕΡΑΣ ---
        day_assigns = [a for a in assignments if a['date'] == curr_iso]
        emp_day_map = {}
        for da in day_assigns:
            eid = da.get('employeeId')
            if eid:
                if eid not in emp_day_map: emp_day_map[eid] = []
                emp_day_map[eid].append(da)

        groups = {}
        for a in day_assigns:
            proj = proj_lookup.get(a['projectId'], {})
            c_hex = a.get('colorHex', proj.get('color', "#999999"))
            c_name = a.get('colorName', "Προεπιλογή")
            notes = a.get('notes', "")
            is_c = a.get('is_cancelled', False)
            arr = a.get('arrivalTime', "")
            if arr: arr = arr[:5]

            key = f"{curr_iso}_{a['projectId']}_{a['startTime']}_{a['endTime']}_{c_hex}_{notes}_{is_c}_{arr}"
            
            if key not in groups:
                groups[key] = {
                    'Key': key, 'ProjectId': a['projectId'], 'Project': proj.get('name', 'Άγνωστο'),
                    'StartTime': a['startTime'][:5], 'EndTime': a['endTime'][:5],
                    'Start': datetime.combine(date(1970,1,1), datetime.strptime(a['startTime'][:5], "%H:%M").time()),
                    'End': datetime.combine(date(1970,1,1), datetime.strptime(a['endTime'][:5], "%H:%M").time()),
                    'Employees': [], 'ColorHex': c_hex, 'Notes': notes, 'is_cancelled': is_c,
                    'AssignmentIds': [], 'ArrivalTime': arr, 'Date': curr_date, 'LegendGroup': f"{proj.get('name', 'Άγνωστο')} ({c_name})"
                }
            
            eid = a.get('employeeId')
            if not eid:
                fname = "ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ"
            else:
                raw_name = emp_lookup.get(eid, {}).get('name', 'Άγνωστος')
                np = raw_name.split()
                fname = f"{np[-1]} {np[0][0]}." if len(np) > 1 else raw_name
                
                prevs = [pa for pa in emp_day_map.get(eid, []) if pa['id'] != a['id'] and pa['endTime'][:5] <= a['startTime'][:5]]
                if prevs:
                    prevs.sort(key=lambda x: x['endTime'][:5], reverse=True)
                    pp = proj_lookup.get(prevs[0]['projectId'])
                    if pp: fname = f"[ΜΕΤΑ ΑΠΟ '{pp['name']}' {fname}]"

            groups[key]['Employees'].append(fname)
            groups[key]['AssignmentIds'].append(a['id'])

        # --- LANE ALLOCATION (Προτεραιότητα Χρωμάτων) ---
        nb_groups = [g for g in groups.values() if g['ColorHex'].lower() != "#4a86e8"]
        b_groups = [g for g in groups.values() if g['ColorHex'].lower() == "#4a86e8"]
        
        day_mapping = []
        lanes = [] 
        for g in sorted(nb_groups, key=lambda x: x['Start']):
            idx = next((i for i, end in enumerate(lanes) if g['Start'] >= end), None)
            if idx is None:
                lanes.append(g['End'])
                day_mapping.append((g, len(lanes)-1))
            else:
                lanes[idx] = g['End']
                day_mapping.append((g, idx))
        
        nb_count = len(lanes)
        blanes = [] 
        for g in sorted(b_groups, key=lambda x: x['Start']):
            idx = next((i for i, end in enumerate(blanes) if g['Start'] >= end), None)
            if idx is None:
                blanes.append(g['End'])
                day_mapping.append((g, len(blanes)-1 + nb_count))
            else:
                blanes[idx] = g['End']
                day_mapping.append((g, idx + nb_count))

        day_row_ids = []
        for g, row_idx in day_mapping:
            rid = f"day_{i}_row_{row_idx}"
            day_row_ids.append(rid)
            
            emps_str = ", ".join(g['Employees']).upper()
            arrival_str = f"[Προσ: {g['ArrivalTime']}] " if g['ArrivalTime'] else ""
            txt = f"{arrival_str}{g['StartTime']}-{g['EndTime']} {g['Project'].upper()} // {emps_str}"
            if g['Notes']: txt += f" ({g['Notes'].upper()})"
            
            dur = (g['End'] - g['Start']).total_seconds() / 3600.0
            wrapped = "<br>".join(textwrap.wrap(txt, width=max(15, int(dur * 16))))
            if g['is_cancelled']: wrapped = f"<s>{wrapped}</s>"

            data.append({
                'Y': rid, 'Start': g['Start'], 'End': g['End'], 'Label': wrapped,
                'Proj': g['Project'], 'Color': g['ColorHex'], 'Key': g['Key'], 'Legend': g['LegendGroup']
            })
            color_map[g['LegendGroup']] = g['ColorHex']
            wk_groups[g['Key']] = g

        # Υπολογισμός Κεντραρίσματος στον Άξονα Υ
        day_rows_sorted = sorted(day_row_ids)
        y_category_order.extend(day_rows_sorted)
        
        if day_rows_sorted:
            mid_idx_pos = len(day_rows_sorted) // 2
            for idx, rid in enumerate(day_rows_sorted):
                tickvals_map[rid] = base_y_label if idx == mid_idx_pos else ""
        else:
            rid = f"day_{i}_empty"
            y_category_order.append(rid)
            tickvals_map[rid] = base_y_label

    # --- 3.4 Σχεδίαση με Plotly ---
    if not data:
        df_plot = pd.DataFrame([{'Y': f"day_{i}_empty", 'Start': datetime(1970,1,1,9,0), 'End': datetime(1970,1,1,9,0), 'Label': '', 'Proj': '', 'Color': '#ffffff', 'Key': 'Empty', 'Legend': ''} for i in range(7)])
    else:
        df_plot = pd.DataFrame(data)
    
    ordered = y_category_order[::-1]
    
    # Ρύθμιση Ύψους για Compact Εμφάνιση
    row_h = 45 * zoom_factor
    dyn_h = 600 # Σταθερό ύψος εσωτερικού παραθύρου

    fig = px.timeline(df_plot, x_start="Start", x_end="End", y="Y", color="Legend", 
                     color_discrete_map=color_map, text="Label", custom_data=["Key"])

    # Σκίαση Ημερών & Διαχωριστικά
    for di in range(7):
        d_idxs = [idx for idx, v in enumerate(ordered) if v.startswith(f"day_{di}_")]
        if d_idxs:
            mn, mx = min(d_idxs), max(d_idxs)
            if di % 2 != 0: 
                fig.add_hrect(y0=mn-0.5, y1=mx+0.5, fillcolor="rgba(0,0,0,0.05)", layer="below", line_width=0)
            if (start_of_week + timedelta(days=di)) == date.today(): 
                fig.add_hrect(y0=mn-0.5, y1=mx+0.5, fillcolor="#b2d8ce", layer="below", line_width=0)

    # Έντονες μαύρες διαχωριστικές γραμμές
    for idx in range(len(ordered) - 1):
        if ordered[idx].split('_')[1] != ordered[idx+1].split('_')[1]:
            fig.add_shape(type="line", x0=0, x1=1, xref="paper", y0=idx+0.5, y1=idx+0.5, yref="y", line=dict(color="black", width=4))

    fig.update_traces(
        textposition='inside', insidetextanchor='middle', 
        textfont=dict(color='black', size=max(7, int(8.5*zoom_factor)), family="Arial Black"), 
        marker=dict(line=dict(color='black', width=1)),
        constraintext='none', hoverinfo='none'
    )

    fig.update_layout(
        bargap=0.15, showlegend=False, plot_bgcolor='#dbece8', paper_bgcolor='#ffffff', height=dyn_h, 
        margin=dict(l=10, r=10, t=50, b=10),
        dragmode='pan', # Ενεργοποίηση "μετακίνησης" μέσα στο παράθυρο
        xaxis=dict(
            side='top', tickformat="%H:%M", dtick=1800000, gridcolor='black', gridwidth=1, 
            range=[datetime(1970,1,1,6,0), datetime(1970,1,1,18,0)],
            tickfont=dict(size=max(8, int(10*zoom_factor)), color="black"),
            fixedrange=False
        ),
        yaxis=dict(
            tickmode='array', 
            tickvals=ordered, 
            ticktext=[tickvals_map.get(v, "") for v in ordered], 
            categoryorder='array', 
            categoryarray=ordered, 
            title="",
            tickfont=dict(size=max(8, int(11*zoom_factor)), color="black"),
            fixedrange=False # Επιτρέπει την κίνηση στον άξονα Υ
        )
    )

    event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", selection_mode="points", config={"displayModeBar": False})
    
    # Διαχείριση κλικ
    clicked_key = None
    if event and "selection" in event and event["selection"]["points"]:
        clicked_key = event["selection"]["points"][0].get("customdata", [None])[0]

    # --- 3.5 Interaction & Forms ---
    if not presentation_mode:
        st.divider()
        col_add, col_edit = st.columns(2)
        
        with col_add:
            st.subheader("+ Νέα Τοποθέτηση")
            with st.form("add_form", clear_on_submit=True):
                f_date = st.date_input("Ημερομηνία", value=selected_date)
                f_proj = st.selectbox("Έργο", [p['id'] for p in projects], format_func=lambda x: proj_lookup[x]['name'])
                f_emps = st.multiselect("Προσωπικό", [e['id'] for e in employees], format_func=lambda x: emp_lookup[x]['name'])
                f_color = st.selectbox("Χρώμα Μπάρας", list(BASIC_COLORS.keys()))
                f_notes = st.text_input("Παρατηρήσεις")
                c1, c2 = st.columns(2)
                f_start = c1.time_input("Έναρξη", datetime.strptime("09:00", "%H:%M").time())
                f_end = c2.time_input("Λήξη", datetime.strptime("17:00", "%H:%M").time())
                
                if st.form_submit_button("✅ Καταχώρηση"):
                    new_list = []
                    for eid in (f_emps if f_emps else [None]):
                        new_list.append({
                            'employeeId': eid, 'projectId': f_proj, 'date': f_date.isoformat(),
                            'startTime': f_start.strftime("%H:%M"), 'endTime': f_end.strftime("%H:%M"),
                            'notes': f_notes, 'colorHex': BASIC_COLORS[f_color], 'is_cancelled': False, 'colorName': f_color
                        })
                    db.init_supabase().table('assignments').insert(new_list).execute()
                    db.fetch_paginated.clear(); st.rerun()

        with col_edit:
            st.subheader("- Επεξεργασία")
            gkeys = list(wk_groups.keys())
            didx = gkeys.index(clicked_key) + 1 if clicked_key in gkeys else 0
            skey = st.selectbox("Επιλεγμένη Μπάρα", [""] + gkeys, index=didx, format_func=lambda x: "Επιλέξτε..." if x=="" else f"{wk_groups[x]['Project']} ({wk_groups[x]['StartTime']})")
            if skey:
                g = wk_groups[skey]
                with st.form("edit_form"):
                    e_notes = st.text_input("Σημειώσεις", value=g['Notes'])
                    e_canc = st.checkbox("Ακύρωση", value=g['is_cancelled'])
                    c1, c2 = st.columns(2)
                    if c1.form_submit_button("💾 Αποθήκευση"):
                        supa = db.init_supabase()
                        for aid in g['AssignmentIds']: supa.table('assignments').update({'notes': e_notes, 'is_cancelled': e_canc}).eq('id', aid).execute()
                        db.fetch_paginated.clear(); st.rerun()
                    if c2.form_submit_button("🗑️ Διαγραφή"):
                        db.init_supabase().table('assignments').delete().in_('id', g['AssignmentIds']).execute()
                        db.fetch_paginated.clear(); st.rerun()

# --- ΕΚΤΕΛΕΣΗ ---
render_dashboard()
gc.collect()
