import streamlit as st
from datetime import datetime, date, timedelta
import uuid
import scheduling
import config
import utils

supabase = utils.supabase

def get_db_current_time():
    """
    Ανακτά την τρέχουσα ώρα του εξυπηρετητή (Supabase server time) 
    χρησιμοποιώντας τη συνάρτηση RPC 'get_server_time' που δημιουργήσαμε.
    """
    if not supabase:
        return datetime.utcnow().isoformat()
    try:
        res = supabase.rpc("get_server_time").execute()
        if res.data:
            return res.data
    except Exception as e:
        # Fallback σε περίπτωση σφάλματος
        print(f"Error getting server time: {e}")
    return datetime.utcnow().isoformat()

def apply_delta_updates(table_name, local_list, delta_records, deleted_ids):
    """
    Εφαρμόζει τις αλλαγές (updates/inserts) και τις διαγραφές στην τοπική λίστα του Session State.
    """
    # 1. Αφαίρεση των διαγραμμένων εγγραφών
    if deleted_ids:
        local_list = [r for r in local_list if str(r.get('id')) not in deleted_ids]
    
    # 2. Ενημέρωση/Προσθήκη νέων εγγραφών
    updated_ids = {str(r['id']) for r in delta_records}
    local_list = [r for r in local_list if str(r.get('id')) not in updated_ids]
    local_list.extend(delta_records)
    
    return local_list

def track_deletion(table_name, record_id):
    """
    Καταγράφει μια διαγραφή στον πίνακα 'deleted_records' της Supabase.
    """
    if not supabase:
        return
    deletion_log = {
        "id": str(uuid.uuid4()),
        "table_name": table_name,
        "record_id": str(record_id),
        "deleted_at": datetime.utcnow().isoformat()
    }
    try:
        supabase.table("deleted_records").insert(deletion_log).execute()
    except Exception as e:
        print(f"Error logging deletion: {e}")

def db_delete_with_tracking(table, column, value, deleted_records=None):
    """
    Εκτελεί τη διαγραφή και καταγράφει το ID της εγγραφής που διαγράφηκε για τους άλλους χρήστες.
    """
    # Αναζήτηση των εγγραφών που πρόκειται να διαγραφούν (για να βρούμε τα ID τους)
    if not deleted_records:
        table_data = st.session_state.get(table, [])
        deleted_records = [r for r in table_data if r.get(column) == value]
        
    # Κλασική διαγραφή στη βάση μέσω utils
    utils.db_delete(table, column, value, deleted_records=deleted_records, track=True)
    
    # Καταγραφή των διαγραφών για Delta Updates
    for r in deleted_records:
        rec_id = r.get('id')
        if rec_id:
            track_deletion(table, rec_id)

def db_delete_in_with_tracking(table, column, values, deleted_records=None):
    """
    Μαζική διαγραφή με καταγραφή.
    """
    if not deleted_records:
        table_data = st.session_state.get(table, [])
        deleted_records = [r for r in table_data if r.get(column) in values]
        
    utils.db_delete_in(table, column, values, deleted_records=deleted_records, track=True)
    
    for r in deleted_records:
        rec_id = r.get('id')
        if rec_id:
            track_deletion(table, rec_id)

def sync_data_incremental():
    """
    Ο πυρήνας του μηχανισμού Delta Updates. Φέρνει ΜΟΝΟ ό,τι άλλαξε ή διαγράφηκε από το last_sync_time.
    """
    if not supabase:
        return

    last_sync = st.session_state.get("last_sync_time", None)
    current_db_time = get_db_current_time()

    # Αν δεν υπάρχει προηγούμενο sync, κάνουμε ένα αρχικό FULL FETCH
    if not last_sync:
        with st.spinner("Πρώτος πλήρης συγχρονισμός δεδομένων..."):
            st.session_state.employees = utils.fetch_paginated("employees")
            st.session_state.projects = utils.fetch_paginated("projects")
            
            assigns = utils.fetch_paginated("assignments")
            for a in assigns:
                if isinstance(a.get('date'), str):
                    a['date'] = datetime.strptime(a['date'].split("T")[0], "%Y-%m-%d").date()
            st.session_state.assignments = assigns
            
            leaves = utils.fetch_paginated("leaves")
            for l in leaves:
                if isinstance(l.get('startDate'), str):
                    l['startDate'] = datetime.strptime(l['startDate'].split("T")[0], "%Y-%m-%d").date()
                if isinstance(l.get('endDate'), str):
                    l['endDate'] = datetime.strptime(l['endDate'].split("T")[0], "%Y-%m-%d").date()
            st.session_state.leaves = leaves
            
            patterns = utils.fetch_paginated("recurring_patterns")
            for p in patterns:
                if isinstance(p.get('startDate'), str):
                    p['startDate'] = datetime.strptime(p['startDate'].split("T")[0], "%Y-%m-%d").date()
            st.session_state.recurring_patterns = patterns
            
            try:
                st.session_state.evaluations = utils.fetch_paginated("evaluations")
            except Exception:
                st.session_state.evaluations = []
                
            st.session_state.last_sync_time = current_db_time
            utils.mark_data_changed()
            return

    # INCREMENTAL SYNC (Delta Updates)
    try:
        # 1. Φέρνουμε όλες τις διαγραφές που έγιναν μετά το τελευταίο συγχρονισμό
        deleted_res = supabase.table("deleted_records").select("table_name, record_id").gte("deleted_at", last_sync).execute()
        deletions = deleted_res.data or []
        
        deleted_by_table = {}
        for d in deletions:
            t = d['table_name']
            if t not in deleted_by_table:
                deleted_by_table[t] = []
            deleted_by_table[t].append(str(d['record_id']))

        # 2. Συγχρονίζουμε κάθε πίνακα ξεχωριστά
        tables_to_sync = ["employees", "projects", "assignments", "leaves", "recurring_patterns", "evaluations"]
        changes_detected = False

        for table in tables_to_sync:
            # Ανάκτηση μόνο των νέων ή τροποποιημένων εγγραφών
            delta_res = supabase.table(table).select("*").gte("updated_at", last_sync).execute()
            delta_records = delta_res.data or []
            
            table_deleted_ids = deleted_by_table.get(table, [])
            
            if delta_records or table_deleted_ids:
                changes_detected = True
                
                # Προσαρμογή ημερομηνιών σε Python dates
                if table == "assignments":
                    for r in delta_records:
                        if isinstance(r.get('date'), str):
                            r['date'] = datetime.strptime(r['date'].split("T")[0], "%Y-%m-%d").date()
                elif table == "leaves":
                    for r in delta_records:
                        if isinstance(r.get('startDate'), str):
                            r['startDate'] = datetime.strptime(r['startDate'].split("T")[0], "%Y-%m-%d").date()
                        if isinstance(r.get('endDate'), str):
                            r['endDate'] = datetime.strptime(r['endDate'].split("T")[0], "%Y-%m-%d").date()
                elif table == "recurring_patterns":
                    for r in delta_records:
                        if isinstance(r.get('startDate'), str):
                            r['startDate'] = datetime.strptime(r['startDate'].split("T")[0], "%Y-%m-%d").date()

                # Εφαρμογή των μερικών αλλαγών στη μνήμη
                st.session_state[table] = apply_delta_updates(
                    table, 
                    st.session_state.get(table, []), 
                    delta_records, 
                    table_deleted_ids
                )

        if changes_detected:
            utils.mark_data_changed()
            
        st.session_state.last_sync_time = current_db_time

    except Exception as e:
        print(f"Incremental Sync Error: {e}")
        # Αν κάτι πάει στραβά, κάνουμε fallback σε full fetch στο επόμενο run
        st.session_state.last_sync_time = None
