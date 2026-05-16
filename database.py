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
    """Σύνδεση με τη Supabase χρησιμοποιώντας τα Secrets του Streamlit Cloud."""
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"Σφάλμα σύνδεσης με Supabase: {e}")
        st.stop()

# ==========================================
# 2. ΑΝΑΓΝΩΣΗ ΔΕΔΟΜΕΝΩΝ
# ==========================================
@st.cache_data(ttl=60)
def fetch_paginated(table_name: str, chunk_size: int = 1000) -> list:
    """Φέρνει όλα τα δεδομένα από έναν πίνακα με σύστημα σελιδοποίησης για ταχύτητα."""
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
        return []

def get_latest_activity_timestamp():
    """Ελέγχει την τελευταία δραστηριότητα στη βάση για αυτόματο συγχρονισμό."""
    supabase = init_supabase()
    try:
        # Χρήση της στήλης 'timestamp' όπως φαίνεται στη βάση σου
        res = supabase.table('activity_logs').select('timestamp').order('timestamp', desc=True).limit(1).execute()
        if res.data:
            return res.data[0]['timestamp']
        return None
    except:
        return None

# ==========================================
# 3. ΙΣΤΟΡΙΚΟ ΔΡΑΣΤΗΡΙΟΤΗΤΩΝ (LOGGING)
# ==========================================
def log_activity(action: str, table_name: str, details: str, user: str):
    """Καταγράφει κάθε αλλαγή στον πίνακα activity_logs της Supabase."""
    supabase = init_supabase()
    try:
        # Προσαρμογή στις στήλες 'action_type' και 'username' της παλιάς σου βάσης
        supabase.table('activity_logs').insert({
            'action_type': action,
            'table_name': table_name,
            'details': details,
            'username': user,
            'timestamp': datetime.now().isoformat()
        }).execute()
    except Exception as e:
        print(f"Log error: {e}")

# ==========================================
# 4. ΔΙΑΧΕΙΡΙΣΗ ΚΑΤΑΣΤΑΣΗΣ (SESSION STATE)
# ==========================================
def init_session_state():
    """Αρχικοποιεί τις μεταβλητές μνήμης της εφαρμογής."""
    if 'current_user' not in st.session_state:
        st.session_state.current_user = None
    if 'user_role' not in st.session_state:
        st.session_state.user_role = None
    if 'global_db_ts' not in st.session_state:
        st.session_state.global_db_ts = None
    if 'undo_stack' not in st.session_state:
        st.session_state.undo_stack = []

def login_user(username: str, role: str):
    """Καταχωρεί τον χρήστη στη μνήμη της τρέχουσας συνεδρίας."""
    st.session_state.current_user = username
    st.session_state.user_role = role
    
def logout_user():
    """Καθαρίζει τη μνήμη και αποσυνδέει τον χρήστη."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# ==========================================
# 5. ΣΥΣΤΗΜΑ UNDO (ΑΝΑΙΡΕΣΗ)
# ==========================================
def add_to_undo_stack(action: str, table_name: str, row_id: str, original_data: dict = None):
    """Προσθέτει μια ενέργεια στη λίστα αναιρέσεων."""
    st.session_state.undo_stack.append({
        'action': action,
        'table': table_name,
        'id': row_id,
        'data': copy.deepcopy(original_data)
    })
    # Κρατάμε μόνο τις τελευταίες 10 ενέργειες
    if len(st.session_state.undo_stack) > 10:
        st.session_state.undo_stack.pop(0)
