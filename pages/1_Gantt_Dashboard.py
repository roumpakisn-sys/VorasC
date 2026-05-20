import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import uuid
import io
import textwrap
import time
import re

# --- INITIALIZATION & ΑΣΠΙΔΑ ΑΣΦΑΛΕΙΑΣ ---
if "authenticated" not in st.session_state: st.session_state.authenticated = False
if "employees" not in st.session_state: st.session_state.employees = []
if "projects" not in st.session_state: st.session_state.projects = []
if "assignments" not in st.session_state: st.session_state.assignments = []
if "leaves" not in st.session_state: st.session_state.leaves = []
if "recurring_patterns" not in st.session_state: st.session_state.recurring_patterns = []
if "evaluations" not in st.session_state: st.session_state.evaluations = []

# ΣΗΜΑΝΤΙΚΟ: Σταματάει τον κώδικα εδώ και σε στέλνει στο Login αν δεν είσαι συνδεδεμένος!
if not st.session_state.get("authenticated"):
    st.switch_page("streamlit_app.py")
    st.stop()

import config
import utils
import scheduling
import gantt_engine  # Εισάγουμε τον native "κινητήρα"

def get_local_today():
    """Επιστρέφει τη σωστή σημερινή ημερομηνία για Ώρα Ελλάδος"""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Athens")).date()
    except Exception:
        return (datetime.utcnow() + timedelta(hours=3)).date()

utils.init_data_and_sync()

# ΑΥΤΟΜΑΤΗ ΕΠΙΔΙΟΡΘΩΣΗ (Self-Healing)
total_indexed = sum(len(v) for v in st.session_state.get('assignments_by_date', {}).values())
if total_indexed != len(st.session_state.get('assignments', [])):
    utils.mark_data_changed()
    utils.init_data_and_sync()

utils.setup_shared_ui()

# Helpers
is_full_admin = st.session_state.get('current_user') != "TAN"
active_employee_ids = [e['id'] for e in st.session_state.employees if e.get('status', 'Ενεργός') == 'Ενεργός']

# --- ΜΗΧΑΝΙΣΜΟΣ ΗΜΕΡΟΜΗΝΙΑΣ (Αλεξίσφαιρος) ---
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
/* Απλώνουμε την οθόνη του Streamlit στο 98% και μειώνουμε τα πάνω κενά */
.block-container, [data-testid="block-container"] {
    max-width: 98% !important; 
    padding-top: 0.5rem !important;
    padding-bottom: 0.5rem !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
}

/* Συμπίεση των Alert Messages (Ορφανές Βάρδιες & Αναλυτικά) στο ελάχιστο δυνατό */
div[data-testid="stNotification"], .stAlert {
    padding: 2px 10px !important;
    margin-top: 0px !important;
    margin-bottom: 2px !important;
}
div[data-testid="stNotification"] p, .stAlert p {
    margin: 0 !important;
    font-size: 13px !important;
}

/* 2. Σβήνουμε το προεπιλεγμένο αχνό περίγραμμα του Streamlit */
div[data-testid="stVerticalBlockBorderWrapper"] {
    border: none !important;
    box-shadow: none !important;
    background: transparent !important;
