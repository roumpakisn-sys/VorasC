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
