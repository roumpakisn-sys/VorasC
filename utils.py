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
    HAS_SECRETS = (
        "SUPABASE_URL" in st.secrets
        and (
            "SUPABASE_SERVICE_ROLE_KEY" in st.secrets
            or "SUPABASE_KEY" in st.secrets
        )
    )
except Exception:
    HAS_SECRETS = False

@st.cache_resource
def init_supabase():
    """
    Server-side Supabase client.

    Προτιμά το SUPABASE_SERVICE_ROLE_KEY για το Streamlit backend,
    ώστε η εφαρμογή να συνεχίσει να δουλεύει σωστά ακόμη και όταν
    ενεργοποιήσουμε RLS στους πίνακες.

    Το SUPABASE_SERVICE_ROLE_KEY δεν πρέπει ποτέ να μπαίνει σε JavaScript,
    HTML ή αρχείο GitHub. Μόνο στα Streamlit Secrets.
    """
    if not SUPABASE_INSTALLED or not HAS_SECRETS:
        return None

    try:
        supabase_url = st.secrets["SUPABASE_URL"]
        supabase_backend_key = st.secrets.get("SUPABASE_SERVICE_ROLE_KEY") or st.secrets.get("SUPABASE_KEY")
        return create_client(supabase_url, supabase_backend_key)
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

def touch_app_sync_state():
    """
    Ενημερώνει τον μικρό πίνακα app_sync_state μέσω Supabase RPC,
    ώστε τα άλλα ανοιχτά sessions να καταλάβουν ότι υπάρχει πραγματική αλλαγή.

    Χρησιμοποιεί τη function public.touch_app_sync_state_public().
    Είναι σιωπηλό: αν αποτύχει, δεν πρέπει να χαλάσει η βασική αποθήκευση.
    """
    if not supabase:
        return

    try:
        supabase.rpc("touch_app_sync_state_public").execute()
    except Exception as e:
        print(f"App sync state touch failed: {e}")

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
    """
    Wrapper συγχρονισμού.

    Το επίσημο ενεργό sync βρίσκεται στο database.py.
    Κρατάμε αυτή τη συνάρτηση μόνο για συμβατότητα, ώστε αν κάποιο αρχείο
    καλέσει utils.sync_data_incremental(), να χρησιμοποιεί τον ίδιο μηχανισμό
    και να μην υπάρχουν δύο διαφορετικοί «εγκέφαλοι» συγχρονισμού.
    """
    import database
    return database.sync_data_incremental()

# ==========================================
# ΣΥΝΕΧΕΙΑ ΛΕΙΤΟΥΡΓΙΩΝ ΒΑΣΗΣ
# ==========================================

def db_insert_bulk_background(table, data, log_action="ΜΑΖΙΚΗ ΠΡΟΣΘΗΚΗ", log_details=""):
    if not supabase or not data: return

    def _thread_task():
        chunk_size = 500
        inserted_any = False

        for i in range(0, len(data), chunk_size):
            try:
                supabase.table(table).insert(serialize_dates(data[i:i+chunk_size])).execute()
                inserted_any = True
            except Exception as e:
                print(f"Bulk insert error: {e}")

        # Σημαντικό για smart polling:
        # Τα μαζικά inserts γίνονται σε background thread, άρα πρέπει να χτυπήσουν
        # και αυτά το app_sync_state για να ενημερωθούν οι άλλοι χρήστες.
        if inserted_any:
            touch_app_sync_state()

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
        touch_app_sync_state()
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
            touch_app_sync_state()
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

                touch_app_sync_state()
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
            touch_app_sync_state()
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
    """
    Wrapper για την αυτόματη επέκταση επαναλαμβανόμενων εργασιών.

    Η πραγματική υλοποίηση βρίσκεται στο recurring_service.py.
    """
    from recurring_service import auto_extend_recurring_patterns as _auto_extend_recurring_patterns
    return _auto_extend_recurring_patterns()

def cleanup_duplicates():
    """
    Wrapper για καθαρισμό διπλότυπων βαρδιών.

    Η πραγματική υλοποίηση βρίσκεται στο maintenance.py.
    """
    from maintenance import cleanup_duplicates as _cleanup_duplicates
    return _cleanup_duplicates()


def cleanup_projects():
    """
    Wrapper για συγχώνευση διπλότυπων έργων.

    Η πραγματική υλοποίηση βρίσκεται στο maintenance.py.
    """
    from maintenance import cleanup_projects as _cleanup_projects
    return _cleanup_projects()

def init_data_and_sync():
    init_undo_stack()

    # Full sync μία φορά ανά χρήστη/session.
    # Καλύπτει και περιπτώσεις όπου ο χρήστης μπαίνει από ήδη ανοιχτό tab
    # και δεν περνά ξανά από το login form.
    current_user = st.session_state.get("current_user")
    if current_user and st.session_state.get("full_sync_done_for_user") != current_user:
        st.session_state.last_sync_time = None
        st.session_state.full_sync_done_for_user = current_user

    skip_remote_sync = bool(st.session_state.pop("skip_remote_sync_once", False))

    if not skip_remote_sync:
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

    # ΠΡΟΣΟΧΗ:
    # Δεν τρέχουμε πλέον cleanup_duplicates() / cleanup_projects() αυτόματα σε κάθε sync/refresh.
    # Αυτές οι λειτουργίες αλλάζουν/διαγράφουν δεδομένα στη βάση σε background thread.
    # Όταν έτρεχαν σε κάθε "Άμεση Ανανέωση", μπορούσαν να προκαλέσουν φαινόμενο:
    # "η αλλαγή φαίνεται στιγμιαία και μετά εξαφανίζεται".
    # Αν χρειαστεί καθαρισμός, πρέπει να γίνεται με ξεχωριστό χειροκίνητο κουμπί/εργαλείο.
    # cleanup_duplicates()
    # cleanup_projects()

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
    """
    Wrapper για το κοινό sidebar/shared UI.

    Η πραγματική υλοποίηση βρίσκεται στο ui_shell.py.
    Κρατάμε αυτή τη συνάρτηση για συμβατότητα, ώστε όλα τα υπάρχοντα pages
    που καλούν utils.setup_shared_ui() να συνεχίσουν να δουλεύουν χωρίς αλλαγή.
    """
    from ui_shell import setup_shared_ui as _setup_shared_ui
    return _setup_shared_ui(show_menu=show_menu, menu_options=menu_options)
