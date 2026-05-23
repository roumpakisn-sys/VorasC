import streamlit as st
from datetime import datetime, date, timedelta
import uuid
import scheduling
import config
import utils

# Αναφορά στον έτοιμο Supabase Client από το utils
supabase = utils.supabase

# Πίνακας 1-row για γρήγορο sync probe (ενημερώνεται από DB triggers)
SYNC_WATERMARK_TABLE = "sync_watermark"

# Βασικοί πίνακες business data
BUSINESS_TABLES = [
    "employees",
    "projects",
    "assignments",
    "leaves",
    "recurring_patterns",
    "evaluations",
]

# Probe tables (business + deletion/activity signals)
PROBE_TABLES = BUSINESS_TABLES + ["deleted_records", "activity_logs"]

# Per-table watermark columns μέσα στο sync_watermark
PROBE_WATERMARK_COLUMNS = {
    "employees": "employees_at",
    "projects": "projects_at",
    "assignments": "assignments_at",
    "leaves": "leaves_at",
    "recurring_patterns": "recurring_patterns_at",
    "evaluations": "evaluations_at",
    "deleted_records": "deleted_records_at",
    "activity_logs": "activity_logs_at",
}


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


def iso_with_safety_lag(iso_str, seconds=90):
    """
    Επιστρέφει ISO χρόνο ελαφρώς προς τα πίσω (safety lag),
    ώστε να μην χαθούν αλλαγές σε οριακές στιγμές login/polling.
    """
    if not iso_str:
        return datetime.utcnow().isoformat()
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        dt = dt - timedelta(seconds=seconds)
        return dt.replace(tzinfo=None).isoformat()
    except Exception:
        return datetime.utcnow().isoformat()


def get_db_current_time():
    """
    Ανακτά την ακριβή τρέχουσα ώρα του εξυπηρετητή (Supabase server time)
    χρησιμοποιώντας τη συνάρτηση RPC 'get_server_time' που δημιουργήθηκε στην PostgreSQL.
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


def get_sync_watermark_payload():
    """
    1-query polling probe:
    Διαβάζει από sync_watermark:
      - last_change_at
      - per-table *_at watermarks (αν υπάρχουν)
    Επιστρέφει dict ή None.
    """
    if not supabase:
        return None

    # Προσπαθούμε πρώτα με extended schema (per-table columns).
    extended_cols = ["last_change_at"] + [PROBE_WATERMARK_COLUMNS[t] for t in PROBE_TABLES]
    extended_select = ",".join(extended_cols)

    try:
        res = (
            supabase.table(SYNC_WATERMARK_TABLE)
            .select(extended_select)
            .eq("id", 1)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]
    except Exception:
        pass

    # Fallback για παλιό schema (μόνο last_change_at)
    try:
        res = (
            supabase.table(SYNC_WATERMARK_TABLE)
            .select("last_change_at")
            .eq("id", 1)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]
    except Exception as e:
        print(f"Error reading sync watermark: {e}")

    return None


def _legacy_probe_signals(tables_to_sync):
    """
    Legacy fallback probe (πολλαπλά queries), αν δεν υπάρχει ακόμα sync_watermark.
    Επιστρέφει:
      - newest_signal_ts
      - activity_signal_ts
    """
    newest_signal_ts = 0.0
    activity_signal_ts = 0.0

    for table in tables_to_sync:
        try:
            probe = (
                supabase.table(table)
                .select("updated_at")
                .order("updated_at", desc=True)
                .limit(1)
                .execute()
            )
            if probe.data:
                ts_val = probe.data[0].get("updated_at")
                if ts_val:
                    newest_signal_ts = max(newest_signal_ts, to_timestamp(ts_val))
        except Exception:
            pass

    try:
        del_probe = (
            supabase.table("deleted_records")
            .select("deleted_at")
            .order("deleted_at", desc=True)
            .limit(1)
            .execute()
        )
        if del_probe.data:
            del_ts = del_probe.data[0].get("deleted_at")
            if del_ts:
                newest_signal_ts = max(newest_signal_ts, to_timestamp(del_ts))
    except Exception:
        pass

    try:
        activity_probe = (
            supabase.table("activity_logs")
            .select("timestamp")
            .order("timestamp", desc=True)
            .limit(1)
            .execute()
        )
        if activity_probe.data:
            act_ts = activity_probe.data[0].get("timestamp")
            if act_ts:
                activity_signal_ts = to_timestamp(act_ts)
                newest_signal_ts = max(newest_signal_ts, activity_signal_ts)
    except Exception:
        pass

    return newest_signal_ts, activity_signal_ts


def apply_delta_updates(table_name, local_list, delta_records, deleted_ids):
    """
    Pure Logic: Εφαρμόζει τις μερικές αλλαγές (εισαγωγές, ενημερώσεις, διαγραφές)
    στην τοπική λίστα που βρίσκεται αποθηκευμένη στο Session State του χρήστη.

    Βελτιστοποίηση:
    - Ένα μόνο πέρασμα στη local_list (αντί για 2), με ίδια ακριβώς λογική αποτελέσματος.
    """
    deleted_set = set(deleted_ids or [])
    updated_set = {str(r["id"]) for r in delta_records}

    if not deleted_set and not updated_set:
        return local_list

    merged = []
    for r in local_list:
        rid = str(r.get("id"))
        if rid in deleted_set or rid in updated_set:
            continue
        merged.append(r)

    # Κρατάμε ακριβώς τη συμπεριφορά του αρχικού κώδικα:
    # τα νέα/ενημερωμένα records μπαίνουν στο τέλος.
    merged.extend(delta_records)
    return merged


def track_deletion(table_name, record_id):
    """
    Καταγράφει τη διαγραφή μιας εγγραφής στον πίνακα 'deleted_records' της Supabase.
    ΣΗΜΑΝΤΙΚΟ: Δεν στέλνουμε τοπική ώρα (Python). Αφήνουμε τη Supabase να προσθέσει
    αυτόματα τη δική της ακριβή ώρα της βάσης για να μην έχουμε clock skew.
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


def _normalize_dates_for_table(table_name, records):
    """
    In-place μετατροπή string ημερομηνιών σε date όπου χρειάζεται.
    """
    if not records:
        return

    if table_name == "assignments":
        for r in records:
            d = utils.safe_date_parse(r.get("date"))
            if d:
                r["date"] = d

    elif table_name == "leaves":
        for r in records:
            sd = utils.safe_date_parse(r.get("startDate"))
            if sd:
                r["startDate"] = sd
            ed = utils.safe_date_parse(r.get("endDate"))
            if ed:
                r["endDate"] = ed

    elif table_name == "recurring_patterns":
        for r in records:
            sd = utils.safe_date_parse(r.get("startDate"))
            if sd:
                r["startDate"] = sd


def _full_fetch_all_tables(current_db_time):
    """
    Κάνει πλήρες fetch όλων των βασικών πινάκων.
    Χρησιμοποιείται στο πρώτο login fetch και ως fallback
    όταν ανιχνεύεται activity χωρίς καθαρό delta από updated_at.
    """
    with st.spinner("Φόρτωση δεδομένων..."):
        st.session_state.employees = utils.fetch_paginated("employees")
        st.session_state.projects = utils.fetch_paginated("projects")

        assigns = utils.fetch_paginated("assignments")
        _normalize_dates_for_table("assignments", assigns)
        st.session_state.assignments = assigns

        leaves = utils.fetch_paginated("leaves")
        _normalize_dates_for_table("leaves", leaves)
        st.session_state.leaves = leaves

        patterns = utils.fetch_paginated("recurring_patterns")
        _normalize_dates_for_table("recurring_patterns", patterns)
        st.session_state.recurring_patterns = patterns

        try:
            st.session_state.evaluations = utils.fetch_paginated("evaluations")
        except Exception:
            st.session_state.evaluations = []

    # Safety lag για να μην χαθεί αλλαγή που έγινε πολύ κοντά στο login
    st.session_state.last_sync_time = iso_with_safety_lag(current_db_time, seconds=120)
    st.session_state.force_full_sync_once = False
    utils.mark_data_changed()


def _changed_after_sync(watermark_payload, table_name, sync_ts):
    col = PROBE_WATERMARK_COLUMNS.get(table_name)
    if not col:
        return False
    return to_timestamp(watermark_payload.get(col)) > sync_ts


def sync_data_incremental():
    """
    Delta sync με lightweight polling probe.

    Λογική:
    - 1 query probe σε sync_watermark.
    - Αν υπάρχουν per-table *_at watermarks, χτυπάμε delta queries μόνο για πίνακες
      που όντως άλλαξαν.
    - Αν όχι, κρατάμε fallback συμπεριφορά για 100% συμβατότητα.
    """
    # Ενεργοποίηση της "αόρατης" λειτουργίας για το Auto-Polling
    inject_silent_refresh_css()

    if not supabase:
        return

    last_sync = st.session_state.get("last_sync_time", None)
    tables_to_sync = BUSINESS_TABLES
    force_full_sync_once = bool(st.session_state.get("force_full_sync_once", False))

    # --- FULL FETCH (Πρώτη είσοδος ή force refresh μετά από login/redirect) ---
    if force_full_sync_once or not last_sync:
        current_db_time = get_db_current_time()
        _full_fetch_all_tables(current_db_time)
        return

    # --- INCREMENTAL SYNC (Delta Updates) ---
    try:
        sync_ts = to_timestamp(last_sync)

        watermark = get_sync_watermark_payload()
        used_legacy_probe = False

        query_delta_for_tables = set(tables_to_sync)
        fetch_deleted_records = True
        activity_signal_ts = 0.0

        if watermark and watermark.get("last_change_at"):
            newest_signal_ts = to_timestamp(watermark.get("last_change_at"))

            # Γρήγορο early exit
            if newest_signal_ts <= sync_ts:
                return

            # Ελέγχουμε αν υπάρχουν usable per-table watermarks.
            has_usable_per_table_watermarks = any(
                watermark.get(PROBE_WATERMARK_COLUMNS[t]) for t in PROBE_TABLES
            )

            if has_usable_per_table_watermarks:
                changed_business_tables = {
                    t for t in tables_to_sync if _changed_after_sync(watermark, t, sync_ts)
                }
                deleted_table_changed = _changed_after_sync(watermark, "deleted_records", sync_ts)

                # Αν άλλαξε μόνο activity_logs (ή noise εκτός business/deleted), δεν χρειάζεται delta sync.
                if not changed_business_tables and not deleted_table_changed:
                    st.session_state.last_sync_time = iso_with_safety_lag(
                        watermark.get("last_change_at"),
                        seconds=30
                    )
                    st.session_state.force_full_sync_once = False
                    return

                query_delta_for_tables = changed_business_tables
                fetch_deleted_records = deleted_table_changed

        else:
            # Fallback για παλιές εγκαταστάσεις χωρίς watermark setup
            used_legacy_probe = True
            newest_signal_ts, activity_signal_ts = _legacy_probe_signals(tables_to_sync)

            if newest_signal_ts <= sync_ts:
                return

        # 2) Ανακτούμε διαγραφές μόνο αν χρειάζεται
        deleted_by_table = {}
        if fetch_deleted_records:
            deleted_res = (
                supabase.table("deleted_records")
                .select("table_name, record_id")
                .gte("deleted_at", last_sync)
                .execute()
            )
            deletions = deleted_res.data or []

            for d in deletions:
                t = d["table_name"]
                if t not in deleted_by_table:
                    deleted_by_table[t] = set()
                deleted_by_table[t].add(str(d["record_id"]))

        # Πίνακες που πρέπει όντως να επεξεργαστούμε
        tables_to_process = [
            t for t in tables_to_sync
            if (t in query_delta_for_tables) or (t in deleted_by_table)
        ]

        # 3) Incremental sync ανά πίνακα
        changes_detected = False

        for table in tables_to_process:
            delta_records = []

            if table in query_delta_for_tables:
                delta_res = supabase.table(table).select("*").gte("updated_at", last_sync).execute()
                delta_records = delta_res.data or []

            table_deleted_ids = deleted_by_table.get(table, set())

            if delta_records or table_deleted_ids:
                changes_detected = True

                if delta_records:
                    _normalize_dates_for_table(table, delta_records)

                st.session_state[table] = apply_delta_updates(
                    table,
                    st.session_state.get(table, []),
                    delta_records,
                    table_deleted_ids
                )

        # Fallback ασφάλειας μόνο για legacy probe.
        if not changes_detected and used_legacy_probe and activity_signal_ts > sync_ts:
            current_db_time = get_db_current_time()
            _full_fetch_all_tables(current_db_time)
            return

        if changes_detected:
            utils.mark_data_changed()

        # Ενημέρωση last_sync
        if watermark and watermark.get("last_change_at") and not used_legacy_probe:
            st.session_state.last_sync_time = iso_with_safety_lag(
                watermark.get("last_change_at"),
                seconds=30
            )
        else:
            current_db_time = get_db_current_time()
            st.session_state.last_sync_time = iso_with_safety_lag(current_db_time, seconds=30)

        st.session_state.force_full_sync_once = False

    except Exception as e:
        print(f"Incremental Sync Error: {e}")
        pass
