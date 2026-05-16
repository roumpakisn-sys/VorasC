import streamlit as st
import pandas as pd
from datetime import datetime
import uuid
import copy
import time
from supabase import create_client, Client

# ==========================================
# 1. ΑΡΧΙΚΟΠΟΙΗΣΗ SUPABASE (CACHED)
# ==========================================
@st.cache_resource
def init_supabase() -> Client:
    """
    Δημιουργεί και διατηρεί ανοιχτή τη σύνδεση με τη Supabase.
    Διαβάζει τα κλειδιά από το Streamlit Secrets.
    """
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"Σφάλμα σύνδεσης με Supabase: Ελέγξτε τα Secrets. Λεπτομέρειες: {e}")
        st.stop()

# ==========================================
# 2. ΑΝΑΓΝΩΣΗ ΔΕΔΟΜΕΝΩΝ ΜΕ CACHING & PAGINATION
# ==========================================
@st.cache_data(ttl=60)
def fetch_paginated(table_name: str, chunk_size: int = 1000) -> list:
    """
    Κατεβάζει δεδομένα από τη Supabase σε κομμάτια (chunks) για να μην
    μπλοκάρει η μνήμη. Κρατάει τα δεδομένα στην cache για 60 δευτερόλεπτα.
    """
    supabase = init_supabase()
    all_data = []
    start = 0
    
    try:
        while True:
            response = supabase.table(table_name).select("*").range(start, start + chunk_size - 1).execute()
            data = response.data
            if not data:
                break
            all_data.extend(data)
            if len(data) < chunk_size:
                break
            start += chunk_size
        return all_data
    except Exception as e:
        st.error(f"Σφάλμα κατά την ανάγνωση του πίνακα '{table_name}': {e}")
        return []

def get_latest_activity_timestamp():
    """
    Ελαφρύ query που φέρνει ΜΟΝΟ την τελευταία ημερομηνία κίνησης. 
    Χρησιμοποιείται από το Smart Polling για γρήγορο συγχρονισμό.
    """
    supabase = init_supabase()
    try:
        res = supabase.table('activity_logs').select('timestamp').order('timestamp', desc=True).limit(1).execute()
        if res.data:
            return res.data[0]['timestamp']
        return None
    except:
        return None

# ==========================================
# 3. ΑΣΦΑΛΗΣ ΕΚΤΕΛΕΣΗ (SAFE DB OPERATION) & LOGGING
# ==========================================
def log_activity(action: str, table_name: str, details: str, user: str):
    """Καταγράφει τις κινήσεις στο ιστορικό (activity_logs)."""
    supabase = init_supabase()
    try:
        supabase.table('activity_logs').insert({
            'action': action,
            'table_name': table_name,
            'details': details,
            'user': user,
            'timestamp': datetime.now().isoformat()
        }).execute()
    except Exception as e:
        print(f"Αποτυχία καταγραφής log: {e}")

def safe_db_operation(operation_func, *args, **kwargs):
    """
    Τυλίγει τις ενέργειες της βάσης σε try-except για να μην κρασάρει η εφαρμογή
    αν πέσει το internet ή η Supabase.
    """
    try:
        return operation_func(*args, **kwargs)
    except Exception as e:
        st.error(f"Προέκυψε σφάλμα κατά την αποθήκευση: {e}")
        return None

# ==========================================
# 4. ΣΥΣΤΗΜΑ UNDO / ΑΝΑΙΡΕΣΗΣ
# ==========================================
def add_to_undo_stack(action: str, table_name: str, row_id: str, original_data: dict = None):
    """Προσθέτει μια ενέργεια στη στοίβα αναιρέσεων του χρήστη."""
    if 'undo_stack' not in st.session_state:
        st.session_state.undo_stack = []
        
    st.session_state.undo_stack.append({
        'action': action,          # π.χ. 'INSERT', 'UPDATE', 'DELETE'
        'table': table_name,       # π.χ. 'assignments'
        'id': row_id,              # Το ID της γραμμής που άλλαξε
        'data': copy.deepcopy(original_data) # Τα παλιά δεδομένα (για restore)
    })
    
    # Κρατάμε μόνο τις 10 τελευταίες κινήσεις για εξοικονόμηση μνήμης
    if len(st.session_state.undo_stack) > 10:
        st.session_state.undo_stack.pop(0)

def perform_undo():
    """Εκτελεί την αναίρεση της τελευταίας κίνησης."""
    if 'undo_stack' not in st.session_state or not st.session_state.undo_stack:
        st.warning("Δεν υπάρχει ενέργεια για αναίρεση.")
        return False
        
    last_action = st.session_state.undo_stack.pop()
    supabase = init_supabase()
    
    try:
        action_type = last_action['action']
        table = last_action['table']
        row_id = last_action['id']
        old_data = last_action['data']
        
        if action_type == 'INSERT':
            # Αν είχε γίνει προσθήκη, η αναίρεση είναι διαγραφή
            supabase.table(table).delete().eq('id', row_id).execute()
            log_activity("UNDO (Διαγραφή)", table, f"Αναίρεση προσθήκης ID: {row_id}", st.session_state.get('current_user', 'System'))
            
        elif action_type == 'DELETE':
            # Αν είχε γίνει διαγραφή, η αναίρεση είναι επαναφορά
            supabase.table(table).insert(old_data).execute()
            log_activity("UNDO (Επαναφορά)", table, f"Αναίρεση διαγραφής ID: {row_id}", st.session_state.get('current_user', 'System'))
            
        elif action_type == 'UPDATE':
            # Αν είχε γίνει επεξεργασία, η αναίρεση είναι επιστροφή στα παλιά δεδομένα
            supabase.table(table).update(old_data).eq('id', row_id).execute()
            log_activity("UNDO (Επαναφορά αλλαγής)", table, f"Αναίρεση επεξεργασίας ID: {row_id}", st.session_state.get('current_user', 'System'))
            
        # Καθαρίζουμε την cache για να φανούν οι αλλαγές
        fetch_paginated.clear()
        return True
        
    except Exception as e:
        st.error(f"Αποτυχία επαναφοράς: {e}")
        return False

# ==========================================
# 5. ΔΙΑΧΕΙΡΙΣΗ ΧΡΗΣΤΩΝ (AUTHENTICATION)
# ==========================================
def init_session_state():
    """Αρχικοποιεί τις βασικές μεταβλητές μνήμης (State)."""
    if 'current_user' not in st.session_state:
        st.session_state.current_user = None
    if 'user_role' not in st.session_state:
        st.session_state.user_role = None
    if 'global_db_ts' not in st.session_state:
        st.session_state.global_db_ts = None
    if 'undo_stack' not in st.session_state:
        st.session_state.undo_stack = []

def login_user(username: str, role: str):
    """Αποθηκεύει τον χρήστη στο session state."""
    st.session_state.current_user = username
    st.session_state.user_role = role
    
def logout_user():
    """Αποσυνδέει τον χρήστη και καθαρίζει τη μνήμη."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()
