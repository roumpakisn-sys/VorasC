import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, date, timedelta
import uuid
import textwrap
import time

# --- INITIALIZATION ---
if not st.session_state.get("authenticated"):
    st.switch_page("streamlit_app.py")

import utils
import ui_dashboard

utils.init_data_and_sync()
utils.setup_shared_ui()

# Helpers local access
is_full_admin = st.session_state.get('current_user') != "TAN"
active_employee_ids = [e['id'] for e in st.session_state.employees if e.get('status', 'Ενεργός') == 'Ενεργός']

def go_prev_week(): st.session_state.view_week_date -= timedelta(days=7)
def go_next_week(): st.session_state.view_week_date += timedelta(days=7)
def go_to_today(): st.session_state.view_week_date = date.today()

# --- VIEW: DASHBOARD (GANTT) ---
st.title("📊 Εβδομαδιαίο Χρονοδιάγραμμα Πόρων")

# Κλήση του UI για την πάνω μπάρα (Navigation & Filters)
selected_date, start_of_week, zoom_level, presentation_mode = ui_dashboard.render_top_nav(go_prev_week, go_next_week, go_to_today)
zoom_factor = zoom_level / 100.0

current_gantt_params = {
    "week": start_of_week, "zoom": zoom_factor, "presentation": presentation_mode,
    "local_version": st.session_state.get('local_gantt_version', 0)
}

if st.session_state.get('last_gantt_params') == current_gantt_params and 'cached_fig' in st.session_state:
    fig = st.session_state.cached_fig
    wk_groups = st.session_state.cached_wk_groups
    export_data = st.session_state.cached_export_data
else:
    data, export_data, color_map, y_category_order, tickvals_map, empty_shift_annotations, wk_groups = [], [], {}, [], {}, [], {}
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
                    leaves_today.append(f"<b>{emp_n}</b><br><span style='font-size: 10px; color:#991b1b;'>↳ Αντικατ: <b>{sub_n}</b></span>")
                else: leaves_today.append(f"<b>{emp_n}</b>")
        
        leaves_str = "<br><br>".join(leaves_today) if leaves_today else "Καμία"
        base_y_label = f"<b>{day_str}</b><br><span style='font-size:11px; color:#d32f2f;'>Άδειες:<br>{leaves_str}</span>" if leaves_today else f"<b>{day_str}</b><br><span style='font-size:11px; color:#d32f2f;'>Άδειες: {leaves_str}</span>"
            
        day_assignments = st.session_state.assignments_by_date.get(curr_date, [])
        day_row_ids = []
        
        if not day_assignments:
            row_id = f"day_{i}_row_0"
            day_row_ids.append(row_id)
        else:
            emp_day_assigns = {}
            for da in day_assignments:
                eid = da.get('employeeId')
                if eid:
                    if eid not in emp_day_assigns: emp_day_assigns[eid] = []
                    emp_day_assigns[eid].append(da)
                    
            groups = {}
            for a in day_assignments:
                proj = utils.get_project_info(a['projectId'])
                c_hex = a.get('colorHex', proj['color'] if proj else "#999999")
                c_name = a.get('colorName', "Προεπιλογή")
                notes = a.get('notes', "")
                is_canc = a.get('is_cancelled', False)
                c_reason = a.get('cancel_reason', "")
                arrival_time = a.get('arrivalTime', "")[:5] if a.get('arrivalTime', "") else ""
                
                key = f"{curr_date}_{a['projectId']}_{a['startTime']}_{a['endTime']}_{c_hex}_{notes}_{is_canc}_{c_reason}_{arrival_time}"
                if key not in groups:
                    legend_val = f"{proj['name']} ({c_name})" if proj else "Άγνωστο"
                    groups[key] = {
                        'Key': key, 'ProjectId': a['projectId'], 'Date': curr_date,
                        'Project': proj['name'] if proj else "Άγνωστο", 'ArrivalTime': arrival_time,
                        'StartTime': str(a['startTime'])[:5], 'EndTime': str(a['endTime'])[:5],
                        'Start': datetime.combine(datetime(1970, 1, 1), datetime.strptime(str(a['startTime'])[:5], "%H:%M").time()),
                        'End': datetime.combine(datetime(1970, 1, 1), datetime.strptime(str(a['endTime'])[:5], "%H:%M").time()),
                        'Employees': [], 'EmployeeIds': [], 'AssignmentIds': [],
                        'ColorHex': c_hex, 'ColorName': c_name, 'Notes': notes,
                        'is_cancelled': is_canc, 'cancel_reason': c_reason, 'LegendGroup': legend_val
                    }
                
                if not a.get('employeeId'): formatted_name = "ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ"
                else:
                    full_name = utils.get_employee_name(a['employeeId'])
                    name_parts = full_name.split()
                    formatted_name = f"{name_parts[-1]} {name_parts[0][0]}." if len(name_parts) > 1 else full_name
                        
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
                    if prev_proj: formatted_name = f"[ΜΕΤΑ ΑΠΟ '{prev_proj['name']}' ▶ {formatted_name}]"
                        
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
                        placed = True; break
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
                        placed = True; break
                if not placed:
                    blue_lanes.append(g['End'])
                    row_idx = len(blue_lanes) - 1
                group_row_mapping.append((g, row_idx + num_non_blue_lanes))
                
            for g, row_idx in group_row_mapping:
                row_id = f"day_{i}_row_{row_idx}"
                if row_id not in day_row_ids: day_row_ids.append(row_id)
                    
                emps_str = ", ".join(g['Employees']).upper()
                proj_name = g['Project'].upper()
                arrival_str = f"[Προσ: {g['ArrivalTime']}] " if g['ArrivalTime'] else ""
                times_str = f"{arrival_str}{g['StartTime']}-{g['EndTime']}"
                base_text = f"{times_str} {proj_name} // {emps_str}"
                if g['Notes']: base_text += f" ({g['Notes'].upper()})"
                
                duration_hours = (g['End'] - g['Start']).total_seconds() / 3600.0
                wrap_w = max(12, int(duration_hours * 13))
                wrapped_base = "<br>".join(textwrap.wrap(base_text, width=wrap_w))
                
                if "ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ" in emps_str:
                    empty_shift_annotations.append(dict(
                        x=g['End'], y=row_id, text="⚠️", showarrow=False, xanchor='right',
                        yanchor='middle', xshift=-4, yshift=int(28* zoom_factor), font=dict(size=max(10, int(14* zoom_factor)))
                    ))
                    
                if g['is_cancelled']:
                    label_text = f"<s>{wrapped_base}</s>"
                    if g['cancel_reason']:
                        wrapped_reason = "<br>".join(textwrap.wrap(f"[{g['cancel_reason'].upper()}]", width=wrap_w))
                        label_text += f"<br><span style='color:#dc2626;'><b>{wrapped_reason}</b></span>"
                else: label_text = wrapped_base
                    
                data.append({
                    'Y_Axis': row_id, 'Έργο': g['Project'], 'Έναρξη': g['Start'], 'Λήξη': g['End'],
                    'Προσωπικό': ", ".join(g['Employees']), 'Προσέλευση': g['ArrivalTime'] if g['ArrivalTime'] else "-",
                    'Παρατηρήσεις': g['Notes'], 'Ετικέτα': label_text, 'LegendGroup': g['LegendGroup'],
                    'ColorHex': g['ColorHex'], 'GroupKey': g['Key']
                })
                export_data.append({
                    'Ημερομηνία': curr_date.strftime('%d/%m/%Y'), 'Ημέρα': day_names_gr[i],
                    'Έργο': g['Project'], 'Προσωπικό': ", ".join(g['Employees']),
                    'Ώρα Προσέλευσης': g['ArrivalTime'] if g['ArrivalTime'] else "-",
                    'Ώρα Έναρξης': g['StartTime'], 'Ώρα Λήξης': g['EndTime'],
                    'Παρατηρήσεις': g['Notes'], 'Ακυρωμένο': 'ΝΑΙ' if g['is_cancelled'] else 'ΟΧΙ', 'Λόγος Ακύρωσης': g['cancel_reason']
                })
                color_map[g['LegendGroup']] = g['ColorHex']
                
        y_category_order.extend(day_row_ids)
        mid_idx = len(day_row_ids) // 2
        for idx, rid in enumerate(day_row_ids): tickvals_map[rid] = base_y_label if idx == mid_idx else ""
            
    df = pd.DataFrame(data)
    ordered_categories = y_category_order[::-1]
    
    fig = px.timeline(df, x_start="Έναρξη", x_end="Λήξη", y="Y_Axis", color="LegendGroup", color_discrete_map=color_map, custom_data=["GroupKey"], text="Ετικέτα")
    
    for di in range(7):
        day_idxs = [idx for idx, val in enumerate(ordered_categories) if val.startswith(f"day_{di}_")]
        if day_idxs:
            mn, mx = min(day_idxs), max(day_idxs)
            if di % 2 != 0: fig.add_hrect(y0=mn-0.5, y1=mx+0.5, fillcolor="rgba(0,0,0,0.05)", opacity=1, layer="below", line_width=0)
            if (start_of_week + timedelta(days=di)) == date.today(): fig.add_hrect(y0=mn-0.5, y1=mx+0.5, fillcolor="#b2d8ce", opacity=1, layer="below", line_width=0)
                
    for idx in range(len(ordered_categories) - 1):
        if ordered_categories[idx].split('_')[1] != ordered_categories[idx+1].split('_')[1]:
            fig.add_shape(type="line", x0=0, x1=1, xref="paper", y0=idx+0.5, y1=idx+0.5, yref="y", line=dict(color="#000000", width=4))
            
    row_h = 40 * zoom_factor
    visible_count = 650 / row_h
    if presentation_mode or len(ordered_categories) <= visible_count:
        dyn_h = max(500, int(len(ordered_categories) * row_h) + 100)
        y_range = None
    else:
        dyn_h = 750
        offset = (date.today() - start_of_week).days
        if 0 <= offset <= 6:
            idxs = [idx for idx, val in enumerate(ordered_categories) if val.startswith(f"day_{offset}_")]
            if idxs:
                mid = sum(idxs) / len(idxs)
                y_range = [max(-0.5, mid - visible_count/2), min(len(ordered_categories)-0.5, mid + visible_count/2)]
            else: y_range = [len(ordered_categories) - visible_count - 0.5, len(ordered_categories) - 0.5]
        else: y_range = [len(ordered_categories) - visible_count - 0.5, len(ordered_categories) - 0.5]
            
    fig.update_yaxes(categoryorder='array', categoryarray=ordered_categories, tickmode='array', tickvals=ordered_categories, ticktext=[tickvals_map[v] for v in ordered_categories], showgrid=True, gridcolor='rgba(0,0,0,0.1)', gridwidth=1)
    fig.update_traces(textposition='inside', insidetextanchor='middle', textfont=dict(color='black', size=max(8, int(9*zoom_factor)), family="Arial Black, Arial, sans-serif"), marker=dict(line=dict(color='black', width=1)), textangle=0, constraintext='none', hoverinfo='none', hovertemplate=None, selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=1)))
    fig.update_layout(
        bargap=0.02, showlegend=False, plot_bgcolor='#dbece8', paper_bgcolor='#ffffff', height=dyn_h, margin=dict(l=10, r=10, t=50, b=10),
        annotations=empty_shift_annotations, dragmode="pan", clickmode="event+select", uirevision="constant",
        xaxis=dict(side='top', tickmode='linear', tick0=datetime(1970, 1, 1, 0, 0), dtick=1800000, tickformat="%H:%M", showgrid=True, gridcolor='black', gridwidth=1, range=[datetime(1970, 1, 1, 6, 0), datetime(1970, 1, 1, 17, 0)], title="", tickfont=dict(size=max(8, int(11*zoom_factor)), color="black", family="Arial"), fixedrange=False, rangeslider=dict(visible=False)),
        yaxis=dict(title="", tickfont=dict(size=max(8, int(12*zoom_factor)), color="black"), fixedrange=False, range=y_range)
    )
    st.session_state.cached_fig = fig
    st.session_state.cached_wk_groups = wk_groups
    st.session_state.cached_export_data = export_data
    st.session_state.last_gantt_params = current_gantt_params

clicked_key = None
try:
    event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", selection_mode="points", config={"displayModeBar": False})
    if event and "selection" in event:
        if event["selection"].get("points"):
            cd = event["selection"]["points"][0].get("customdata", [None])[0]
            if cd != "Empty": clicked_key = cd
            else: clicked_key = None
except Exception:
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# Κλήση του UI για Εξαγωγή Προγράμματος
ui_dashboard.render_export_section(export_data, start_of_week)

if not presentation_mode:
    st.divider()
    if is_full_admin:
        col_add, col_edit = st.columns(2)
        with col_add:
            # Κλήση του UI για Φόρμα Προσθήκης
            add_data = ui_dashboard.render_quick_add_form(selected_date, active_employee_ids)
            if add_data:
                str_arrival = add_data["t_arrival"].strftime("%H:%M") if add_data["use_arr"] else ""
                str_start = add_data["t_start"].strftime("%H:%M")
                str_end = add_data["t_end"].strftime("%H:%M")
                
                if str_start >= str_end:
                    st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                elif not add_data["custom_proj_name"].strip() and not add_data["proj_choice"]:
                    st.error("Παρακαλώ επιλέξτε ή πληκτρολογήστε ένα Έργο.")
                else:
                    emps_to_process = add_data["emp_choices"] if add_data["emp_choices"] else [""]
                    errors = []
                    valid_assignments = []
                    for eid in emps_to_process:
                        if eid:
                            emp_name = utils.get_employee_name(eid)
                            if utils.is_on_leave(eid, add_data["add_date"]):
                                errors.append(f"O/H {emp_name} βρίσκεται σε άδεια στις {add_data['add_date'].strftime('%d/%m')}.")
                                st.toast(f"Αδύνατη ανάθεση: Ο/Η {emp_name} έχει άδεια!", icon="❌")
                            else:
                                adj_start, adj_end, is_conflict, msg = utils.check_and_resolve_conflict(eid, add_data["add_date"], str_start, str_end)
                                if is_conflict:
                                    errors.append(f"⚠️ ΔΙΠΛΟΚΡΑΤΗΣΗ: Ο/Η {emp_name} έχει ήδη άλλη βάρδια που συμπίπτει ({str_start} - {str_end}).")
                                    st.toast(f"Προσοχή: Διπλοκράτηση για τον/την {emp_name}!", icon="⚠️")
                                else:
                                    valid_assignments.append({'eid': eid, 'start': adj_start, 'end': adj_end, 'msg': msg, 'emp_name': emp_name})
                        else:
                            valid_assignments.append({'eid': "", 'start': str_start, 'end': str_end, 'msg': "", 'emp_name': ""})
                            
                    if errors:
                        for err in errors: st.error(err)
                    else:
                        if add_data["custom_proj_name"].strip():
                            final_proj_id = str(uuid.uuid4())
                            new_p = {'id': final_proj_id, 'name': add_data["custom_proj_name"].strip(), 'color': utils.BASIC_COLORS[add_data["color_choice"]]}
                            st.session_state.projects.append(new_p)
                            utils.db_insert('projects', new_p, track=False)
                        else: final_proj_id = add_data["proj_choice"]
                            
                        new_assigns = []
                        for va in valid_assignments:
                            if va['msg'] == "Allowed Overlap": st.toast(f"ℹ️ Επιτράπηκε επικάλυψη ωραρίου για τον/την {va['emp_name']}.", icon="ℹ️")
                            new_assign = {
                                'id': str(uuid.uuid4()), 'employeeId': va['eid'], 'projectId': final_proj_id,
                                'date': add_data["add_date"], 'arrivalTime': str_arrival, 'startTime': va['start'], 'endTime': va['end'],
                                'colorName': add_data["color_choice"], 'colorHex': utils.BASIC_COLORS[add_data["color_choice"]],
                                'notes': add_data["add_notes"], 'is_cancelled': False, 'cancel_reason': "", 'recurring_id': None
                            }
                            new_assigns.append(new_assign)
                            st.session_state.assignments.append(new_assign)
                        utils.db_insert("assignments", new_assigns, track=False)
                        st.success("Η ανάθεση ολοκληρώθηκε!")
                        time.sleep(0.5)
                        st.session_state.qa_rc += 1
                        st.rerun()

        with col_edit:
            # Κλήση του UI για Φόρμα Επεξεργασίας
            edit_data = ui_dashboard.render_edit_form(wk_groups, clicked_key, active_employee_ids)
            
            if edit_data:
                action = edit_data["action"]
                target_group = edit_data["target_group"]
                
                if action == "move":
                    has_error = False
                    new_assigns, old_assigns = [], []
                    for a_id in target_group['AssignmentIds']:
                        orig_a = next(a for a in st.session_state.assignments if a['id'] == a_id)
                        new_a = dict(orig_a)
                        if edit_data["delta_days"] != 0: new_a['date'] = orig_a['date'] + timedelta(days=edit_data["delta_days"])
                        if edit_data["delta_hours"] != 0:
                            dummy_date = datetime(2000, 1, 1)
                            s_dt = datetime.combine(dummy_date, datetime.strptime(str(orig_a['startTime'])[:5], "%H:%M").time())
                            e_dt = datetime.combine(dummy_date, datetime.strptime(str(orig_a['endTime'])[:5], "%H:%M").time())
                            new_s_dt = s_dt + timedelta(hours=edit_data["delta_hours"])
                            new_e_dt = e_dt + timedelta(hours=edit_data["delta_hours"])
                            if new_s_dt.date() != dummy_date.date() or new_e_dt.date() != dummy_date.date():
                                st.error("Η αλλαγή ώρας ξεπερνάει τα όρια της ημέρας.")
                                has_error = True; break
                            new_a['startTime'] = new_s_dt.strftime("%H:%M")
                            new_a['endTime'] = new_e_dt.strftime("%H:%M")
                            if orig_a.get('arrivalTime'):
                                arr_dt = datetime.combine(dummy_date, datetime.strptime(str(orig_a['arrivalTime'])[:5], "%H:%M").time())
                                new_a['arrivalTime'] = (arr_dt + timedelta(hours=edit_data["delta_hours"])).strftime("%H:%M")
                                
                        if new_a['employeeId']:
                            emp_name = utils.get_employee_name(new_a['employeeId'])
                            if utils.is_on_leave(new_a['employeeId'], new_a['date']):
                                st.toast(f"Αδύνατη μετακίνηση: Ο/Η {emp_name} έχει άδεια!", icon="❌")
                                has_error = True; break
                            adj_start, adj_end, is_conflict, msg = utils.check_and_resolve_conflict(new_a['employeeId'], new_a['date'], new_a['startTime'], new_a['endTime'], exclude_ids=target_group['AssignmentIds'])
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

                elif action == "delete":
                    old_assigns = [a for a in st.session_state.assignments if a['id'] in target_group['AssignmentIds']]
                    st.session_state.assignments = [a for a in st.session_state.assignments if a['id'] not in target_group['AssignmentIds']]
                    utils.db_delete_in('assignments', 'id', target_group['AssignmentIds'], deleted_records=old_assigns)
                    st.rerun()

                elif action == "edit":
                    str_arrival = edit_data["new_t_arrival"].strftime("%H:%M") if edit_data["use_arr_edit"] else ""
                    str_start = edit_data["new_t_start"].strftime("%H:%M")
                    str_end = edit_data["new_t_end"].strftime("%H:%M")
                    
                    if str_start >= str_end:
                        st.error("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
                    elif not edit_data["edit_custom_proj_name"].strip() and not edit_data["edit_proj"]:
                        st.error("Παρακαλώ επιλέξτε ή πληκτρολογήστε ένα Έργο.")
                    else:
                        emps_to_process = edit_data["edit_emps"] if edit_data["edit_emps"] else [""]
                        errors, valid_assignments = [], []
                        for eid in emps_to_process:
                            if eid:
                                emp_name = utils.get_employee_name(eid)
                                if utils.is_on_leave(eid, edit_data["edit_date"]):
                                    errors.append(f"O/H {emp_name} βρίσκεται σε άδεια στις {edit_data['edit_date'].strftime('%d/%m')}.")
                                    st.toast(f"Αδύνατη ανάθεση: Ο/Η {emp_name} έχει άδεια!", icon="❌")
                                else:
                                    adj_start, adj_end, is_conflict, msg = utils.check_and_resolve_conflict(eid, edit_data["edit_date"], str_start, str_end, exclude_ids=target_group['AssignmentIds'])
                                    if is_conflict:
                                        errors.append(f"⚠️ ΔΙΠΛΟΚΡΑΤΗΣΗ: Ο/Η {emp_name} έχει ήδη άλλη βάρδια που συμπίπτει.")
                                        st.toast(f"Προσοχή: Διπλοκράτηση για τον/την {emp_name}!", icon="⚠️")
                                    else:
                                        valid_assignments.append({'eid': eid, 'start': adj_start, 'end': adj_end, 'msg': msg, 'emp_name': emp_name})
                            else:
                                valid_assignments.append({'eid': "", 'start': str_start, 'end': str_end, 'msg': "", 'emp_name': ""})
                                
                        if errors:
                            for err in errors: st.error(err)
                        else:
                            if edit_data["edit_custom_proj_name"].strip():
                                final_edit_proj_id = str(uuid.uuid4())
                                new_p = {'id': final_edit_proj_id, 'name': edit_data["edit_custom_proj_name"].strip(), 'color': utils.BASIC_COLORS[edit_data["edit_color"]]}
                                st.session_state.projects.append(new_p)
                                utils.db_insert('projects', new_p, track=False)
                            else: final_edit_proj_id = edit_data["edit_proj"]
                                
                            old_assigns = [a for a in st.session_state.assignments if a['id'] in target_group['AssignmentIds']]
                            st.session_state.assignments = [a for a in st.session_state.assignments if a['id'] not in target_group['AssignmentIds']]
                            utils.db_delete_in('assignments', 'id', target_group['AssignmentIds'], track=False)
                            
                            new_assigns = []
                            for va in valid_assignments:
                                if va['msg'] == "Allowed Overlap": st.toast(f"ℹ️ Επιτράπηκε επικάλυψη ωραρίου: {va['emp_name']} ({va['start']})", icon="ℹ️")
                                new_a = {
                                    'id': str(uuid.uuid4()), 'employeeId': va['eid'], 'projectId': final_edit_proj_id,
                                    'date': edit_data["edit_date"], 'arrivalTime': str_arrival, 'startTime': va['start'], 'endTime': va['end'],
                                    'colorName': edit_data["edit_color"], 'colorHex': utils.BASIC_COLORS[edit_data["edit_color"]], 'notes': edit_data["edit_notes"],
                                    'is_cancelled': edit_data["e_is_cancelled"], 'cancel_reason': edit_data["e_cancel_reason"] if edit_data["e_is_cancelled"] else "", 'recurring_id': None
                                }
                                new_assigns.append(new_a)
                                st.session_state.assignments.append(new_a)
                            utils.db_insert('assignments', new_assigns, track=False)
                            st.rerun()
