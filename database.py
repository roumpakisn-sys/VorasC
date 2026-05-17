import streamlit as st
from datetime import datetime, date
import uuid
import scheduling
import config
import utils

# Αναφορά στον έτοιμο Supabase Client από το utils
supabase = utils.supabase

def get_db_current_time():
    """
    Ανακτά την ακριβή τρέχουσα ώρα του εξυπηρετητή (Supabase server time) 
    χρησιμοποιώντας τη συνάρτηση RPC 'get_server_time' που δημιουργήσαμε στην PostgreSQL.
    """
    if not supabase:
        return datetime.utcnow().isoformat()
    try:
        res = supabase.rpc("get_server_time").execute()
        if res.data:
            return res.data
    except Exception as e:
        print(f"Error getting server time: {e}")
    return datetime.utcnow().isoformat()

def apply_delta_updates(table_name, local_list, delta_records, deleted_ids):
    """
    Pure Logic: Εφαρμόζει τις μερικές αλλαγές (εισαγωγές, ενημερώσεις, διαγραφές)
    στην τοπική λίστα που βρίσκεται αποθηκευμένη στο Session State του χρήστη.
    """
    # 1. Αφαίρεση των εγγραφών που έχουν διαγραφεί από άλλον χρήστη
    if deleted_ids:
        local_list = [r for r in local_list if str(r.get('id')) not in deleted_ids]
    
    # 2. Αντικατάσταση των παλιών εγγραφών με τις νέες/ενημερωμένες
    updated_ids = {str(r['id']) for r in delta_records}
    local_list = [r for r in local_list if str(r.get('id')) not in updated_ids]
    local_list.extend(delta_records)
    
    return local_list

def track_deletion(table_name, record_id):
    """
    Καταγράφει τη διαγραφή μιας εγγραφής στον πίνακα 'deleted_records' της Supabase,
    ώστε οι υπόλοιποι συνδεδεμένοι χρήστες να ενημερωθούν άμεσα για το ποιο ID αφαιρέθηκε.
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

def sync_data_incremental():
    """
    Ο έξυπνος μηχανισμός Delta Updates.
    Φέρνει ΜΟΝΟ τις αλλαγές που έγιναν μετά το last_sync_time, χρησιμοποιώντας 
    ένα ελαφρύ Polling Guard για την ελαχιστοποίηση των ερωτημάτων στη βάση.
    """
    if not supabase:
        return

    last_sync = st.session_state.get("last_sync_time", None)
    current_db_time = get_db_current_time()

    # --- FULL FETCH (Εκτελείται ΜΟΝΟ κατά την πρώτη είσοδο στην εφαρμογή) ---
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

    # --- INCREMENTAL SYNC (Delta Updates) με Polling Guard ---
    try:
        # 1. ULTRA-LIGHT POLLING GUARD
        # Κάνουμε select μόνο μία εγγραφή (την τελευταία) από το activity_logs.
        # Αν η ημερομηνία της τελευταίας δραστηριότητας στη βάση είναι παλαιότερη ή ίση 
        # με το δικό μας last_sync, σημαίνει ότι δεν έχει αλλάξει απολύτως τίποτα!
        # Τερματίζουμε αμέσως τη συνάρτηση, γλιτώνοντας 7 βαριά queries στη Supabase!
        res_logs = supabase.table("activity_logs").select("timestamp").order("timestamp", desc=True).limit(1).execute()
        if res_logs.data:
            latest_activity_ts = res_logs.data[0]['timestamp']
            if latest_activity_ts <= last_sync:
                return

        # 2. Αν ανιχνευτεί νέα δραστηριότητα, ανακτούμε τις διαγραφές που έγιναν μετά το τελευταίο μας sync
        deleted_res = supabase.table("deleted_records").select("table_name, record_id").gte("deleted_at", last_sync).execute()
        deletions = deleted_res.data or []
        
        # Ομαδοποίηση των διαγραμμένων IDs ανά πίνακα
        deleted_by_table = {}
        for d in deletions:
            t = d['table_name']
            if t not in deleted_by_table:
                deleted_by_table[t] = []
            deleted_by_table[t].append(str(d['record_id']))

        # 3. Συγχρονίζουμε Incremental μόνο τους πίνακες που παρουσίασαν αλλαγές
        tables_to_sync = ["employees", "projects", "assignments", "leaves", "recurring_patterns", "evaluations"]
        changes_detected = False

        for table in tables_to_sync:
            # Ζητάμε μόνο τις εγγραφές που προστέθηκαν ή τροποποιήθηκαν μετά το last_sync
            delta_res = supabase.table(table).select("*").gte("updated_at", last_sync).execute()
            delta_records = delta_res.data or []
            
            table_deleted_ids = deleted_by_table.get(table, [])
            
            if delta_records or table_deleted_ids:
                changes_detected = True
                
                # Μετατροπή των ISO string ημερομηνιών σε Python date objects
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

                # Εφαρμογή των αλλαγών στην τοπική μνήμη του χρήστη
                st.session_state[table] = apply_delta_updates(
                    table, 
                    st.session_state.get(table, []), 
                    delta_records, 
                    table_deleted_ids
                )

        if changes_detected:
            # Αν υπήρξαν αλλαγές, ενημερώνουμε το σύστημα να ξαναχτίσει τα ευρετήρια (Gantt, maps κλπ)
            utils.mark_data_changed()
            
        st.session_state.last_sync_time = current_db_time

    except Exception as e:
        print(f"Incremental Sync Error: {e}")
        # Σε περίπτωση σφάλματος, καθαρίζουμε το sync_time για να γίνει full fetch στην επόμενη προσπάθεια
        st.session_state.last_sync_time = None
