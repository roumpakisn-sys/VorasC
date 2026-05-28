import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from datetime import datetime, date, timedelta
import uuid
import calendar
import textwrap
import threading
import re
import ast
import time
import config
import scheduling

try:
    from supabase import create_client
    SUPABASE_INSTALLED = True
except ImportError:
    SUPABASE_INSTALLED = False

# --- SETUP SUPABASE ---
try:
    HAS_SECRETS = "SUPABASE_URL" in st.secrets and "SUPABASE_KEY" in st.secrets
except Exception:
    HAS_SECRETS = False

@st.cache_resource
def init_supabase():
    if not SUPABASE_INSTALLED or not HAS_SECRETS:
        return None
    try:
        return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except Exception:
        return None

supabase = init_supabase()

# --- ΣΥΣΤΗΜΑ UNDO/REDO ---
def init_undo_stack():
    if "undo_stack" not in st.session_state:
        st.session_state.undo_stack = []
    if "redo_stack" not in st.session_state:
        st.session_state.redo_stack = []

def add_transaction(actions):
    init_undo_stack()
    st.session_state.undo_stack.append(actions)
    st.session_state.redo_stack.clear()
    if len(st.session_state.undo_stack) > 30:
        st.session_state.undo_stack.pop(0)

# --- ΒΑΣΗ ΔΕΔΟΜΕΝΩΝ - HELPERS ---
def mark_data_changed():
    st.session_state.local_gantt_version = st.session_state.get('local_gantt_version', 0) + 1
    st.session_state.data_dirty = True

def fetch_paginated(table):
    if not supabase: return []
    all_rows = []
    offset = 0
    limit = 1000
    while True:
        try:
            data = supabase.table(table).select("*").range(offset, offset + limit - 1).execute().data
            if data:
                all_rows.extend(data)
            if not data or len(data) < limit:
                break
            offset += limit
        except Exception:
            break
    return all_rows

def serialize_dates(data):
    if isinstance(data, list):
        return [serialize_dates(item) for item in data]
    elif isinstance(data, dict):
        return {k: (v.isoformat() if isinstance(v, (datetime, date)) else v) for k, v in data.items()}
    return data

def safe_date_parse(d_val):
    if isinstance(d_val, date) and not isinstance(d_val, datetime):
        return d_val
    if isinstance(d_val, datetime):
        return d_val.date()
    if isinstance(d_val, str):
        s = d_val.split("T")[0][:10]
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
    return None

def format_log_details(table_name, records):
    if not records: return "Καμία εγγραφή"
    if isinstance(records, dict): records = [records]
    if isinstance(records, str): return records
    lines = []
    for r in records:
        if not isinstance(r, dict): continue
        if table_name == 'employees':
            lines.append(f"{r.get('name', 'Άγνωστος')}")
        elif table_name == 'projects':
            lines.append(f"'{r.get('name', 'Άγνωστο Έργο')}'")
        elif table_name == 'assignments':
            emp_id = r.get('employeeId')
            emp_name = "Χαμηλό / Χωρίς Προσωπικό"
            if emp_id and 'employees' in st.session_state:
                e_info = next((e for e in st.session_state.get('employees', []) if e.get('id') == emp_id), None)
                if e_info: emp_name = e_info.get('name', emp_name)
            proj_id = r.get('projectId')
            proj_name = "Άγνωστο Έργο"
            if proj_id and 'projects' in st.session_state:
                p_info = next((p for p in st.session_state.get('projects', []) if p.get('id') == proj_id), None)
                if p_info: proj_name = p_info.get('name', proj_name)
            d = r.get('date', "")
            if isinstance(d, date): d = d.strftime('%d/%m/%Y')
            elif isinstance(d, str) and "T" in d: d = d.split("T")[0]
            lines.append(f"Βάρδια: {emp_name} στο '{proj_name}' ({d})")
        elif table_name == 'leaves':
            emp_id = r.get('employeeId')
            emp_name = next((e.get('name', 'Άγνωστος') for e in st.session_state.get('employees', []) if e.get('id') == emp_id), "Άγνωστος")
            sd = r.get('startDate', "")
            ed = r.get('endDate', "")
            if isinstance(sd, date): sd = sd.strftime('%d/%m/%Y')
            if isinstance(ed, date): ed = ed.strftime('%d/%m/%Y')
            sub_id = r.get('substituteId')
            sub_str = f" [Αντικατ: {next((e.get('name', 'Άγνωστος') for e in st.session_state.get('employees', []) if e.get('id') == sub_id), 'Άγνωστος')}]" if sub_id else ""
            lines.append(f"Άδεια: {emp_name} ({sd} - {ed}){sub_str}")
        elif table_name == 'evaluations':
            emp_id = r.get('employeeId')
            emp_name = next((e.get('name', 'Άγνωστος') for e in st.session_state.get('employees', []) if e.get('id') == emp_id), "Άγνωστος")
            lines.append(f"Αξιολόγηση: {emp_name} ({r.get('month')}/{r.get('year')})")
        elif table_name == 'recurring_patterns':
            lines.append(f"Επαναλαμβανόμενη σειρά: {r.get('type')}")
        else:
            lines.append("Εγγραφή")
    if not lines: return "Λεπτομέρειες μη διαθέσιμες"
    if len(lines) > 5:
        return " | ".join(lines[:5]) + f" ...και άλλες {len(lines)-5} εγγραφές"
    return " | ".join(lines)

def parse_old_log_details(table_name, details_str):
    if not isinstance(details_str, str): return details_str
    if not (details_str.startswith("[{") or details_str.startswith("{")): return details_str
    try:
        clean_str = re.sub(r"datetime\.date\((\d+),\s*(\d+),\s*(\d+)\)", r" \3/\2/\1", details_str)
        parsed_data = ast.literal_eval(clean_str)
        return format_log_details(table_name, parsed_data)
    except:
        return details_str

def log_activity(action_type, table_name, details_raw):
    if not supabase or table_name == 'activity_logs': return
    user = st.session_state.get("current_user", "Άγνωστος")
    try:
        from zoneinfo import ZoneInfo
        now_gr = datetime.now(ZoneInfo("Europe/Athens")).isoformat()
    except:
        now_gr = (datetime.utcnow() + timedelta(hours=3)).isoformat()
    
    log_entry = {
        "id": str(uuid.uuid4()),
        "timestamp": now_gr,
        "username": user,
        "action_type": action_type,
        "table_name": table_name,
        "details": str(details_raw)[:2000]
    }
    try:
        res = supabase.table("activity_logs").insert(log_entry).execute()
        if res.data:
            st.session_state.global_db_ts = res.data[0]['timestamp']
    except Exception as e:
        print(f"Log Error: {e}")

# ==========================================
# ΕΝΣΩΜΑΤΩΣΗ ΛΟΓΙΚΗΣ ΣΥΓΧΡΟΝΙΣΜΟΥ (ΑΠΟΦΥΓΗ CIRCULAR IMPORTS)
# ==========================================

def inject_silent_refresh_css():
    st.markdown(
        """
        <style>
        /* 1. Εξαφάνιση του προεπιλεγμένου εικονιδίου 'Running...' */
        [data-testid="stStatusWidget"] { 
            visibility: hidden !important; 
            display: none !important; 
        }
        
        /* 2. Κλείδωμα της διαφάνειας στο 100% για να μην "θολώνει" (αφαίρεση του veil effect) */
        [data-testid="stAppViewContainer"], 
        [data-testid="stMainBlockContainer"],
        [data-testid="stAppViewBlockContainer"],
        .stApp, .stApp > div {
            opacity: 1 !important;
            filter: none !important;
            transition: none !important;
        }
        
        /* 3. Κρύβουμε την κόκκινη/πολύχρωμη γραμμή φόρτωσης στην κορυφή */
        [data-testid="stDecoration"] { 
            display: none !important; 
        }
        </style>
        """,
        unsafe_allow_html=True
    )

def to_timestamp(iso_str):
    if not iso_str: return 0.0
    try: return datetime.fromisoformat(iso_str.replace("Z", "+00:00")).timestamp()
    except Exception: return 0.0

def get_db_current_time():
    if not supabase: return datetime.utcnow().isoformat()
    try:
        res = supabase.rpc("get_server_time").execute()
        if res.data: return res.data
    except Exception: pass
    return datetime.utcnow().isoformat()

def apply_delta_updates(table_name, local_list, delta_records, deleted_ids):
    if deleted_ids:
        local_list = [r for r in local_list if str(r.get('id')) not in deleted_ids]
    updated_ids = {str(r['id']) for r in delta_records}
    local_list = [r for r in local_list if str(r.get('id')) not in updated_ids]
    local_list.extend(delta_records)
    return local_list

def track_deletion(table_name, record_id):
    if not supabase: return
    deletion_log = {"table_name": table_name, "record_id": str(record_id)}
    try: supabase.table("deleted_records").insert(deletion_log).execute()
    except Exception: pass

def sync_data_incremental():
    inject_silent_refresh_css()
    if not supabase: return

    last_sync = st.session_state.get("last_sync_time", None)
    current_db_time = get_db_current_time()

    if not last_sync:
        with st.spinner("Φόρτωση δεδομένων..."):
            st.session_state.employees = fetch_paginated("employees")
            st.session_state.projects = fetch_paginated("projects")
            
            assigns = fetch_paginated("assignments")
            for a in assigns:
                d = safe_date_parse(a.get('date'))
                if d: a['date'] = d
            st.session_state.assignments = assigns
            
            leaves = fetch_paginated("leaves")
            for l in leaves:
                sd = safe_date_parse(l.get('startDate'))
                if sd: l['startDate'] = sd
                ed = safe_date_parse(l.get('endDate'))
                if ed: l['endDate'] = ed
            st.session_state.leaves = leaves
            
            patterns = fetch_paginated("recurring_patterns")
            for p in patterns:
                sd = safe_date_parse(p.get('startDate'))
                if sd: p['startDate'] = sd
            st.session_state.recurring_patterns = patterns
            
            try: st.session_state.evaluations = fetch_paginated("evaluations")
            except Exception: st.session_state.evaluations = []
                
            st.session_state.last_sync_time = current_db_time
            mark_data_changed()
            return

    try:
        res_logs = supabase.table("activity_logs").select("timestamp").order("timestamp", desc=True).limit(1).execute()
        if res_logs.data:
            latest_ts = to_timestamp(res_logs.data[0]['timestamp'])
            sync_ts = to_timestamp(last_sync)
            if (latest_ts + 30.0) <= sync_ts: return

        deleted_res = supabase.table("deleted_records").select("table_name, record_id").gte("deleted_at", last_sync).execute()
        deletions = deleted_res.data or []
        
        deleted_by_table = {}
        for d in deletions:
            t = d['table_name']
            if t not in deleted_by_table: deleted_by_table[t] = []
            deleted_by_table[t].append(str(d['record_id']))

        tables_to_sync = ["employees", "projects", "assignments", "leaves", "recurring_patterns", "evaluations"]
        changes_detected = False

        for table in tables_to_sync:
            delta_res = supabase.table(table).select("*").gte("updated_at", last_sync).execute()
            delta_records = delta_res.data or []
            table_deleted_ids = deleted_by_table.get(table, [])
            
            if delta_records or table_deleted_ids:
                changes_detected = True
                if table == "assignments":
                    for r in delta_records:
                        d = safe_date_parse(r.get('date'))
                        if d: r['date'] = d
                elif table == "leaves":
                    for r in delta_records:
                        sd = safe_date_parse(r.get('startDate'))
                        if sd: r['startDate'] = sd
                        ed = safe_date_parse(r.get('endDate'))
                        if ed: r['endDate'] = ed
                elif table == "recurring_patterns":
                    for r in delta_records:
                        sd = safe_date_parse(r.get('startDate'))
                        if sd: r['startDate'] = sd

                st.session_state[table] = apply_delta_updates(
                    table, st.session_state.get(table, []), delta_records, table_deleted_ids
                )

        if changes_detected: mark_data_changed()
        st.session_state.last_sync_time = current_db_time

    except Exception as e:
        print(f"Incremental Sync Error: {e}")

# ==========================================
# ΣΥΝΕΧΕΙΑ ΛΕΙΤΟΥΡΓΙΩΝ ΒΑΣΗΣ
# ==========================================

def db_insert_bulk_background(table, data, log_action="ΜΑΖΙΚΗ ΠΡΟΣΘΗΚΗ", log_details=""):
    if not supabase or not data: return
    
    def _thread_task():
        chunk_size = 500
        for i in range(0, len(data), chunk_size):
            try:
                supabase.table(table).insert(serialize_dates(data[i:i+chunk_size])).execute()
            except Exception as e:
                print(f"Bulk insert error: {e}")
        
        try:
            now_utc = datetime.utcnow().isoformat() + "Z"
            log_entry = {
                "id": str(uuid.uuid4()),
                "timestamp": now_utc,
                "username": st.session_state.get("current_user", "Σύστημα (Παρασκήνιο)"),
                "action_type": log_action,
                "table_name": table,
                "details": log_details or f"Προστέθηκαν {len(data)} εγγραφές"
            }
            supabase.table("activity_logs").insert(log_entry).execute()
        except: pass

    threading.Thread(target=_thread_task, daemon=True).start()

def db_insert(table, data, track=True):
    mark_data_changed()

    if track:
        records = data if isinstance(data, list) else [data]
        add_transaction([{'type': 'insert', 'table': table, 'records': records}])

    # Αν δεν υπάρχει Supabase, θεωρούμε επιτυχία για τοπική/δοκιμαστική χρήση.
    if not supabase:
        return True

    try:
        supabase.table(table).insert(serialize_dates(data)).execute()
        log_activity("ΠΡΟΣΘΗΚΗ", table, format_log_details(table, data))
        return True
    except Exception as e:
        st.error(f"Σφάλμα αποθήκευσης στη βάση: {e}")
        return False

def db_delete(table, column, value, deleted_records=None, track=True):
    mark_data_changed()
    if not deleted_records:
        table_data = st.session_state.get(table, [])
        deleted_records = [r for r in table_data if r.get(column) == value]
    if track and deleted_records:
        add_transaction([{'type': 'delete', 'table': table, 'records': deleted_records}])
    if supabase:
        try:
            supabase.table(table).delete().eq(column, value).execute()
            log_activity("ΔΙΑΓΡΑΦΗ", table, format_log_details(table, deleted_records) if deleted_records else f"{column} = {value}")
            for r in deleted_records:
                rec_id = r.get('id')
                if rec_id: track_deletion(table, rec_id)
        except Exception as e:
            st.error(f"Σφάλμα διαγραφής στη βάση: {e}")

def db_delete_in(table, column, values, deleted_records=None, track=True):
    mark_data_changed()
    if values:
        if not deleted_records:
            table_data = st.session_state.get(table, [])
            deleted_records = [r for r in table_data if r.get(column) in values]
        if track and deleted_records:
            add_transaction([{'type': 'delete', 'table': table, 'records': deleted_records}])
        if supabase:
            try:
                chunk_size = 100
                for i in range(0, len(values), chunk_size):
                    chunk_values = values[i:i+chunk_size]
                    supabase.table(table).delete().in_(column, chunk_values).execute()
                    
                log_activity("ΜΑΖΙΚΗ ΔΙΑΓΡΑΦΗ", table, format_log_details(table, deleted_records) if deleted_records else f"{len(values)} εγγραφές")
                for r in deleted_records:
                    rec_id = r.get('id')
                    if rec_id: track_deletion(table, rec_id)
            except Exception as e:
                st.error(f"Σφάλμα μαζικής διαγραφής: {e}")

def db_update(table, id_val, new_data, old_data=None, track=True):
    mark_data_changed()
    if track and not old_data:
        table_data = st.session_state.get(table, [])
        old_data = next((r for r in table_data if r.get('id') == id_val), None)
    if track and old_data:
        add_transaction([{'type': 'update', 'table': table, 'old_records': [old_data], 'new_records': [new_data]}])
    if supabase:
        try:
            supabase.table(table).update(serialize_dates(new_data)).eq('id', id_val).execute()
            log_activity("ΕΝΗΜΕΡΩΣΗ", table, format_log_details(table, new_data))
        except Exception as e:
            st.error(f"Σφάλμα ενημέρωσης στη βάση: {e}")

def perform_undo():
    if not st.session_state.get('undo_stack'): return
    transaction = st.session_state.undo_stack.pop()
    st.session_state.redo_stack.append(transaction)
    for act in reversed(transaction):
        if act['type'] == 'insert':
            ids = [r['id'] for r in act['records']]
            db_delete_in(act['table'], 'id', ids, track=False)
        elif act['type'] == 'delete':
            db_insert(act['table'], act['records'], track=False)
        elif act['type'] == 'update':
            for old_r in act['old_records']:
                db_update(act['table'], old_r['id'], old_r, track=False)
    mark_data_changed()

def perform_redo():
    if not st.session_state.get('redo_stack'): return
    transaction = st.session_state.redo_stack.pop()
    st.session_state.undo_stack.append(transaction)
    for act in transaction:
        if act['type'] == 'insert':
            db_insert(act['table'], act['records'], track=False)
        elif act['type'] == 'delete':
            ids = [r['id'] for r in act['records']]
            db_delete_in(act['table'], 'id', ids, track=False)
        elif act['type'] == 'update':
            for new_r in act['new_records']:
                db_update(act['table'], new_r['id'], new_r, track=False)
    mark_data_changed()

def get_employee_name(emp_id):
    if not emp_id: return "Χωρίς Προσωπικό"
    emp = st.session_state.get('emp_map', {}).get(emp_id)
    return emp.get('name', 'Άγνωστος') if emp else "Άγνωστος"

def get_project_name(proj_id):
    proj = st.session_state.get('proj_map', {}).get(proj_id)
    return proj.get('name', 'Άγνωστο Έργο') if proj else "Άγνωστο Έργο"

def get_project_info(proj_id):
    return st.session_state.get('proj_map', {}).get(proj_id)

def auto_extend_recurring_patterns():
    if not st.session_state.get('recurring_patterns'): return
    max_dates = {}
    for a in st.session_state.get('assignments', []):
        if not isinstance(a, dict): continue
        rid = a.get('recurring_id')
        if rid:
            d = safe_date_parse(a.get('date'))
            if d:
                if rid not in max_dates or d > max_dates[rid]:
                    max_dates[rid] = d
    
    new_assignments_batch = []
    today = date.today()
    for pat in st.session_state.get('recurring_patterns', []):
        if not isinstance(pat, dict): continue
        rid = pat.get('id')
        if not rid: continue
        
        latest_date = max_dates.get(rid)
        
        if not latest_date:
            pat_start = safe_date_parse(pat.get('startDate'))
            if pat_start:
                latest_date = pat_start - timedelta(days=1)
            else:
                latest_date = today - timedelta(days=1)
        
        if (latest_date - today).days <= 30:
            start_ext_date = latest_date + timedelta(days=1)
            target_end_date = today + timedelta(days=365)
            end_ext_date = max(start_ext_date + timedelta(days=30), target_end_date)
            
            if start_ext_date > end_ext_date:
                continue
            
            r_type = pat.get('type')
            
            r_emps_raw = pat.get('employeeIds', [])
            if isinstance(r_emps_raw, str):
                try: r_emps = ast.literal_eval(r_emps_raw)
                except: r_emps = []
            else:
                r_emps = r_emps_raw
                
            r_proj = pat.get('projectId')
            r_color = pat.get('colorName')
            c_hex = config.BASIC_COLORS.get(r_color, "#999999")
            r_notes = pat.get('notes', "")
            str_arrival = pat.get('arrivalTime', "")
            str_start = str(pat.get('startTime'))[:5] if pat.get('startTime') else "09:00"
            str_end = str(pat.get('endTime'))[:5] if pat.get('endTime') else "17:00"
            
            weekdays_raw = pat.get('weekdays', [])
            if isinstance(weekdays_raw, str):
                try: selected_weekdays = ast.literal_eval(weekdays_raw)
                except: selected_weekdays = []
            else:
                selected_weekdays = weekdays_raw
                
            dates_to_assign = []
            curr_date = start_ext_date
            day_map_inv = {0: "Δευτέρα", 1: "Τρίτη", 2: "Τετάρτη", 3: "Πέμπτη", 4: "Παρασκευή", 5: "Σάββατο", 6: "Κυριακή"}
            day_map = {v: k for k, v in day_map_inv.items()}
            
            selected_weekday_ints = []
            if selected_weekdays:
                for d_val in selected_weekdays:
                    if isinstance(d_val, int):
                        selected_weekday_ints.append(d_val)
                    elif d_val in day_map:
                        selected_weekday_ints.append(day_map[d_val])
            
            while curr_date <= end_ext_date:
                if r_type == "Εβδομαδιαία":
                    dates_to_assign.append(curr_date)
                    curr_date += timedelta(days=7)
                elif r_type == "Μηνιαία":
                    dates_to_assign.append(curr_date)
                    month = curr_date.month
                    year = curr_date.year
                    if month == 12:
                        month = 1; year += 1
                    else:
                        month += 1
                    try:
                        curr_date = curr_date.replace(year=year, month=month)
                    except ValueError:
                        last_day = calendar.monthrange(year, month)[1]
                        curr_date = curr_date.replace(year=year, month=month, day=last_day)
                elif r_type == "Επιλεγμένες Μέρες Εβδομάδας":
                    if curr_date.weekday() in selected_weekday_ints:
                        dates_to_assign.append(curr_date)
                    curr_date += timedelta(days=1)
                else:
                    curr_date += timedelta(days=1)
            
            for d in dates_to_assign:
                if r_type == "Επιλεγμένες Μέρες Εβδομάδας":
                    d_name = day_map_inv[d.weekday()]
                    emps_to_process = r_emps.get(d_name, []) if isinstance(r_emps, dict) else r_emps
                else:
                    emps_to_process = r_emps
                
                emps_to_process = emps_to_process if emps_to_process else [""]
                leaves_dict = st.session_state.get('leaves_by_emp', {})
                day_assigns = st.session_state.get('assignments_by_date', {}).get(d, [])
                
                for eid in emps_to_process:
                    final_eid = eid
                    final_start = str_start
                    final_end = str_end
                    conflict_note = ""
                    
                    if eid:
                        if scheduling.is_on_leave(eid, d, leaves_dict):
                            final_eid = ""
                            emp_name = get_employee_name(eid)
                            conflict_note = f"[Άδεια: {emp_name}]"
                        else:
                            adj_start, adj_end, is_conflict, msg = scheduling.check_and_resolve_conflict(eid, str_start, str_end, day_assigns)
                            if is_conflict:
                                final_eid = ""
                                emp_name = get_employee_name(eid)
                                conflict_note = f"[Εμπλοκή: {emp_name}]"
                            else:
                                final_start = adj_start
                                final_end = adj_end
                    
                    combined_notes = r_notes
                    if conflict_note:
                        combined_notes = f"{r_notes} {conflict_note}".strip()
                    
                    new_assign = {
                        'id': str(uuid.uuid4()), 'recurring_id': rid, 'employeeId': final_eid, 'projectId': r_proj,
                        'date': d, 'arrivalTime': str_arrival, 'startTime': final_start, 'endTime': final_end,
                        'colorName': r_color, 'colorHex': c_hex, 'notes': combined_notes, 'is_cancelled': False, 'cancel_reason': ""
                    }
                    new_assignments_batch.append(new_assign)
                    if 'assignments_by_date' not in st.session_state:
                        st.session_state.assignments_by_date = {}
                    if d not in st.session_state.assignments_by_date:
                        st.session_state.assignments_by_date[d] = []
                    st.session_state.assignments_by_date[d].append(new_assign)
                    
    if new_assignments_batch:
        if 'assignments' not in st.session_state:
            st.session_state.assignments = []
        st.session_state.assignments.extend(new_assignments_batch)
        st.session_state.data_dirty = True
        st.session_state.local_gantt_version = st.session_state.get('local_gantt_version', 0) + 1
        db_insert_bulk_background('assignments', new_assignments_batch, "ΑΥΤΟΜΑΤΗ ΕΠΕΚΤΑΣΗ", f"Επεκτάθηκαν {len(new_assignments_batch)} βάρδιες στο παρασκήνιο")

def cleanup_duplicates():
    """Ο Σιωπηλός Καθαριστής: Εξολοθρεύει τα 'Φαντάσματα' με 100% ασφάλεια τύπων (TypeError Proof)."""
    if not st.session_state.get('assignments'): return
    
    seen_signatures = set()
    duplicates_to_kill = []
    clean_assignments = []
    
    for a in st.session_state.get('assignments', []):
        if not isinstance(a, dict): continue
        sig = (
            str(a.get('date', '')), 
            str(a.get('projectId', '')), 
            str(a.get('employeeId', '')), 
            str(a.get('startTime', ''))[:5] if a.get('startTime') else "", 
            str(a.get('endTime', ''))[:5] if a.get('endTime') else "",
            str(a.get('notes', ''))
        )
        if sig in seen_signatures:
            duplicates_to_kill.append(a)
        else:
            seen_signatures.add(sig)
            clean_assignments.append(a)
            
    if duplicates_to_kill:
        st.session_state.assignments = clean_assignments
        st.session_state.data_dirty = True
        dup_ids = [d['id'] for d in duplicates_to_kill if d.get('id')]
        
        if supabase and dup_ids:
            def delete_ghosts():
                chunk_size = 100
                for i in range(0, len(dup_ids), chunk_size):
                    chunk = dup_ids[i:i+chunk_size]
                    try:
                        supabase.table('assignments').delete().in_('id', chunk).execute()
                        for rec_id in chunk:
                            track_deletion('assignments', rec_id)
                    except: pass
                
                try:
                    now_utc = datetime.utcnow().isoformat() + "Z"
                    log_entry = {
                        "id": str(uuid.uuid4()),
                        "timestamp": now_utc,
                        "username": "Σύστημα (Καθαριστής)",
                        "action_type": "ΕΚΚΑΘΑΡΙΣΗ",
                        "table_name": "assignments",
                        "details": f"Διαγράφηκαν {len(dup_ids)} διπλότυπες βάρδιες"
                    }
                    supabase.table("activity_logs").insert(log_entry).execute()
                except: pass
            threading.Thread(target=delete_ghosts, daemon=True).start()

def cleanup_projects():
    """Συγχωνεύει τα διπλά έργα με 100% προστασία από None (AttributeError Proof)."""
    if not st.session_state.get('projects'): return
    
    name_map = {}
    projects_to_kill = []
    projects_to_keep = []
    id_remap = {}
    
    for p in st.session_state.get('projects', []):
        if not isinstance(p, dict): continue
        name_lower = str(p.get('name') or '').strip().lower()
        
        if not name_lower:
            projects_to_keep.append(p)
            continue
            
        if name_lower in name_map:
            keep_id = name_map[name_lower]
            projects_to_kill.append(p)
            pid = p.get('id')
            if pid:
                id_remap[pid] = keep_id
        else:
            pid = p.get('id')
            if pid:
                name_map[name_lower] = pid
            projects_to_keep.append(p)
            
    if projects_to_kill:
        st.session_state.projects = projects_to_keep
        
        assignments_to_update = []
        for a in st.session_state.get('assignments', []):
            if isinstance(a, dict) and a.get('projectId') in id_remap:
                a['projectId'] = id_remap[a['projectId']]
                assignments_to_update.append(a)
                
        patterns_to_update = []
        for pat in st.session_state.get('recurring_patterns', []):
            if isinstance(pat, dict) and pat.get('projectId') in id_remap:
                pat['projectId'] = id_remap[pat['projectId']]
                patterns_to_update.append(pat)
                
        st.session_state.data_dirty = True
        
        if supabase:
            def merge_db():
                for a in assignments_to_update:
                    if a.get('id'):
                        try: supabase.table('assignments').update({'projectId': a['projectId']}).eq('id', a['id']).execute()
                        except: pass
                for pat in patterns_to_update:
                    if pat.get('id'):
                        try: supabase.table('recurring_patterns').update({'projectId': pat['projectId']}).eq('id', pat['id']).execute()
                        except: pass
                
                chunk_size = 100
                del_ids = [p['id'] for p in projects_to_kill if p.get('id')]
                for i in range(0, len(del_ids), chunk_size):
                    try: 
                        chunk = del_ids[i:i+chunk_size]
                        supabase.table('projects').delete().in_('id', chunk).execute()
                        for rec_id in chunk:
                            track_deletion('projects', rec_id)
                    except: pass
                
                try:
                    now_utc = datetime.utcnow().isoformat() + "Z"
                    log_entry = {
                        "id": str(uuid.uuid4()),
                        "timestamp": now_utc,
                        "username": "Σύστημα (Καθαριστής)",
                        "action_type": "ΕΚΚΑΘΑΡΙΣΗ",
                        "table_name": "projects",
                        "details": f"Συγχωνεύτηκαν {len(projects_to_kill)} διπλότυπα έργα"
                    }
                    supabase.table("activity_logs").insert(log_entry).execute()
                except: pass
            threading.Thread(target=merge_db, daemon=True).start()

def init_data_and_sync():
    init_undo_stack()

    # Full sync μία φορά ανά χρήστη/session.
    # Καλύπτει και περιπτώσεις όπου ο χρήστης μπαίνει από ήδη ανοιχτό tab
    # και δεν περνά ξανά από το login form.
    current_user = st.session_state.get("current_user")
    if current_user and st.session_state.get("full_sync_done_for_user") != current_user:
        st.session_state.last_sync_time = None
        st.session_state.full_sync_done_for_user = current_user
    
    try:
        import database
        database.sync_data_incremental()
    except Exception as e:
        print(f"Αποτροπή κρασαρίσματος από το Database Sync: {e}")

    if 'view_week_date' not in st.session_state:
        st.session_state.view_week_date = date.today()

    valid_assignments = []
    for a in st.session_state.get('assignments', []):
        if isinstance(a, dict):
            parsed_d = safe_date_parse(a.get('date'))
            if parsed_d:
                a['date'] = parsed_d
                valid_assignments.append(a)
    st.session_state.assignments = valid_assignments

    valid_leaves = []
    for l in st.session_state.get('leaves', []):
        if isinstance(l, dict):
            sd = safe_date_parse(l.get('startDate'))
            ed = safe_date_parse(l.get('endDate'))
            if sd: l['startDate'] = sd
            if ed: l['endDate'] = ed
            valid_leaves.append(l)
    st.session_state.leaves = valid_leaves

    cleanup_duplicates()
    cleanup_projects()

    st.session_state.emp_map = {e['id']: e for e in st.session_state.get('employees', []) if isinstance(e, dict) and 'id' in e}
    st.session_state.proj_map = {p['id']: p for p in st.session_state.get('projects', []) if isinstance(p, dict) and 'id' in p}
    
    assign_date_map = {}
    for a in st.session_state.get('assignments', []):
        d = a.get('date')
        if d:
            if d not in assign_date_map: assign_date_map[d] = []
            assign_date_map[d].append(a)
    st.session_state.assignments_by_date = assign_date_map
    
    leaves_by_emp = {}
    for l in st.session_state.get('leaves', []):
        eid = l.get('employeeId')
        if eid:
            if eid not in leaves_by_emp: leaves_by_emp[eid] = []
            leaves_by_emp[eid].append(l)
    st.session_state.leaves_by_emp = leaves_by_emp
    
    st.session_state.data_dirty = False

    if "last_auto_extend_check" not in st.session_state or time.time() - st.session_state.last_auto_extend_check > 3600:
        auto_extend_recurring_patterns()
        st.session_state.last_auto_extend_check = time.time()

def setup_shared_ui(show_menu=False, menu_options=None):
    st.markdown("""
    <style>
    /* =========================================================
       STAFF.PRO sidebar HTML/CSS skin
       Αλλάζει μόνο εμφάνιση. Δεν αλλάζει καθόλου λειτουργικότητα.
       ========================================================= */

    [data-testid="stSidebar"] {
        background: #f8fafc !important;
        border-right: 1px solid #e2e8f0 !important;
        box-shadow: 8px 0 24px rgba(15, 23, 42, 0.08) !important;
    }

    [data-testid="stSidebar"] > div:first-child {
        padding-top: 1.1rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }

    /* Streamlit multipage menu:
       streamlit app / Gantt Dashboard / Management / Viber Export */
    [data-testid="stSidebarNav"] {
        padding-top: 0.3rem !important;
        padding-bottom: 0.8rem !important;
        border-bottom: 1px solid #e2e8f0 !important;
        margin-bottom: 1rem !important;
    }

    [data-testid="stSidebarNav"] ul {
        padding-left: 0 !important;
        gap: 0.25rem !important;
    }

    [data-testid="stSidebarNav"] li {
        margin: 0.15rem 0 !important;
    }

    [data-testid="stSidebarNav"] a {
        border-radius: 9px !important;
        padding: 0.50rem 0.60rem !important;
        color: #334155 !important;
        font-weight: 600 !important;
        text-decoration: none !important;
        transition: background 0.15s ease, color 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease !important;
    }

    [data-testid="stSidebarNav"] a:hover {
        background: #e2e8f0 !important;
        color: #0f172a !important;
        transform: translateX(2px) !important;
        box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08) !important;
    }

    [data-testid="stSidebarNav"] a[aria-current="page"] {
        background: #e2e8f0 !important;
        color: #0f172a !important;
        font-weight: 800 !important;
        box-shadow: inset 3px 0 0 #334155, 0 2px 6px rgba(15, 23, 42, 0.08) !important;
    }

    /* Management εσωτερικό menu: st.sidebar.radio σαν HTML menu buttons */
    [data-testid="stSidebar"] div[role="radiogroup"] {
        gap: 0.35rem !important;
        display: flex !important;
        flex-direction: column !important;
    }

    [data-testid="stSidebar"] div[role="radiogroup"] label {
        background: #ffffff !important;
        border: 1px solid #cbd5e1 !important;
        border-radius: 9px !important;
        padding: 0.55rem 0.65rem !important;
        margin: 0.05rem 0 !important;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06) !important;
        transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease !important;
        cursor: pointer !important;
    }

    [data-testid="stSidebar"] div[role="radiogroup"] label:hover {
        background: #f1f5f9 !important;
        border-color: #94a3b8 !important;
        transform: translateX(2px) !important;
        box-shadow: 0 4px 10px rgba(15, 23, 42, 0.10) !important;
    }

    [data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {
        background: #e2e8f0 !important;
        border-color: #94a3b8 !important;
        box-shadow: inset 3px 0 0 #334155, 0 2px 6px rgba(15, 23, 42, 0.08) !important;
    }

    [data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) p {
        color: #0f172a !important;
        font-weight: 800 !important;
    }

    [data-testid="stSidebar"] div[role="radiogroup"] input {
        display: none !important;
    }

    /* Sidebar titles / text */
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {
        color: #1e293b !important;
        letter-spacing: 0.02em !important;
    }

    [data-testid="stSidebar"] hr {
        margin: 1rem 0 !important;
        border-color: #e2e8f0 !important;
    }

    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] label {
        color: #334155;
    }

    /* Streamlit buttons μέσα στη sidebar: Undo / Redo / Refresh / Logout */
    [data-testid="stSidebar"] .stButton > button {
        width: 100% !important;
        border-radius: 9px !important;
        border: 1px solid #cbd5e1 !important;
        background: #ffffff !important;
        color: #334155 !important;
        font-weight: 700 !important;
        min-height: 2.35rem !important;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06) !important;
        transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease !important;
    }

    [data-testid="stSidebar"] .stButton > button:hover:not(:disabled) {
        background: #f1f5f9 !important;
        border-color: #94a3b8 !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 10px rgba(15, 23, 42, 0.10) !important;
    }

    [data-testid="stSidebar"] .stButton > button:disabled {
        opacity: 0.45 !important;
        background: #f8fafc !important;
        color: #94a3b8 !important;
        box-shadow: none !important;
    }

    [data-testid="stSidebar"] [data-testid="stAlert"] {
        border-radius: 10px !important;
        border: 1px solid rgba(148, 163, 184, 0.35) !important;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06) !important;
    }

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

    .hidden-btn-container {
        display: none !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    polling_js = """
    (function () {
        if (window.staffProSmartPollingStarted) return;
        window.staffProSmartPollingStarted = true;

        function userIsWorking() {
            const isEditing = doc.getElementById("is_editing_flag");
            if (isEditing) return true;

            if (doc.hidden) return true;

            const active = doc.activeElement;
            if (active) {
                const tag = (active.tagName || "").toLowerCase();
                const role = active.getAttribute ? (active.getAttribute("role") || "") : "";
                if (["input", "textarea", "select", "button"].includes(tag)) return true;
                if (["combobox", "listbox", "textbox", "spinbutton", "slider"].includes(role)) return true;
                if (active.isContentEditable) return true;
            }

            return false;
        }

        function clickCheckUpdates() {
            if (userIsWorking()) return;

            const buttons = doc.querySelectorAll("button");
            for (let btn of buttons) {
                if (btn.innerText && btn.innerText.includes("🔄 Check Updates")) {
                    btn.click();
                    break;
                }
            }
        }

        setInterval(clickCheckUpdates, 30000);
    })();
    """ if not show_menu else ""
    
    components.html("""
    <script>
    const doc = window.parent.document;
    
    // 1. Ψηφιακό Ρολόι
    let clockDiv = doc.getElementById("staff_pro_clock");
    if (!clockDiv) {
        clockDiv = doc.createElement("div");
        clockDiv.id = "staff_pro_clock";
        doc.body.appendChild(clockDiv);
        clockDiv.style.cssText = "position: fixed; top: 12px; right: 300px; font-size: 18px; font-weight: bold; color: #1e293b; z-index: 999999; background: #ffffff; padding: 6px 14px; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06); border: 1px solid #cbd5e1; font-family: 'Courier New', Courier, monospace; letter-spacing: 2px;";
    }
    function updateClock() {
        const now = new Date();
        const dateOptions = { day: 'numeric', month: 'long', year: 'numeric' };
        clockDiv.innerHTML = now.toLocaleDateString('el-GR', dateOptions) + " | " + now.toLocaleTimeString('el-GR', {hour12: false});
    }
    updateClock();
    setInterval(updateClock, 1000);

    // 2. Εναλλασσόμενα Εικονίδια Καθαριότητας
    let loaderDiv = doc.getElementById("staff_pro_cleaner");
    if (!loaderDiv) {
        loaderDiv = doc.createElement("div");
        loaderDiv.id = "staff_pro_cleaner";
        doc.body.appendChild(loaderDiv);
        loaderDiv.style.cssText = "position: fixed; top: 12px; right: 20px; font-size: 20px; font-weight: bold; color: #334155; z-index: 999999; display: none; background: #f8fafc; padding: 6px 14px; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); border: 1px solid #cbd5e1; font-family: sans-serif; letter-spacing: 1px;";
    }
    
    const cleaningIcons = ["🧹", "🪣", "🧼", "🧽"];
    let cIdx = 0;
    setInterval(() => {
        loaderDiv.innerText = "Ανανέωση " + cleaningIcons[cIdx];
        cIdx = (cIdx + 1) % cleaningIcons.length;
    }, 400);

    let refreshBadgeTimer = null;
    setInterval(() => {
        const isRunning = doc.querySelector('[data-testid="stStatusWidget"]');
        if (isRunning) {
            if (!refreshBadgeTimer && loaderDiv.style.display !== 'block') {
                refreshBadgeTimer = setTimeout(() => {
                    loaderDiv.style.display = 'block';
                    refreshBadgeTimer = null;
                }, 900);
            }
        } else {
            if (refreshBadgeTimer) {
                clearTimeout(refreshBadgeTimer);
                refreshBadgeTimer = null;
            }
            loaderDiv.style.display = 'none';
        }
    }, 150);

    """ + polling_js + """
    </script>
    """, height=0, width=0)

    st.sidebar.title("STAFF.PRO")
    st.sidebar.write("---")
    
    selected_menu = None
    if show_menu and menu_options:
        selected_menu = st.sidebar.radio("Μενού Επιλογών", menu_options)
        st.sidebar.write("---")
    
    col_u, col_r = st.sidebar.columns(2)
    with col_u:
        if st.button("⏪ Undo", disabled=len(st.session_state.get('undo_stack', [])) == 0, use_container_width=True):
            perform_undo()
            st.rerun()
    with col_r:
        if st.button("⏩ Redo", disabled=len(st.session_state.get('redo_stack', [])) == 0, use_container_width=True):
            perform_redo()
            st.rerun()
            
    st.sidebar.write("---")
    st.sidebar.subheader("Κατάσταση Συστήματος")
    if supabase:
        st.sidebar.success("☁️ Cloud Sync (Incremental)")
        
        st.sidebar.markdown('<div class="hidden-btn-container">', unsafe_allow_html=True)
        if st.sidebar.button("🔄 Check Updates", key="hidden_silent_refresh_btn"):
            st.rerun()
        st.sidebar.markdown('</div>', unsafe_allow_html=True)
        
        if st.sidebar.button("🔄 Άμεση Ανανέωση", use_container_width=True):
            st.session_state.last_sync_time = None 
            st.rerun()
    else:
        st.sidebar.error("🔌 Εκτός Σύνδεσης (Τοπικά)")
        
    if not SUPABASE_INSTALLED:
        st.sidebar.caption("⚠️ **Πρόβλημα:** Λείπει η βιβλιοθήκη 'supabase'. Κάνε Reboot την εφαρμογή.")
    elif not HAS_SECRETS:
        st.sidebar.caption("⚠️ **Πρόβλημα:** Δεν βρέθηκαν τα Secrets (SUPABASE_URL ή SUPABASE_KEY).")

    st.sidebar.write("---")
    st.sidebar.markdown(f"👤 Συνδεδεμένος ως: **{st.session_state.get('current_user', 'Άγνωστος')}**")
    if st.sidebar.button("🚪 Αποσύνδεση", use_container_width=True):
        # Καθαρό logout: δεν αφήνουμε cached δεδομένα/χρόνους sync
        # να περάσουν στον επόμενο χρήστη στο ίδιο browser/session.
        for key in [
            "last_sync_time",
            "full_sync_done_for_user",
            "employees",
            "projects",
            "assignments",
            "leaves",
            "recurring_patterns",
            "evaluations",
            "emp_map",
            "proj_map",
            "assignments_by_date",
            "leaves_by_emp",
            "data_dirty",
        ]:
            st.session_state.pop(key, None)

        st.session_state.authenticated = False
        st.session_state.current_user = None
        st.switch_page("streamlit_app.py")

    today_date = date.today()
    orphan_count = 0
    orphan_details = []
    for i in range(8):
        check_d = today_date + timedelta(days=i)
        day_assigns = st.session_state.get('assignments_by_date', {}).get(check_d, [])
        for a in day_assigns:
            if not a.get('employeeId') and not a.get('is_cancelled', False):
                orphan_count += 1
                proj = get_project_info(a['projectId'])
                proj_name = proj.get('name', "Άγνωστο Έργο") if proj else "Άγνωστο Έργο"
                orphan_details.append(f"🔴 **{check_d.strftime('%d/%m/%Y')}** | Ώρες: {str(a.get('startTime', ''))[:5]}-{str(a.get('endTime', ''))[:5]} | Έργο: **{proj_name}**")
    
    if orphan_count > 0:
        st.error(f"⚠️ **Προσοχή: {orphan_count} βάρδια/ες τις επόμενες 7 ημέρες έμειναν ορφανές (χωρίς προσωπικό)!**")
        with st.expander("🔍 Δείτε αναλυτικά τις ορφανές βάρδιες"):
            for detail in orphan_details:
                st.markdown(detail)
        st.write("---")

    return selected_menu
