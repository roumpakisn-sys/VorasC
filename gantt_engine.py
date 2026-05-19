import pandas as pd
import plotly.express as px
from datetime import datetime, date, timedelta
import textwrap

def get_local_today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Athens")).date()
    except Exception:
        return (datetime.utcnow() + timedelta(hours=3)).date()

def get_employee_name(emp_id, emp_map):
    if not emp_id: return "Χωρίς Προσωπικό"
    emp = emp_map.get(emp_id)
    return emp['name'] if emp else "Άγνωστος"

def get_project_info(proj_id, proj_map):
    return proj_map.get(proj_id)

def generate_gantt_chart(start_of_week, zoom_factor, presentation_mode, data_version, assignments_by_date, leaves, employees, projects, emp_map, proj_map):
    """
    Αναλαμβάνει όλη τη βαριά δουλειά της δημιουργίας του Gantt Chart.
    Βελτιστοποιημένη με προ-υπολογισμούς.
    """
    data = []
    export_data = []
    color_map = {}
    y_category_order = []
    tickvals_map = {}
    empty_shift_annotations = []
    wk_groups = {}
    
    # --- ΥΠΕΡ-ΒΕΛΤΙΣΤΟΠΟΙΗΣΗ ΤΑΧΥΤΗΤΑΣ (Pre-computation) ---
    emp_short_names = {}
    external_crews = []
    for emp in employees:
        eid = emp['id']
        full_name = emp['name']
        parts = full_name.split()
        emp_short_names[eid] = f"{parts[-1]} {parts[0][0]}." if len(parts) > 1 else full_name
        if emp.get('status', 'Ενεργός') == 'Ενεργός' and emp.get('is_external_crew', False):
            external_crews.append(emp)
            
    end_of_week = start_of_week + timedelta(days=6)
    active_leaves_this_week = [l for l in leaves if l['startDate'] <= end_of_week and l['endDate'] >= start_of_week]

    leaves_by_emp_dict = {}
    for l in active_leaves_this_week:
        eid = l['employeeId']
        if eid not in leaves_by_emp_dict:
            leaves_by_emp_dict[eid] = []
        leaves_by_emp_dict[eid].append(l)

    def is_on_leave_fast(eid, check_date):
        for l in leaves_by_emp_dict.get(eid, []):
            if l['startDate'] <= check_date <= l['endDate']: return True
        return False

    day_names_gr = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
    for i in range(7):
        curr_date = start_of_week + timedelta(days=i)
        day_str = f"{day_names_gr[i]} {curr_date.strftime('%d/%m')}"
        
        leaves_today = []
        for l in active_leaves_this_week:
            if l['startDate'] <= curr_date <= l['endDate']:
                emp_n = emp_short_names.get(l['employeeId'], get_employee_name(l['employeeId'], emp_map))
                sub_id = l.get('substituteId')
                if sub_id:
                    sub_n = emp_short_names.get(sub_id, get_employee_name(sub_id, emp_map))
                    leaves_today.append(f"{emp_n} (Αντ: {sub_n})")
                else:
                    leaves_today.append(f"{emp_n}")
        
        available_ext_crew = []
        day_assigns = assignments_by_date.get(curr_date, [])
        
        for emp in external_crews:
            eid = emp['id']
            if is_on_leave_fast(eid, curr_date):
                continue
            
            is_busy_after_10 = False
            for a in day_assigns:
                if a.get('employeeId') == eid and not a.get('is_cancelled', False):
                    if str(a.get('endTime', ''))[:5] > "10:00":
                        is_busy_after_10 = True
                        break
            
            if not is_busy_after_10:
                available_ext_crew.append(emp_short_names.get(eid, emp['name']))

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
                proj = get_project_info(a['projectId'], proj_map)
                c_hex = a.get('colorHex', proj['color'] if proj else "#999999")
                c_name = a.get('colorName', "Προεπιλογή")
                notes = a.get('notes', "")
                is_canc = a.get('is_cancelled', False)
                c_reason = a.get('cancel_reason', "")
                arrival_time = a.get('arrivalTime', "")
                if arrival_time: arrival_time = arrival_time[:5]
                
                key = f"{curr_date}_{a['projectId']}_{a['startTime']}_{a['endTime']}_{c_hex}_{is_canc}_{c_reason}_{arrival_time}"
                if key not in groups:
                    legend_val = f"{proj['name']} ({c_name})" if proj else "Άγνωστο"
                    groups[key] = {
                        'Key': key, 'ProjectId': a['projectId'], 'Date': curr_date, 'Project': proj['name'] if proj else "Άγνωστο",
                        'ArrivalTime': arrival_time, 'StartTime': str(a['startTime'])[:5], 'EndTime': str(a['endTime'])[:5],
                        'Start': datetime.combine(datetime(1970, 1, 1), datetime.strptime(str(a['startTime'])[:5], "%H:%M").time()),
                        'End': datetime.combine(datetime(1970, 1, 1), datetime.strptime(str(a['endTime'])[:5], "%H:%M").time()),
                        'Employees': [], 'EmployeeIds': [], 'AssignmentIds': [], 'ColorHex': c_hex, 'ColorName': c_name,
                        'Notes_List': [], 'is_cancelled': is_canc, 'cancel_reason': c_reason, 'LegendGroup': legend_val,
                        'RecurringId': a.get('recurring_id') 
                    }
                
                if notes and notes not in groups[key]['Notes_List']:
                    groups[key]['Notes_List'].append(notes)
                
                if not a.get('employeeId'):
                    formatted_name = "ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ"
                else:
                    formatted_name = emp_short_names.get(a['employeeId'], get_employee_name(a['employeeId'], emp_map))
                        
                prev_assigns = []
                my_eid = a.get('employeeId')
                if my_eid in emp_day_assigns:
                    t_a_start_str = str(a['startTime'])[:5]
                    t_a_end_str = str(a['endTime'])[:5]
                    for pa in emp_day_assigns[my_eid]:
                        if pa.get('id') != a['id']:
                            t_pa_start_str = str(pa['startTime'])[:5]
                            t_pa_end_str = str(pa['endTime'])[:5]
                            pa_proj = get_project_info(pa['projectId'], proj_map)
                            a_proj = get_project_info(a['projectId'], proj_map)
                            pa_name = pa_proj['name'].strip().lower() if pa_proj else "1"
                            a_name = a_proj['name'].strip().lower() if a_proj else "2"
                            
                            if (pa_name != a_name) and (t_pa_start_str <= t_a_start_str) and (t_pa_end_str > t_a_start_str) and (t_a_end_str > t_pa_end_str):
                                prev_assigns.append(pa)
                                
                if prev_assigns:
                    prev_assigns.sort(key=lambda x: str(x['endTime'])[:5], reverse=True)
                    prev_proj = get_project_info(prev_assigns[0]['projectId'], proj_map)
                    if prev_proj:
                        formatted_name = f"[ΜΕΤΑ ΑΠΟ '{prev_proj['name']}' ▶ {formatted_name}]"
                        
                groups[key]['Employees'].append(formatted_name)
                groups[key]['EmployeeIds'].append(a['employeeId'])
                groups[key]['AssignmentIds'].append(a['id'])
                
            for g in groups.values():
                g['Notes'] = " | ".join(g['Notes_List'])
                
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
                    'Παρατηρήσεις': g['Notes'], 'Ακυρωμένο': 'ΝΑΙ' if g['is_cancelled'] else 'ΟΧΙ',
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
            if (start_of_week + timedelta(days=di)) == get_local_today():
                fig.add_hrect(y0=mn-0.5, y1=mx+0.5, fillcolor="#4f46e5", opacity=0.15, layer="below", line_width=2, line_color="#4f46e5")
                
    for idx in range(len(ordered_categories) - 1):
        if ordered_categories[idx].split('_')[1] != ordered_categories[idx+1].split('_')[1]:
            fig.add_shape(type="line", x0=0, x1=1, xref="paper", y0=idx+0.5, y1=idx+0.5, yref="y", line=dict(color="#000000", width=4))
            
    row_h = 50 * zoom_factor
    margin_top = 50
    margin_bottom = 10
    
    dyn_h = int(len(ordered_categories) * row_h) + margin_top + margin_bottom
    dyn_h = max(250, dyn_h)
    
    y_range = [-0.5, len(ordered_categories) - 0.5]
            
    fig.update_yaxes(
        categoryorder='array', categoryarray=ordered_categories,
        tickmode='array', tickvals=ordered_categories,
        ticktext=[tickvals_map[v] for v in ordered_categories],
        showgrid=True, gridcolor='rgba(0,0,0,0.1)', gridwidth=1,
        automargin=True, range=y_range, fixedrange=True
    )
    fig.update_traces(
        textposition='inside', insidetextanchor='middle',
        textfont=dict(color='black', size=max(8, int(9*zoom_factor)), family="Arial Black, Arial, sans-serif"),
        marker=dict(line=dict(color='black', width=1)), textangle=0, constraintext='none',
        hoverinfo='none', hovertemplate=None,
        selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=1))
    )
    fig.update_layout(
        bargap=0.02, showlegend=False, plot_bgcolor='#dbece8', paper_bgcolor='rgba(0,0,0,0)',
        height=dyn_h, margin=dict(l=0, r=0, t=50, b=10),
        annotations=empty_shift_annotations, dragmode="pan", clickmode="event+select",
        uirevision="constant",
        xaxis=dict(
            side='top', tickmode='linear', tick0="1970-01-01 00:00:00", dtick=1800000,
            tickformat="%H:%M", showgrid=True, gridcolor='black', gridwidth=1,
            autorange=False, range=["1970-01-01 06:00:00", "1970-01-01 16:00:00"],
            title="", tickfont=dict(size=max(8, int(11*zoom_factor)), color="black", family="Arial"),
            fixedrange=False, rangeslider=dict(visible=False)
        )
    )
    return fig, wk_groups, export_data
