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


def get_sync_watermark_time():
    """
    1-query polling probe:
    Διαβάζει το τελευταίο timestamp αλλαγής από τον πίνακα sync_watermark.
    Επιστρέφει ISO string ή None αν δεν υπάρχει/δεν είναι διαθέσιμο.
    """
    if not supabase:
        return None
    try:
        res = (
            supabase.table(SYNC_WATERMARK_TABLE)
            .select("last_change_at")
            .eq("id", 1)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0].get("last_change_at")
    except Exception as e:
        print(f"Error reading sync watermark: {e}")
    return None


def _legacy_probe_signals(tables_to_sync):
    """
    Legacy fallback probe (πολλαπλά queries), αν δεν υπάρχει ακόμη sync_watermark.
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
    """
    # 1. Αφαίρεση των εγγραφών που έχουν διαγραφεί από άλλον χρήστη
    if deleted_ids:
        local_list = [r for r in local_list if str(r.get("id")) not in deleted_ids]

    # 2. Αντικατάσταση των παλιών εγγραφών με τις νέες/ενημερωμένες
    updated_ids = {str(r["id"]) for r in delta_records}
    local_list = [r for r in local_list if str(r.get("id")) not in updated_ids]
    local_list.extend(delta_records)

    return local_list


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
        for a in assigns:
            d = utils.safe_date_parse(a.get("date"))
            if d:
                a["date"] = d
        st.session_state.assignments = assigns

        leaves = utils.fetch_paginated("leaves")
        for l in leaves:
            sd = utils.safe_date_parse(l.get("startDate"))
            if sd:
                l["startDate"] = sd
            ed = utils.safe_date_parse(l.get("endDate"))
            if ed:
                l["endDate"] = ed
        st.session_state.leaves = leaves

        patterns = utils.fetch_paginated("recurring_patterns")
        for p in patterns:
            sd = utils.safe_date_parse(p.get("startDate"))
            if sd:
                p["startDate"] = sd
        st.session_state.recurring_patterns = patterns

        try:
            st.session_state.evaluations = utils.fetch_paginated("evaluations")
        except Exception:
            st.session_state.evaluations = []

    # Safety lag για να μην χαθεί αλλαγή που έγινε πολύ κοντά στο login
    st.session_state.last_sync_time = iso_with_safety_lag(current_db_time, seconds=120)
    st.session_state.force_full_sync_once = False
    utils.mark_data_changed()


def sync_data_incremental():
    """
    Delta sync με lightweight polling probe.

    Νέα λογική:
    - 1 query probe σε sync_watermark για να ξέρουμε αν υπάρχει νέα αλλαγή.
    - Αν δεν έχει γίνει setup του sync_watermark, γίνεται αυτόματο fallback στο legacy probe.
    - Τα delta fetches παραμένουν ίδια για 100% συμβατή λειτουργία.
    """
    # Ενεργοποίηση της "αόρατης" λειτουργίας για το Auto-Polling
    inject_silent_refresh_css()

    if not supabase:
        return

    last_sync = st.session_state.get("last_sync_time", None)
    tables_to_sync = ["employees", "projects", "assignments", "leaves", "recurring_patterns", "evaluations"]
    force_full_sync_once = bool(st.session_state.get("force_full_sync_once", False))

    # --- FULL FETCH (Πρώτη είσοδος ή force refresh μετά από login/redirect) ---
    if force_full_sync_once or not last_sync:
        current_db_time = get_db_current_time()
        _full_fetch_all_tables(current_db_time)
        return

    # --- INCREMENTAL SYNC (Delta Updates) ---
    try:
        sync_ts = to_timestamp(last_sync)

        # 1-query probe από sync_watermark
        watermark_iso = get_sync_watermark_time()
        used_legacy_probe = False

        if watermark_iso:
            newest_signal_ts = to_timestamp(watermark_iso)
            activity_signal_ts = 0.0
        else:
            # Fallback για παλιές εγκαταστάσεις που δεν έχουν ακόμα το SQL migration.
            used_legacy_probe = True
            newest_signal_ts, activity_signal_ts = _legacy_probe_signals(tables_to_sync)

        # Αν δεν υπάρχει τίποτα νεότερο από το last_sync, σταματάμε.
        if newest_signal_ts <= sync_ts:
            return

        # 2) Ανακτούμε διαγραφές μετά το last_sync
        deleted_res = (
            supabase.table("deleted_records")
            .select("table_name, record_id")
            .gte("deleted_at", last_sync)
            .execute()
        )
        deletions = deleted_res.data or []

        deleted_by_table = {}
        for d in deletions:
            t = d["table_name"]
            if t not in deleted_by_table:
                deleted_by_table[t] = []
            deleted_by_table[t].append(str(d["record_id"]))

        # 3) Incremental sync ανά πίνακα
        changes_detected = False

        for table in tables_to_sync:
            delta_res = supabase.table(table).select("*").gte("updated_at", last_sync).execute()
            delta_records = delta_res.data or []
            table_deleted_ids = deleted_by_table.get(table, [])

            if delta_records or table_deleted_ids:
                changes_detected = True

                # Ασφαλής μετάφραση ημερομηνιών
                if table == "assignments":
                    for r in delta_records:
                        d = utils.safe_date_parse(r.get("date"))
                        if d:
                            r["date"] = d
                elif table == "leaves":
                    for r in delta_records:
                        sd = utils.safe_date_parse(r.get("startDate"))
                        if sd:
                            r["startDate"] = sd
                        ed = utils.safe_date_parse(r.get("endDate"))
                        if ed:
                            r["endDate"] = ed
                elif table == "recurring_patterns":
                    for r in delta_records:
                        sd = utils.safe_date_parse(r.get("startDate"))
                        if sd:
                            r["startDate"] = sd

                st.session_state[table] = apply_delta_updates(
                    table,
                    st.session_state.get(table, []),
                    delta_records,
                    table_deleted_ids
                )

        # Fallback ασφάλειας:
        # Αν το probe είπε "υπάρχει αλλαγή", αλλά δεν φάνηκε καθαρό delta,
        # κάνουμε full fetch για να μη χαθεί συγχρονισμός.
        if not changes_detected:
            # Legacy behavior: αν υπήρχε activity σήμα, κάναμε full fetch.
            # Νέο behavior με watermark: επίσης full fetch για 100% ασφάλεια.
            if (used_legacy_probe and activity_signal_ts > sync_ts) or (not used_legacy_probe):
                current_db_time = get_db_current_time()
                _full_fetch_all_tables(current_db_time)
                return

        if changes_detected:
            utils.mark_data_changed()

        # Ενημέρωση last_sync χωρίς extra query όταν έχουμε watermark timestamp.
        if watermark_iso and not used_legacy_probe:
            st.session_state.last_sync_time = iso_with_safety_lag(watermark_iso, seconds=30)
        else:
            current_db_time = get_db_current_time()
            st.session_state.last_sync_time = iso_with_safety_lag(current_db_time, seconds=30)

        st.session_state.force_full_sync_once = False

    except Exception as e:
        print(f"Incremental Sync Error: {e}")
        pass
