import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, date, timedelta
import uuid
import io
import textwrap
import time

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
import scheduling  # Εισαγωγή του καθαρού module για βάρδιες/άδειες

utils.init_data_and_sync()

# ΑΥΤΟΜΑΤΗ ΕΠΙΔΙΟΡΘΩΣΗ (Self-Healing):
total_indexed = sum(len(v) for v in st.session_state.get('assignments_by_date', {}).values())
if total_indexed != len(st.session_state.get('assignments', [])):
    utils.mark_data_changed()
    utils.init_data_and_sync()

utils.setup_shared_ui()

# Helpers local access
is_full_admin = st.session_state.get('current_user') != "TAN"
active_employee_ids = [e['id'] for e in st.session_state.employees if e.get('status', 'Ενεργός') == 'Ενεργός']

# Μηχανισμός Κλειδώματος Εβδομάδας
if "view_week_date_val" not in st.session_state:
    st.session_state.view_week_date_val = date.today()

def go_prev_week():
    st.session_state.view_week_date_val -= timedelta(days=7)
def go_next_week():
    st.session_state.view_week_date_val += timedelta(days=7)
def go_to_today():
    st.session_state.view_week_date_val = date.today()

# --- VIEW: DASHBOARD (GANTT) ---
st.title("📊 Εβδομαδιαίο Χρονοδιάγραμμα Πόρων")

col_nav1, col_date, col_nav2, col_today, col_zoom, col_pres = st.columns([1, 2, 1, 1, 2, 2.5])
with col_nav1:
    st.write("")
    st.button("⬅️ Προηγούμενη", on_click=go_prev_week, use_container_width=True)
with col_date:
    selected_date = st.date_input("Επιλογή Εβδομάδας", value=st.session_state.view_week_date_val)
    if selected_date != st.session_state.view_week_date_val:
        st.session_state.view_week_date_val = selected_date
        st.rerun()
    start_of_week = st.session_state.view_week_date_val - timedelta(days=st.session_state.view_week_date_val.weekday())
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

zoom_factor = zoom_level / 100.0

current_gantt_params = {
    "week": start_of_week,
    "zoom": zoom_factor,
    "presentation": presentation_mode,
    "local_version": st.session_state.get('local_gantt_version', 0),
    "total_assigns": len(st.session_state.get('assignments', []))
}

if st.session_state.get('last_gantt_params') == current_gantt_params and 'cached_fig' in st.session_state and not st.session_state.get('data_dirty', False):
    fig = st.session_state.cached_fig
    wk_groups = st.session_state.cached_wk_groups
    export_data = st.session_state.cached_export_data
else:
    data = []
    export_data = []
    color_map = {}
    y_category_order = []
    tickvals_map = {}
    empty_shift_annotations = []
    wk_groups = {}
    
    day_names_gr = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
    for i in range(7):
        curr_date = start_of_week + timedelta(days=i)
        day_str = f"{day_names_gr[i]} {curr_date.strftime('%d/%m')}"
        leaves_today = []
        for l in st.session_state.leaves:
            if l['startDate'] <= curr_date <= l['endDate']:
                emp_full = utils.get_employee_name(l['employeeId'])
                emp_parts = emp_full.split()
                emp_n = f"{emp_parts[-1]} {emp_parts[0][0]}." if len(emp_parts) > 1 else emp_full
                sub_id = l.get('substituteId')
                if sub_id:
                    sub_full = utils.get_employee_name(sub_id)
                    sub_parts = sub_full.split()
                    sub_n = f"{sub_parts[-1]} {sub_parts[0][0]}." if len(sub_parts) > 1 else sub_full
                    leaves_today.append(f"{emp_n} (Αντ: {sub_n})")
                else:
                    leaves_today.append(f"{emp_n}")
        
        # --- ΛΟΓΙΚΗ: Εξωτερικό Συνεργείο Διαθέσιμο μετά τις 10:00 ---
        available_ext_crew = []
        leaves_dict = st.session_state.get('leaves_by_emp', {})
        day_assigns = st.session_state.get('assignments_by_date', {}).get(curr_date, [])
        
        for emp in st.session_state.employees:
            if emp.get('status', 'Ενεργός') == 'Ενεργός' and emp.get('is_external_crew', False):
                eid = emp['id']
                if scheduling.is_on_leave(eid, curr_date, leaves_dict):
                    continue
                
                is_busy_after_10 = False
                for a in day_assigns:
                    if a.get('employeeId') == eid and not a.get('is_cancelled', False):
                        if str(a.get('endTime', ''))[:5] > "10:00":
                            is_busy_after_10 = True
                            break
                
                if not is_busy_after_10:
                    emp_full = emp['name']
                    emp_parts = emp_full.split()
                    emp_n = f"{emp_parts[-1]} {emp_parts[0][0]}." if len(emp_parts) > 1 else emp_full
                    available_ext_crew.append(emp_n)

        # ΕΞΥΠΝΗ ΟΡΙΖΟΝΤΙΑ ΣΤΟΙΧΙΣΗ ΓΙΑ ΝΑ ΜΗΝ ΔΙΑΛΥΕΤΑΙ ΤΟ ΔΙΑΓΡΑΜΜΑ
        y_label_parts = [f"<b>{day_str}</b>"]
        
        if leaves_today:
            leaves_str = ", ".join(leaves_today)
            wrapped_leaves = "<br>".join(textwrap.wrap(leaves_str, width=35))
            y_label_parts.append(f"<span style='font-size:10px; color:#d32f2f;'>Άδειες:<br>{wrapped_leaves}</span>")
            
        if available_ext_crew:
            ext_str = ", ".join(available_ext_crew)
            wrapped_ext = "<br>".join(textwrap.wrap(ext_str, width=35))
            y_label_parts.append(f"<span style='font-size:10px; color:#0369a1;'>ΜΕΤΑ ΤΑ ΠΡΩΙΝΑ:<br><b>{wrapped_ext}</b></span>")
            
        base_y_label = "<br>".join(y_label_parts)
            
        day_row_ids = []
        
        if not day_assigns:
            row_id = f"day_{i}_row_0"
            day_row_ids.append(row_id)
        else:
            emp_day_assigns = {}
            for da in day_assigns:
                eid = da.get('employeeId')
                if eid:
                    if eid not in emp_day_assigns: emp_day_assigns[eid] = []
                    emp_day_assigns[eid].append(da)
                    
            groups = {}
            for a in day_assigns:
                proj = utils.get_project_info(a['projectId'])
                c_hex = a.get('colorHex', proj['color'] if proj else "#999999")
                c_name = a.get('colorName', "Προεπιλογή")
                notes = a.get('notes', "")
                is_canc = a.get('is_cancelled', False)
                c_reason = a.get('cancel_reason', "")
                arrival_time = a.get('arrivalTime', "")
                if arrival_time: arrival_time = arrival_time[:5]
                
                key = f"{curr_date}_{a['projectId']}_{a['startTime']}_{a['endTime']}_{c_hex}_{notes}_{is_canc}_{c_reason}_{arrival_time}"
                if key not in groups:
                    legend_val = f"{proj['name']} ({c_name})" if proj else "Άγνωστο"
                    groups[key] = {
                        'Key': key,
                        'ProjectId': a['projectId'],
                        'Date': curr_date,
                        'Project': proj['name'] if proj else "Άγνωστο",
                        'ArrivalTime': arrival_time,
                        'StartTime': str(a['startTime'])[:5],
                        'EndTime': str(a['endTime'])[:5],
                        'Start': datetime.combine(datetime(1970, 1, 1), datetime.strptime(str(a['startTime'])[:5], "%H:%M").time()),
                        'End': datetime.combine(datetime(1970, 1, 1), datetime.strptime(str(a['endTime'])[:5], "%H:%M").time()),
                        'Employees': [],
                        'EmployeeIds': [],
                        'AssignmentIds': [],
                        'ColorHex': c_hex,
                        'ColorName': c_name,
                        'Notes': notes,
                        'is_cancelled': is_canc,
                        'cancel_reason': c_reason,
                        'LegendGroup': legend_val
                    }
                
                if not a.get('employeeId'):
                    formatted_name = "ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ"
                else:
                    full_name = utils.get_employee_name(a['employeeId'])
                    name_parts = full_name.split()
                    if len(name_parts) > 1:
                        first_name_initial = name_parts[0][0] + "."
                        last_name = name_parts[-1]
                        formatted_name = f"{last_name} {first_name_initial}"
                    else:
                        formatted_name = full_name
                        
                prev_assigns = []
                my_eid = a.get('employeeId')
                if my_eid in emp_day_assigns:
                    t_a_start_str = str(a['startTime'])[:5]
                    t_a_end_str = str(a['endTime'])[:5]
                    for pa in emp_day_assigns[my_eid]:
                        if pa.get('id') != a['id']:
                            t_pa_start_str = str(pa['startTime'])[:5]
                            t_pa_end_str = str(pa['endTime'])[:5]
                            
                            pa_proj = utils.get_project_info(pa['projectId'])
                            a_proj = utils.get_project_info(a['projectId'])
                            pa_name = pa_proj['name'].strip().lower() if pa_proj else "1"
                            a_name = a_proj['name'].strip().lower() if a_proj else "2"
                            
                            is_diff_project = (pa_name != a_name)
                            starts_earlier_or_same = (t_pa_start_str <= t_a_start_str)
                            overlaps = (t_pa_end_str > t_a_start_str)
                            ends_later = (t_a_end_str > t_pa_end_str)
                            
                            if is_diff_project and starts_earlier_or_same and overlaps and ends_later:
                                prev_assigns.append(pa)
                                
                if prev_assigns:
                    prev_assigns.sort(key=lambda x: str(x['endTime'])[:5], reverse=True)
                    prev_proj = utils.get_project_info(prev_assigns[0]['projectId'])
                    if prev_proj:
                        formatted_name = f"[ΜΕΤΑ ΑΠΟ '{prev_proj['name']}' ▶ {formatted_name}]"
                        
                groups[key]['Employees'].append(formatted_name)
                groups[key]['EmployeeIds'].append(a['employeeId'])
                groups[key]['AssignmentIds'].append(a['id'])
                
            wk_groups.update(groups)
            
            non_blue_groups = [g for g in groups.values() if g['ColorHex'].lower() != "#4a86e8"]
            blue_groups = [g for g in groups.values() if g['ColorHex'].lower() == "#4a86e8"]
            
            non_blue_lanes = []
            group_row_mapping = []
            for g in sorted(non_blue_groups, key=lambda x: x['Start']):
                placed = False
                for lane_idx, lane_end in enumerate(non_blue_lanes):
                    if g['Start'] >= lane_end:
                        row_idx = lane_idx
                        non_blue_lanes[lane_idx] = g['End']
                        placed = True
                        break
                if not placed:
                    non_blue_lanes.append(g['End'])
                    row_idx = len(non_blue_lanes) - 1
                group_row_mapping.append((g, row_idx))
                
            num_non_blue_lanes = len(non_blue_lanes)
            blue_lanes = []
            for g in sorted(blue_groups, key=lambda x: x['Start']):
                placed = False
                for lane_idx, lane_end in enumerate(blue_lanes):
                    if g['Start'] >= lane_end:
                        row_idx = lane_idx
                        blue_lanes[lane_idx] = g['End']
                        placed = True
                        break
                if not placed:
                    blue_lanes.append(g['End'])
                    row_idx = len(blue_lanes) - 1
                group_row_mapping.append((g, row_idx + num_non_blue_lanes))
                
            for g, row_idx in group_row_mapping:
                row_id = f"day_{i}_row_{row_idx}"
                if row_id not in day_row_ids:
                    day_row_ids.append(row_id)
                    
                emps_str = ", ".join(g['Employees']).upper()
                proj_name = g['Project'].upper()
                arrival_str = f"[Προσ: {g['ArrivalTime']}] " if g['ArrivalTime'] else ""
                times_str = f"{arrival_str}{g['StartTime']}-{g['EndTime']}"
                base_text = f"{times_str} {proj_name} // {emps_str}"
                if g['Notes']:
                    base_text += f" ({g['Notes'].upper()})"
                
                duration_hours = (g['End'] - g['Start']).total_seconds() / 3600.0
                wrap_w = max(12, int(duration_hours * 13))
                wrapped_base = "<br>".join(textwrap.wrap(base_text, width=wrap_w))
                
                if "ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ" in emps_str:
                    empty_shift_annotations.append(dict(
                        x=g['End'], y=row_id, text="⚠️", showarrow=False, xanchor='right',
                        yanchor='middle', xshift=-4, yshift=int(28* zoom_factor), 
                        font=dict(size=max(10, int(14* zoom_factor)))
                    ))
                    
                if g['is_cancelled']:
                    label_text = f"<s>{wrapped_base}</s>"
                    if g['cancel_reason']:
                        wrapped_reason = "<br>".join(textwrap.wrap(f"[{g['cancel_reason'].upper()}]", width=wrap_w))
                        label_text += f"<br><span style='color:#dc2626;'><b>{wrapped_reason}</b></span>"
                else:
                    label_text = wrapped_base
                    
                data.append({
                    'Y_Axis': row_id,
                    'Έργο': g['Project'],
                    'Έναρξη': g['Start'],
                    'Λήξη': g['End'],
                    'Προσωπικό': ", ".join(g['Employees']),
                    'Προσέλευση': g['ArrivalTime'] if g['ArrivalTime'] else "-",
                    'Παρατηρήσεις': g['Notes'],
                    'Ετικέτα': label_text,
                    'LegendGroup': g['LegendGroup'],
                    'ColorHex': g['ColorHex'],
                    'GroupKey': g['Key']
                })
                
                export_data.append({
                    'Ημερομηνία': curr_date.strftime('%d/%m/%Y'),
                    'Ημέρα': day_names_gr[i],
                    'Έργο': g['Project'],
                    'Προσωπικό': ", ".join(g['Employees']),
                    'Ώρα Προσέλευσης': g['ArrivalTime'] if g['ArrivalTime'] else "-",
                    'Ώρα Έναρξης': g['StartTime'],
                    'Ώρα Λήξης': g['EndTime'],
                    'Παρατηρήσεις': g['Notes'],
                    'Ακυρωμένο': 'ΝΑΙ' if g['is_cancelled'] else 'ΟΧΙ',
                    'Λόγος Ακύρωσης': g['cancel_reason']
                })
                color_map[g['LegendGroup']] = g['ColorHex']
                
        y_category_order.extend(day_row_ids)
        mid_idx = len(day_row_ids) // 2
        for idx, rid in enumerate(day_row_ids):
            tickvals_map[rid] = base_y_label if idx == mid_idx else ""
            
    df = pd.DataFrame(data)

    if df.empty:
        df = pd.DataFrame(columns=[
            'Y_Axis', 'Έργο', 'Έναρξη', 'Λήξη', 'Προσωπικό', 
            'Προσέλευση', 'Παρατηρήσεις', 'Ετικέτα', 'LegendGroup', 
            'ColorHex', 'GroupKey'
        ])

    ordered_categories = y_category_order[::-1]
    
    fig = px.timeline(
        df, x_start="Έναρξη", x_end="Λήξη", y="Y_Axis",
        color="LegendGroup", color_discrete_map=color_map,
        custom_data=["GroupKey"], text="Ετικέτα"
    )
    
    for di in range(7):
        day_idxs = [idx for idx, val in enumerate(ordered_categories) if val.startswith(f"day_{di}_")]
        if day_idxs:
            mn, mx = min(day_idxs), max(day_idxs)
            if di % 2 != 0:
                fig.add_hrect(y0=mn-0.5, y1=mx+0.5, fillcolor="rgba(0,0,0,0.05)", opacity=1, layer="below", line_width=0)
            if (start_of_week + timedelta(days=di)) == date.today():
                fig.add_hrect(y0=mn-0.5, y1=mx+0.5, fillcolor="#b2d8ce", opacity=1, layer="below", line_width=0)
                
    for idx in range(len(ordered_categories) - 1):
        if ordered_categories[idx].split('_')[1] != ordered_categories[idx+1].split('_')[1]:
            fig.add_shape(type="line", x0=0, x1=1, xref="paper", y0=idx+0.5, y1=idx+0.5, yref="y", line=dict(color="#000000", width=4))
            
    row_h = 50 * zoom_factor
    margin_top = 50
    margin_bottom = 10
    
    dyn_h = int(len(ordered_categories) * row_h) + margin_top + margin_bottom
    dyn_h = max(250, dyn_h)
    
    # Κλείδωμα της κάθετης μετακίνησης (Y-axis)
    y_range = [-0.5, len(ordered_categories) - 0.5]
            
    fig.update_yaxes(
        categoryorder='array', categoryarray=ordered_categories,
        tickmode='array', tickvals=ordered_categories,
        ticktext=[tickvals_map[v] for v in ordered_categories],
        showgrid=True, gridcolor='rgba(0,0,0,0.1)', gridwidth=1,
        automargin=True,
        range=y_range,
        fixedrange=True  # ΚΛΕΙΔΩΜΑ ΚΑΘΕΤΗΣ ΜΕΤΑΚΙΝΗΣΗΣ!
    )
    fig.update_traces(
        textposition='inside', insidetextanchor='middle',
        textfont=dict(color='black', size=max(8, int(9*zoom_factor)), family="Arial Black, Arial, sans-serif"),
        marker=dict(line=dict(color='black', width=1)), textangle=0, constraintext='none',
        hoverinfo='none', hovertemplate=None,
        selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=1))
    )
    fig.update_layout(
        bargap=0.02, 
        showlegend=False, 
        plot_bgcolor='#dbece8', 
        paper_bgcolor='rgba(0,0,0,0)', # ΔΙΑΦΑΝΕΣ ΦΟΝΤΟ για να φαίνεται η χρωματική διαβάθμιση από πίσω
        height=dyn_h, 
        margin=dict(l=10, r=10, t=50, b=10),
        annotations=empty_shift_annotations, 
        dragmode="pan", 
        clickmode="event+select",
        uirevision="constant",
        xaxis=dict(
            side='top', tickmode='linear', tick0="1970-01-01 00:00:00", dtick=1800000,
            tickformat="%H:%M", showgrid=True, gridcolor='black', gridwidth=1,
            autorange=False, 
            range=["1970-01-01 06:00:00", "1970-01-01 16:00:00"], # Καθαρή ορατή περιοχή
            title="",
            tickfont=dict(size=max(8, int(11*zoom_factor)), color="black", family="Arial"),
            fixedrange=False, # ΕΛΕΥΘΕΡΗ ΟΡΙΖΟΝΤΙΑ ΜΕΤΑΚΙΝΗΣΗ
            rangeslider=dict(visible=False)
        )
    )
    st.session_state.cached_fig = fig
    st.session_state.cached_wk_groups = wk_groups
    st.session_state.cached_export_data = export_data
    st.session_state.last_gantt_params = current_gantt_params

clicked_key = None

# --- ΜΑΓΙΚΟ CSS ΓΙΑ ΤΟ ΕΞΩΤΕΡΙΚΟ ΠΑΡΑΘΥΡΟ (ΚΥΛΙΟΜΕΝΟ ΔΟΧΕΙΟ) ---
st.markdown("""
<style>
/* Στοχεύει το εσωτερικό παράθυρο κύλισης (container) που περιέχει το γράφημα Plotly */
div[data-testid="stVerticalBlockBorderWrapper"]:has(.stPlotlyChart) {
    border: 3px solid #334155 !important; /* Έντονο σκούρο γκρι/μπλε περίγραμμα */
    border-radius: 12px !important;       /* Πιο στρογγυλεμένες γωνίες */
    background: linear-gradient(180deg, #f8fafc 0%, #e2e8f0 100%) !important; /* Απαλή χρωματική διαβάθμιση */
    box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1) !important; /* Ελαφριά σκιά 3D */
    padding: 2px !important;
}
</style>
""", unsafe_allow_html=True)

# Τοποθετούμε το διάγραμμα σε ένα κυλιόμενο δοχείο (εσωτερικό παράθυρο)
with st.container(height=650, border=True):
    try:
        event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", selection_mode="points", config={"displayModeBar": False})
        if event and "selection" in event:
            if event["selection"].get("points"):
                cd = event["selection"]["points"][0].get("customdata", [None])[0]
                if cd != "Empty": clicked_key = cd
                else: clicked_key = None
    except Exception:
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

if clicked_key:
    st.markdown('<div id="is_editing_flag" style="display:none;"></div>', unsafe_allow_html=True)

hint_text = "💡 *Συμβουλές:* **1)** Κλικ σε μπάρα για επεξεργασία. **2)** Σύρετε το διάγραμμα (Pan) δεξιά-αριστερά για τον χρόνο. **3)** Σύρετε την κύλιση δίπλα στο διάγραμμα (Scroll) για να δείτε όλες τις μέρες."

if export_data:
    col_hint, col_btn = st.columns([3, 1])
    with col_hint: st.caption(hint_text)
    with col_btn:
        df_export = pd.DataFrame(export_data)
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False, sheet_name='Πρόγραμμα')
        st.download_button(
            label="📥 Εξαγωγή Προγράμματος (Excel)", data=buffer.getvalue(),
            file_name=f"Gantt_Programma_{start_of_week.strftime('%d_%m_%Y')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
else:
    st.caption(hint_text)

if not presentation_mode:
    st.divider()
    if is_full_admin:
        col_add, col_edit = st.columns(2)
        with col_add:
            st.subheader("➕ Νέα Τοποθέτηση")
            if "qa_rc" not in st.session_state: st.session_state.qa_rc = 0
            qa_rc = st.session_state.qa_rc
            
            with st.form("quick_add", clear_on_submit=True):
                add_date = st.date_input("Ημερομηνία", value=selected_date, key=f"qa_date_{qa_rc}")
                proj_choice = st.selectbox("Επιλογή Έργου (Από Λίστα)", options=[p['id'] for p in st.session_state.projects], format_func=utils.get_project_name, key=f"qa_proj_{qa_rc}")
                custom_proj_name = st.text_input("Ή πληκτρολογήστε Νέο Έργο (Αν συμπληρωθεί, αγνοεί την παραπάνω λίστα)", key=f"qa_cproj_{qa_rc}")
                emp_choices = st.multiselect("Προσωπικό (Προαιρετικό - Μόνο Ενεργοί)", options=active_employee_ids, format_func=utils.get_employee_name, key=f"qa_emps_{qa_rc}")
                c_color, c_notes = st.columns(2)
                with c_color: color_choice = st.selectbox("Χρώμα Μπάρας", options=list(config.BASIC_COLORS.keys()), key=f"qa_color_{qa_rc}")
                with c_notes: add_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", key=f"qa_notes_{qa_rc}")
                c_arr, c_start, c_end = st.columns(3)
                with c_arr:
                    use_arr = st.checkbox("Προσέλευση;", key=f"chk_arr_{qa_rc}")
                    t_arrival = st.time_input("Ώρα Προσέλευσης", value=datetime.strptime("08:00", "%H:%M").time(), key=f"qa_arrival_{qa_rc}")
                with c_start:
                    t_start = st.time_input("Έναρξη", value=datetime.strptime("09:00", "%H:%M").time(), key=f"qa_start_{qa_rc}")
                with c_end:
                    t_end = st.time_input("Λήξη", value=datetime.strptime("17:00", "%H:%M").time(), key=f"qa_end_{qa_rc}")
                
                if st.form_submit_button("Καταχώρηση"):
                    str_arrival = t_arrival.strftime("%H:%M") if use_arr else ""
                    str_start = t_start.strftime("%H:%M")
                    str_end = t_end.strftime("%H:%M")
                    if str_start >= str_end:
                        st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                    else:
                        emps_to_process = emp_choices if emp_choices else [""]
                        valid_assignments = []
                        for eid in emps_to_process:
                            if eid:
                                emp_name = utils.get_employee_name(eid)
                                if scheduling.is_on_leave(eid, add_date, st.session_state.leaves_by_emp):
                                    valid_assignments.append({'eid': "", 'start': str_start, 'end': str_end, 'msg': f"[Άδεια: {emp_name}]", 'emp_name': emp_name})
                                    st.toast(f"Ο/Η {emp_name} έχει άδεια. Καταχωρήθηκε ως 'Χωρίς Προσωπικό'.", icon="⚠️")
                                else:
                                    day_assigns = st.session_state.assignments_by_date.get(add_date, [])
                                    adj_start, adj_end, is_conflict, msg = scheduling.check_and_resolve_conflict(eid, str_start, str_end, day_assigns)
                                    if is_conflict:
                                        valid_assignments.append({'eid': "", 'start': str_start, 'end': str_end, 'msg': f"[Εμπλοκή: {emp_name}]", 'emp_name': emp_name})
                                        st.toast(f"Διπλοκράτηση {emp_name}. Καταχωρήθηκε ως 'Χωρίς Προσωπικό'.", icon="⚠️")
                                    else:
                                        valid_assignments.append({'eid': eid, 'start': adj_start, 'end': adj_end, 'msg': msg, 'emp_name': emp_name})
                            else:
                                valid_assignments.append({'eid': "", 'start': str_start, 'end': str_end, 'msg': "", 'emp_name': ""})
                                
                        if custom_proj_name.strip():
                            c_name = custom_proj_name.strip()
                            existing_p = next((p for p in st.session_state.projects if p['name'].strip().lower() == c_name.lower()), None)
                            if existing_p:
                                final_proj_id = existing_p['id']
                            else:
                                final_proj_id = str(uuid.uuid4())
                                new_p = {'id': final_proj_id, 'name': c_name, 'color': config.BASIC_COLORS[color_choice]}
                                st.session_state.projects.append(new_p)
                                utils.db_insert('projects', new_p, track=False)
                        else:
                            final_proj_id = proj_choice
                            
                        new_assigns = []
                        for va in valid_assignments:
                            if va['msg'] == "Allowed Overlap": st.toast(f"ℹ️ Επιτράπηκε επικάλυψη ωραρίου για τον/την {va['emp_name']}.", icon="ℹ️")
                            
                            c_notes = add_notes
                            if va['msg'] and va['msg'] != "Allowed Overlap":
                                c_notes = f"{add_notes} {va['msg']}".strip()
                                
                            new_assign = {
                                'id': str(uuid.uuid4()), 'employeeId': va['eid'], 'projectId': final_proj_id,
                                'date': add_date, 'arrivalTime': str_arrival, 'startTime': va['start'], 'endTime': va['end'],
                                'colorName': color_choice, 'colorHex': config.BASIC_COLORS[color_choice],
                                'notes': c_notes, 'is_cancelled': False, 'cancel_reason': "", 'recurring_id': None
                            }
                            new_assigns.append(new_assign)
                            st.session_state.assignments.append(new_assign)
                        utils.db_insert("assignments", new_assigns, track=False)
                        st.success("Η ανάθεση ολοκληρώθηκε!")
                        time.sleep(0.5)
                        st.session_state.qa_rc += 1
                        st.rerun()

        with col_edit:
            st.subheader("✏️ Επεξεργασία Μπάρας της Εβδομάδας")
            if not wk_groups:
                st.info("Δεν υπάρχουν μπάρες για επεξεργασία αυτή την εβδομάδα.")
            else:
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
                        has_error = False
                        new_assigns, old_assigns = [], []
                        
                        for a_id in target_group['AssignmentIds']:
                            orig_a = next(a for a in st.session_state.assignments if a['id'] == a_id)
                            new_a = dict(orig_a)
                            if delta_days != 0: new_a['date'] = orig_a['date'] + timedelta(days=delta_days)
                            if delta_hours != 0:
                                dummy_date = datetime(2000, 1, 1)
                                s_dt = datetime.combine(dummy_date, datetime.strptime(str(orig_a['startTime'])[:5], "%H:%M").time())
                                e_dt = datetime.combine(dummy_date, datetime.strptime(str(orig_a['endTime'])[:5], "%H:%M").time())
                                new_s_dt = s_dt + timedelta(hours=delta_hours)
                                new_e_dt = e_dt + timedelta(hours=delta_hours)
                                if new_s_dt.date() != dummy_date.date() or new_e_dt.date() != dummy_date.date():
                                    st.error("Η αλλαγή ώρας ξεπερνάει τα όρια της ημέρας.")
                                    has_error = True; break
                                new_a['startTime'] = new_s_dt.strftime("%H:%M")
                                new_a['endTime'] = new_e_dt.strftime("%H:%M")
                                if orig_a.get('arrivalTime'):
                                    arr_dt = datetime.combine(dummy_date, datetime.strptime(str(orig_a['arrivalTime'])[:5], "%H:%M").time())
                                    new_a['arrivalTime'] = (arr_dt + timedelta(hours=delta_hours)).strftime("%H:%M")
                                    
                            if new_a['employeeId']:
                                emp_name = utils.get_employee_name(new_a['employeeId'])
                                if scheduling.is_on_leave(new_a['employeeId'], new_a['date'], st.session_state.leaves_by_emp):
                                    st.toast(f"Αδύνατη μετακίνηση: Ο/Η {emp_name} έχει άδεια!", icon="❌")
                                    has_error = True; break
                                
                                day_assigns = st.session_state.assignments_by_date.get(new_a['date'], [])
                                adj_start, adj_end, is_conflict, msg = scheduling.check_and_resolve_conflict(new_a['employeeId'], new_a['startTime'], new_a['endTime'], day_assigns, exclude_ids=target_group['AssignmentIds'])
                                if is_conflict:
                                    st.toast(f"Αδύνατη μετακίνηση: Διπλοκράτηση {emp_name}!", icon="⚠️")
                                    has_error = True; break
                                new_a['startTime'], new_a['endTime'] = adj_start, adj_end
                                if msg == "Allowed Overlap": st.toast(f"ℹ️ Επιτράπηκε επικάλυψη ωραρίου ({emp_name}).", icon="ℹ️")
                                
                            old_assigns.append(orig_a)
                            new_assigns.append(new_a)
                            
                        if not has_error:
                            for old_a, new_a in zip(old_assigns, new_assigns):
                                utils.db_update('assignments', new_a['id'], new_a, old_data=old_a, track=False)
                            st.session_state.assignments = [a for a in st.session_state.assignments if a['id'] not in target_group['AssignmentIds']]
                            st.session_state.assignments.extend(new_assigns)
                            st.rerun()

                    with st.form("quick_edit"):
                        edit_date = st.date_input("Αλλαγή Ημερομηνίας", value=target_group['Date'])
                        proj_ids = [p['id'] for p in st.session_state.projects]
                        default_proj_idx = proj_ids.index(target_group['ProjectId']) if target_group['ProjectId'] in proj_ids else 0
                        edit_proj = st.selectbox("Αλλαγή Έργου (Από Λίστα)", options=proj_ids, index=default_proj_idx, format_func=utils.get_project_name)
                        edit_custom_proj_name = st.text_input("Ή πληκτρολογήστε Νέο Έργο (προαιρετικό)")
                        
                        valid_emp_ids = [eid for eid in target_group['EmployeeIds'] if eid]
                        edit_options = list(set(active_employee_ids + valid_emp_ids))
                        edit_emps = st.multiselect("Αλλαγή Προσωπικού (Προαιρετικό)", options=edit_options, default=valid_emp_ids, format_func=utils.get_employee_name)
                        
                        e_color_col, e_notes_col = st.columns(2)
                        with e_color_col:
                            default_color_idx = list(config.BASIC_COLORS.keys()).index(target_group['ColorName']) if target_group['ColorName'] in config.BASIC_COLORS else 0
                            edit_color = st.selectbox("Αλλαγή Χρώματος", options=list(config.BASIC_COLORS.keys()), index=default_color_idx)
                        with e_notes_col:
                            edit_notes = st.text_input("Παρατηρήσεις (Προαιρετικό)", value=target_group['Notes'])
                            
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
                            old_assigns = [a for a in st.session_state.assignments if a['id'] in target_group['AssignmentIds']]
                            st.session_state.assignments = [a for a in st.session_state.assignments if a['id'] not in target_group['AssignmentIds']]
                            utils.db_delete_in('assignments', 'id', target_group['AssignmentIds'], deleted_records=old_assigns)
                            st.rerun()
                            
                        if save_edit:
                            str_arrival = new_t_arrival.strftime("%H:%M") if use_arr_edit else ""
                            str_start = new_t_start.strftime("%H:%M")
                            str_end = new_t_end.strftime("%H:%M")
                            if str_start >= str_end:
                                st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                            else:
                                emps_to_process = edit_emps if edit_emps else [""]
                                valid_assignments = []
                                for eid in emps_to_process:
                                    if eid:
                                        emp_name = utils.get_employee_name(eid)
                                        if scheduling.is_on_leave(eid, edit_date, st.session_state.leaves_by_emp):
                                            valid_assignments.append({'eid': "", 'start': str_start, 'end': str_end, 'msg': f"[Άδεια: {emp_name}]", 'emp_name': emp_name})
                                            st.toast(f"Ο/Η {emp_name} έχει άδεια. Καταχωρήθηκε ως 'Χωρίς Προσωπικό'.", icon="⚠️")
                                        else:
                                            day_assigns = st.session_state.assignments_by_date.get(edit_date, [])
                                            adj_start, adj_end, is_conflict, msg = scheduling.check_and_resolve_conflict(eid, str_start, str_end, day_assigns, exclude_ids=target_group['AssignmentIds'])
                                            if is_conflict:
                                                valid_assignments.append({'eid': "", 'start': str_start, 'end': str_end, 'msg': f"[Εμπλοκή: {emp_name}]", 'emp_name': emp_name})
                                                st.toast(f"Διπλοκράτηση {emp_name}. Καταχωρήθηκε ως 'Χωρίς Προσωπικό'.", icon="⚠️")
                                            else:
                                                valid_assignments.append({'eid': eid, 'start': adj_start, 'end': adj_end, 'msg': msg, 'emp_name': emp_name})
                                    else:
                                        valid_assignments.append({'eid': "", 'start': str_start, 'end': str_end, 'msg': "", 'emp_name': ""})
                                        
                                if edit_custom_proj_name.strip():
                                    c_name = edit_custom_proj_name.strip()
                                    existing_p = next((p for p in st.session_state.projects if p['name'].strip().lower() == c_name.lower()), None)
                                    if existing_p:
                                        final_edit_proj_id = existing_p['id']
                                    else:
                                        final_edit_proj_id = str(uuid.uuid4())
                                        new_p = {'id': final_edit_proj_id, 'name': c_name, 'color': config.BASIC_COLORS[edit_color]}
                                        st.session_state.projects.append(new_p)
                                        utils.db_insert('projects', new_p, track=False)
                                else:
                                    final_edit_proj_id = edit_proj
                                    
                                old_assigns = [a for a in st.session_state.assignments if a['id'] in target_group['AssignmentIds']]
                                st.session_state.assignments = [a for a in st.session_state.assignments if a['id'] not in target_group['AssignmentIds']]
                                utils.db_delete_in('assignments', 'id', target_group['AssignmentIds'], deleted_records=old_assigns, track=False)
                                
                                new_assigns = []
                                for va in valid_assignments:
                                    if va['msg'] == "Allowed Overlap": st.toast(f"ℹ️ Επιτράπηκε επικάλυψη ωραρίου: {va['emp_name']} ({va['start']})", icon="ℹ️")
                                    
                                    c_notes = edit_notes
                                    if va['msg'] and va['msg'] != "Allowed Overlap":
                                        c_notes = f"{edit_notes} {va['msg']}".strip()
                                        
                                    new_a = {
                                        'id': str(uuid.uuid4()), 'employeeId': va['eid'], 'projectId': final_edit_proj_id,
                                        'date': edit_date, 'arrivalTime': str_arrival, 'startTime': va['start'], 'endTime': va['end'],
                                        'colorName': edit_color, 'colorHex': config.BASIC_COLORS[edit_color], 'notes': c_notes,
                                        'is_cancelled': e_is_cancelled, 'cancel_reason': e_cancel_reason if e_is_cancelled else "", 'recurring_id': None
                                    }
                                    new_assigns.append(new_a)
                                    st.session_state.assignments.append(new_a)
                                utils.db_insert('assignments', new_assigns, track=False)
                                st.rerun()
