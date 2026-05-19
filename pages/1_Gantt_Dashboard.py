import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import uuid
import io
import textwrap
import time
import re
import urllib.parse

# --- INITIALIZATION & ΑΣΠΙΔΑ ΑΣΦΑΛΕΙΑΣ ---
if "authenticated" not in st.session_state: st.session_state.authenticated = False
if "employees" not in st.session_state: st.session_state.employees = []
if "projects" not in st.session_state: st.session_state.projects = []
if "assignments" not in st.session_state: st.session_state.assignments = []
if "leaves" not in st.session_state: st.session_state.leaves = []
if "recurring_patterns" not in st.session_state: st.session_state.recurring_patterns = []
if "evaluations" not in st.session_state: st.session_state.evaluations = []

if not st.session_state.get("authenticated"):
    st.switch_page("streamlit_app.py")
    st.stop()

import config
import utils
import scheduling
import gantt_engine

def get_local_today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Athens")).date()
    except Exception:
        return (datetime.utcnow() + timedelta(hours=3)).date()

utils.init_data_and_sync()

total_indexed = sum(len(v) for v in st.session_state.get('assignments_by_date', {}).values())
if total_indexed != len(st.session_state.get('assignments', [])):
    utils.mark_data_changed()
    utils.init_data_and_sync()

utils.setup_shared_ui()

is_full_admin = st.session_state.get('current_user') != "TAN"
active_employee_ids = [e['id'] for e in st.session_state.employees if e.get('status', 'Ενεργός') == 'Ενεργός']

# --- ΜΗΧΑΝΙΣΜΟΣ ΗΜΕΡΟΜΗΝΙΑΣ ---
if "view_week_date" not in st.session_state:
    st.session_state.view_week_date = get_local_today()

def sync_from_widget():
    st.session_state.view_week_date = st.session_state.date_picker

def go_prev_week():
    new_date = st.session_state.view_week_date - timedelta(days=7)
    st.session_state.view_week_date = new_date
    st.session_state.date_picker = new_date

def go_next_week():
    new_date = st.session_state.view_week_date + timedelta(days=7)
    st.session_state.view_week_date = new_date
    st.session_state.date_picker = new_date

def go_to_today():
    new_date = get_local_today()
    st.session_state.view_week_date = new_date
    st.session_state.date_picker = new_date

# --- ΣΥΜΠΙΕΣΗ ΤΟΥ ΠΑΝΩ ΜΕΡΟΥΣ ΣΕ ΜΙΑ ΣΥΜΠΑΓΗ ΓΡΑΜΜΗ (Compact UI) ---
st.markdown("""
<style>
.block-container, [data-testid="block-container"] {
    max-width: 98% !important; 
    padding-top: 0.5rem !important;
    padding-bottom: 0.5rem !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
}
div[data-testid="stNotification"], .stAlert {
    padding: 2px 10px !important;
    margin-top: 0px !important;
    margin-bottom: 2px !important;
}
div[data-testid="stNotification"] p, .stAlert p {
    margin: 0 !important;
    font-size: 13px !important;
}
</style>
""", unsafe_allow_html=True)

st.markdown("<h3 style='margin-top: -30px; margin-bottom: 5px;'>📊 Εβδομαδιαίο Χρονοδιάγραμμα Πόρων</h3>", unsafe_allow_html=True)

col_date, col_nav1, col_nav2, col_today, col_zoom, col_pres = st.columns([1.5, 0.8, 0.8, 0.8, 1.5, 1.5])
with col_date:
    selected_date = st.date_input("Εβδομάδα", value=st.session_state.view_week_date, key="date_picker", on_change=sync_from_widget, label_visibility="collapsed")
    start_of_week = st.session_state.view_week_date - timedelta(days=st.session_state.view_week_date.weekday())
with col_nav1:
    st.button("⬅️ Πριν", on_click=go_prev_week, use_container_width=True)
with col_nav2:
    st.button("Μετά ➡️", on_click=go_next_week, use_container_width=True)
with col_today:
    st.button("📅 Σήμερα", on_click=go_to_today, use_container_width=True)
with col_zoom:
    zoom_level = st.slider("Ζουμ", min_value=50, max_value=200, value=100, step=5, label_visibility="collapsed")
with col_pres:
    presentation_mode = st.checkbox("📺 Πλήρης Προβολή")

zoom_factor = zoom_level / 100.0

# --- ΕΞΑΓΩΓΗ ΔΕΔΟΜΕΝΩΝ ΑΠΟ ΤΟ ENGINE ---
@st.cache_data(show_spinner=False, max_entries=5)
def get_cached_data(start_of_week, zoom_factor, presentation_mode, data_version, _assignments_by_date, _leaves, _employees, _projects, _emp_map, _proj_map):
    _, wk_groups, export_data = gantt_engine.generate_gantt_chart(start_of_week, zoom_factor, presentation_mode, data_version, _assignments_by_date, _leaves, _employees, _projects, _emp_map, _proj_map)
    return wk_groups, export_data

wk_groups, export_data = get_cached_data(
    start_of_week, zoom_factor, presentation_mode, st.session_state.get('local_gantt_version', 0),
    st.session_state.assignments_by_date, st.session_state.leaves, st.session_state.employees, st.session_state.projects, st.session_state.emp_map, st.session_state.proj_map
)

# --- ΔΙΑΒΑΣΜΑ ΤΟΥ ΚΛΙΚ ΑΠΟ ΤΟ URL (st.query_params) ---
clicked_key = st.query_params.get("edit_key", None)


# --- NATIVE HTML GANTT CHART BUILDER ---
def build_html_gantt(wk_groups, start_of_week, zoom_factor):
    # Επέκταση σε 20 ώρες (04:00 - 24:00) για να φαίνεται η βάρδια των 04:45
    min_width_px = int(2400 * zoom_factor) 
    day_names_gr = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]

    emp_short_names = {}
    external_crews = []
    for emp in st.session_state.employees:
        eid = emp['id']
        full_name = emp['name']
        parts = full_name.split()
        emp_short_names[eid] = f"{parts[-1]} {parts[0][0]}." if len(parts) > 1 else full_name
        if emp.get('status', 'Ενεργός') == 'Ενεργός' and emp.get('is_external_crew', False):
            external_crews.append(emp)

    def is_on_leave_fast(eid, check_date):
        for l in st.session_state.leaves:
            if l['employeeId'] == eid and l['startDate'] <= check_date <= l['endDate']:
                return True
        return False

    html = [f"""
    <!DOCTYPE html>
    <html>
    <head>
    <style>
    body {{ margin: 0; padding: 0; background: transparent; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }}
    
    .mygantt-container {{ width: 100%; height: 640px; overflow: auto; border: 4px solid #1e293b; border-radius: 12px; box-shadow: 0px 12px 35px rgba(0,0,0,0.4); position: relative; background: #ffffff; box-sizing: border-box; user-select: none; scroll-behavior: smooth; }}
    
    .mygantt-container::-webkit-scrollbar {{ width: 12px; height: 12px; }}
    .mygantt-container::-webkit-scrollbar-track {{ background: #f1f5f9; border-radius: 8px; }}
    .mygantt-container::-webkit-scrollbar-thumb {{ background: #94a3b8; border-radius: 8px; border: 3px solid #f1f5f9; }}
    .mygantt-container::-webkit-scrollbar-thumb:hover {{ background: #64748b; }}

    .mygantt-header {{ position: sticky; top: 0; z-index: 50; display: flex; width: max-content; min-width: 100%; background: #ffffff; border-bottom: 3px solid #1e293b; }}
    .mygantt-header-corner {{ position: sticky; left: 0; z-index: 60; width: 230px; flex-shrink: 0; background: #ffffff; border-right: 3px solid #1e293b; }}
    .mygantt-header-timeline {{ position: relative; height: 40px; width: {min_width_px}px; flex-grow: 1; background: #ffffff; }}
    .mygantt-tick {{ position: absolute; border-left: 2px solid #94a3b8; height: 100%; padding-left: 4px; font-size: 13px; font-weight: bold; color: #334155; padding-top: 10px; }}
    
    .mygantt-row {{ display: flex; width: max-content; min-width: 100%; border-bottom: 2px solid #e2e8f0; }}
    .mygantt-row-odd {{ background-color: #ffffff; }}
    .mygantt-row-even {{ background-color: #f8fafc; }}
    .mygantt-row-today {{ background-color: #eef2ff !important; }}
    
    .mygantt-left {{ position: sticky; left: 0; z-index: 40; width: 230px; flex-shrink: 0; padding: 10px; border-right: 3px solid #1e293b; font-size: 12px; box-sizing: border-box; }}
    .mygantt-row-odd .mygantt-left {{ background-color: #ffffff; }}
    .mygantt-row-even .mygantt-left {{ background-color: #f8fafc; }}
    .mygantt-row-today .mygantt-left {{ background-color: #eef2ff; border-right: 3px solid #4f46e5; }}

    /* Προσαρμογή του πλέγματος για 20 ώρες (04:00 - 24:00) */
    .mygantt-lanes {{ position: relative; width: {min_width_px}px; flex-grow: 1; background-size: calc(100% / 20) 100%; background-image: linear-gradient(to right, rgba(148, 163, 184, 0.3) 1px, transparent 1px); padding-top: 10px; padding-bottom: 10px; }}
    
    .mygantt-bar {{ position: absolute; height: 38px; border: 1px solid black; border-radius: 6px; box-shadow: 0 4px 6px rgba(0,0,0,0.2); display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: bold; color: black !important; text-decoration: none !important; cursor: pointer; transition: transform 0.1s; box-sizing: border-box; overflow: hidden; z-index: 10; }}
    .mygantt-bar:hover {{ transform: scale(1.02); z-index: 30; box-shadow: 0 6px 12px rgba(0,0,0,0.3); outline: 2px solid #1e293b; }}
    .mygantt-bar-text {{ text-align: center; line-height: 1.2; pointer-events: none; width: 100%; padding: 0 4px; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }}
    </style>
    </head>
    <body>
    <div class="mygantt-container" id="mygantt">
    """]

    html.append('<div class="mygantt-header"><div class="mygantt-header-corner"></div><div class="mygantt-header-timeline">')
    # Ώρες 04:00 έως 24:00 (20 ώρες σύνολο)
    for h in range(4, 25):
        pct = ((h - 4) / 20) * 100
        lbl = f"{h:02d}:00" if h < 24 else "00:00"
        html.append(f'<div class="mygantt-tick" style="left: {pct}%;">{lbl}</div>')
    html.append('</div></div>')

    for i in range(7):
        curr_date = start_of_week + timedelta(days=i)
        day_str = f"{day_names_gr[i]} {curr_date.strftime('%d/%m')}"

        leaves_today = []
        for l in st.session_state.leaves:
            if l['startDate'] <= curr_date <= l['endDate']:
                emp_n = emp_short_names.get(l['employeeId'], utils.get_employee_name(l['employeeId']))
                sub_id = l.get('substituteId')
                if sub_id:
                    sub_n = emp_short_names.get(sub_id, utils.get_employee_name(sub_id))
                    leaves_today.append(f"{emp_n} (Αντ: {sub_n})")
                else:
                    leaves_today.append(f"{emp_n}")

        available_ext_crew = []
        day_assigns = st.session_state.assignments_by_date.get(curr_date, [])
        for emp in external_crews:
            eid = emp['id']
            if is_on_leave_fast(eid, curr_date): continue
            is_busy_after_10 = False
            for a in day_assigns:
                if a.get('employeeId') == eid and not a.get('is_cancelled', False):
                    if str(a.get('endTime', ''))[:5] > "10:00":
                        is_busy_after_10 = True
                        break
            if not is_busy_after_10:
                available_ext_crew.append(emp_short_names.get(eid, emp['name']))

        label_html = f"<div style='font-size: 14px; font-weight: bold; margin-bottom: 8px;'>🗓️ {day_str}</div>"
        if leaves_today:
            label_html += f"<div style='color: #d32f2f; margin-bottom: 8px; font-size: 11px;'><b>Άδειες:</b><br>{'<br>'.join(leaves_today)}</div>"
        if available_ext_crew:
            label_html += f"<div style='color: #0369a1; font-size: 11px;'><b>ΜΕΤΑ ΤΑ ΠΡΩΙΝΑ:</b><br>{'<br>'.join(available_ext_crew)}</div>"

        day_groups = [g for g in wk_groups.values() if g['Date'] == curr_date]
        lanes = []
        group_lanes = []
        for g in sorted(day_groups, key=lambda x: x['StartTime']):
            placed = False
            for idx, lane_end in enumerate(lanes):
                if g['StartTime'] >= lane_end:
                    lanes[idx] = g['EndTime']
                    group_lanes.append((g, idx))
                    placed = True
                    break
            if not placed:
                lanes.append(g['EndTime'])
                group_lanes.append((g, len(lanes)-1))

        num_lanes = max(1, len(lanes))
        row_height = num_lanes * 48 + 20 
        
        row_class = "mygantt-row-today" if curr_date == get_local_today() else ("mygantt-row-even" if i%2==1 else "mygantt-row-odd")

        html.append(f'<div class="mygantt-row {row_class}" style="min-height: {row_height}px;">')
        html.append(f'<div class="mygantt-left">{label_html}</div>')
        html.append('<div class="mygantt-lanes">')

        for g, lane_idx in group_lanes:
            def t2p(t_str):
                h, m = map(int, t_str.split(':'))
                if h < 4: h += 24 # Χειρισμός για βάρδιες που περνάνε τα μεσάνυχτα
                mins = (h - 4) * 60 + m # Η βάση είναι 04:00
                return max(0, min(100, (mins / 1200.0) * 100)) # 1200 mins = 20 ώρες

            left_pct = t2p(g['StartTime'])
            right_pct = t2p(g['EndTime'])
            width_pct = right_pct - left_pct
            top_px = lane_idx * 48 + 10 

            emps_str = ", ".join(g['Employees']).upper()
            proj_name = g['Project'].upper()
            arr_str = f"[Προσ: {g['ArrivalTime']}] " if g['ArrivalTime'] else ""
            
            if "ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ" in emps_str:
                emps_str = "⚠️ " + emps_str

            base_text = f"{arr_str}{g['StartTime']}-{g['EndTime']} | {proj_name} | {emps_str}"
            if g['Notes']:
                base_text += f" ({g['Notes'].upper()})"

            if g['is_cancelled']:
                base_text = f"<s>{base_text}</s>"
                if g['cancel_reason']:
                    base_text += f"<br><span style='color:#dc2626;'>[{g['cancel_reason'].upper()}]</span>"

            bg_color = g['ColorHex']
            
            # --- ΣΗΜΑΝΤΙΚΟ: ΑΣΦΑΛΗΣ ΠΛΟΗΓΗΣΗ ΓΙΑ ΚΛΙΚ ---
            # Κωδικοποιούμε το URL για να μην κόβεται από το σύμβολο '#' του χρώματος
            safe_key = urllib.parse.quote(g['Key'])
            
            html.append(f"""
            <a href="?edit_key={safe_key}" target="_parent" class="mygantt-bar" style="left: {left_pct}%; width: {width_pct}%; top: {top_px}px; background-color: {bg_color};" title="{base_text.replace('<br>', ' ')}">
                <div class="mygantt-bar-text">{base_text}</div>
            </a>
            """)

        html.append('</div></div>')

    # Το JavaScript script αναλαμβάνει 2 πράγματα:
    # 1. Το Drag and scroll (δεξιά - αριστερά)
    # 2. Κάνει αυτόματα scroll στο 06:00 (που είναι 2 ώρες μετά τις 04:00 -> 2/20 = 10% του πλάτους)
    html.append("""
    </div>
    <script>
    var s=document.getElementById('mygantt');
    if(s&&!s.dataset.d){
        s.dataset.d='1';
        
        // Αυτόματο scroll για να δείχνει από τις 06:00 (αποκρύπτει αρχικά 04:00-06:00)
        var lanes = s.querySelector('.mygantt-lanes');
        if(lanes) { 
            setTimeout(() => { s.scrollLeft = lanes.offsetWidth * (2/20); }, 50);
        }
        
        let d=false,x,l;
        s.addEventListener('mousedown',e=>{d=true;s.style.cursor='grabbing';x=e.pageX-s.offsetLeft;l=s.scrollLeft;});
        s.addEventListener('mouseleave',()=>{d=false;s.style.cursor='auto';});
        s.addEventListener('mouseup',()=>{d=false;s.style.cursor='auto';});
        s.addEventListener('mousemove',e=>{if(!d)return;e.preventDefault();s.scrollLeft=l-(e.pageX-s.offsetLeft-x)*1.5;});
    }
    </script>
    </body>
    </html>
    """)
    return "".join(html)

# --- ΕΜΦΑΝΙΣΗ ΜΕΣΩ IFRAME ΓΙΑ ΑΣΦΑΛΕΙΑ ---
html_chart = build_html_gantt(wk_groups, start_of_week, zoom_factor)
st.components.v1.html(html_chart, height=660, scrolling=False)


# --- ΕΝΟΤΗΤΑ ΕΞΑΓΩΓΗΣ EXCEL ---
hint_text = "💡 *Συμβουλές:* **1)** Κάντε κλικ σε μια μπάρα για επεξεργασία. **2)** Κάντε αριστερό κλικ (Pan/Drag) για οριζόντια κύλιση στο χρόνο. **3)** Σύρετε με τη ροδέλα πάνω-κάτω για τις ημέρες."
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


# --- ΦΟΡΜΕΣ ΠΡΟΣΘΗΚΗΣ ΚΑΙ ΕΠΕΞΕΡΓΑΣΙΑΣ ΜΠΑΡΑΣ ---
if not presentation_mode:
    st.divider()
    if is_full_admin:
        col_add, col_edit = st.columns(2)
        
        with col_add:
            st.subheader("➕ Νέα Τοποθέτηση")
            if "qa_rc" not in st.session_state: st.session_state.qa_rc = 0
            qa_rc = st.session_state.qa_rc
            
            with st.form("quick_add", clear_on_submit=True):
                c_date, c_dur = st.columns(2)
                with c_date:
                    add_date = st.date_input("Ημερομηνία", value=st.session_state.view_week_date, key=f"qa_date_{qa_rc}")
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
                    str_arrival = t_arrival.strftime("%H:%M") if use_arr else ""
                    str_start = t_start.strftime("%H:%M")
                    str_end = t_end.strftime("%H:%M")
                    
                    if str_start >= str_end:
                        st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                    else:
                        emps_to_process = emp_choices if emp_choices else [""]
                        new_assigns = []
                        
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
                            
                        for day_offset in range(duration_days):
                            current_assign_date = add_date + timedelta(days=day_offset)
                            valid_assignments = []
                            
                            for eid in emps_to_process:
                                if eid:
                                    emp_name = utils.get_employee_name(eid)
                                    if scheduling.is_on_leave(eid, current_assign_date, st.session_state.leaves_by_emp):
                                        valid_assignments.append({'eid': "", 'start': str_start, 'end': str_end, 'msg': f"[Άδεια: {emp_name}]", 'emp_name': emp_name})
                                        st.toast(f"Ο/Η {emp_name} έχει άδεια στις {current_assign_date.strftime('%d/%m')}. Καταχωρήθηκε ως 'Χωρίς Προσωπικό'.", icon="⚠️")
                                    else:
                                        day_assigns = st.session_state.assignments_by_date.get(current_assign_date, [])
                                        adj_start, adj_end, is_conflict, msg = scheduling.check_and_resolve_conflict(eid, str_start, str_end, day_assigns)
                                        if is_conflict:
                                            valid_assignments.append({'eid': "", 'start': str_start, 'end': str_end, 'msg': f"[Εμπλοκή: {emp_name}]", 'emp_name': emp_name})
                                            st.toast(f"Διπλοκράτηση {emp_name} στις {current_assign_date.strftime('%d/%m')}. Καταχωρήθηκε ως 'Χωρίς Προσωπικό'.", icon="⚠️")
                                        else:
                                            valid_assignments.append({'eid': eid, 'start': adj_start, 'end': adj_end, 'msg': msg, 'emp_name': emp_name})
                                else:
                                    valid_assignments.append({'eid': "", 'start': str_start, 'end': str_end, 'msg': "", 'emp_name': ""})
                                    
                            for va in valid_assignments:
                                if va['msg'] == "Allowed Overlap": st.toast(f"ℹ️ Επιτράπηκε επικάλυψη ωραρίου για τον/την {va['emp_name']} στις {current_assign_date.strftime('%d/%m')}.", icon="ℹ️")
                                
                                c_notes = add_notes
                                if va['msg'] and va['msg'] != "Allowed Overlap":
                                    c_notes = f"{add_notes} {va['msg']}".strip()
                                    
                                new_assign = {
                                    'id': str(uuid.uuid4()), 'employeeId': va['eid'], 'projectId': final_proj_id,
                                    'date': current_assign_date, 'arrivalTime': str_arrival, 'startTime': va['start'], 'endTime': va['end'],
                                    'colorName': color_choice, 'colorHex': config.BASIC_COLORS[color_choice],
                                    'notes': c_notes, 'is_cancelled': False, 'cancel_reason': "", 'recurring_id': None
                                }
                                new_assigns.append(new_assign)
                                st.session_state.assignments.append(new_assign)
                                
                        utils.db_insert("assignments", new_assigns, track=False)
                        st.success(f"Η ανάθεση ολοκληρώθηκε επιτυχώς για {duration_days} ημέρα/ες!")
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
                
                # --- AUTO-SELECT ΑΠΟ ΤΟ ΚΛΙΚ (ΜΕΣΩ URL PARAMETER) ---
                default_idx = 0
                if clicked_key and clicked_key in group_keys:
                    default_idx = group_keys.index(clicked_key) + 1
                    
                selected_key = st.selectbox(
                    "Επιλέξτε Μπάρα (Ημέρα & Έργο)", options=[""] + group_keys, index=default_idx,
                    format_func=lambda x: "Επιλέξτε..." if x == "" else f"{wk_groups[x]['Date'].strftime('%d/%m')} - {wk_groups[x]['Project']} ({wk_groups[x]['StartTime']}-{wk_groups[x]['EndTime']})"
                )
                
                if selected_key != "":
                    target_group = wk_groups[selected_key]
                    st.markdown("⚡ **Γρήγορη Μετακίνηση**")
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
                            # Καθαρίζουμε το URL μετά την επεξεργασία
                            st.query_params.clear()
                            st.rerun()

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
                            old_assigns = [a for a in st.session_state.assignments if a['id'] in target_group['AssignmentIds']]
                            st.session_state.assignments = [a for a in st.session_state.assignments if a['id'] not in target_group['AssignmentIds']]
                            utils.db_delete_in('assignments', 'id', target_group['AssignmentIds'], deleted_records=old_assigns)
                            st.query_params.clear()
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
                                        'is_cancelled': e_is_cancelled, 'cancel_reason': e_cancel_reason if e_is_cancelled else "", 
                                        'recurring_id': target_group.get('RecurringId')
                                    }
                                    new_assigns.append(new_a)
                                    st.session_state.assignments.append(new_a)
                                utils.db_insert('assignments', new_assigns, track=False)
                                st.query_params.clear()
                                st.rerun()
