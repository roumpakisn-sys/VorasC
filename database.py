import streamlit as st
from datetime import datetime, date
import uuid
import scheduling
import config
import utils

# Αναφορά στον έτοιμο Supabase Client από το utils
supabase = utils.supabase

def inject_silent_refresh_css():
    """
    Εισάγει CSS κανόνες που απενεργοποιούν εντελώς τα προεπιλεγμένα 
    οπτικά εφέ φόρτωσης του Streamlit (το γκριζάρισμα και το Running...).
    Έτσι, το Auto-Polling λειτουργεί 100% αόρατα στο παρασκήνιο!
    """
    st.markdown(
        """
        <style>
        /* Εξαφανίζει το εικονίδιο 'Running...' πάνω δεξιά */
        [data-testid="stStatusWidget"] {
            visibility: hidden !important;
            display: none !important;
        }
        /* Αποτρέπει το γκριζάρισμα/ημιδιαφάνεια της οθόνης κατά το polling */
        [data-testid="stAppViewBlockContainer"] {
            opacity: 1 !important;
            transition: none !important;
        }
        .stApp {
            opacity: 1 !important;
        }
        /* Κρύβει τη λεπτή γραμμή φόρτωσης (loading progress bar) στην κορυφή */
        .stApp [data-testid="stDecoration"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

def to_timestamp(iso_str):
    """
    Βοηθητική συνάρτηση που μετατρέπει ασφαλώς τα ISO strings της βάσης 
    σε αριθμούς (timestamps) για να κάνουμε ακριβή σύγκριση.
    """
    if not iso_str: 
        return 0.0
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0

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
    Καταγράφει τη διαγραφή μιας εγγραφής στον πίνακα 'deleted_records' της Supabase.
    ΣΗΜΑΝΤΙΚΟ: ΔΕΝ στέλνουμε τοπική ώρα (Python). Αφήνουμε τη Supabase να προσθέσει
    ΑΥΤΟΜΑΤΑ τη δική της ακριβή ώρα της βάσης για να μην έχουμε Clock Skew!
    """
    if not supabase:
        return
    deletion_log = {
        "table_name": table_name,
        "record_id": str(record_id)
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
    # Ενεργοποίηση της "αόρατης" λειτουργίας για το Auto-Polling
    inject_silent_refresh_css()

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
        res_logs = supabase.table("activity_logs").select("timestamp").order("timestamp", desc=True).limit(1).execute()
        if res_logs.data:
            latest_activity_ts = res_logs.data[0]['timestamp']
            
            # Μετατροπή των ημερομηνιών σε αριθμούς (timestamps)
            latest_ts = to_timestamp(latest_activity_ts)
            sync_ts = to_timestamp(last_sync)
            
            # Βάζουμε +30s tolerance (ανοχή) στο Polling Guard.
            # Αν η δραστηριότητα (ακόμα και με +30s) είναι παλαιότερη από το τελευταίο sync, δεν κάνουμε fetch!
            if (latest_ts + 30.0) <= sync_ts:
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
        # ΔΕΝ μηδενίζουμε πλέον το last_sync_time εδώ.
        pass
